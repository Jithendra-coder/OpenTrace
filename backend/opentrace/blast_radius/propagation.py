"""Bounded reverse propagation over the M5 caller graph."""

from __future__ import annotations

import hashlib
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass

from opentrace.blast_radius.models import (
    BlastRadius,
    ImpactedSymbol,
    ImpactType,
    PropagationEvidence,
)
from opentrace.blast_radius.risk import HeuristicRiskAssessor, RiskPolicy
from opentrace.code_analysis.call_models import CallEdge, StaticCallGraph
from opentrace.code_analysis.models import (
    APICallSite,
    CodeSymbol,
    RepositoryFile,
    ResolutionState,
)
from opentrace.contracts.models import APIChange
from opentrace.impact.models import DirectImpact


@dataclass(frozen=True)
class PropagationPolicy:
    version: str = "blast-radius-v1"


@dataclass(frozen=True)
class _Path:
    distance: int
    names: tuple[str, ...]
    edge_ids: tuple[str, ...]
    resolution_state: ResolutionState


class BlastRadiusPropagator:
    """Propagate M4 direct seeds to upstream callers using reverse CALLS edges."""

    def __init__(
        self,
        policy: PropagationPolicy | None = None,
        risk_policy: RiskPolicy | None = None,
    ) -> None:
        self.policy = policy or PropagationPolicy()
        self.risk_assessor = HeuristicRiskAssessor(risk_policy)

    def analyze(
        self,
        direct_impacts: tuple[DirectImpact, ...] | list[DirectImpact],
        graph: StaticCallGraph,
        *,
        changes: tuple[APIChange, ...] | list[APIChange] = (),
        call_sites: tuple[APICallSite, ...] | list[APICallSite] = (),
        files: tuple[RepositoryFile, ...] | list[RepositoryFile] = (),
        unmatched_change_ids: tuple[str, ...] | list[str] = (),
    ) -> BlastRadius:
        nodes = {node.id: node for node in graph.nodes}
        call_site_symbols = {call.id: call.owning_symbol_id for call in call_sites}
        direct_sorted = tuple(sorted(direct_impacts, key=lambda item: (item.id, item.symbol)))
        source_paths: dict[str, dict[str, _Path]] = {}
        source_direct: dict[str, set[str]] = {}
        source_changes: dict[str, set[str]] = {}
        direct_scores: dict[str, float] = {}
        warnings = list(graph.warnings)
        if graph.coverage.calls_unresolved:
            warnings.append(
                f"{graph.coverage.calls_unresolved} unresolved call(s); blast radius may be "
                "incomplete."
            )
        if graph.coverage.files_failed:
            warnings.append(
                f"{graph.coverage.files_failed} failed file(s); blast radius may be incomplete."
            )
        incoming = _incoming_edges(graph.edges)
        for direct in direct_sorted:
            symbol_id = call_site_symbols.get(direct.call_site_id)
            if symbol_id is None:
                symbol_id = next(
                    (
                        node.id
                        for node in graph.nodes
                        if node.file == direct.file and node.qualified_name == direct.symbol
                    ),
                    None,
                )
            if symbol_id not in nodes:
                warnings.append(f"Direct impact {direct.id} has no matching graph symbol.")
                continue
            direct_node = nodes[symbol_id]
            source_paths.setdefault(symbol_id, {})[direct.id] = _Path(
                distance=0,
                names=(direct_node.qualified_name,),
                edge_ids=(),
                resolution_state=direct.certainty,
            )
            source_direct.setdefault(symbol_id, set()).add(direct.id)
            source_changes.setdefault(symbol_id, set()).add(direct.change_id)
            direct_scores[symbol_id] = max(direct_scores.get(symbol_id, 0.0), direct.impact_score)
            self._walk_source(
                symbol_id,
                direct,
                nodes,
                incoming,
                source_paths,
                source_direct,
                source_changes,
            )
        impacted: list[ImpactedSymbol] = []
        for symbol_id, paths in source_paths.items():
            node = nodes[symbol_id]
            evidence = tuple(
                _propagation_evidence(source_id, path, direct_sorted)
                for source_id, path in sorted(
                    paths.items(), key=lambda item: (item[1].distance, item[1].names, item[0])
                )
            )
            distance = min(path.distance for path in paths.values())
            certainty = _combine_states(path.resolution_state for path in paths.values())
            is_direct = distance == 0 and any(path.distance == 0 for path in paths.values())
            direct_ids = tuple(sorted(source_direct.get(symbol_id, ())))
            change_ids = tuple(sorted(source_changes.get(symbol_id, ())))
            symbol_warnings = tuple(
                sorted(
                    {
                        warning
                        for direct in direct_sorted
                        if direct.id in direct_ids
                        for warning in direct.warnings
                    }
                )
            )
            impacted.append(
                ImpactedSymbol(
                    id="impacted-" + _digest(self.policy.version, symbol_id, *direct_ids),
                    symbol_id=symbol_id,
                    file=node.file,
                    symbol=node.qualified_name,
                    impact_type=ImpactType.DIRECT if is_direct else ImpactType.INDIRECT,
                    distance=distance,
                    source_direct_impact_ids=direct_ids,
                    source_change_ids=change_ids,
                    propagation=evidence,
                    direct_impact_score=direct_scores.get(symbol_id),
                    certainty=certainty,
                    warnings=symbol_warnings,
                )
            )
        impacted = sorted(
            impacted,
            key=lambda item: (
                0 if item.impact_type is ImpactType.DIRECT else 1,
                item.distance,
                item.file,
                item.symbol,
                item.id,
            ),
        )
        matched_direct_ids = {
            direct_id for direct_ids in source_direct.values() for direct_id in direct_ids
        }
        source_direct_ids = tuple(
            sorted(direct.id for direct in direct_sorted if direct.id in matched_direct_ids)
        )
        source_change_ids = tuple(
            sorted({direct.change_id for direct in direct_sorted if direct.id in source_direct_ids})
        )
        result = BlastRadius(
            id="blast-radius-" + _digest(self.policy.version, *source_direct_ids),
            policy_version=self.policy.version,
            changes=tuple(sorted(changes, key=lambda item: item.id)),
            call_sites=tuple(sorted(call_sites, key=lambda item: (item.file, item.line, item.id))),
            files=tuple(sorted(files, key=lambda item: item.path)),
            direct_impacts=direct_sorted,
            graph=graph,
            impacted_symbols=tuple(impacted),
            unmatched_change_ids=tuple(sorted(unmatched_change_ids)),
            source_direct_impact_ids=source_direct_ids,
            source_change_ids=source_change_ids,
            direct_symbol_count=sum(item.impact_type is ImpactType.DIRECT for item in impacted),
            indirect_symbol_count=sum(item.impact_type is ImpactType.INDIRECT for item in impacted),
            maximum_distance=max((item.distance for item in impacted), default=0),
            coverage=graph.coverage,
            warnings=tuple(sorted(set(warnings))),
        )
        risk = self.risk_assessor.assess(result, tuple(changes), direct_sorted)
        return result.model_copy(update={"risk_assessment": risk})

    def _walk_source(
        self,
        seed_id: str,
        direct: DirectImpact,
        nodes: dict[str, CodeSymbol],
        incoming: dict[str, tuple[CallEdge, ...]],
        paths: dict[str, dict[str, _Path]],
        source_direct: dict[str, set[str]],
        source_changes: dict[str, set[str]],
    ) -> None:
        queue: deque[tuple[str, _Path]] = deque([(seed_id, paths[seed_id][direct.id])])
        while queue:
            current_id, current_path = queue.popleft()
            for edge in incoming.get(current_id, ()):
                candidate = _Path(
                    distance=current_path.distance + 1,
                    names=(nodes[edge.caller_symbol_id].qualified_name, *current_path.names),
                    edge_ids=(edge.id, *current_path.edge_ids),
                    resolution_state=_combine_states(
                        (current_path.resolution_state, edge.resolution_state)
                    ),
                )
                existing = paths.setdefault(edge.caller_symbol_id, {}).get(direct.id)
                if existing is not None and not _path_precedes(candidate, existing):
                    continue
                paths[edge.caller_symbol_id][direct.id] = candidate
                source_direct.setdefault(edge.caller_symbol_id, set()).add(direct.id)
                source_changes.setdefault(edge.caller_symbol_id, set()).add(direct.change_id)
                queue.append((edge.caller_symbol_id, candidate))


