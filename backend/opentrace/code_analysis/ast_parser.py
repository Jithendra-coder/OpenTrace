"""AST-only extraction of symbols and supported HTTP call sites."""

import ast
import hashlib
from dataclasses import dataclass, field
from typing import Final

from opentrace.code_analysis.models import APICallSite, CodeSymbol, ResolutionState, SymbolKind
from opentrace.code_analysis.values import (
    StaticEvaluator,
    expression_text,
    extract_mapping_fields,
    resolve_url,
    static_mapping_keys,
)

_METHODS: Final = frozenset({"get", "post", "put", "patch", "delete", "head", "options"})
_LIBRARIES: Final = frozenset({"requests", "httpx"})


@dataclass(frozen=True)
class Binding:
    library: str
    method: str | None = None
    kind: str = "module"


@dataclass
class ScopeFrame:
    file: str
    qualified_name: str
    symbol: CodeSymbol
    parent: "ScopeFrame | None"
    class_name: str | None = None
    bindings: dict[str, Binding] = field(default_factory=dict)
    shadowed: set[str] = field(default_factory=set)
    values: dict[str, ast.AST] = field(default_factory=dict)
    client_bindings: dict[str, Binding] = field(default_factory=dict)
    response_aliases: dict[str, set[int]] = field(default_factory=dict)

    def resolve_binding(self, name: str) -> Binding | None:
        if name in self.shadowed:
            return None
        binding = self.bindings.get(name) or self.client_bindings.get(name)
        if binding is not None:
            return binding
        return self.parent.resolve_binding(name) if self.parent is not None else None

    def evaluator(self) -> StaticEvaluator:
        parent = self.parent.evaluator() if self.parent is not None else None
        return StaticEvaluator(self.values, parent)


