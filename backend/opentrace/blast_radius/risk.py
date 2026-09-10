"""Centralized deterministic M6 heuristic risk policy."""

import hashlib
from dataclasses import dataclass, field

from opentrace.blast_radius.models import (
    BlastRadius,
    RiskAssessment,
    RiskContribution,
    RiskLevel,
)
from opentrace.code_analysis.models import ResolutionState
from opentrace.contracts.models import APIChange, ChangeSeverity
from opentrace.impact.models import DirectImpact


@dataclass(frozen=True)
class RiskPolicy:
    version: str = "heuristic-risk-v1"
    severity_points: dict[ChangeSeverity, float] = field(
        default_factory=lambda: {
            ChangeSeverity.LOW: 10.0,
            ChangeSeverity.MEDIUM: 25.0,
            ChangeSeverity.HIGH: 40.0,
            ChangeSeverity.CRITICAL: 50.0,
        }
    )
    direct_evidence_weight: float = 20.0
    direct_symbol_weight: float = 5.0
    indirect_symbol_weight: float = 5.0
    distance_weight: float = 5.0
    incomplete_graph_weight: float = 5.0
    partial_resolution_weight: float = 3.0
    low_max: float = 24.0
    medium_max: float = 49.0
    high_max: float = 74.0
    maximum_distance_for_score: int = 5


class HeuristicRiskAssessor:
    """Compute explainable prioritization risk; never a probability."""

    def __init__(self, policy: RiskPolicy | None = None) -> None:
        self.policy = policy or RiskPolicy()

    def assess(
        self,
        blast_radius: BlastRadius,
        changes: tuple[APIChange, ...] | list[APIChange],
        direct_impacts: tuple[DirectImpact, ...] | list[DirectImpact],
    ) -> RiskAssessment:
        change_index = {change.id: change for change in changes}
        source_changes = tuple(
            change_index[change_id]
            for change_id in blast_radius.source_change_ids
            if change_id in change_index
        )
        contributions: list[RiskContribution] = []
        severity = max(
            (self.policy.severity_points.get(change.severity, 0.0) for change in source_changes),
            default=0.0,
        )
        if source_changes:
            severity_name = max(
                source_changes,
                key=lambda change: self.policy.severity_points.get(change.severity, 0.0),
            ).severity.value
            contributions.append(
                RiskContribution(
                    feature="change_severity",
                    observed_value=severity_name,
                    contribution=severity,
                    explanation=f"Highest source change severity is {severity_name}.",
                )
            )
        impact_score = max((impact.impact_score for impact in direct_impacts), default=0.0)
        direct_evidence = impact_score * self.policy.direct_evidence_weight
        contributions.append(
            RiskContribution(
                feature="direct_evidence",
                observed_value=impact_score,
                contribution=direct_evidence,
                explanation="The strongest M4 direct-impact score contributes bounded evidence.",
            )
        )
        direct_symbols = min(blast_radius.direct_symbol_count, 3) * self.policy.direct_symbol_weight
        contributions.append(
            RiskContribution(
                feature="direct_symbol_count",
                observed_value=blast_radius.direct_symbol_count,
                contribution=direct_symbols,
                explanation="Directly exposed symbols contribute to prioritization.",
            )
        )
        indirect_symbols = (
            min(blast_radius.indirect_symbol_count, 5) * self.policy.indirect_symbol_weight
        )
        contributions.append(
            RiskContribution(
                feature="indirect_symbol_count",
                observed_value=blast_radius.indirect_symbol_count,
                contribution=indirect_symbols,
                explanation="Upstream graph-reachable symbols contribute to prioritization.",
            )
        )
        distance = min(
            blast_radius.maximum_distance, self.policy.maximum_distance_for_score
        ) * self.policy.distance_weight
        contributions.append(
            RiskContribution(
                feature="maximum_distance",
                observed_value=blast_radius.maximum_distance,
                contribution=distance,
                explanation="The maximum observed upstream distance contributes bounded breadth.",
            )
        )
        incomplete = 0.0
        if blast_radius.coverage.calls_unresolved or blast_radius.coverage.files_failed:
            incomplete = self.policy.incomplete_graph_weight
            contributions.append(
                RiskContribution(
                    feature="incomplete_graph_coverage",
                    observed_value=True,
                    contribution=incomplete,
                    explanation=(
                        "Unresolved calls or failed files mean the graph may be incomplete."
                    ),
                )
            )
        partial = 0.0
        if any(
            symbol.certainty is ResolutionState.PARTIAL
            for symbol in blast_radius.impacted_symbols
        ):
            partial = self.policy.partial_resolution_weight
            contributions.append(
                RiskContribution(
                    feature="partial_resolution",
                    observed_value=True,
                    contribution=partial,
                    explanation="Partial direct or propagation evidence remains uncertain.",
                )
            )
        score = min(
            100.0,
            max(
                0.0,
                severity
                + direct_evidence
                + direct_symbols
                + indirect_symbols
                + distance
                + incomplete
                + partial,
            ),
        )
        level = self._level(score)
        certainty = (
            blast_radius.impacted_symbols[0].certainty
            if blast_radius.impacted_symbols
            else ResolutionState.UNRESOLVED
        )
        if any(
            symbol.certainty is ResolutionState.UNRESOLVED
            for symbol in blast_radius.impacted_symbols
        ):
            certainty = ResolutionState.UNRESOLVED
        elif any(
            symbol.certainty is ResolutionState.PARTIAL
            for symbol in blast_radius.impacted_symbols
        ):
            certainty = ResolutionState.PARTIAL
        warnings = blast_radius.warnings
        return RiskAssessment(
            id="risk-" + _digest(self.policy.version, blast_radius.id),
            target_id=blast_radius.id,
            policy_version=self.policy.version,
            change_ids=blast_radius.source_change_ids,
            risk_score=score,
            risk_level=level,
            contributions=tuple(contributions),
            certainty=certainty,
            warnings=warnings,
        )

    def _level(self, score: float) -> RiskLevel:
        if score <= self.policy.low_max:
            return RiskLevel.LOW
        if score <= self.policy.medium_max:
            return RiskLevel.MEDIUM
        if score <= self.policy.high_max:
            return RiskLevel.HIGH
        return RiskLevel.CRITICAL


def _digest(*parts: object) -> str:
    return hashlib.sha256("\x1f".join(str(part) for part in parts).encode()).hexdigest()[:24]
