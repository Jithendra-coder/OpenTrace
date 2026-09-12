"""Conservative, source-range deterministic migration planning."""

from __future__ import annotations

import ast
import difflib
import hashlib
import io
import json
import tokenize
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from opentrace.code_analysis.models import APICallSite, ResolutionState
from opentrace.contracts.models import APIChange, ChangeCertainty
from opentrace.impact.models import DirectImpact
from opentrace.migration.models import (
    DeterministicMigrationPlan,
    EditKind,
    GeneratedPatch,
    MigrationBatchResult,
    MigrationCandidate,
    MigrationConflict,
    MigrationEdit,
    MigrationOutcome,
    MigrationResult,
    MigrationSummary,
    Repairability,
    RepairStrategy,
    SourcePrecondition,
    UnsupportedMigration,
)
from opentrace.migration.rules import (
    REMOVE_REQUEST_PROPERTY_RULE,
    rule_for,
)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _stable_id(prefix: str, *values: object) -> str:
    material = json.dumps(values, sort_keys=True, separators=(",", ":"), default=str)
    return f"{prefix}-{hashlib.sha256(material.encode('utf-8')).hexdigest()[:24]}"


def _position_to_offset(source: str, line: int, column: int) -> int:
    lines = source.splitlines(keepends=True)
    if line < 1 or line > len(lines) + 1:
        raise ValueError(f"source line is outside content: {line}")
    line_start = sum(len(item) for item in lines[: line - 1])
    if line > len(lines):
        return line_start
    prefix = lines[line - 1].encode("utf-8")[:column]
    return line_start + len(prefix.decode("utf-8"))


def _node_start(source: str, node: ast.AST) -> int:
    return _position_to_offset(source, node.lineno, node.col_offset)  # type: ignore[attr-defined]


def _node_end(source: str, node: ast.AST) -> int:
    end_line = getattr(node, "end_lineno", None)
    end_column = getattr(node, "end_col_offset", None)
    if not isinstance(end_line, int) or not isinstance(end_column, int):
        raise ValueError("AST node has no source end position")
    return _position_to_offset(source, end_line, end_column)


def _offset_to_position(source: str, offset: int) -> tuple[int, int]:
    before = source[:offset]
    line = before.count("\n") + 1
    column = len(before.rsplit("\n", 1)[-1])
    return line, column