@dataclass
class MutableCall:
    node: ast.Call
    file: str
    symbol: CodeSymbol
    class_name: str | None
    line: int
    column: int
    end_line: int
    end_column: int
    library: str
    invocation_kind: str
    method: str
    raw_url_expression: str | None
    resolved_host: str | None
    resolved_path: str | None
    url_state: ResolutionState
    request_fields: tuple[str, ...]
    request_state: ResolutionState
    request_input_present: bool
    query_parameters: tuple[str, ...]
    headers: tuple[str, ...]
    response_fields: set[str] = field(default_factory=set)
    response_state: ResolutionState = ResolutionState.UNRESOLVED
    evidence: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class ASTFileAnalyzer(ast.NodeVisitor):
    """Analyze one parsed module without importing or executing it."""

    def __init__(self, path: str, tree: ast.Module) -> None:
        self.path = path
        self.tree = tree
        self.symbols: list[CodeSymbol] = []
        self.calls: list[MutableCall] = []
        self._call_indexes: dict[int, MutableCall] = {}
        self._frames: list[ScopeFrame] = []
        self._module_frame: ScopeFrame | None = None

    def analyze(self) -> tuple[tuple[CodeSymbol, ...], tuple[APICallSite, ...], tuple[str, ...]]:
        module_symbol = self._symbol(
            qualified_name=f"{self.path}::module",
            kind=SymbolKind.MODULE,
            node=self.tree,
        )
        module = self._frame(module_symbol, self.tree, None)
        self._module_frame = module
        self._frames.append(module)
        self.visit_statements(self.tree.body)
        self._frames.pop()
        calls = tuple(self._finalize_call(call) for call in self.calls)
        return (
            tuple(self.symbols),
            calls,
            tuple(warning for call in self.calls for warning in call.warnings),
        )

    @property
    def frame(self) -> ScopeFrame:
        return self._frames[-1]

    def visit_statements(self, statements: list[ast.stmt]) -> None:
        for statement in statements:
            self.visit(statement)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node, is_async=True)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef, is_async: bool) -> None:
        parent = self.frame
        parent_name = parent.qualified_name.split("::", 1)[1]
        name = (
            node.name if parent.symbol.kind is SymbolKind.MODULE else f"{parent_name}.{node.name}"
        )
        kind = (
            SymbolKind.ASYNC_METHOD
            if is_async and parent.class_name is not None
            else SymbolKind.METHOD
            if parent.class_name is not None
            else SymbolKind.ASYNC_FUNCTION
            if is_async
            else SymbolKind.FUNCTION
        )
        qualified_name = f"{self.path}::{name}"
        symbol = self._symbol(qualified_name, kind, node)
        frame = self._frame(symbol, node, parent)
        self._frames.append(frame)
        self.visit_statements(node.body)
        self._frames.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        parent = self.frame
        parent_name = parent.qualified_name.split("::", 1)[1]
        name = (
            node.name if parent.symbol.kind is SymbolKind.MODULE else f"{parent_name}.{node.name}"
        )
        symbol = self._symbol(f"{self.path}::{name}", SymbolKind.CLASS, node)
        frame = self._frame(symbol, node, parent, class_name=node.name)
        self._frames.append(frame)
        self.visit_statements(node.body)
        self._frames.pop()

    def visit_Assign(self, node: ast.Assign) -> None:
        records_before = len(self.calls)
        self.visit(node.value)
        new_records = self.calls[records_before:]
        if len(new_records) == 1 and node.value is new_records[0].node:
            record = new_records[0]
            for target in node.targets:
                for name in _target_names(target):
                    self.frame.response_aliases[name] = {self.calls.index(record)}
        elif _is_response_json(node.value, self.frame.response_aliases):
            aliases = _response_aliases(node.value, self.frame.response_aliases)
            for target in node.targets:
                for name in _target_names(target):
                    self.frame.response_aliases[name] = aliases
        else:
            for target in node.targets:
                for name in _target_names(target):
                    self.frame.response_aliases.pop(name, None)
        for target in node.targets:
            if isinstance(target, (ast.Tuple, ast.List)):
                self.visit(target)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self.visit_Assign(ast.Assign(targets=[node.target], value=node.value))

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        for item in node.items:
            self._bind_client_context(item.context_expr, item.optional_vars)
        self.visit_statements(node.body)

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            self._bind_client_context(item.context_expr, item.optional_vars)
        self.visit_statements(node.body)

    def visit_Call(self, node: ast.Call) -> None:
        classified = self._classify_call(node)
        if classified is not None:
            record = self._extract_call(node, *classified)
            self.calls.append(record)
            self._call_indexes[id(node)] = record
            return
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        aliases, field_path, dynamic = _response_access(node, self.frame.response_aliases)
        if aliases:
            for index in aliases:
                if index < len(self.calls):
                    call = self.calls[index]
                    if field_path:
                        call.response_fields.add(field_path)
                    if dynamic:
                        call.response_state = ResolutionState.PARTIAL
                        call.warnings.append("dynamic response field access")
                    elif field_path:
                        call.response_state = ResolutionState.EXACT
        self.generic_visit(node)

    def _classify_call(self, node: ast.Call) -> tuple[str, str, str] | None:
        function = node.func
        if isinstance(function, ast.Name):
            binding = self.frame.resolve_binding(function.id)
            if binding is not None and binding.library in _LIBRARIES and binding.method in _METHODS:
                return (
                    binding.library,
                    binding.method,
                    "FROM_IMPORT" if binding.kind == "from" else "DIRECT",
                )
            return None
        if not isinstance(function, ast.Attribute) or not isinstance(function.value, ast.Name):
            return None
        binding = self.frame.resolve_binding(function.value.id)
        if binding is None or function.attr.lower() not in _METHODS:
            return None
        if binding.kind == "module" and binding.library in _LIBRARIES:
            return binding.library, function.attr.lower(), "DIRECT"
        if binding.kind == "client" and binding.library in _LIBRARIES:
            return binding.library, function.attr.lower(), "CLIENT_INSTANCE"
        if binding.kind == "session" and binding.library == "requests":
            return binding.library, function.attr.lower(), "SESSION_INSTANCE"
        return None

    def _extract_call(
        self, node: ast.Call, library: str, method: str, invocation_kind: str
    ) -> MutableCall:
        evaluator = self.frame.evaluator()
        url_node = _keyword(node, "url") or (node.args[0] if node.args else None)
        host, path, url_state, url_evidence = resolve_url(url_node, evaluator)
        json_node = _keyword(node, "json")
        request_fields, request_state, request_evidence = (
            extract_mapping_fields(json_node, evaluator)
            if json_node is not None
            else ((), ResolutionState.UNRESOLVED, ("no JSON body argument",))
        )
        query_parameters, _ = static_mapping_keys(_keyword(node, "params"), evaluator)
        headers, _ = static_mapping_keys(_keyword(node, "headers"), evaluator)
        warnings: list[str] = []
        if url_state is not ResolutionState.EXACT:
            warnings.append("URL resolution is not exact")
        if request_state is not ResolutionState.EXACT and json_node is not None:
            warnings.append("request JSON fields are not fully resolved")
        return MutableCall(
            node=node,
            file=self.path,
            symbol=self.frame.symbol,
            class_name=self.frame.class_name,
            line=getattr(node, "lineno", 0),
            column=getattr(node, "col_offset", 0),
            end_line=getattr(node, "end_lineno", getattr(node, "lineno", 0)),
            end_column=getattr(node, "end_col_offset", getattr(node, "col_offset", 0)),
            library=library,
            invocation_kind=invocation_kind,
            method=method.upper(),
            raw_url_expression=expression_text(url_node) if url_node is not None else None,
            resolved_host=host,
            resolved_path=path,
            url_state=url_state,
            request_fields=request_fields,
            request_state=request_state,
            request_input_present=json_node is not None,
            query_parameters=query_parameters,
            headers=headers,
            evidence=[*url_evidence, *request_evidence],
            warnings=warnings,
        )

    def _bind_client_context(self, expression: ast.AST, target: ast.AST | None) -> None:
        if not isinstance(target, ast.Name) or not isinstance(expression, ast.Call):
            return
        binding = _client_constructor(expression, self.frame)
        if binding is not None:
            self.frame.client_bindings[target.id] = binding

    def _frame(
        self,
        symbol: CodeSymbol,
        node: ast.AST,
        parent: ScopeFrame | None,
        class_name: str | None = None,
    ) -> ScopeFrame:
        bindings, shadowed, values, clients = _scope_bindings(node, parent)
        return ScopeFrame(
            file=self.path,
            qualified_name=symbol.qualified_name,
            symbol=symbol,
            parent=parent,
            class_name=class_name or (parent.class_name if parent else None),
            bindings=bindings,
            shadowed=shadowed,
            values=values,
            client_bindings=clients,
        )

    def _symbol(self, qualified_name: str, kind: SymbolKind, node: ast.AST) -> CodeSymbol:
        line = getattr(node, "lineno", 1)
        end_line = getattr(node, "end_lineno", line)
        column = getattr(node, "col_offset", 0)
        end_column = getattr(node, "end_col_offset", column)
        identifier = _stable_id("symbol", self.path, qualified_name, kind.value, line, end_line)
        symbol = CodeSymbol(
            id=identifier,
            file=self.path,
            qualified_name=qualified_name,
            kind=kind,
            line=line,
            end_line=end_line,
            column=column,
            end_column=end_column,
        )
        if not any(existing.id == symbol.id for existing in self.symbols):
            self.symbols.append(symbol)
        return symbol

    def _finalize_call(self, call: MutableCall) -> APICallSite:
        response_state = call.response_state
        states = [call.url_state]
        if call.request_input_present:
            states.append(call.request_state)
        if response_state is not ResolutionState.UNRESOLVED:
            states.append(response_state)
        overall = _overall_state(tuple(states))
        identifier = _stable_id(
            "call",
            call.file,
            call.symbol.qualified_name,
            call.line,
            call.column,
            call.library,
            call.method,
            call.raw_url_expression or "",
        )
        evidence = (*call.evidence, f"source location: {call.file}:{call.line}:{call.column}")
        return APICallSite(
            id=identifier,
            file=call.file,
            owning_symbol=call.symbol.qualified_name,
            owning_symbol_id=call.symbol.id,
            class_name=call.class_name,
            line=call.line,
            column=call.column,
            end_line=call.end_line,
            end_column=call.end_column,
            library=call.library,
            invocation_kind=call.invocation_kind,
            method=call.method,
            raw_url_expression=call.raw_url_expression,
            resolved_host=call.resolved_host,
            resolved_path=call.resolved_path,
            url_resolution_state=call.url_state,
            request_fields=tuple(sorted(call.request_fields)),
            request_field_resolution_state=call.request_state,
            query_parameters=call.query_parameters,
            headers=call.headers,
            response_fields_used=tuple(sorted(call.response_fields)),
            response_field_resolution_state=response_state,
            resolution_state=overall,
            evidence=evidence,
            warnings=tuple(sorted(set(call.warnings))),
        )


