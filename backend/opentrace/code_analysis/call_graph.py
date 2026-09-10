"""Deterministic, non-executing local Python call-graph construction."""

from __future__ import annotations

import ast
import builtins
import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from opentrace.code_analysis.call_models import (
    CallEdge,
    GraphCoverage,
    StaticCallGraph,
    UnresolvedCall,
)
from opentrace.code_analysis.models import (
    CodeSymbol,
    FileAnalysisState,
    RepositoryAnalysis,
    ResolutionState,
    SymbolKind,
)
from opentrace.code_analysis.repository import analyze_repository


@dataclass(frozen=True)
class _Binding:
    kind: str
    symbol: CodeSymbol | None = None
    module_file: str | None = None
    module_name: str | None = None


@dataclass
class _Scope:
    node: ast.AST
    symbol: CodeSymbol
    parent: _Scope | None
    class_symbol: CodeSymbol | None = None
    imports: dict[str, _Binding] = field(default_factory=dict)
    local_bindings: dict[str, _Binding] = field(default_factory=dict)
    local_names: set[str] = field(default_factory=set)
    assignment_values: dict[str, list[ast.AST]] = field(default_factory=dict)
    global_names: set[str] = field(default_factory=set)
    nonlocal_names: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class _Module:
    path: str
    tree: ast.Module
    module_names: tuple[str, ...]


