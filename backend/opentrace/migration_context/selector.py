"""Deterministic, source-safe M14 selection of bounded migration evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

from opentrace.blast_radius.models import BlastRadius, ImpactType
from opentrace.code_analysis.models import APICallSite, ResolutionState
from opentrace.contracts.models import APIChange
from opentrace.impact.models import DirectImpact
from opentrace.migration.models import MigrationResult
from opentrace.migration_context.models import (
    MIGRATION_CONTEXT_SCHEMA_VERSION,
    ContextBudget,
    ContextItem,
    ContextItemRole,
    ContextManifest,
    ContextOmission,
    ContextOmissionReason,
    ContextSelection,
    ContextSelectionPolicy,
    ContextSelectionStatus,
    ContextSelectionSummary,
    MigrationContext,
)
from opentrace.routeforge.models import RouteChoice
from opentrace.routeforge.router import RoutingDecision

_SENSITIVE_FILE_NAMES = frozenset(
    {
        "credentials",
        "credentials.json",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "id_rsa",
        "known_hosts",
    }
)
_SENSITIVE_PARTS = frozenset({".aws", ".git", ".ssh", "credentials", "secrets"})
_SENSITIVE_SUFFIXES = frozenset({".key", ".pem", ".p12", ".pfx"})


@dataclass(frozen=True)
class _Candidate:
    role: ContextItemRole
    file: str | None
    symbol: str | None
    start_line: int | None
    end_line: int | None
    content: str
    reason: str
    provenance_ids: tuple[str, ...]
    priority: int
    required: bool
    graph_distance: int | None = None

    @property
    def content_hash(self) -> str:
        return _sha256(self.content)

    @property
    def characters(self) -> int:
        return len(self.content)

    def key(self) -> tuple[object, ...]:
        if self.file is not None and self.start_line is not None and self.end_line is not None:
            return ("span", self.file, self.start_line, self.end_line, self.content_hash)
        return ("content", self.role.value, self.content_hash)


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _stable_id(prefix: str, *parts: object) -> str:
    return f"{prefix}-{_sha256(_json(parts))[:24]}"


def _omission(
    candidate: _Candidate,
    reason: ContextOmissionReason,
    detail: str,
) -> ContextOmission:
    return ContextOmission(
        id=_stable_id(
            "context-omission",
            candidate.role.value,
            candidate.file,
            candidate.start_line,
            candidate.end_line,
            candidate.content_hash,
            reason.value,
            candidate.provenance_ids,
        ),
        role=candidate.role,
        file=candidate.file,
        symbol=candidate.symbol,
        provenance_ids=candidate.provenance_ids,
        reason=reason,
        priority=candidate.priority,
        content_characters=candidate.characters,
        detail=detail,
    )


def _missing_omission(
    *,
    role: ContextItemRole,
    file: str | None,
    symbol: str | None,
    provenance_ids: tuple[str, ...],
    reason: ContextOmissionReason,
    detail: str,
    priority: int,
) -> ContextOmission:
    return ContextOmission(
        id=_stable_id("context-omission", role.value, file, symbol, reason.value, provenance_ids),
        role=role,
        file=file,
        symbol=symbol,
        provenance_ids=provenance_ids,
        reason=reason,
        priority=priority,
        content_characters=0,
        detail=detail,
    )


class _SourceReader:
    """Read only explicit M3/M4/M5 evidence paths, never repository-wide content."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise ValueError(f"repository root is not a directory: {self.root}")
        self._cache: dict[str, tuple[str | None, ContextOmissionReason | None, str | None]] = {}

    def span(
        self, file: str, start_line: int, end_line: int
    ) -> tuple[str | None, ContextOmissionReason | None, str | None]:
        source, reason, detail = self._source(file)
        if source is None:
            return None, reason, detail
        lines = source.splitlines(keepends=True)
        if start_line < 1 or end_line < start_line or end_line > len(lines):
            return (
                None,
                ContextOmissionReason.UNRESOLVED_SOURCE,
                f"Evidence span {start_line}-{end_line} is outside the static source range.",
            )
        return "".join(lines[start_line - 1 : end_line]), None, None

    def _source(
        self, file: str
    ) -> tuple[str | None, ContextOmissionReason | None, str | None]:
        result: tuple[str | None, ContextOmissionReason | None, str | None]
        cached = self._cache.get(file)
        if cached is not None:
            return cached
        relative = Path(file)
        posix = PurePosixPath(file)
        windows = PureWindowsPath(file)
        parts = tuple(part.lower() for part in (*posix.parts, *windows.parts))
        name = relative.name.lower()
        if (
            relative.is_absolute()
            or posix.is_absolute()
            or windows.is_absolute()
            or ".." in parts
        ):
            result = (
                None,
                ContextOmissionReason.OUTSIDE_REPOSITORY,
                "Source path is absolute or traverses outside the repository.",
            )
        elif (
            name == ".env"
            or name.startswith(".env.")
            or name in _SENSITIVE_FILE_NAMES
            or any(part in _SENSITIVE_PARTS for part in parts)
            or relative.suffix.lower() in _SENSITIVE_SUFFIXES
            or "credential" in name
        ):
            result = (
                None,
                ContextOmissionReason.UNSAFE_FILE,
                "Sensitive configuration, credential, key, or VCS source is excluded.",
            )
        elif relative.suffix.lower() != ".py":
            result = (
                None,
                ContextOmissionReason.UNSAFE_FILE,
                "Only static Python source evidence may enter MigrationContext.",
            )
        else:
            candidate = self.root / relative
            try:
                resolved = candidate.resolve(strict=True)
            except FileNotFoundError:
                result = (
                    None,
                    ContextOmissionReason.UNRESOLVED_SOURCE,
                    "Static source evidence path does not exist.",
                )
            except OSError as error:
                result = (None, ContextOmissionReason.UNRESOLVED_SOURCE, str(error))
            else:
                try:
                    resolved.relative_to(self.root)
                except ValueError:
                    result = (
                        None,
                        ContextOmissionReason.OUTSIDE_REPOSITORY,
                        "Source path resolves outside the repository root.",
                    )
                else:
                    try:
                        raw = resolved.read_bytes()
                        if b"\x00" in raw:
                            raise ValueError("binary source contains NUL bytes")
                        result = (raw.decode("utf-8"), None, None)
                    except ValueError as error:
                        result = (None, ContextOmissionReason.UNSAFE_FILE, str(error))
                    except UnicodeDecodeError as error:
                        result = (
                            None,
                            ContextOmissionReason.UNSAFE_FILE,
                            f"source is not UTF-8: {error}",
                        )
                    except OSError as error:
                        result = (None, ContextOmissionReason.UNRESOLVED_SOURCE, str(error))
        self._cache[file] = result
        return result