def parse_source(
    path: str, source: str
) -> tuple[tuple[CodeSymbol, ...], tuple[APICallSite, ...], tuple[str, ...]]:
    tree = ast.parse(source, filename=path, mode="exec", type_comments=True)
    return ASTFileAnalyzer(path, tree).analyze()


def _scope_bindings(
    node: ast.AST, parent: ScopeFrame | None
) -> tuple[dict[str, Binding], set[str], dict[str, ast.AST], dict[str, Binding]]:
    collector = _ScopeCollector()
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        collector.visit(node.args)
    body = getattr(node, "body", [])
    for statement in body:
        collector.visit(statement)
    inherited = dict(parent.bindings) if parent is not None else {}
    inherited_clients = dict(parent.client_bindings) if parent is not None else {}
    shadowed = {
        name
        for name in collector.non_import_stores
        if name in inherited or name in inherited_clients or name in collector.bindings
    }
    bindings = {name: binding for name, binding in inherited.items() if name not in shadowed}
    bindings.update(
        {name: binding for name, binding in collector.bindings.items() if name not in shadowed}
    )
    clients = {name: binding for name, binding in inherited_clients.items() if name not in shadowed}
    clients.update(
        {
            name: binding
            for name, binding in collector.clients.items()
            if name not in collector.non_client_stores
        }
    )
    return bindings, shadowed, collector.values, clients