class StaticCallGraphBuilder:
    """Build local CALLS edges from M3 symbols and static AST evidence."""

    def __init__(self, root: Path | str, analysis: RepositoryAnalysis | None = None) -> None:
        self.root = Path(root).resolve()
        self.analysis = analysis or analyze_repository(self.root)
        self.symbols = tuple(
            sorted(self.analysis.symbols, key=lambda symbol: (symbol.file, symbol.line, symbol.id))
        )
        self._by_id = {symbol.id: symbol for symbol in self.symbols}
        self._by_qualified = {symbol.qualified_name: symbol for symbol in self.symbols}
        self._by_file: dict[str, list[CodeSymbol]] = {}
        for symbol in self.symbols:
            self._by_file.setdefault(symbol.file, []).append(symbol)
        self._methods: dict[str, dict[str, CodeSymbol]] = {}
        for symbol in self.symbols:
            if symbol.kind in {SymbolKind.METHOD, SymbolKind.ASYNC_METHOD}:
                owner = symbol.qualified_name.rsplit(".", 1)[0]
                method_name = symbol.qualified_name.rsplit(".", 1)[1]
                self._methods.setdefault(owner, {})[method_name] = symbol
        self._module_files: dict[str, set[str]] = {}
        self._modules: list[_Module] = []
        self._scope_by_node: dict[int, _Scope] = {}
        self._scopes: list[_Scope] = []
        self._load_modules()

    def build(self) -> StaticCallGraph:
        edges: list[CallEdge] = []
        unresolved: list[UnresolvedCall] = []
        warnings = list(self.analysis.warnings)
        inspected = 0
        parsed_files = 0
        failed_files = len(self.analysis.failed_files)
        for module in self._modules:
            parsed_files += 1
            root_scope = self._build_scopes(module)
            visitor = _CallVisitor(self, module.path, root_scope, edges, unresolved)
            visitor.visit(module.tree)
            inspected += visitor.inspected
        for file in self.analysis.files:
            if file.state is FileAnalysisState.PARTIAL:
                warnings.append(f"{file.path}: partial M3 analysis coverage")
        edges = _unique_edges(edges)
        unresolved = _unique_unresolved(unresolved)
        coverage = GraphCoverage(
            files_discovered=len(self.analysis.files),
            files_parsed=parsed_files,
            files_failed=failed_files,
            symbols_discovered=len(self.symbols),
            call_expressions_inspected=inspected,
            edges_resolved=len(edges),
            calls_unresolved=len(unresolved),
        )
        return StaticCallGraph(
            nodes=self.symbols,
            edges=tuple(edges),
            unresolved_calls=tuple(unresolved),
            coverage=coverage,
            warnings=tuple(sorted(set(warnings))),
            api_call_sites=self.analysis.call_sites,
        )

    def _load_modules(self) -> None:
        for file in self.analysis.files:
            if file.state is FileAnalysisState.FAILED:
                continue
            source_path = self.root / file.path
            try:
                tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=file.path)
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue
            names = _module_names(self.root, file.path)
            module = _Module(file.path, tree, names)
            self._modules.append(module)
            for name in names:
                self._module_files.setdefault(name, set()).add(file.path)

    def _build_scopes(self, module: _Module) -> _Scope:
        module_symbol = self._by_qualified.get(f"{module.path}::module")
        if module_symbol is None:
            module_symbol = next(symbol for symbol in self.symbols if symbol.file == module.path)
        self._scope_by_node.clear()
        self._scopes.clear()
        return self._make_scope(module.tree, None, module_symbol, None, module.path)

    def _make_scope(
        self,
        node: ast.AST,
        parent: _Scope | None,
        symbol: CodeSymbol,
        class_symbol: CodeSymbol | None,
        path: str,
    ) -> _Scope:
        scope = _Scope(node=node, symbol=symbol, parent=parent, class_symbol=class_symbol)
        self._scope_by_node[id(node)] = scope
        self._scopes.append(scope)
        _collect_scope_bindings(self, scope, node, path)
        for child in _child_scopes(node):
            child_name = getattr(child, "name", None)
            child_symbol = (
                self._child_symbol(symbol, child_name, path)
                if isinstance(child_name, str)
                else None
            )
            if child_symbol is None and isinstance(child, ast.Lambda):
                child_symbol = symbol
            if child_symbol is None:
                continue
            next_class = child_symbol if isinstance(child, ast.ClassDef) else class_symbol
            if isinstance(child, ast.ClassDef):
                next_class = child_symbol
            self._make_scope(child, scope, child_symbol, next_class, path)
        return scope

    def _child_symbol(self, parent: CodeSymbol, name: str, path: str) -> CodeSymbol | None:
        prefix = parent.qualified_name.split("::", 1)[1]
        qualified = (
            f"{path}::{name}"
            if parent.kind is SymbolKind.MODULE
            else f"{path}::{prefix}.{name}"
        )
        return self._by_qualified.get(qualified)

    def resolve_import_module(
        self, current_file: str, module: str | None, level: int
    ) -> tuple[str, str] | None:
        if level:
            current_names = _module_names(self.root, current_file)
            base = next((name for name in current_names if "." in name), current_names[0])
            package = (
                base.split(".")
                if current_file.endswith("__init__.py")
                else base.split(".")[:-1]
            )
            if level > len(package) + 1:
                return None
            parts = package[: len(package) - level + 1]
            if module:
                parts.extend(module.split("."))
            candidate = ".".join(part for part in parts if part)
        else:
            candidate = module or ""
        files = self._module_files.get(candidate, set())
        if len(files) == 1:
            return candidate, next(iter(files))
        suffix = {
            (name, path)
            for name, candidates in self._module_files.items()
            if name == candidate or name.endswith(f".{candidate}")
            for path in candidates
        }
        if len(suffix) == 1:
            return next(iter(suffix))
        return None

    def resolve_symbol(self, file: str, module_name: str, member: str) -> CodeSymbol | None:
        module = self.resolve_import_module(file, module_name, 0)
        if module is None:
            return None
        _, target_file = module
        qualified = f"{target_file}::{member}"
        return self._by_qualified.get(qualified)

    def resolve_module_file(self, module_name: str) -> str | None:
        result = self.resolve_import_module("", module_name, 0)
        return result[1] if result is not None else None

    def class_method(self, class_symbol: CodeSymbol, name: str) -> CodeSymbol | None:
        return self._methods.get(class_symbol.qualified_name, {}).get(name)

    def lookup(self, scope: _Scope, name: str) -> _Binding | None:
        if name in scope.global_names:
            root = scope
            while root.parent is not None:
                root = root.parent
            return self.lookup(root, name) if root is not scope else root.local_bindings.get(name)
        if name in scope.nonlocal_names and scope.parent is not None:
            return self.lookup(scope.parent, name)
        if name in scope.local_names:
            return scope.local_bindings.get(name, _Binding("unknown"))
        if name in scope.imports:
            return scope.imports[name]
        return self.lookup(scope.parent, name) if scope.parent is not None else None

    def resolve_name(self, scope: _Scope, name: str) -> _Binding | None:
        binding = self.lookup(scope, name)
        if binding is not None:
            return binding
        if name in dir(builtins):
            return _Binding("external")
        return None

    def resolve_call_target(self, node: ast.Call, scope: _Scope) -> tuple[CodeSymbol | None, str]:
        function = node.func
        if isinstance(function, ast.Name):
            binding = self.resolve_name(scope, function.id)
            if binding is None:
                return None, "name is not statically bound"
            if binding.kind == "symbol":
                return binding.symbol, "direct symbol binding"
            if binding.kind == "external":
                return None, "external or builtin call"
            if binding.kind == "unknown":
                return None, "local binding is unknown or shadowed"
            return None, "name does not identify a callable local symbol"
        if not isinstance(function, ast.Attribute):
            return None, "dynamic call expression"
        base = self._resolve_value(function.value, scope)
        if base.kind == "module":
            target = self.resolve_symbol(
                scope.symbol.file,
                base.module_name or "",
                function.attr,
            )
            return (
                (target, "module-qualified import")
                if target is not None
                else (None, "module member is not local")
            )
        if base.kind == "instance" and base.symbol is not None:
            target = self.class_method(base.symbol, function.attr)
            return (
                (target, "statically known instance method")
                if target is not None
                else (None, "instance method is not local")
            )
        if base.kind == "class" and base.symbol is not None:
            target = self.class_method(base.symbol, function.attr)
            return (
                (target, "statically known class method")
                if target is not None
                else (None, "class member is not local")
            )
        if isinstance(function.value, ast.Name) and function.value.id in {"self", "cls"}:
            if scope.class_symbol is None:
                return None, "self or cls is outside a class"
            target = self.class_method(scope.class_symbol, function.attr)
            return (
                (target, "unambiguous class method")
                if target is not None
                else (None, "class method is not local")
            )
        return None, "dynamic or external attribute dispatch"

    def _resolve_value(self, node: ast.AST, scope: _Scope) -> _Binding:
        if isinstance(node, ast.Name):
            return self.resolve_name(scope, node.id) or _Binding("unknown")
        if isinstance(node, ast.Call):
            target, _ = self.resolve_call_target(node, scope)
            if target is not None and target.kind is SymbolKind.CLASS:
                return _Binding("instance", symbol=target)
            return _Binding("unknown")
        if isinstance(node, ast.Attribute):
            base = self._resolve_value(node.value, scope)
            if base.kind == "module":
                module_name = f"{base.module_name}.{node.attr}" if base.module_name else node.attr
                return _Binding("module", module_name=module_name)
            return _Binding("unknown")
        return _Binding("unknown")


