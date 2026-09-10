"""Bounded, non-executing static value helpers."""

import ast
from dataclasses import dataclass
from urllib.parse import urlsplit

from opentrace.code_analysis.models import ResolutionState


@dataclass(frozen=True)
class StaticValue:
    value: str | None
    state: ResolutionState
    evidence: tuple[str, ...] = ()


def expression_text(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except (AttributeError, ValueError):
        return ast.dump(node, annotate_fields=False, include_attributes=False)


class StaticEvaluator:
    """Resolve only literals, known names, safe concatenation, and bounded f-strings."""

    def __init__(self, values: dict[str, ast.AST], parent: "StaticEvaluator | None" = None) -> None:
        self._values = values
        self._parent = parent

    def resolve_string(self, node: ast.AST, seen: frozenset[str] = frozenset()) -> StaticValue:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return StaticValue(node.value, ResolutionState.EXACT, ("static string literal",))
        if isinstance(node, ast.Name):
            if node.id in seen:
                return StaticValue(None, ResolutionState.UNRESOLVED, ("cyclic constant",))
            value_node = self._values.get(node.id)
            if value_node is None and self._parent is not None:
                return self._parent.resolve_string(node, seen)
            if value_node is None:
                return StaticValue(None, ResolutionState.UNRESOLVED, (f"unknown name: {node.id}",))
            return self.resolve_string(value_node, seen | {node.id})
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = self.resolve_string(node.left, seen)
            right = self.resolve_string(node.right, seen)
            if left.state is ResolutionState.EXACT and right.state is ResolutionState.EXACT:
                return StaticValue(
                    (left.value or "") + (right.value or ""),
                    ResolutionState.EXACT,
                    (*left.evidence, *right.evidence, "safe string concatenation"),
                )
            if left.value is not None or right.value is not None:
                return StaticValue(
                    (left.value or "{dynamic}") + (right.value or "{dynamic}"),
                    ResolutionState.PARTIAL,
                    (*left.evidence, *right.evidence, "partially resolved concatenation"),
                )
            return StaticValue(None, ResolutionState.UNRESOLVED, (*left.evidence, *right.evidence))
        if isinstance(node, ast.JoinedStr):
            parts: list[str] = []
            state = ResolutionState.EXACT
            evidence: list[str] = []
            for part in node.values:
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    parts.append(part.value)
                    continue
                if isinstance(part, ast.FormattedValue):
                    resolved = self.resolve_string(part.value, seen)
                    evidence.extend(resolved.evidence)
                    if resolved.value is None:
                        parts.append("{dynamic}")
                        state = ResolutionState.PARTIAL
                    else:
                        parts.append(resolved.value)
                        if resolved.state is not ResolutionState.EXACT:
                            state = ResolutionState.PARTIAL
                    continue
                parts.append("{dynamic}")
                state = ResolutionState.PARTIAL
            return StaticValue("".join(parts), state, (*evidence, "bounded f-string resolution"))
        return StaticValue(
            None, ResolutionState.UNRESOLVED, (f"unsupported expression: {expression_text(node)}",)
        )


def resolve_url(
    node: ast.AST | None, evaluator: StaticEvaluator
) -> tuple[str | None, str | None, ResolutionState, tuple[str, ...]]:
    if node is None:
        return None, None, ResolutionState.UNRESOLVED, ("URL argument is absent",)
    value = evaluator.resolve_string(node)
    if value.value is None:
        return None, None, value.state, value.evidence
    parts = urlsplit(value.value)
    if parts.scheme and parts.netloc:
        path = parts.path or "/"
        return parts.hostname, path, value.state, (*value.evidence, "absolute URL parsed")
    if value.value.startswith("/"):
        path = urlsplit(value.value).path or "/"
        return None, path, value.state, (*value.evidence, "relative URL parsed")
    return (
        None,
        None,
        ResolutionState.UNRESOLVED,
        (*value.evidence, "URL is not an absolute or slash path"),
    )


def extract_mapping_fields(
    node: ast.AST | None,
    evaluator: StaticEvaluator,
    prefix: str = "",
    seen: frozenset[str] = frozenset(),
) -> tuple[tuple[str, ...], ResolutionState, tuple[str, ...]]:
    """Extract dictionary keys without evaluating values or executing source."""
    if node is None:
        return (), ResolutionState.UNRESOLVED, ("mapping expression is absent",)
    if isinstance(node, ast.Name):
        if node.id in seen:
            return (), ResolutionState.UNRESOLVED, ("cyclic mapping alias",)
        value = evaluator._values.get(node.id)
        if value is None and evaluator._parent is not None:
            return extract_mapping_fields_from_parent(node, evaluator, prefix, seen)
        if value is None:
            return (), ResolutionState.UNRESOLVED, (f"unknown mapping name: {node.id}",)
        return extract_mapping_fields(value, evaluator, prefix, seen | {node.id})
    if not isinstance(node, ast.Dict):
        return (
            (),
            ResolutionState.UNRESOLVED,
            (f"unsupported mapping expression: {expression_text(node)}",),
        )
    fields: list[str] = []
    state = ResolutionState.EXACT
    evidence: list[str] = []
    for key, value in zip(node.keys, node.values, strict=True):
        if key is None:
            state = ResolutionState.PARTIAL
            evidence.append("dictionary unpacking prevents complete field extraction")
            continue
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            state = ResolutionState.PARTIAL
            evidence.append("dynamic dictionary key prevents complete field extraction")
            continue
        field = f"{prefix}.{key.value}" if prefix else key.value
        fields.append(field)
        if isinstance(value, ast.Dict):
            nested, nested_state, nested_evidence = extract_mapping_fields(value, evaluator, field)
            fields.extend(nested)
            evidence.extend(nested_evidence)
            if nested_state is not ResolutionState.EXACT:
                state = ResolutionState.PARTIAL
    return tuple(sorted(set(fields))), state, tuple(evidence)


def extract_mapping_fields_from_parent(
    node: ast.Name,
    evaluator: StaticEvaluator,
    prefix: str,
    seen: frozenset[str],
) -> tuple[tuple[str, ...], ResolutionState, tuple[str, ...]]:
    if evaluator._parent is None:
        return (), ResolutionState.UNRESOLVED, (f"unknown mapping name: {node.id}",)
    return extract_mapping_fields(node, evaluator._parent, prefix, seen)


def static_mapping_keys(
    node: ast.AST | None, evaluator: StaticEvaluator
) -> tuple[tuple[str, ...], ResolutionState]:
    if node is None:
        return (), ResolutionState.UNRESOLVED
    if isinstance(node, ast.Name):
        value = evaluator._values.get(node.id)
        if value is None and evaluator._parent is not None:
            return static_mapping_keys(node, evaluator._parent)
        if value is None:
            return (), ResolutionState.UNRESOLVED
        return static_mapping_keys(value, evaluator)
    if not isinstance(node, ast.Dict):
        return (), ResolutionState.PARTIAL
    names: list[str] = []
    state = ResolutionState.EXACT
    for key in node.keys:
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            names.append(key.value)
        else:
            state = ResolutionState.PARTIAL
    return tuple(sorted(set(names))), state