class MigrationContextSelector:
    """Select whole, relevant evidence spans under explicit deterministic bounds."""

    def __init__(self, policy: ContextSelectionPolicy | None = None) -> None:
        self.policy = policy or ContextSelectionPolicy()

    def select(
        self,
        repository_root: Path | str,
        blast_radius: BlastRadius,
        migration_results: Iterable[MigrationResult],
        routing_decision: RoutingDecision,
        *,
        budget_characters: int | None = None,
    ) -> ContextSelection:
        if not isinstance(routing_decision, RoutingDecision):
            raise TypeError("routing_decision must be the M13 typed RoutingDecision artifact")
        limit = budget_characters or self.policy.default_budget_characters
        if limit < self.policy.minimum_budget_characters:
            raise ValueError("context budget is below the policy minimum")
        route = routing_decision.selected_strategy
        empty_budget = self._budget(limit, 0, 0, False)
        route_warning = tuple(sorted(set(routing_decision.warnings)))
        if route is RouteChoice.NO_AI:
            return self._terminal(
                ContextSelectionStatus.NOT_REQUIRED,
                empty_budget,
                route_warning
                + ("NO_AI selected by RouteForge; no AI MigrationContext was built.",),
            )
        if route is RouteChoice.NO_FEASIBLE_STRATEGY:
            reason = routing_decision.abstention.reason if routing_decision.abstention else ""
            terminal_warnings = route_warning + tuple(filter(None, (reason,)))
            return self._terminal(
                ContextSelectionStatus.NO_FEASIBLE_STRATEGY, empty_budget, terminal_warnings
            )

        reader = _SourceReader(repository_root)
        results = tuple(
            sorted(
                migration_results,
                key=lambda item: (
                    item.plan.change_id,
                    item.plan.direct_impact_id,
                    item.plan.id,
                ),
            )
        )
        candidates, omissions, required_missing, warnings = self._candidates(
            reader, blast_radius, results, routing_decision
        )
        warnings.update(route_warning)
        if route is RouteChoice.DETERMINISTIC:
            warnings.add(
                "DETERMINISTIC selected by RouteForge; context is provenance only and does "
                "not invoke AI."
            )

        deduplicated, duplicate_omissions = self._deduplicate(candidates)
        omissions.extend(duplicate_omissions)
        if required_missing:
            return self._terminal(
                ContextSelectionStatus.INCOMPLETE_EVIDENCE,
                self._budget(limit, 0, 0, bool(omissions)),
                tuple(sorted(warnings)),
                tuple(self._sort_omissions(omissions)),
            )

        required = tuple(item for item in deduplicated if item.required)
        required_size = sum(item.characters for item in required)
        required_files = {item.file for item in required if item.file is not None}
        if required_size > limit or len(required_files) > self.policy.maximum_files:
            overflow_reason = (
                ContextOmissionReason.BUDGET_EXCEEDED
                if required_size > limit
                else ContextOmissionReason.FILE_LIMIT_EXCEEDED
            )
            detail = (
                "Required API/direct-target evidence exceeds the explicit character budget."
                if overflow_reason is ContextOmissionReason.BUDGET_EXCEEDED
                else "Required API/direct-target evidence exceeds the explicit file budget."
            )
            omissions.extend(_omission(item, overflow_reason, detail) for item in required)
            return self._terminal(
                ContextSelectionStatus.INSUFFICIENT_CONTEXT_BUDGET,
                self._budget(limit, 0, 0, True),
                tuple(sorted(warnings)),
                tuple(self._sort_omissions(omissions)),
            )

        selected = list(required)
        used = required_size
        files = set(required_files)
        for candidate in (item for item in deduplicated if not item.required):
            adds_file = candidate.file is not None and candidate.file not in files
            if adds_file and len(files) >= self.policy.maximum_files:
                omissions.append(
                    _omission(
                        candidate,
                        ContextOmissionReason.FILE_LIMIT_EXCEEDED,
                        "Optional evidence exceeded the explicit file budget.",
                    )
                )
                continue
            if used + candidate.characters > limit:
                omissions.append(
                    _omission(
                        candidate,
                        ContextOmissionReason.BUDGET_EXCEEDED,
                        "Optional evidence exceeded the explicit character budget; no text was "
                        "cut.",
                    )
                )
                continue
            selected.append(candidate)
            used += candidate.characters
            if candidate.file is not None:
                files.add(candidate.file)

        budget = self._budget(limit, used, len(files), bool(omissions))
        items = self._items(selected)
        ordered_omissions = tuple(self._sort_omissions(omissions))
        summary = self._summary(
            ContextSelectionStatus.CONTEXT_READY,
            items,
            budget,
            ordered_omissions,
            tuple(sorted(warnings)),
        )
        change_ids = tuple(sorted({item.plan.change_id for item in results}))
        target_ids = tuple(sorted({item.plan.direct_impact_id for item in results}))
        repository_fingerprint = self._repository_fingerprint(blast_radius)
        route_identity = self._route_identity(routing_decision)
        context_id = _stable_id(
            "migration-context",
            MIGRATION_CONTEXT_SCHEMA_VERSION,
            self.policy.version,
            repository_fingerprint,
            change_ids,
            target_ids,
            route_identity,
            budget.model_dump(mode="json"),
            tuple(f"{item.id}:{item.content_hash}" for item in items),
        )
        manifest_payload: dict[str, object] = {
            "schema_version": MIGRATION_CONTEXT_SCHEMA_VERSION,
            "context_id": context_id,
            "selection_policy_version": self.policy.version,
            "repository_fingerprint": repository_fingerprint,
            "api_change_ids": change_ids,
            "target_ids": target_ids,
            "route_identity": route_identity,
            "budget": budget.model_dump(mode="json"),
            "selected_item_hashes": tuple(f"{item.id}:{item.content_hash}" for item in items),
        }
        manifest = ContextManifest.model_validate(
            {"checksum": _sha256(_json(manifest_payload)), **manifest_payload}
        )
        context = MigrationContext(
            id=context_id,
            selection_policy_version=self.policy.version,
            repository_fingerprint=repository_fingerprint,
            api_change_ids=change_ids,
            target_ids=target_ids,
            route_identity=route_identity,
            selected_strategy=route,
            items=items,
            omissions=ordered_omissions,
            budget=budget,
            warnings=tuple(sorted(warnings)),
            summary=summary,
            manifest=manifest,
        )
        return ContextSelection(
            status=ContextSelectionStatus.CONTEXT_READY,
            context=context,
            budget=budget,
            omissions=ordered_omissions,
            summary=summary,
            warnings=tuple(sorted(warnings)),
        )

    def _candidates(
        self,
        reader: _SourceReader,
        blast: BlastRadius,
        results: tuple[MigrationResult, ...],
        routing_decision: RoutingDecision,
    ) -> tuple[list[_Candidate], list[ContextOmission], bool, set[str]]:
        candidates: list[_Candidate] = []
        omissions: list[ContextOmission] = []
        warnings: set[str] = set(blast.warnings)
        impacts = {item.id: item for item in blast.direct_impacts}
        calls = {item.id: item for item in blast.call_sites}
        changes = {item.id: item for item in blast.changes}
        graph_nodes = {
            item.id: item for item in blast.graph.nodes
        } if blast.graph is not None else {}
        nodes_by_name = {item.qualified_name: item for item in graph_nodes.values()}
        required_missing = False

        if not results:
            omissions.append(
                _missing_omission(
                    role=ContextItemRole.MIGRATION_EVIDENCE,
                    file=None,
                    symbol=None,
                    provenance_ids=(),
                    reason=ContextOmissionReason.MISSING_EVIDENCE,
                    detail="M14 requires M10 migration evidence for a repair route.",
                    priority=5,
                )
            )
            required_missing = True

        direct_ids: set[str] = set()
        for result in results:
            plan = result.plan
            impact = impacts.get(plan.direct_impact_id)
            change = changes.get(plan.change_id)
            call = calls.get(plan.call_site_id)
            if impact is None or change is None or call is None:
                omissions.append(
                    _missing_omission(
                        role=ContextItemRole.DIRECT_API_CALL,
                        file=plan.target_file,
                        symbol=plan.target_symbol,
                        provenance_ids=(plan.id,),
                        reason=ContextOmissionReason.MISSING_EVIDENCE,
                        detail=(
                            "M10 plan does not resolve to canonical M1–M4 API-change, impact, "
                            "and call evidence."
                        ),
                        priority=2,
                    )
                )
                required_missing = True
                continue
            direct_ids.add(impact.id)
            candidates.append(self._api_change_candidate(change, impact, plan.id))
            direct_candidate, direct_omission = self._span_candidate(
                reader,
                role=ContextItemRole.DIRECT_API_CALL,
                file=call.file,
                symbol=call.owning_symbol,
                start_line=call.line,
                end_line=call.end_line,
                reason="Exact M3 HTTP call matched by M4 direct impact.",
                provenance_ids=(change.id, impact.id, call.id, plan.id),
                priority=2,
                required=True,
            )
            if direct_candidate is None:
                omissions.append(direct_omission)
                required_missing = True
            else:
                candidates.append(direct_candidate)
            target = graph_nodes.get(call.owning_symbol_id) or nodes_by_name.get(call.owning_symbol)
            if target is None:
                omissions.append(
                    _missing_omission(
                        role=ContextItemRole.TARGET_SYMBOL,
                        file=call.file,
                        symbol=call.owning_symbol,
                        provenance_ids=(impact.id, call.id, plan.id),
                        reason=ContextOmissionReason.MISSING_EVIDENCE,
                        detail="M5 graph has no static owning symbol for the direct API call.",
                        priority=3,
                    )
                )
                required_missing = True
            else:
                target_candidate, target_omission = self._span_candidate(
                    reader,
                    role=ContextItemRole.TARGET_SYMBOL,
                    file=target.file,
                    symbol=target.qualified_name,
                    start_line=target.line,
                    end_line=target.end_line,
                    reason="Containing M3 symbol for the exact direct API call.",
                    provenance_ids=(change.id, impact.id, call.id, target.id, plan.id),
                    priority=3,
                    required=True,
                )
                if target_candidate is None:
                    omissions.append(target_omission)
                    required_missing = True
                else:
                    candidates.append(target_candidate)
            candidates.append(self._request_candidate(call, change, impact, plan.id))
            candidates.append(self._migration_candidate(result))
            warnings.update(call.warnings)
            if call.url_resolution_state is not ResolutionState.EXACT:
                warnings.add(
                    f"{call.id}: URL resolution is {call.url_resolution_state.value}."
                )
            if call.request_field_resolution_state is not ResolutionState.EXACT:
                warnings.add(
                    f"{call.id}: request payload resolution is "
                    f"{call.request_field_resolution_state.value}."
                )
            if call.response_field_resolution_state is not ResolutionState.EXACT:
                warnings.add(
                    f"{call.id}: response usage resolution is "
                    f"{call.response_field_resolution_state.value}."
                )

        candidates.append(self._routing_candidate(routing_decision))
        for impacted in sorted(
            blast.impacted_symbols,
            key=lambda item: (item.distance, item.file, item.symbol, item.id),
        ):
            if (
                impacted.impact_type is not ImpactType.INDIRECT
                or impacted.distance > self.policy.maximum_caller_distance
                or not set(impacted.source_direct_impact_ids).intersection(direct_ids)
            ):
                continue
            node = graph_nodes.get(impacted.symbol_id) or nodes_by_name.get(impacted.symbol)
            if node is None:
                omissions.append(
                    _missing_omission(
                        role=ContextItemRole.CALLER_SYMBOL,
                        file=impacted.file,
                        symbol=impacted.symbol,
                        provenance_ids=(impacted.id, *impacted.source_direct_impact_ids),
                        reason=ContextOmissionReason.MISSING_EVIDENCE,
                        detail="Blast-radius caller has no static M5 symbol source span.",
                        priority=6,
                    )
                )
                continue
            caller, caller_omission = self._span_candidate(
                reader,
                role=ContextItemRole.CALLER_SYMBOL,
                file=node.file,
                symbol=node.qualified_name,
                start_line=node.line,
                end_line=node.end_line,
                reason=(
                    f"Nearest static M5/M6 caller at graph distance {impacted.distance}; "
                    "optional after direct evidence."
                ),
                provenance_ids=(impacted.id, *impacted.source_direct_impact_ids),
                priority=6,
                required=False,
                graph_distance=impacted.distance,
            )
            if caller is None:
                omissions.append(caller_omission)
            else:
                candidates.append(caller)
        return candidates, omissions, required_missing, warnings

    def _span_candidate(
        self,
        reader: _SourceReader,
        *,
        role: ContextItemRole,
        file: str,
        symbol: str,
        start_line: int,
        end_line: int,
        reason: str,
        provenance_ids: tuple[str, ...],
        priority: int,
        required: bool,
        graph_distance: int | None = None,
    ) -> tuple[_Candidate | None, ContextOmission]:
        content, omission_reason, detail = reader.span(file, start_line, end_line)
        if content is None:
            return None, _missing_omission(
                role=role,
                file=file,
                symbol=symbol,
                provenance_ids=provenance_ids,
                reason=omission_reason or ContextOmissionReason.UNRESOLVED_SOURCE,
                detail=detail or "Static source could not be selected.",
                priority=priority,
            )
        return (
            _Candidate(
                role=role,
                file=file,
                symbol=symbol,
                start_line=start_line,
                end_line=end_line,
                content=content,
                reason=reason,
                provenance_ids=tuple(sorted(set(provenance_ids))),
                priority=priority,
                required=required,
                graph_distance=graph_distance,
            ),
            _missing_omission(
                role=role,
                file=file,
                symbol=symbol,
                provenance_ids=provenance_ids,
                reason=ContextOmissionReason.UNRESOLVED_SOURCE,
                detail="Unused omission placeholder.",
                priority=priority,
            ),
        )

    @staticmethod
    def _api_change_candidate(change: APIChange, impact: DirectImpact, plan_id: str) -> _Candidate:
        content = _json(
            {
                "id": change.id,
                "category": change.category,
                "operation": {"method": change.method, "path": change.path},
                "location": change.location,
                "old_value": change.old_value,
                "new_value": change.new_value,
                "severity": change.severity,
                "certainty": change.certainty,
                "breaking_classification": change.breaking_classification,
                "compatibility_direction": change.compatibility_direction,
                "reason": change.reason,
            }
        )
        return _Candidate(
            role=ContextItemRole.API_CHANGE,
            file=None,
            symbol=None,
            start_line=None,
            end_line=None,
            content=content,
            reason=(
                "Changed API operation and old/new contract values required for migration "
                "evidence."
            ),
            provenance_ids=(change.id, impact.id, plan_id),
            priority=1,
            required=True,
        )

    @staticmethod
    def _request_candidate(
        call: APICallSite, change: APIChange, impact: DirectImpact, plan_id: str
    ) -> _Candidate:
        content = _json(
            {
                "call_site_id": call.id,
                "method": call.method,
                "resolved_host": call.resolved_host,
                "resolved_path": call.resolved_path,
                "url_resolution_state": call.url_resolution_state,
                "request_fields": call.request_fields,
                "request_field_resolution_state": call.request_field_resolution_state,
                "response_fields_used": call.response_fields_used,
                "response_field_resolution_state": call.response_field_resolution_state,
                "warnings": call.warnings,
            }
        )
        return _Candidate(
            role=ContextItemRole.REQUEST_EVIDENCE,
            file=call.file,
            symbol=call.owning_symbol,
            start_line=None,
            end_line=None,
            content=content,
            reason="M3 payload and response-use evidence for the direct API call.",
            provenance_ids=(change.id, impact.id, call.id, plan_id),
            priority=4,
            required=True,
        )

    @staticmethod
    def _migration_candidate(result: MigrationResult) -> _Candidate:
        plan = result.plan
        content = _json(
            {
                "migration_result_id": result.id,
                "plan_id": plan.id,
                "outcome": result.outcome,
                "repairability": result.repairability,
                "rule_id": plan.rule_id,
                "rule_version": plan.rule_version,
                "target_file": plan.target_file,
                "target_symbol": plan.target_symbol,
                "edit_count": len(plan.edits),
                "conflicts": tuple(conflict.kind for conflict in plan.conflicts),
                "warnings": tuple(sorted(set(plan.warnings) | set(result.summary.warnings))),
            }
        )
        return _Candidate(
            role=ContextItemRole.MIGRATION_EVIDENCE,
            file=None,
            symbol=plan.target_symbol,
            start_line=None,
            end_line=None,
            content=content,
            reason="M10 deterministic repairability, rule, conflict, and warning evidence.",
            provenance_ids=(result.id, plan.id, plan.change_id, plan.direct_impact_id),
            priority=5,
            required=True,
        )

    @staticmethod
    def _routing_candidate(decision: RoutingDecision) -> _Candidate:
        content = _json(
            {
                "decision_id": decision.decision_id,
                "selected_strategy": decision.selected_strategy,
                "router_version": decision.router_version,
                "decision_policy_version": decision.decision_policy_version,
                "model_id": decision.model_id,
                "model_artifact_checksum": decision.model_artifact_checksum,
                "selection_basis": decision.explanation.selection_basis,
                "evidence_features": decision.explanation.evidence_features,
                "warnings": decision.warnings,
                "abstention": decision.abstention.model_dump(mode="json")
                if decision.abstention is not None
                else None,
            }
        )
        return _Candidate(
            role=ContextItemRole.ROUTING_EVIDENCE,
            file=None,
            symbol=None,
            start_line=None,
            end_line=None,
            content=content,
            reason="M13 selected abstract RouteForge strategy and non-oracle decision evidence.",
            provenance_ids=(decision.decision_id,),
            priority=5,
            required=True,
        )

    @staticmethod
    def _deduplicate(
        candidates: list[_Candidate],
    ) -> tuple[tuple[_Candidate, ...], tuple[ContextOmission, ...]]:
        merged: dict[tuple[object, ...], _Candidate] = {}
        duplicates: list[ContextOmission] = []
        for candidate in sorted(
            MigrationContextSelector._ordered(candidates), key=lambda item: item.key()
        ):
            existing = merged.get(candidate.key())
            if existing is None:
                merged[candidate.key()] = candidate
                continue
            primary = min((existing, candidate), key=MigrationContextSelector._order_key)
            merged[candidate.key()] = _Candidate(
                role=primary.role,
                file=primary.file,
                symbol=primary.symbol,
                start_line=primary.start_line,
                end_line=primary.end_line,
                content=primary.content,
                reason="; ".join(sorted({existing.reason, candidate.reason})),
                provenance_ids=tuple(
                    sorted(set(existing.provenance_ids) | set(candidate.provenance_ids))
                ),
                priority=min(existing.priority, candidate.priority),
                required=existing.required or candidate.required,
                graph_distance=min(
                    (
                        item
                        for item in (existing.graph_distance, candidate.graph_distance)
                        if item is not None
                    ),
                    default=None,
                ),
            )
            duplicates.append(
                _omission(
                    candidate,
                    ContextOmissionReason.DUPLICATE,
                    "Identical source span was included once with merged provenance and reasons.",
                )
            )
        return tuple(MigrationContextSelector._ordered(merged.values())), tuple(duplicates)

    @staticmethod
    def _order_key(candidate: _Candidate) -> tuple[object, ...]:
        return (
            candidate.priority,
            candidate.graph_distance if candidate.graph_distance is not None else -1,
            candidate.file or "",
            candidate.start_line or 0,
            candidate.end_line or 0,
            candidate.role.value,
            candidate.content_hash,
        )

    @staticmethod
    def _ordered(candidates: Iterable[_Candidate]) -> tuple[_Candidate, ...]:
        return tuple(sorted(candidates, key=MigrationContextSelector._order_key))

    @staticmethod
    def _items(candidates: Iterable[_Candidate]) -> tuple[ContextItem, ...]:
        items: list[ContextItem] = []
        for rank, candidate in enumerate(MigrationContextSelector._ordered(candidates), start=1):
            items.append(
                ContextItem(
                    id=_stable_id(
                        "context-item",
                        candidate.role.value,
                        candidate.file,
                        candidate.start_line,
                        candidate.end_line,
                        candidate.content_hash,
                        candidate.provenance_ids,
                    ),
                    role=candidate.role,
                    file=candidate.file,
                    symbol=candidate.symbol,
                    start_line=candidate.start_line,
                    end_line=candidate.end_line,
                    content=candidate.content,
                    content_hash=candidate.content_hash,
                    reason_selected=candidate.reason,
                    provenance_ids=candidate.provenance_ids,
                    priority=candidate.priority,
                    rank=rank,
                    graph_distance=candidate.graph_distance,
                )
            )
        return tuple(items)

    def _budget(self, limit: int, used: int, files: int, truncated: bool) -> ContextBudget:
        return ContextBudget(
            limit_characters=limit,
            used_characters=used,
            remaining_characters=limit - used,
            file_limit=self.policy.maximum_files,
            files_used=files,
            truncated=truncated,
        )

    @staticmethod
    def _summary(
        status: ContextSelectionStatus,
        items: tuple[ContextItem, ...],
        budget: ContextBudget,
        omissions: tuple[ContextOmission, ...],
        warnings: tuple[str, ...],
    ) -> ContextSelectionSummary:
        required_roles = {
            ContextItemRole.API_CHANGE,
            ContextItemRole.DIRECT_API_CALL,
            ContextItemRole.TARGET_SYMBOL,
            ContextItemRole.REQUEST_EVIDENCE,
            ContextItemRole.MIGRATION_EVIDENCE,
            ContextItemRole.ROUTING_EVIDENCE,
        }
        return ContextSelectionSummary(
            required_items_selected=sum(item.role in required_roles for item in items),
            optional_items_selected=sum(item.role not in required_roles for item in items),
            files_represented=tuple(sorted({item.file for item in items if item.file is not None})),
            symbols_represented=tuple(sorted({item.symbol for item in items if item.symbol})),
            graph_distances_represented=tuple(
                sorted({item.graph_distance for item in items if item.graph_distance is not None})
            ),
            budget_used_characters=budget.used_characters,
            omitted_items=len(omissions),
            uncertainty_warnings=warnings,
            completeness=status,
        )

    def _terminal(
        self,
        status: ContextSelectionStatus,
        budget: ContextBudget,
        warnings: tuple[str, ...],
        omissions: tuple[ContextOmission, ...] = (),
    ) -> ContextSelection:
        summary = self._summary(status, (), budget, omissions, tuple(sorted(set(warnings))))
        return ContextSelection(
            status=status,
            budget=budget,
            omissions=omissions,
            summary=summary,
            warnings=tuple(sorted(set(warnings))),
        )

    @staticmethod
    def _sort_omissions(omissions: Iterable[ContextOmission]) -> tuple[ContextOmission, ...]:
        return tuple(
            sorted(
                omissions,
                key=lambda item: (
                    item.priority,
                    item.reason.value,
                    item.file or "",
                    item.symbol or "",
                    item.id,
                ),
            )
        )

    @staticmethod
    def _repository_fingerprint(blast: BlastRadius) -> str:
        material = tuple(
            (item.path, item.source_hash, item.state.value)
            for item in sorted(blast.files, key=lambda item: item.path)
        )
        return _sha256(_json(material))

    @staticmethod
    def _route_identity(decision: RoutingDecision) -> str:
        return _stable_id(
            "route-identity",
            decision.decision_id,
            decision.selected_strategy.value,
            decision.router_version,
            decision.decision_policy_version,
            decision.model_id,
            decision.model_artifact_checksum,
            decision.context_fingerprint,
        )


def select_migration_context(
    repository_root: Path | str,
    blast_radius: BlastRadius,
    migration_results: Iterable[MigrationResult],
    routing_decision: RoutingDecision,
    *,
    budget_characters: int | None = None,
    policy: ContextSelectionPolicy | None = None,
) -> ContextSelection:
    """Select static evidence only; this function never executes repository source."""

    return MigrationContextSelector(policy).select(
        repository_root,
        blast_radius,
        migration_results,
        routing_decision,
        budget_characters=budget_characters,
    )