class _CallVisitor(ast.NodeVisitor):
    def __init__(
        self,
        builder: StaticCallGraphBuilder,
        path: str,
        root_scope: _Scope,
        edges: list[CallEdge],
        unresolved: list[UnresolvedCall],
    ) -> None:
        self.builder = builder
        self.path = path
        self.scope = root_scope
        self.edges = edges
        self.unresolved = unresolved
        self.inspected = 0

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_definition_header(node)
        child = self.builder._scope_by_node.get(id(node))
        if child is not None:
            previous = self.scope
            self.scope = child
            for statement in node.body:
                self.visit(statement)
            self.scope = previous

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.visit_FunctionDef(node)  # type: ignore[arg-type]

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._visit_definition_header(node)
        child = self.builder._scope_by_node.get(id(node))
        if child is not None:
            previous = self.scope
            self.scope = child
            for statement in node.body:
                self.visit(statement)
            self.scope = previous

    def visit_Lambda(self, node: ast.Lambda) -> None:
        defaults = (*node.args.defaults, *(default for default in node.args.kw_defaults if default))
        for default in defaults:
            self.visit(default)
        child = self.builder._scope_by_node.get(id(node))
        if child is not None:
            previous = self.scope
            self.scope = child
            self.visit(node.body)
            self.scope = previous

    def _visit_definition_header(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
    ) -> None:
        for decorator in getattr(node, "decorator_list", ()):
            self.visit(decorator)
        for base in getattr(node, "bases", ()):
            self.visit(base)
        arguments = getattr(node, "args", None)
        if arguments is not None:
            defaults = (
                *arguments.defaults,
                *(default for default in arguments.kw_defaults if default),
            )
            for default in defaults:
                self.visit(default)

    def visit_Call(self, node: ast.Call) -> None:
        self.inspected += 1
        target, reason = self.builder.resolve_call_target(node, self.scope)
        raw_call = ast.unparse(node)
        if target is not None:
            self.edges.append(
                CallEdge(
                    id=_edge_id(self.scope.symbol, target, node),
                    caller_symbol_id=self.scope.symbol.id,
                    callee_symbol_id=target.id,
                    caller_symbol=self.scope.symbol.qualified_name,
                    callee_symbol=target.qualified_name,
                    caller_file=self.scope.symbol.file,
                    callee_file=target.file,
                    line=getattr(node, "lineno", 0),
                    column=getattr(node, "col_offset", 0),
                    resolution_state=ResolutionState.EXACT,
                    evidence=(reason,),
                )
            )
        else:
            self.unresolved.append(
                UnresolvedCall(
                    id=_unresolved_id(self.scope.symbol, node),
                    caller_symbol_id=self.scope.symbol.id,
                    caller_symbol=self.scope.symbol.qualified_name,
                    caller_file=self.scope.symbol.file,
                    line=getattr(node, "lineno", 0),
                    column=getattr(node, "col_offset", 0),
                    raw_call=raw_call,
                    reason=reason,
                )
            )
        self.generic_visit(node)