class _ScopeCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.bindings: dict[str, Binding] = {}
        self.clients: dict[str, Binding] = {}
        self.values: dict[str, ast.AST] = {}
        self.stored_names: set[str] = set()
        self.non_import_stores: set[str] = set()
        self.non_client_stores: set[str] = set()

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name in _LIBRARIES:
                self.bindings[alias.asname or alias.name] = Binding(alias.name)
            else:
                self.stored_names.add(alias.asname or alias.name.split(".", 1)[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module not in _LIBRARIES:
            return
        for alias in node.names:
            if alias.name == "*":
                continue
            name = alias.asname or alias.name
            if alias.name in _METHODS:
                self.bindings[name] = Binding(node.module, alias.name, "from")
            elif alias.name in {"Client", "AsyncClient"} and node.module == "httpx":
                self.bindings[name] = Binding(node.module, alias.name, "constructor")
            elif alias.name == "Session" and node.module == "requests":
                self.bindings[name] = Binding(node.module, alias.name, "constructor")

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.stored_names.add(node.name)
        self.non_import_stores.add(node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.stored_names.add(node.name)
        self.non_import_stores.add(node.name)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.stored_names.add(node.name)
        self.non_import_stores.add(node.name)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Store):
            self.stored_names.add(node.id)
            self.non_import_stores.add(node.id)

    def visit_arg(self, node: ast.arg) -> None:
        self.stored_names.add(node.arg)
        self.non_import_stores.add(node.arg)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._record_target(target, node.value)
        self.visit(node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._record_target(node.target, node.value)
        if node.value is not None:
            self.visit(node.value)

    def _record_target(self, target: ast.AST, value: ast.AST | None) -> None:
        names = _target_names(target)
        self.stored_names.update(names)
        self.non_import_stores.update(names)
        if value is not None:
            for name in names:
                if name not in self.values:
                    self.values[name] = value
        if isinstance(value, ast.Call):
            binding = _constructor_binding(value, self.bindings)
            if binding is not None:
                for name in names:
                    self.clients[name] = binding
            else:
                self.non_client_stores.update(names)
        else:
            self.non_client_stores.update(names)


def _constructor_binding(node: ast.Call, bindings: dict[str, Binding]) -> Binding | None:
    if not isinstance(node.func, ast.Attribute) or not isinstance(node.func.value, ast.Name):
        return None
    base = bindings.get(node.func.value.id)
    if base is None and node.func.value.id in _LIBRARIES:
        base = Binding(node.func.value.id)
    if base is None:
        return None
    if base.library == "httpx" and node.func.attr in {"Client", "AsyncClient"}:
        return Binding("httpx", node.func.attr, "client")
    if base.library == "requests" and node.func.attr == "Session":
        return Binding("requests", node.func.attr, "session")
    return None


def _client_constructor(node: ast.Call, frame: ScopeFrame) -> Binding | None:
    if not isinstance(node.func, ast.Attribute) or not isinstance(node.func.value, ast.Name):
        return None
    base = frame.resolve_binding(node.func.value.id)
    if base is None:
        return None
    if base.library == "httpx" and node.func.attr in {"Client", "AsyncClient"}:
        return Binding("httpx", node.func.attr, "client")
    if base.library == "requests" and node.func.attr == "Session":
        return Binding("requests", node.func.attr, "session")
    return None


def _keyword(node: ast.Call, name: str) -> ast.AST | None:
    for keyword in node.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _target_names(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, (ast.Tuple, ast.List)):
        return tuple(name for element in node.elts for name in _target_names(element))
    return ()


def _is_response_json(node: ast.AST, aliases: dict[str, set[int]]) -> bool:
    return bool(_response_aliases(node, aliases))


def _response_aliases(node: ast.AST, aliases: dict[str, set[int]]) -> set[int]:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return set()
    if node.func.attr != "json" or not isinstance(node.func.value, ast.Name):
        return set()
    return set(aliases.get(node.func.value.id, set()))


def _response_access(
    node: ast.Subscript, aliases: dict[str, set[int]]
) -> tuple[set[int], str | None, bool]:
    parts: list[str] = []
    current: ast.AST = node
    dynamic = False
    while isinstance(current, ast.Subscript):
        key = current.slice
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            parts.append(key.value)
        else:
            dynamic = True
        current = current.value
    if isinstance(current, ast.Call) and isinstance(current.func, ast.Attribute):
        if current.func.attr != "json" or not isinstance(current.func.value, ast.Name):
            return set(), None, False
        result = aliases.get(current.func.value.id, set())
    elif isinstance(current, ast.Name):
        result = aliases.get(current.id, set())
    else:
        result = set()
    if not result:
        return set(), None, dynamic
    return result, ".".join(reversed(parts)) if parts else None, dynamic


def _overall_state(states: tuple[ResolutionState, ...]) -> ResolutionState:
    if ResolutionState.UNRESOLVED in states:
        return ResolutionState.UNRESOLVED
    if ResolutionState.PARTIAL in states:
        return ResolutionState.PARTIAL
    return ResolutionState.EXACT


def _stable_id(prefix: str, *parts: object) -> str:
    payload = "\x1f".join(str(part) for part in parts)
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"