def analyze_blast_radius(
    direct_impacts: tuple[DirectImpact, ...] | list[DirectImpact],
    graph: StaticCallGraph,
    *,
    changes: tuple[APIChange, ...] | list[APIChange] = (),
    call_sites: tuple[APICallSite, ...] | list[APICallSite] = (),
    files: tuple[RepositoryFile, ...] | list[RepositoryFile] = (),
    unmatched_change_ids: tuple[str, ...] | list[str] = (),
    policy: PropagationPolicy | None = None,
    risk_policy: RiskPolicy | None = None,
) -> BlastRadius:
    return BlastRadiusPropagator(policy, risk_policy).analyze(
        direct_impacts,
        graph,
        changes=changes,
        call_sites=call_sites,
        files=files,
        unmatched_change_ids=unmatched_change_ids,
    )


def _incoming_edges(edges: tuple[CallEdge, ...]) -> dict[str, tuple[CallEdge, ...]]:
    incoming: dict[str, list[CallEdge]] = {}
    for edge in edges:
        incoming.setdefault(edge.callee_symbol_id, []).append(edge)
    return {
        target: tuple(
            sorted(items, key=lambda edge: (edge.caller_symbol, edge.line, edge.column, edge.id))
        )
        for target, items in incoming.items()
    }


def _path_precedes(candidate: _Path, existing: _Path) -> bool:
    return (candidate.distance, candidate.names, candidate.edge_ids) < (
        existing.distance,
        existing.names,
        existing.edge_ids,
    )


def _propagation_evidence(
    source_id: str, path: _Path, direct_impacts: tuple[DirectImpact, ...]
) -> PropagationEvidence:
    direct = next(item for item in direct_impacts if item.id == source_id)
    return PropagationEvidence(
        id="propagation-" + _digest(source_id, *path.edge_ids, *path.names),
        source_direct_impact_id=source_id,
        source_change_id=direct.change_id,
        path=path.names,
        edge_ids=path.edge_ids,
        distance=path.distance,
        resolution_state=path.resolution_state,
        explanation=(
            "Direct M4 evidence seeds this symbol."
            if path.distance == 0
            else f"Static CALLS path reaches the direct symbol in {path.distance} upstream edge(s)."
        ),
    )


def _combine_states(states: Iterable[ResolutionState]) -> ResolutionState:
    values = tuple(states)
    if ResolutionState.UNRESOLVED in values:
        return ResolutionState.UNRESOLVED
    if ResolutionState.PARTIAL in values:
        return ResolutionState.PARTIAL
    return ResolutionState.EXACT


def _digest(*parts: object) -> str:
    return hashlib.sha256("\x1f".join(str(part) for part in parts).encode()).hexdigest()[:24]