class _BindingCollector(ast.NodeVisitor):
    def __init__(self, builder: StaticCallGraphBuilder, scope: _Scope, path: str) -> None:
        self.builder = builder
        self.scope = scope
        self.path = path

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            name = alias.asname or alias.name.split(".", 1)[0]
            module_name = alias.name if alias.asname else alias.name.split(".", 1)[0]
            self.scope.imports[name] = _Binding("module", module_name=module_name)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        resolved = self.builder.resolve_import_module(self.path, node.module, node.level)
        module_name, module_file = resolved if resolved is not None else (None, None)
        for alias in node.names:
            name = alias.asname or alias.name
            if alias.name == "*":
                self.scope.imports[name] = _Binding("unknown")
            elif module_name is not None and module_file is not None:
                target = self.builder.resolve_symbol(self.path, module_name, alias.name)
                if target is not None:
                    self.scope.imports[name] = _Binding("symbol", symbol=target)
                else:
                    submodule = self.builder.resolve_import_module(
                        self.path, f"{module_name}.{alias.name}", 0
                    )
                    self.scope.imports[name] = (
                        _Binding("module", module_name=submodule[0])
                        if submodule is not None
                        else _Binding("unknown")
                    )
            else:
                self.scope.imports[name] = _Binding("unknown")

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._definition(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._definition(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._definition(node)

    def _definition(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> None:
        symbol = self.builder._child_symbol(self.scope.symbol, node.name, self.path)
        self.scope.local_names.add(node.name)
        if symbol is not None:
            self.scope.local_bindings[node.name] = _Binding("symbol", symbol=symbol)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def visit_arg(self, node: ast.arg) -> None:
        self.scope.local_names.add(node.arg)
        self.scope.local_bindings[node.arg] = _Binding("unknown")

    def visit_Global(self, node: ast.Global) -> None:
        self.scope.global_names.update(node.names)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self.scope.nonlocal_names.update(node.names)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._assignment(target, node.value)
        self.visit(node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._assignment(node.target, node.value)
        if node.value is not None:
            self.visit(node.value)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._assignment(node.target, None)
        self.visit(node.value)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self._assignment(node.target, node.value)
        self.visit(node.value)

    def visit_For(self, node: ast.For) -> None:
        self._assignment(node.target, None)
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self.visit_For(node)  # type: ignore[arg-type]

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            if item.optional_vars is not None:
                self._assignment(item.optional_vars, None)
        self.generic_visit(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self.visit_With(node)  # type: ignore[arg-type]

    def _assignment(self, target: ast.AST, value: ast.AST | None) -> None:
        for name in _target_names(target):
            self.scope.local_names.add(name)
            unknown = value or ast.Name(id="__unknown__")
            self.scope.assignment_values.setdefault(name, []).append(unknown)
            self.scope.local_bindings[name] = _Binding("unknown")


def _collect_scope_bindings(
    builder: StaticCallGraphBuilder, scope: _Scope, node: ast.AST, path: str
) -> None:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        arguments = node.args
        for argument in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs):
            scope.local_names.add(argument.arg)
            scope.local_bindings[argument.arg] = _Binding("unknown")
        if arguments.vararg is not None:
            scope.local_names.add(arguments.vararg.arg)
            scope.local_bindings[arguments.vararg.arg] = _Binding("unknown")
        if arguments.kwarg is not None:
            scope.local_names.add(arguments.kwarg.arg)
            scope.local_bindings[arguments.kwarg.arg] = _Binding("unknown")
    collector = _BindingCollector(builder, scope, path)
    statements = getattr(node, "body", ())
    for statement in statements if isinstance(statements, list) else ():
        collector.visit(statement)
    for name, values in scope.assignment_values.items():
        if len(values) != 1:
            continue
        value = values[0]
        if not isinstance(value, ast.Call):
            continue
        target, _ = builder.resolve_call_target(value, scope)
        if target is not None and target.kind is SymbolKind.CLASS:
            scope.local_bindings[name] = _Binding("instance", symbol=target)


class _ScopeChildren(ast.NodeVisitor):
    def __init__(self) -> None:
        self.children: list[ast.AST] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.children.append(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.children.append(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.children.append(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self.children.append(node)


def _child_scopes(node: ast.AST) -> tuple[ast.AST, ...]:
    collector = _ScopeChildren()
    statements = getattr(node, "body", ())
    for statement in statements if isinstance(statements, list) else ():
        collector.visit(statement)
    return tuple(collector.children)


def _target_names(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, (ast.Tuple, ast.List)):
        return tuple(name for element in node.elts for name in _target_names(element))
    return ()


def _module_names(root: Path, relative: str) -> tuple[str, ...]:
    path = Path(relative)
    parts = list(path.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    if not parts:
        return ()
    names = {".".join(parts)}
    if root.name.isidentifier():
        names.add(".".join((root.name, *parts)))
    if root.parent.name.isidentifier() and root.parent.name != root.name:
        names.add(".".join((root.parent.name, root.name, *parts)))
    if len(parts) > 1:
        names.add(parts[-1])
    return tuple(sorted(names))


def _edge_id(caller: CodeSymbol, callee: CodeSymbol, node: ast.Call) -> str:
    return "call-edge-" + _digest(
        "python-callgraph-v1",
        caller.id,
        callee.id,
        "CALLS",
        getattr(node, "lineno", 0),
        getattr(node, "col_offset", 0),
    )


def _unresolved_id(caller: CodeSymbol, node: ast.Call) -> str:
    return "unresolved-call-" + _digest(
        "python-callgraph-v1",
        caller.id,
        getattr(node, "lineno", 0),
        getattr(node, "col_offset", 0),
        ast.unparse(node),
    )


def _digest(*parts: object) -> str:
    return hashlib.sha256("\x1f".join(str(part) for part in parts).encode()).hexdigest()[:24]


def _unique_edges(edges: Iterable[CallEdge]) -> list[CallEdge]:
    return sorted({edge.id: edge for edge in edges}.values(), key=lambda edge: edge.id)


def _unique_unresolved(calls: Iterable[UnresolvedCall]) -> list[UnresolvedCall]:
    return sorted({call.id: call for call in calls}.values(), key=lambda call: call.id)


def build_call_graph(
    root: Path | str, analysis: RepositoryAnalysis | None = None
) -> StaticCallGraph:
    """Analyze a repository and return its deterministic local call graph."""

    return StaticCallGraphBuilder(root, analysis).build()


analyze_call_graph = build_call_graph