def _literal_key(node: ast.expr | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _field_path(change: APIChange) -> tuple[str, ...]:
    evidence = change.evidence.get("property")
    if isinstance(evidence, str) and evidence:
        # Contract change locations encode nested properties after the media-type bracket.
        marker = "]."
        if marker in change.location:
            suffix = change.location.split(marker, 1)[1]
            return tuple(part for part in suffix.split(".") if part)
        return (evidence,)
    suffix = change.location.rsplit(".", 1)[-1]
    return (suffix,) if suffix else ()


@dataclass(frozen=True)
class _TargetEntry:
    key: ast.Constant
    value: ast.expr


def _find_target_entry(mapping: ast.Dict, path: tuple[str, ...]) -> _TargetEntry | None:
    if not path:
        return None
    entries: list[tuple[ast.Constant, ast.expr]] = []
    for key, value in zip(mapping.keys, mapping.values, strict=True):
        if key is None:
            raise ValueError("dictionary unpacking prevents deterministic editing")
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            raise ValueError("dynamic dictionary key prevents deterministic editing")
        entries.append((key, value))
    matches = [(key, value) for key, value in entries if key.value == path[0]]
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError(f"duplicate dictionary key is ambiguous: {path[0]}")
    key, value = matches[0]
    if len(path) == 1:
        return _TargetEntry(key=key, value=value)
    if not isinstance(value, ast.Dict):
        raise ValueError("nested request field is not a literal dictionary")
    return _find_target_entry(value, path[1:])


def _function_nodes(tree: ast.AST) -> Iterable[ast.FunctionDef | ast.AsyncFunctionDef]:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def _function_end_line(node: ast.FunctionDef | ast.AsyncFunctionDef, default: int) -> int:
    value = getattr(node, "end_lineno", None)
    return value if isinstance(value, int) else default


def _call_node(tree: ast.AST, call_site: APICallSite) -> ast.Call | None:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if node.lineno == call_site.line and node.col_offset == call_site.column:
            return node
    return None


def _owner_function(
    tree: ast.AST, call: ast.Call, symbol: str
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    name = symbol.rsplit("::", 1)[-1]
    candidates = [
        node
        for node in _function_nodes(tree)
        if node.name == name
        and node.lineno <= call.lineno <= _function_end_line(node, call.lineno)
    ]
    return (
        min(candidates, key=lambda node: getattr(node, "end_lineno", 0) - node.lineno)
        if candidates
        else None
    )


def _walk_without_nested_functions(node: ast.AST) -> Iterable[ast.AST]:
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield child
            continue
        yield child
        yield from _walk_without_nested_functions(child)


def _local_payload(
    tree: ast.AST, call: ast.Call, call_site: APICallSite
) -> tuple[ast.Dict | None, str | None]:
    keyword = next((item for item in call.keywords if item.arg == "json"), None)
    if keyword is None:
        return None, "exact request body keyword json was not found"
    if isinstance(keyword.value, ast.Dict):
        return keyword.value, None
    if not isinstance(keyword.value, ast.Name):
        return None, "request body is dynamically assembled"
    owner = _owner_function(tree, call, call_site.owning_symbol)
    if owner is None:
        return None, "local payload owner could not be resolved"
    name = keyword.value.id
    assignments: list[ast.Dict] = []
    loads: list[ast.Name] = []
    for node in _walk_without_nested_functions(owner):
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            if node.target.id == name and node.lineno < call.lineno:
                return None, "payload is mutated before the direct API call"
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == name
            and node.lineno < call.lineno
        ):
            return None, "payload is mutated or merged before the direct API call"
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
                if node.lineno < call.lineno:
                    assignments.append(node.value)
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if (
                node.target.id == name
                and isinstance(node.value, ast.Dict)
                and node.lineno < call.lineno
            ):
                assignments.append(node.value)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id == name:
            loads.append(node)
    if len(assignments) != 1:
        return None, "payload has no single local literal assignment"
    if len(loads) > 1:
        return None, "payload is shared or reused outside the direct API call"
    return assignments[0], None


def _comma_after_value(source: str, value: ast.expr) -> tuple[int, int] | None:
    value_end = _node_end(source, value)
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for token in tokens:
            start = _position_to_offset(source, token.start[0], token.start[1])
            if start < value_end:
                continue
            if token.type in {
                tokenize.NL,
                tokenize.NEWLINE,
                tokenize.INDENT,
                tokenize.DEDENT,
                tokenize.COMMENT,
            }:
                continue
            if token.string == "," and token.type == tokenize.OP:
                return start, _position_to_offset(source, token.end[0], token.end[1])
            if token.string in {"}", "]", ")"}:
                return None
            return None
    except (IndentationError, tokenize.TokenError) as error:
        raise ValueError(f"source tokenization failed: {error}") from error
    return None


def _make_edit(
    source: str,
    target: _TargetEntry,
    *,
    file: str,
    change: APIChange,
    impact: DirectImpact,
    call_site: APICallSite,
) -> MigrationEdit:
    start = _node_start(source, target.key)
    value_end = _node_end(source, target.value)
    comma = _comma_after_value(source, target.value)
    if comma is None:
        end = value_end
        replacement = ""
    else:
        comma_start, comma_end = comma
        trailing_end = comma_end
        while trailing_end < len(source) and source[trailing_end] in " \t\r\n":
            trailing_end += 1
        trailing = source[comma_end:trailing_end]
        has_following_comment = (
            trailing_end < len(source) and source[trailing_end] == "#"
        )
        if (
            has_following_comment
            or "#" in trailing
            or "#" in source[value_end:comma_start]
        ):
            end = comma_end
        else:
            end = trailing_end
        replacement = ""
    original = source[start:end]
    start_line, start_column = _offset_to_position(source, start)
    end_line, end_column = _offset_to_position(source, end)
    return MigrationEdit(
        id=_stable_id(
            "migration-edit",
            file,
            start,
            end,
            _sha256(original),
            replacement,
            change.id,
            impact.id,
        ),
        file=file,
        start_offset=start,
        end_offset=end,
        start_line=start_line,
        start_column=start_column,
        end_line=end_line,
        end_column=end_column,
        original_text_hash=_sha256(original),
        original_text=original,
        replacement_text=replacement,
        edit_kind=EditKind.REMOVE_REQUEST_PROPERTY,
        reason=f"Remove outgoing request-body property {target.key.value!r}.",
        change_id=change.id,
        direct_impact_id=impact.id,
        call_site_id=call_site.id,
        rule_id=REMOVE_REQUEST_PROPERTY_RULE.id,
        rule_version=REMOVE_REQUEST_PROPERTY_RULE.version,
    )


def detect_edit_conflicts(edits: Iterable[MigrationEdit]) -> tuple[MigrationConflict, ...]:
    conflicts: list[MigrationConflict] = []
    by_file: dict[str, list[MigrationEdit]] = {}
    for edit in edits:
        by_file.setdefault(edit.file, []).append(edit)
    for file, grouped in sorted(by_file.items()):
        ordered = sorted(grouped, key=lambda item: (item.start_offset, item.end_offset, item.id))
        for first, second in zip(ordered, ordered[1:], strict=False):
            if first.start_offset == second.start_offset and first.end_offset == second.end_offset:
                kind = "DUPLICATE_EDIT"
            elif second.start_offset < first.end_offset:
                kind = "OVERLAPPING_EDIT"
            else:
                continue
            conflicts.append(
                MigrationConflict(
                    id=_stable_id("migration-conflict", file, kind, first.id, second.id),
                    kind=kind,
                    file=file,
                    edit_ids=(first.id, second.id),
                    reason="Structured edits overlap and cannot be applied in arbitrary order.",
                    ranges=(
                        (first.start_offset, first.end_offset),
                        (second.start_offset, second.end_offset),
                    ),
                )
            )
    return tuple(conflicts)


def apply_edits(source: str, edits: Iterable[MigrationEdit]) -> str:
    """Apply checked, non-overlapping edits to text without touching a file."""

    ordered = tuple(sorted(edits, key=lambda item: (item.start_offset, item.end_offset, item.id)))
    conflicts = detect_edit_conflicts(ordered)
    if conflicts:
        raise ValueError(conflicts[0].reason)
    for edit in ordered:
        original = source[edit.start_offset : edit.end_offset]
        if _sha256(original) != edit.original_text_hash or original != edit.original_text:
            raise ValueError(f"stale source or unexpected text for edit {edit.id}")
    result = source
    for edit in reversed(ordered):
        result = result[: edit.start_offset] + edit.replacement_text + result[edit.end_offset :]
    return result


def apply_plan(source: str, plan: DeterministicMigrationPlan) -> str:
    """Apply a plan to an in-memory source snapshot after hash checks."""

    for precondition in plan.preconditions:
        if _sha256(source) != precondition.source_hash:
            raise ValueError(f"stale source for {precondition.file}")
    return apply_edits(source, plan.edits)


def render_unified_diff(file: str, original: str, patched: str) -> str:
    diff = difflib.unified_diff(
        original.splitlines(),
        patched.splitlines(),
        fromfile=f"a/{file}",
        tofile=f"b/{file}",
        lineterm="",
    )
    return "\n".join(diff)


def _empty_plan(
    *,
    change: APIChange,
    impact: DirectImpact,
    call_site: APICallSite,
    file: str,
    outcome: MigrationOutcome,
    repairability: Repairability,
    explanation: str,
    rule_id: str | None = None,
    rule_version: str | None = None,
    warnings: tuple[str, ...] = (),
) -> DeterministicMigrationPlan:
    return DeterministicMigrationPlan(
        id=_stable_id("migration-plan", change.id, impact.id, call_site.id, file, outcome.value),
        change_id=change.id,
        direct_impact_id=impact.id,
        call_site_id=call_site.id,
        target_file=file,
        target_symbol=call_site.owning_symbol,
        target_line=call_site.line,
        target_column=call_site.column,
        strategy=(
            RepairStrategy.DETERMINISTIC
            if outcome is MigrationOutcome.DETERMINISTIC_CANDIDATE
            else RepairStrategy.NO_AI
        ),
        rule_id=rule_id,
        rule_version=rule_version,
        outcome=outcome,
        repairability=repairability,
        explanation=explanation,
        assumptions=change.assumptions,
        required_evidence=REMOVE_REQUEST_PROPERTY_RULE.required_evidence
        if rule_id is not None
        else (),
        warnings=warnings,
    )


def _result_for_plan(plan: DeterministicMigrationPlan) -> MigrationResult:
    unsupported = None
    if plan.outcome is MigrationOutcome.UNSUPPORTED:
        unsupported = UnsupportedMigration(
            id=_stable_id("unsupported-migration", plan.id),
            change_id=plan.change_id,
            direct_impact_id=plan.direct_impact_id,
            call_site_id=plan.call_site_id,
            reason=plan.explanation,
            assumptions=plan.assumptions,
            warnings=plan.warnings,
        )
    summary = MigrationSummary(
        changes_analyzed=1,
        deterministically_repairable=int(plan.outcome is MigrationOutcome.DETERMINISTIC_CANDIDATE),
        unsupported=int(plan.outcome is MigrationOutcome.UNSUPPORTED),
        partial_or_ambiguous=int(plan.outcome is MigrationOutcome.AI_REQUIRED),
        edits_generated=len(plan.edits),
        files_targeted=len({edit.file for edit in plan.edits}),
        conflicts=len(plan.conflicts),
        warnings=plan.warnings,
    )
    return MigrationResult(
        id=_stable_id("migration-result", plan.id, plan.outcome.value, plan.canonical_json()),
        outcome=plan.outcome,
        repairability=plan.repairability,
        plan=plan,
        unsupported=unsupported,
        conflicts=plan.conflicts,
        summary=summary,
    )


class DeterministicMigrationEngine:
    """Generate conservative candidate patches from exact static evidence."""

    policy_version = "deterministic-migration-v1"

    def plan(
        self,
        change: APIChange,
        direct_impact: DirectImpact,
        call_site: APICallSite,
        source: str,
        *,
        source_path: str | Path | None = None,
    ) -> MigrationResult:
        file = str(source_path or call_site.file)
        rule = rule_for(change.category)
        if rule is None:
            plan = _empty_plan(
                change=change,
                impact=direct_impact,
                call_site=call_site,
                file=file,
                outcome=MigrationOutcome.UNSUPPORTED,
                repairability=Repairability.UNSUPPORTED,
                explanation=(
                    f"No trusted deterministic rule exists for {change.category.value}; "
                    "unsupported deterministic repair is reported instead of guessed."
                ),
            )
            return _result_for_plan(plan)
        if direct_impact.change_id != change.id or direct_impact.call_site_id != call_site.id:
            return _result_for_plan(
                _empty_plan(
                    change=change,
                    impact=direct_impact,
                    call_site=call_site,
                    file=file,
                    outcome=MigrationOutcome.AI_REQUIRED,
                    repairability=Repairability.PARTIALLY_SUPPORTED,
                    explanation=(
                        "Direct-impact provenance does not identify this exact "
                        "change and call site."
                    ),
                    rule_id=rule.id,
                    rule_version=rule.version,
                    warnings=("Direct-impact evidence is not exact for deterministic repair.",),
                )
            )
        target_path = _field_path(change)
        target_field = ".".join(target_path)
        exact_evidence = (
            change.certainty in {ChangeCertainty.EXACT, ChangeCertainty.CONDITIONAL}
            and call_site.resolution_state is ResolutionState.EXACT
            and call_site.url_resolution_state is ResolutionState.EXACT
            and call_site.request_field_resolution_state is ResolutionState.EXACT
            and direct_impact.certainty is ResolutionState.EXACT
            and call_site.method.upper() == change.method.upper()
            and call_site.resolved_path == change.path
            and target_field in call_site.request_fields
            and target_field in direct_impact.matched_request_fields
            and (
                direct_impact.matched_path is None
                or direct_impact.matched_path == change.path
            )
            and (
                direct_impact.matched_method is None
                or direct_impact.matched_method.upper() == change.method.upper()
            )
            and (
                direct_impact.matched_host is None
                or direct_impact.matched_host == call_site.resolved_host
            )
        )
        if not exact_evidence:
            plan = _empty_plan(
                change=change,
                impact=direct_impact,
                call_site=call_site,
                file=file,
                outcome=MigrationOutcome.AI_REQUIRED,
                repairability=Repairability.PARTIALLY_SUPPORTED,
                explanation=(
                    f"The removed request property {target_field!r} lacks exact "
                    "API/call/source evidence; "
                    "a deterministic edit would guess."
                ),
                rule_id=rule.id,
                rule_version=rule.version,
                warnings=(
                    "Exact URL, method, request-field, and direct-impact evidence is required.",
                ),
            )
            return _result_for_plan(plan)
        try:
            tree = ast.parse(source, filename=file)
        except SyntaxError as error:
            plan = _empty_plan(
                change=change,
                impact=direct_impact,
                call_site=call_site,
                file=file,
                outcome=MigrationOutcome.AI_REQUIRED,
                repairability=Repairability.PARTIALLY_SUPPORTED,
                explanation="Source is not parseable; no source transformation was generated.",
                rule_id=rule.id,
                rule_version=rule.version,
                warnings=(f"Python syntax error at line {error.lineno}: {error.msg}",),
            )
            return _result_for_plan(plan)
        call = _call_node(tree, call_site)
        if call is None:
            return _result_for_plan(
                _empty_plan(
                    change=change,
                    impact=direct_impact,
                    call_site=call_site,
                    file=file,
                    outcome=MigrationOutcome.AI_REQUIRED,
                    repairability=Repairability.PARTIALLY_SUPPORTED,
                    explanation="The exact call-site source span was not found.",
                    rule_id=rule.id,
                    rule_version=rule.version,
                    warnings=("Source evidence is stale or call-site coordinates changed.",),
                )
            )
        try:
            mapping, mapping_error = _local_payload(tree, call, call_site)
            if mapping_error is not None or mapping is None:
                plan = _empty_plan(
                    change=change,
                    impact=direct_impact,
                    call_site=call_site,
                    file=file,
                    outcome=MigrationOutcome.AI_REQUIRED,
                    repairability=Repairability.PARTIALLY_SUPPORTED,
                    explanation=mapping_error or "Request body mapping could not be resolved.",
                    rule_id=rule.id,
                    rule_version=rule.version,
                    warnings=("Only exact local literal request bodies are supported.",),
                )
                return _result_for_plan(plan)
            target = _find_target_entry(mapping, target_path)
            if target is None:
                plan = _empty_plan(
                    change=change,
                    impact=direct_impact,
                    call_site=call_site,
                    file=file,
                    outcome=MigrationOutcome.NO_CHANGE,
                    repairability=Repairability.SUPPORTED,
                    explanation=(
                        f"Request property {target_field!r} is already absent from "
                        "the exact request body."
                    ),
                    rule_id=rule.id,
                    rule_version=rule.version,
                )
                return _result_for_plan(plan)
            edit = _make_edit(
                source,
                target,
                file=file,
                change=change,
                impact=direct_impact,
                call_site=call_site,
            )
            patched = apply_edits(source, (edit,))
            ast.parse(patched, filename=file)
        except (ValueError, SyntaxError) as error:
            plan = _empty_plan(
                change=change,
                impact=direct_impact,
                call_site=call_site,
                file=file,
                outcome=MigrationOutcome.AI_REQUIRED,
                repairability=Repairability.PARTIALLY_SUPPORTED,
                explanation=f"Deterministic request-body editing is unsafe: {error}",
                rule_id=rule.id,
                rule_version=rule.version,
                warnings=("No speculative edit was emitted.",),
            )
            return _result_for_plan(plan)
        precondition = SourcePrecondition(
            file=file,
            source_hash=_sha256(source),
            start_offset=edit.start_offset,
            end_offset=edit.end_offset,
            expected_text_hash=edit.original_text_hash,
            expected_text=edit.original_text,
        )
        plan_id = _stable_id(
            "migration-plan",
            change.id,
            direct_impact.id,
            call_site.id,
            file,
            _sha256(source),
            edit.start_offset,
            edit.end_offset,
            rule.id,
        )
        edit = edit.model_copy(
            update={"id": _stable_id("migration-edit", plan_id, edit.canonical_json())}
        )
        patched = apply_edits(source, (edit,))
        plan = DeterministicMigrationPlan(
            id=plan_id,
            change_id=change.id,
            direct_impact_id=direct_impact.id,
            call_site_id=call_site.id,
            target_file=file,
            target_symbol=call_site.owning_symbol,
            target_line=call_site.line,
            target_column=call_site.column,
            strategy=RepairStrategy.DETERMINISTIC,
            rule_id=rule.id,
            rule_version=rule.version,
            outcome=MigrationOutcome.DETERMINISTIC_CANDIDATE,
            repairability=Repairability.SUPPORTED,
            explanation=(
                f"Removed only outgoing request-body property {target_field!r} from "
                f"{call_site.owning_symbol}; no other same-named source usage was edited."
            ),
            assumptions=change.assumptions,
            required_evidence=rule.required_evidence,
            warnings=(),
            edits=(edit,),
            preconditions=(precondition,),
        )
        patch_id = _stable_id("generated-patch", plan.id, patched)
        patch = GeneratedPatch(
            id=patch_id,
            plan_id=plan.id,
            unified_diff=render_unified_diff(file, source, patched),
            files=(file,),
            source_hashes={file: _sha256(source)},
        )
        candidate = MigrationCandidate(
            id=_stable_id("migration-candidate", plan.id, patch.id),
            plan_id=plan.id,
            outcome=plan.outcome,
            repairability=plan.repairability,
            patch=patch,
            explanation=plan.explanation,
        )
        result = _result_for_plan(plan)
        return result.model_copy(update={"candidate": candidate})

    def plan_many(
        self,
        change: APIChange,
        direct_impacts: Iterable[DirectImpact],
        call_sites: Iterable[APICallSite],
        sources: Mapping[str, str],
    ) -> MigrationBatchResult:
        calls = {call.id: call for call in call_sites}
        results = []
        for impact in sorted(direct_impacts, key=lambda item: (item.file, item.line, item.id)):
            call = calls.get(impact.call_site_id)
            if call is None:
                continue
            source = sources.get(call.file)
            if source is None:
                rule = rule_for(change.category)
                plan = _empty_plan(
                    change=change,
                    impact=impact,
                    call_site=call,
                    file=call.file,
                    outcome=MigrationOutcome.AI_REQUIRED,
                    repairability=Repairability.PARTIALLY_SUPPORTED,
                    explanation=f"Source content is unavailable for {call.file}.",
                    rule_id=rule.id if rule else None,
                    rule_version=(
                        rule.version if rule else None
                    ),
                    warnings=("Source content is required for patch generation.",),
                )
                results.append(_result_for_plan(plan))
                continue
            results.append(self.plan(change, impact, call, source, source_path=call.file))
        ordered = tuple(results)
        warnings = tuple(
            sorted({warning for result in ordered for warning in result.summary.warnings})
        )
        summary = MigrationSummary(
            changes_analyzed=1,
            deterministically_repairable=sum(
                result.outcome is MigrationOutcome.DETERMINISTIC_CANDIDATE for result in ordered
            ),
            unsupported=sum(result.outcome is MigrationOutcome.UNSUPPORTED for result in ordered),
            partial_or_ambiguous=sum(
                result.outcome is MigrationOutcome.AI_REQUIRED for result in ordered
            ),
            edits_generated=sum(len(result.plan.edits) for result in ordered),
            files_targeted=len({edit.file for result in ordered for edit in result.plan.edits}),
            conflicts=sum(len(result.conflicts) for result in ordered),
            warnings=warnings,
        )
        return MigrationBatchResult(
            id=_stable_id("migration-batch", change.id, [result.id for result in ordered]),
            results=ordered,
            summary=summary,
        )


def plan_migration(
    change: APIChange,
    direct_impact: DirectImpact,
    call_site: APICallSite,
    source: str,
    *,
    source_path: str | Path | None = None,
) -> MigrationResult:
    return DeterministicMigrationEngine().plan(
        change, direct_impact, call_site, source, source_path=source_path
    )


def migration_support_matrix() -> dict[str, dict[str, str]]:
    from opentrace.migration.rules import support_matrix

    return support_matrix()
