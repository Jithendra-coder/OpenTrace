"""Provider-independent, offline RouteForge dataset contracts."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from opentrace.code_analysis.models import ResolutionState

ROUTEFORGE_SCHEMA_VERSION = "routeforge-dataset-v1"
ROUTEFORGE_DATASET_VERSION = "routeforge-dataset-v1"
ROUTEFORGE_GENERATOR_VERSION = "routeforge-offline-generator-v1"
ROUTEFORGE_OBJECTIVE_VERSION = "routeforge-objective-v1"
ROUTEFORGE_FEATURE_SCHEMA_VERSION = "routeforge-features-v1"
ROUTEFORGE_STRATEGY_TAXONOMY_VERSION = "routeforge-strategies-v1"


class CanonicalModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    def canonical_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json", exclude_none=True),
            sort_keys=True,
            separators=(",", ":"),
        )


class RouteForgeStrategy(StrEnum):
    NO_AI = "NO_AI"
    DETERMINISTIC = "DETERMINISTIC"
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    STRONG = "STRONG"


class OutcomeProvenance(StrEnum):
    OBSERVED_DETERMINISTIC = "OBSERVED_DETERMINISTIC"
    SYNTHETIC_ORACLE = "SYNTHETIC_ORACLE"
    CURATED_ORACLE = "CURATED_ORACLE"


class StrategyOutcomeStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class RouteChoice(StrEnum):
    NO_AI = "NO_AI"
    DETERMINISTIC = "DETERMINISTIC"
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    STRONG = "STRONG"
    NO_FEASIBLE_STRATEGY = "NO_FEASIBLE_STRATEGY"


class DatasetFamily(StrEnum):
    SYNTHETIC = "SYNTHETIC"
    CURATED_ADVERSARIAL = "CURATED_ADVERSARIAL"
    REALISTIC = "REALISTIC"


class FeatureOrigin(StrEnum):
    OBSERVED_M1_M10 = "OBSERVED_M1_M10"
    SCENARIO_AUTHORED = "SCENARIO_AUTHORED"


class SplitPartition(StrEnum):
    TRAIN = "TRAIN"
    VALIDATION = "VALIDATION"
    TEST = "TEST"


class CostSemantics(StrEnum):
    SYNTHETIC_RELATIVE_UNITS = "SYNTHETIC_RELATIVE_UNITS"


class LatencySemantics(StrEnum):
    SYNTHETIC_RELATIVE_UNITS = "SYNTHETIC_RELATIVE_UNITS"


class RouteForgeFeatures(CanonicalModel):
    """Allowlisted information available before a strategy is selected."""

    ALLOWLIST: ClassVar[tuple[str, ...]] = (
        "change_category",
        "change_severity",
        "change_certainty",
        "breaking_classification",
        "compatibility_direction",
        "url_resolution_state",
        "request_resolution_state",
        "response_resolution_state",
        "direct_impact_count",
        "direct_reference",
        "indirect_exposure_count",
        "maximum_graph_distance",
        "direct_caller_count",
        "upstream_caller_count",
        "coverage_unresolved_calls",
        "coverage_failed_files",
        "m10_outcome",
        "m10_repairability",
        "deterministic_rule_available",
        "supported_rule_count",
        "expected_edit_count",
        "target_file_count",
        "repair_conflict_count",
        "shared_payload_ambiguity",
        "dynamic_payload",
        "nested_literal",
        "ambiguity_flag_count",
        "source_shape",
    )

    change_category: str
    change_severity: str
    change_certainty: str
    breaking_classification: str
    compatibility_direction: str
    url_resolution_state: ResolutionState
    request_resolution_state: ResolutionState
    response_resolution_state: ResolutionState
    direct_impact_count: int = Field(ge=0)
    direct_reference: bool
    indirect_exposure_count: int = Field(ge=0)
    maximum_graph_distance: int = Field(ge=0)
    direct_caller_count: int = Field(ge=0)
    upstream_caller_count: int = Field(ge=0)
    coverage_unresolved_calls: int = Field(ge=0)
    coverage_failed_files: int = Field(ge=0)
    m10_outcome: str
    m10_repairability: str
    deterministic_rule_available: bool
    supported_rule_count: int = Field(ge=0)
    expected_edit_count: int = Field(ge=0)
    target_file_count: int = Field(ge=0)
    repair_conflict_count: int = Field(ge=0)
    shared_payload_ambiguity: bool
    dynamic_payload: bool
    nested_literal: bool
    ambiguity_flag_count: int = Field(ge=0)
    source_shape: str

    @model_validator(mode="after")
    def allowlisted_fields_only(self) -> RouteForgeFeatures:
        if set(self.model_dump()) != set(self.ALLOWLIST):
            raise ValueError("RouteForge feature schema contains a non-allowlisted field")
        return self


class M10ObservedEvidence(CanonicalModel):
    """Observed deterministic facts, distinct from synthetic strategy outcomes."""

    outcome: str
    repairability: str
    rule_id: str | None = None
    candidate_generated: bool = False
    edit_count: int = Field(default=0, ge=0)
    target_file_count: int = Field(default=0, ge=0)
    conflict_count: int = Field(default=0, ge=0)
    warnings: tuple[str, ...] = ()


class RoutingDecisionContext(CanonicalModel):
    """Migration identity and only pre-decision routing evidence."""

    id: str
    scenario_id: str
    decision_group_id: str
    migration_id: str
    repository_family_id: str
    api_family_id: str
    mutation_family: str
    template_family_id: str
    feature_schema_version: str = ROUTEFORGE_FEATURE_SCHEMA_VERSION
    feature_origin: FeatureOrigin
    features: RouteForgeFeatures
    m10_evidence: M10ObservedEvidence
    no_repair_required: bool = False


class StrategyOutcome(CanonicalModel):
    """One strategy-level offline outcome; never a validated provider result."""

    id: str
    decision_group_id: str
    strategy: RouteForgeStrategy
    outcome: StrategyOutcomeStatus
    provenance: OutcomeProvenance
    producer: str
    candidate_generated: bool = False
    synthetic_cost_units: float | None = Field(default=None, ge=0.0)
    synthetic_latency_units: float | None = Field(default=None, ge=0.0)
    quality_units: float | None = Field(default=None, ge=0.0)
    no_repair_required: bool = False
    notes: str

    @model_validator(mode="after")
    def validate_provenance(self) -> StrategyOutcome:
        if self.provenance is OutcomeProvenance.OBSERVED_DETERMINISTIC:
            if self.strategy is not RouteForgeStrategy.DETERMINISTIC:
                raise ValueError("observed deterministic evidence is only valid for DETERMINISTIC")
            if self.synthetic_cost_units is not None or self.synthetic_latency_units is not None:
                raise ValueError("observed deterministic evidence cannot carry synthetic units")
        elif self.producer == "m10:deterministic-migration-v1":
            raise ValueError("synthetic/oracle outcomes cannot use the deterministic observed producer")
        if self.outcome is StrategyOutcomeStatus.UNKNOWN and self.no_repair_required:
            raise ValueError("no-repair rows must be explicit NOT_APPLICABLE or SUCCESS")
        return self


class RoutingObjective(CanonicalModel):
    version: str = ROUTEFORGE_OBJECTIVE_VERSION
    required_outcome: StrategyOutcomeStatus = StrategyOutcomeStatus.SUCCESS
    max_latency_units: float = Field(default=4.0, ge=0.0)
    minimum_quality_units: float = Field(default=70.0, ge=0.0)
    cost_semantics: CostSemantics = CostSemantics.SYNTHETIC_RELATIVE_UNITS
    latency_semantics: LatencySemantics = LatencySemantics.SYNTHETIC_RELATIVE_UNITS
    tie_break_order: tuple[RouteForgeStrategy, ...] = (
        RouteForgeStrategy.NO_AI,
        RouteForgeStrategy.DETERMINISTIC,
        RouteForgeStrategy.SMALL,
        RouteForgeStrategy.MEDIUM,
        RouteForgeStrategy.STRONG,
    )

    @model_validator(mode="after")
    def complete_tie_break(self) -> RoutingObjective:
        if set(self.tie_break_order) != set(RouteForgeStrategy):
            raise ValueError("objective tie-break order must contain every strategy exactly once")
        return self


class RouteForgeScenario(CanonicalModel):
    scenario_id: str
    scenario_fingerprint: str
    source_fingerprint: str
    routing_feature_fingerprint: str
    template_fingerprint: str
    family: DatasetFamily
    repository_family_id: str
    api_family_id: str
    migration_id: str
    mutation_family: str
    template_family_id: str
    decision_group_id: str
    context: RoutingDecisionContext
    outcomes: tuple[StrategyOutcome, ...]
    feasible_strategies: tuple[RouteForgeStrategy, ...] = ()
    preferred_strategy: RouteChoice
    outcome_table_fingerprint: str
    provenance: str
    tags: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_group(self) -> RouteForgeScenario:
        if self.context.scenario_id != self.scenario_id:
            raise ValueError("context scenario identity mismatch")
        if self.context.decision_group_id != self.decision_group_id:
            raise ValueError("context decision-group identity mismatch")
        if {outcome.strategy for outcome in self.outcomes} != set(RouteForgeStrategy):
            raise ValueError("every scenario must contain one outcome for every strategy")
        if any(outcome.decision_group_id != self.decision_group_id for outcome in self.outcomes):
            raise ValueError("strategy outcomes must remain in one decision group")
        return self


class RouteForgeDatasetRow(CanonicalModel):
    id: str
    schema_version: str = ROUTEFORGE_SCHEMA_VERSION
    dataset_version: str = ROUTEFORGE_DATASET_VERSION
    scenario_id: str
    scenario_fingerprint: str
    decision_group_id: str
    split_group_id: str
    split_partition: SplitPartition
    context_id: str
    strategy: RouteForgeStrategy
    outcome: StrategyOutcomeStatus
    outcome_provenance: OutcomeProvenance
    producer: str
    candidate_generated: bool
    synthetic_cost_units: float | None = Field(default=None, ge=0.0)
    synthetic_latency_units: float | None = Field(default=None, ge=0.0)
    quality_units: float | None = Field(default=None, ge=0.0)
    features: RouteForgeFeatures
    preferred_strategy: RouteChoice
    feasible_strategies: tuple[RouteForgeStrategy, ...] = ()


class DuplicateAudit(CanonicalModel):
    scenario_fingerprint_duplicates: int = Field(ge=0)
    source_fingerprint_duplicates: int = Field(ge=0)
    routing_feature_clone_groups: int = Field(ge=0)
    outcome_table_duplicates: int = Field(ge=0)
    template_clone_groups: int = Field(ge=0)


class RouteForgeConfig(CanonicalModel):
    seed: int = 1101
    dataset_version: str = ROUTEFORGE_DATASET_VERSION
    generator_version: str = ROUTEFORGE_GENERATOR_VERSION
    objective_version: str = ROUTEFORGE_OBJECTIVE_VERSION
    feature_schema_version: str = ROUTEFORGE_FEATURE_SCHEMA_VERSION
    strategy_taxonomy_version: str = ROUTEFORGE_STRATEGY_TAXONOMY_VERSION
    include_canonical_m10: bool = True


class RouteForgeManifest(CanonicalModel):
    schema_version: str = ROUTEFORGE_SCHEMA_VERSION
    dataset_version: str = ROUTEFORGE_DATASET_VERSION
    generator_version: str = ROUTEFORGE_GENERATOR_VERSION
    objective: RoutingObjective
    strategy_taxonomy_version: str = ROUTEFORGE_STRATEGY_TAXONOMY_VERSION
    feature_schema_version: str = ROUTEFORGE_FEATURE_SCHEMA_VERSION
    seed: int
    config: RouteForgeConfig
    scenario_count: int = Field(ge=0)
    decision_group_count: int = Field(ge=0)
    strategy_outcome_row_count: int = Field(ge=0)
    strategy_counts: dict[str, int] = Field(default_factory=dict)
    preferred_strategy_counts: dict[str, int] = Field(default_factory=dict)
    strategy_outcome_counts: dict[str, dict[str, int]] = Field(default_factory=dict)
    provenance_counts: dict[str, int] = Field(default_factory=dict)
    repairability_counts: dict[str, int] = Field(default_factory=dict)
    change_category_counts: dict[str, int] = Field(default_factory=dict)
    api_family_counts: dict[str, int] = Field(default_factory=dict)
    repository_family_counts: dict[str, int] = Field(default_factory=dict)
    template_family_counts: dict[str, int] = Field(default_factory=dict)
    resolution_state_counts: dict[str, int] = Field(default_factory=dict)
    duplicate_audit: DuplicateAudit
    content_sha256: str


class RouteForgeDataset(CanonicalModel):
    manifest: RouteForgeManifest
    scenarios: tuple[RouteForgeScenario, ...]
    rows: tuple[RouteForgeDatasetRow, ...]


def stable_id(prefix: str, *parts: object) -> str:
    payload = json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str)
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def derive_preferred_strategy(
    outcomes: tuple[StrategyOutcome, ...],
    objective: RoutingObjective,
    *,
    no_repair_required: bool,
) -> tuple[RouteChoice, tuple[RouteForgeStrategy, ...]]:
    if no_repair_required:
        return RouteChoice.NO_AI, (RouteForgeStrategy.NO_AI,)
    feasible = tuple(
        outcome.strategy
        for outcome in outcomes
        if outcome.strategy is not RouteForgeStrategy.NO_AI
        and outcome.outcome is objective.required_outcome
        and outcome.synthetic_cost_units is not None
        and outcome.synthetic_latency_units is not None
        and outcome.quality_units is not None
        and outcome.synthetic_latency_units <= objective.max_latency_units
        and outcome.quality_units >= objective.minimum_quality_units
    )
    if not feasible:
        return RouteChoice.NO_FEASIBLE_STRATEGY, ()
    order = {strategy: index for index, strategy in enumerate(objective.tie_break_order)}
    candidates = [outcome for outcome in outcomes if outcome.strategy in feasible]
    selected = min(
        candidates,
        key=lambda outcome: (
            outcome.synthetic_cost_units or 0.0,
            outcome.synthetic_latency_units or 0.0,
            -(outcome.quality_units or 0.0),
            order[outcome.strategy],
        ),
    )
    return RouteChoice(selected.strategy.value), feasible
