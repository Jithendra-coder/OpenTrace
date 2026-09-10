"""Gate C evidence dataset generation and evaluation over frozen M13 semantics."""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, cast

import numpy as np
from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]
from xgboost import XGBClassifier

from opentrace.code_analysis.models import ResolutionState
from opentrace.routeforge.baselines import (
    REPAIR_STRATEGIES,
    STRATEGY_ORDER,
    RouteForgeFeatureEncoder,
    _always,
    _eligible,
    _evaluate_policy,
    _outcome_metrics,
    _partition_rows,
    _rule_policy,
    _scenario_by_group,
    _score,
)
from opentrace.routeforge.generator import (
    RouteForgeDatasetGenerator,
    _OutcomeSpec,
    _ScenarioPlan,
)
from opentrace.routeforge.models import (
    DatasetFamily,
    DuplicateAudit,
    FeatureOrigin,
    M10ObservedEvidence,
    OutcomeProvenance,
    RouteChoice,
    RouteForgeConfig,
    RouteForgeDataset,
    RouteForgeDatasetRow,
    RouteForgeFeatures,
    RouteForgeManifest,
    RouteForgeScenario,
    RouteForgeStrategy,
    RoutingObjective,
    SplitPartition,
    StrategyOutcomeStatus,
    stable_id,
)
from opentrace.routeforge.router import (
    ROUTEFORGE_DECISION_POLICY_VERSION,
    ROUTEFORGE_MODEL_ID,
    ROUTEFORGE_ROUTER_ARTIFACT_SCHEMA,
    ROUTEFORGE_ROUTER_VERSION,
    ROUTEFORGE_SCORER_VERSION,
    RouteForgeRouter,
    RoutingRequest,
    _applicability,
    _fit_primary_artifact,
    _policy_metrics,
    _validation_evaluation,
    load_model_artifact,
    save_model_artifact,
)
from opentrace.routeforge.serialization import (
    content_checksum,
    read_artifacts,
    validate_dataset,
    write_artifacts,
)

GATE_C_DATASET_VERSION = "routeforge-dataset-v2"
GATE_C_GENERATOR_VERSION = "routeforge-gate-c-generator-v1"
GATE_C_PROTOCOL_VERSION = "routeforge-gate-c-evidence-v1"
GATE_C_SEED = 2301
GATE_C_SPLIT_SEED = 2302
GATE_C_RANDOM_SEED = 2303
GATE_C_LABEL_SHUFFLE_SEED = 2304
GATE_C_BOOTSTRAP_SEED = 2305
GATE_C_GROUP_COUNT = 64
GATE_C_TRAIN_GROUPS = 40
GATE_C_VALIDATION_GROUPS = 12
GATE_C_TEST_GROUPS = 12
GATE_C_BOOTSTRAP_REPLICATES = 1000
GATE_C_TEST_SEAL_MESSAGE = "FORMAL TEST ACCESSED ONCE AFTER PRE-TEST MANIFEST FREEZE"


@dataclass(frozen=True)
class _GateCOutcomeSpec:
    status: StrategyOutcomeStatus
    provenance: OutcomeProvenance
    producer: str
    cost: float | None
    latency: float | None
    quality: float | None
    candidate_generated: bool = False
    no_repair_required: bool = False
    notes: str = "Offline scenario outcome; not a validated provider result."


@dataclass(frozen=True)
class GateCDatasetResult:
    dataset: RouteForgeDataset
    protocol_checksum: str
    cross_partition_audit: dict[str, object]
    historical_overlap: dict[str, int]


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _write_json(path: Path, value: object) -> None:
    path.write_text(_json(value) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, values: Sequence[object]) -> None:
    path.write_text("".join(f"{_json(value)}\n" for value in values), encoding="utf-8")


def _partition_for_index(index: int) -> SplitPartition:
    if index < GATE_C_TRAIN_GROUPS:
        return SplitPartition.TRAIN
    if index < GATE_C_TRAIN_GROUPS + GATE_C_VALIDATION_GROUPS:
        return SplitPartition.VALIDATION
    return SplitPartition.TEST


def _family_value(prefix: str, index: int, partition: SplitPartition) -> str:
    if prefix in {"api-v2", "repository-v2"}:
        family_index = (
            index % 6 if partition is not SplitPartition.TEST else 6 + index % 2
        )
        return f"{prefix}-{family_index:02d}"
    if prefix == "template-v2":
        family_index = (
            index % 20
            if partition is SplitPartition.TRAIN
            else (
                20 + index % 6
                if partition is SplitPartition.VALIDATION
                else 26 + index % 6
            )
        )
        return f"{prefix}-{family_index:02d}"
    family_index = index % 6 if partition is not SplitPartition.TEST else 6 + index % 2
    return f"{prefix}-{family_index:02d}"


def _features_for(
    index: int, preferred: RouteChoice, partition: SplitPartition
) -> RouteForgeFeatures:
    categories = (
        "request_property_removed",
        "required_parameter_added",
        "response_property_removed",
        "request_property_type_changed",
        "response_property_type_changed",
        "endpoint_removed",
        "enum_restricted",
        "nullable_removed",
    )
    severities = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    certainties = ("EXACT", "CONDITIONAL", "PARTIAL", "UNRESOLVED")
    shapes = (
        "literal_inline",
        "dynamic_payload",
        "shared_payload",
        "nested_literal",
        "conflicting_edits",
        "partial-static-evidence",
        "missing-authoritative-value",
        "multiple-direct-impacts",
    )
    no_repair = preferred is RouteChoice.NO_AI
    unsupported = preferred is RouteChoice.NO_FEASIBLE_STRATEGY or (
        not no_repair and index % 4 == 0
    )
    partial = not no_repair and not unsupported and index % 3 == 0
    m10_outcome = (
        "NO_CHANGE"
        if no_repair
        else (
            "UNSUPPORTED"
            if preferred is RouteChoice.NO_FEASIBLE_STRATEGY
            else (
                "AI_REQUIRED" if unsupported or partial else "DETERMINISTIC_CANDIDATE"
            )
        )
    )
    m10_repairability = (
        "SUPPORTED"
        if no_repair or not (unsupported or partial)
        else ("UNSUPPORTED" if unsupported else "PARTIALLY_SUPPORTED")
    )
    deterministic_rule = no_repair or not (unsupported or partial)
    return RouteForgeFeatures(
        change_category=categories[index % len(categories)],
        change_severity=severities[index % len(severities)],
        change_certainty=certainties[(index // 2) % len(certainties)],
        breaking_classification=("CLIENT_BREAKING" if index % 3 else "SERVER_BREAKING"),
        compatibility_direction=(
            "CLIENT_TO_SERVER" if index % 2 else "SERVER_TO_CLIENT"
        ),
        url_resolution_state=tuple(ResolutionState)[index % 3],
        request_resolution_state=tuple(ResolutionState)[(index + 1) % 3],
        response_resolution_state=tuple(ResolutionState)[(index + 2) % 3],
        direct_impact_count=1 + index % 5,
        direct_reference=index % 7 != 0,
        indirect_exposure_count=index % 8,
        maximum_graph_distance=index % 6,
        direct_caller_count=index % 4,
        upstream_caller_count=index % 7,
        coverage_unresolved_calls=index % 5,
        coverage_failed_files=index % 3,
        m10_outcome=m10_outcome,
        m10_repairability=m10_repairability,
        deterministic_rule_available=deterministic_rule,
        supported_rule_count=int(deterministic_rule),
        expected_edit_count=0 if no_repair or unsupported else 1 + index % 4,
        target_file_count=0 if no_repair else 1 + index % 4,
        repair_conflict_count=index % 3 if not no_repair else 0,
        shared_payload_ambiguity=index % 5 == 0,
        dynamic_payload=index % 4 == 1,
        nested_literal=index % 6 == 2,
        ambiguity_flag_count=index % 4,
        source_shape=shapes[index % len(shapes)],
    )


def _m10_evidence(features: RouteForgeFeatures, index: int) -> M10ObservedEvidence:
    candidate = (
        features.deterministic_rule_available
        and features.m10_outcome == "DETERMINISTIC_CANDIDATE"
    )
    return M10ObservedEvidence(
        outcome=features.m10_outcome,
        repairability=features.m10_repairability,
        rule_id="remove-request-property-v1" if candidate else None,
        candidate_generated=candidate,
        edit_count=features.expected_edit_count,
        target_file_count=features.target_file_count,
        conflict_count=features.repair_conflict_count,
        warnings=(
            ("partial static evidence",)
            if features.m10_repairability == "PARTIALLY_SUPPORTED"
            else ()
        ),
    )


def _oracle_spec(
    strategy: RouteForgeStrategy,
    status: StrategyOutcomeStatus,
    provenance: OutcomeProvenance,
    index: int,
    *,
    no_repair: bool = False,
    observed: bool = False,
) -> _GateCOutcomeSpec:
    economics = {
        RouteForgeStrategy.NO_AI: (0.0, 0.0, None),
        RouteForgeStrategy.DETERMINISTIC: (0.0, 0.0, 100.0),
        RouteForgeStrategy.SMALL: (1.0, 1.0, 75.0),
        RouteForgeStrategy.MEDIUM: (2.0, 2.0, 88.0),
        RouteForgeStrategy.STRONG: (4.0, 4.0, 98.0),
    }
    cost, latency, quality = economics[strategy]
    if observed:
        return _GateCOutcomeSpec(
            status=StrategyOutcomeStatus.UNKNOWN,
            provenance=OutcomeProvenance.OBSERVED_DETERMINISTIC,
            producer="m10:deterministic-migration-v1",
            cost=None,
            latency=None,
            quality=None,
            candidate_generated=True,
            notes=f"Observed M10 candidate in fresh scenario {index}; validation is not available.",
        )
    return _GateCOutcomeSpec(
        status=status if not no_repair else StrategyOutcomeStatus.NOT_APPLICABLE,
        provenance=provenance,
        producer="routeforge-gate-c-oracle-v1",
        cost=cost,
        latency=latency,
        quality=quality,
        no_repair_required=no_repair,
        notes=f"Fixed protocol outcome pattern for fresh Gate C scenario {index}; not validated.",
    )


def _outcomes_for(
    preferred: RouteChoice,
    index: int,
    provenance: OutcomeProvenance,
    features: RouteForgeFeatures,
) -> tuple[_GateCOutcomeSpec, ...]:
    if preferred is RouteChoice.NO_AI:
        return tuple(
            _oracle_spec(
                strategy,
                StrategyOutcomeStatus.NOT_APPLICABLE,
                provenance,
                index,
                no_repair=True,
            )
            for strategy in RouteForgeStrategy
        )
    if preferred is RouteChoice.NO_FEASIBLE_STRATEGY:
        statuses = {
            RouteForgeStrategy.NO_AI: StrategyOutcomeStatus.NOT_APPLICABLE,
            RouteForgeStrategy.DETERMINISTIC: (
                StrategyOutcomeStatus.UNKNOWN
                if index % 2
                else StrategyOutcomeStatus.FAILURE
            ),
            RouteForgeStrategy.SMALL: StrategyOutcomeStatus.FAILURE,
            RouteForgeStrategy.MEDIUM: StrategyOutcomeStatus.FAILURE,
            RouteForgeStrategy.STRONG: StrategyOutcomeStatus.FAILURE,
        }
    else:
        statuses = {
            strategy: StrategyOutcomeStatus.FAILURE for strategy in REPAIR_STRATEGIES
        }
        if preferred is RouteChoice.DETERMINISTIC:
            statuses[RouteForgeStrategy.DETERMINISTIC] = StrategyOutcomeStatus.SUCCESS
            statuses[RouteForgeStrategy.SMALL] = (
                StrategyOutcomeStatus.SUCCESS
                if index % 2
                else StrategyOutcomeStatus.FAILURE
            )
            statuses[RouteForgeStrategy.STRONG] = (
                StrategyOutcomeStatus.SUCCESS
                if index % 3 == 0
                else StrategyOutcomeStatus.FAILURE
            )
        elif preferred is RouteChoice.SMALL:
            statuses[RouteForgeStrategy.SMALL] = StrategyOutcomeStatus.SUCCESS
            statuses[RouteForgeStrategy.MEDIUM] = (
                StrategyOutcomeStatus.SUCCESS
                if index % 3 == 0
                else StrategyOutcomeStatus.FAILURE
            )
            statuses[RouteForgeStrategy.STRONG] = (
                StrategyOutcomeStatus.UNKNOWN
                if index % 4 == 0
                else StrategyOutcomeStatus.FAILURE
            )
        elif preferred is RouteChoice.MEDIUM:
            statuses[RouteForgeStrategy.MEDIUM] = StrategyOutcomeStatus.SUCCESS
            statuses[RouteForgeStrategy.STRONG] = (
                StrategyOutcomeStatus.SUCCESS
                if index % 2
                else StrategyOutcomeStatus.FAILURE
            )
            statuses[RouteForgeStrategy.SMALL] = (
                StrategyOutcomeStatus.UNKNOWN
                if index % 3 == 0
                else StrategyOutcomeStatus.FAILURE
            )
        elif preferred is RouteChoice.STRONG:
            statuses[RouteForgeStrategy.STRONG] = StrategyOutcomeStatus.SUCCESS
            statuses[RouteForgeStrategy.MEDIUM] = (
                StrategyOutcomeStatus.UNKNOWN
                if index % 2
                else StrategyOutcomeStatus.FAILURE
            )
    observed = (
        features.m10_outcome == "DETERMINISTIC_CANDIDATE"
        and preferred is not RouteChoice.DETERMINISTIC
        and index % 5 == 0
    )
    specs: list[_GateCOutcomeSpec] = []
    for strategy in RouteForgeStrategy:
        if strategy is RouteForgeStrategy.NO_AI:
            specs.append(
                _oracle_spec(
                    strategy,
                    StrategyOutcomeStatus.NOT_APPLICABLE,
                    provenance,
                    index,
                )
            )
            continue
        if strategy is RouteForgeStrategy.DETERMINISTIC and observed:
            specs.append(
                _oracle_spec(
                    strategy, statuses[strategy], provenance, index, observed=True
                )
            )
        else:
            specs.append(_oracle_spec(strategy, statuses[strategy], provenance, index))
    return tuple(specs)


def _preferred_target(index: int) -> RouteChoice:
    targets = (
        (RouteChoice.NO_AI, 8),
        (RouteChoice.DETERMINISTIC, 10),
        (RouteChoice.SMALL, 12),
        (RouteChoice.MEDIUM, 12),
        (RouteChoice.STRONG, 10),
        (RouteChoice.NO_FEASIBLE_STRATEGY, 12),
    )
    cursor = 0
    for strategy, count in targets:
        if index < cursor + count:
            return strategy
        cursor += count
    raise ValueError("Gate C preferred-strategy plan exceeded frozen group count")


def _plan_for(index: int) -> _ScenarioPlan:
    partition = _partition_for_index(index)
    preferred = _preferred_target(index)
    features = _features_for(index, preferred, partition)
    provenance = (
        OutcomeProvenance.CURATED_ORACLE
        if index % 3 == 0
        else OutcomeProvenance.SYNTHETIC_ORACLE
    )
    scenario_id = f"v2-scenario-{index + 1:03d}"
    return _ScenarioPlan(
        scenario_id=scenario_id,
        family=(
            DatasetFamily.REALISTIC,
            DatasetFamily.CURATED_ADVERSARIAL,
            DatasetFamily.SYNTHETIC,
        )[index % 3],
        repository_family_id=_family_value("repository-v2", index, partition),
        api_family_id=_family_value("api-v2", index, partition),
        migration_id=f"v2-migration-{index + 1:03d}",
        mutation_family=features.change_category,
        template_family_id=_family_value("template-v2", index, partition),
        feature_origin=FeatureOrigin.SCENARIO_AUTHORED,
        features=features,
        m10_evidence=_m10_evidence(features, index + 1),
        no_repair_required=preferred is RouteChoice.NO_AI,
        outcomes=cast(
            tuple[_OutcomeSpec, ...],
            _outcomes_for(preferred, index + 1, provenance, features),
        ),
        provenance="Frozen Gate C evidence protocol; synthetic/curated offline outcomes only.",
        tags=(
            f"preferred-{preferred.value.lower()}",
            f"partition-{partition.value.lower()}",
            (
                "unsupported-m10"
                if features.m10_repairability == "UNSUPPORTED"
                else "supported-m10"
            ),
            (
                "large-blast-radius"
                if features.maximum_graph_distance >= 4
                else "bounded-blast-radius"
            ),
        ),
    )


def _materialize_v2(
    plan: _ScenarioPlan, config: RouteForgeConfig
) -> RouteForgeScenario:
    generator = RouteForgeDatasetGenerator(config)
    scenario = generator._materialize(plan)
    source_fingerprint = stable_id(
        "routeforge-v2-source",
        plan.scenario_id,
        plan.repository_family_id,
        plan.api_family_id,
        plan.mutation_family,
        plan.features.source_shape,
    )
    routing_fingerprint = stable_id(
        "routeforge-v2-routing", plan.scenario_id, plan.features.canonical_json()
    )
    template_fingerprint = stable_id(
        "routeforge-v2-template", plan.template_family_id, plan.scenario_id
    )
    scenario_fingerprint = stable_id(
        "routeforge-v2-scenario",
        plan.scenario_id,
        scenario.context.canonical_json(),
        source_fingerprint,
    )
    return scenario.model_copy(
        update={
            "source_fingerprint": source_fingerprint,
            "routing_feature_fingerprint": routing_fingerprint,
            "template_fingerprint": template_fingerprint,
            "scenario_fingerprint": scenario_fingerprint,
        }
    )


def _rows_v2(
    scenarios: Sequence[RouteForgeScenario],
) -> tuple[RouteForgeDatasetRow, ...]:
    by_group = {scenario.decision_group_id: scenario for scenario in scenarios}
    rows: list[RouteForgeDatasetRow] = []
    for scenario in scenarios:
        partition = _partition_for_index(int(scenario.scenario_id[-3:]) - 1)
        outcomes = {outcome.strategy: outcome for outcome in scenario.outcomes}
        for strategy in RouteForgeStrategy:
            outcome = outcomes[strategy]
            rows.append(
                RouteForgeDatasetRow(
                    id=stable_id(
                        "routeforge-v2-row", scenario.decision_group_id, strategy.value
                    ),
                    schema_version=GATE_C_DATASET_VERSION,
                    dataset_version=GATE_C_DATASET_VERSION,
                    scenario_id=scenario.scenario_id,
                    scenario_fingerprint=scenario.scenario_fingerprint,
                    decision_group_id=scenario.decision_group_id,
                    split_group_id=scenario.decision_group_id,
                    split_partition=partition,
                    context_id=scenario.context.id,
                    strategy=strategy,
                    outcome=outcome.outcome,
                    outcome_provenance=outcome.provenance,
                    producer=outcome.producer,
                    candidate_generated=outcome.candidate_generated,
                    synthetic_cost_units=outcome.synthetic_cost_units,
                    synthetic_latency_units=outcome.synthetic_latency_units,
                    quality_units=outcome.quality_units,
                    features=scenario.context.features,
                    preferred_strategy=scenario.preferred_strategy,
                    feasible_strategies=scenario.feasible_strategies,
                )
            )
    if set(by_group) != {scenario.decision_group_id for scenario in scenarios}:
        raise ValueError("v2 scenario groups are not unique")
    return tuple(sorted(rows, key=lambda row: row.id))


def _manifest_v2(
    scenarios: tuple[RouteForgeScenario, ...],
    rows: tuple[RouteForgeDatasetRow, ...],
    config: RouteForgeConfig,
) -> RouteForgeManifest:
    strategy_counts = Counter(row.strategy.value for row in rows)
    preferred_counts = Counter(
        scenario.preferred_strategy.value for scenario in scenarios
    )
    outcomes: dict[str, dict[str, int]] = {}
    for row in rows:
        outcomes.setdefault(row.strategy.value, {})[row.outcome.value] = (
            outcomes.setdefault(row.strategy.value, {}).get(row.outcome.value, 0) + 1
        )
    duplicate_audit = DuplicateAudit(
        scenario_fingerprint_duplicates=sum(
            max(0, count - 1)
            for count in Counter(s.scenario_fingerprint for s in scenarios).values()
        ),
        source_fingerprint_duplicates=sum(
            max(0, count - 1)
            for count in Counter(s.source_fingerprint for s in scenarios).values()
        ),
        routing_feature_clone_groups=sum(
            count > 1
            for count in Counter(
                s.routing_feature_fingerprint for s in scenarios
            ).values()
        ),
        outcome_table_duplicates=sum(
            max(0, count - 1)
            for count in Counter(
                s.outcome_table_fingerprint for s in scenarios
            ).values()
        ),
        template_clone_groups=sum(
            count > 1
            for count in Counter(s.template_fingerprint for s in scenarios).values()
        ),
    )
    resolution_counts = Counter(
        state.value
        for scenario in scenarios
        for state in (
            scenario.context.features.url_resolution_state,
            scenario.context.features.request_resolution_state,
            scenario.context.features.response_resolution_state,
        )
    )
    kwargs: dict[str, object] = {
        "schema_version": GATE_C_DATASET_VERSION,
        "dataset_version": GATE_C_DATASET_VERSION,
        "generator_version": GATE_C_GENERATOR_VERSION,
        "objective": RoutingObjective(),
        "strategy_taxonomy_version": config.strategy_taxonomy_version,
        "feature_schema_version": config.feature_schema_version,
        "seed": config.seed,
        "config": config,
        "scenario_count": len(scenarios),
        "decision_group_count": len(scenarios),
        "strategy_outcome_row_count": len(rows),
        "strategy_counts": dict(sorted(strategy_counts.items())),
        "preferred_strategy_counts": dict(sorted(preferred_counts.items())),
        "strategy_outcome_counts": {
            key: dict(sorted(value.items())) for key, value in sorted(outcomes.items())
        },
        "provenance_counts": dict(
            sorted(Counter(row.outcome_provenance.value for row in rows).items())
        ),
        "repairability_counts": dict(
            sorted(
                Counter(s.context.features.m10_repairability for s in scenarios).items()
            )
        ),
        "change_category_counts": dict(
            sorted(Counter(s.mutation_family for s in scenarios).items())
        ),
        "api_family_counts": dict(
            sorted(Counter(s.api_family_id for s in scenarios).items())
        ),
        "repository_family_counts": dict(
            sorted(Counter(s.repository_family_id for s in scenarios).items())
        ),
        "template_family_counts": dict(
            sorted(Counter(s.template_family_id for s in scenarios).items())
        ),
        "resolution_state_counts": dict(sorted(resolution_counts.items())),
        "duplicate_audit": duplicate_audit,
        "content_sha256": "PENDING",
    }
    preliminary = RouteForgeManifest.model_validate(kwargs)
    checksum = content_checksum(
        RouteForgeDataset(manifest=preliminary, scenarios=scenarios, rows=rows)
    )
    return preliminary.model_copy(update={"content_sha256": checksum})


def _partition_fingerprints(dataset: RouteForgeDataset) -> dict[str, object]:
    by_partition: dict[str, dict[str, set[str]]] = {}
    for partition in ("TRAIN", "VALIDATION", "TEST"):
        scenarios = {
            row.scenario_id: next(
                s for s in dataset.scenarios if s.scenario_id == row.scenario_id
            )
            for row in dataset.rows
            if row.split_partition.value == partition
        }
        by_partition[partition] = {
            "source": {scenario.source_fingerprint for scenario in scenarios.values()},
            "routing": {
                scenario.routing_feature_fingerprint for scenario in scenarios.values()
            },
            "template": {
                scenario.template_fingerprint for scenario in scenarios.values()
            },
            "outcome": {
                scenario.outcome_table_fingerprint for scenario in scenarios.values()
            },
        }
    overlap: dict[str, int] = {}
    for name in ("source", "routing", "template", "outcome"):
        overlap[name] = sum(
            len(by_partition[left][name] & by_partition[right][name])
            for left, right in (
                ("TRAIN", "VALIDATION"),
                ("TRAIN", "TEST"),
                ("VALIDATION", "TEST"),
            )
        )
    return {
        "cross_partition_overlap": overlap,
        "all_zero": all(value == 0 for value in overlap.values()),
    }


def generate_gate_c_dataset(
    protocol_path: Path | str = Path("data/routeforge-gate-c/protocol.json"),
    output_directory: Path | str = Path("data/routeforge-v2"),
) -> GateCDatasetResult:
    protocol = json.loads(Path(protocol_path).read_text(encoding="utf-8"))
    if protocol.get("protocol_version") != GATE_C_PROTOCOL_VERSION:
        raise ValueError("Gate C protocol version mismatch")
    if (
        not protocol.get("created_before_generation")
        or protocol.get("dataset_checksum") != "PENDING_GENERATION"
    ):
        raise ValueError(
            "Gate C dataset generation requires an unfrozen pre-generation protocol"
        )
    config = RouteForgeConfig(
        seed=GATE_C_SEED,
        dataset_version=GATE_C_DATASET_VERSION,
        generator_version=GATE_C_GENERATOR_VERSION,
        objective_version="routeforge-objective-v1",
        feature_schema_version="routeforge-features-v1",
        strategy_taxonomy_version="routeforge-strategies-v1",
        include_canonical_m10=False,
    )
    plans = tuple(_plan_for(index) for index in range(GATE_C_GROUP_COUNT))
    scenarios = tuple(
        _materialize_v2(plan, config)
        for plan in sorted(plans, key=lambda item: item.scenario_id)
    )
    rows = _rows_v2(scenarios)
    manifest = _manifest_v2(scenarios, rows, config)
    dataset = RouteForgeDataset(manifest=manifest, scenarios=scenarios, rows=rows)
    validate_dataset(dataset)
    output = Path(output_directory)
    write_artifacts(dataset, output)
    protocol_checksum = hashlib.sha256(Path(protocol_path).read_bytes()).hexdigest()
    historical = read_artifacts(Path("data/routeforge-m11"))
    historical_sets = {
        "scenario": {
            scenario.scenario_fingerprint for scenario in historical.scenarios
        },
        "source": {scenario.source_fingerprint for scenario in historical.scenarios},
        "routing": {
            scenario.routing_feature_fingerprint for scenario in historical.scenarios
        },
        "template": {
            scenario.template_fingerprint for scenario in historical.scenarios
        },
    }
    current_sets = {
        "scenario": {scenario.scenario_fingerprint for scenario in scenarios},
        "source": {scenario.source_fingerprint for scenario in scenarios},
        "routing": {scenario.routing_feature_fingerprint for scenario in scenarios},
        "template": {scenario.template_fingerprint for scenario in scenarios},
    }
    historical_overlap = {
        name: len(historical_sets[name] & current_sets[name])
        for name in historical_sets
    }
    return GateCDatasetResult(
        dataset=dataset,
        protocol_checksum=protocol_checksum,
        cross_partition_audit=_partition_fingerprints(dataset),
        historical_overlap=historical_overlap,
    )


def _score_policy_v2(
    scenario: RouteForgeScenario, scores: Mapping[RouteForgeStrategy, float]
) -> tuple[RouteChoice, str]:
    if scenario.context.no_repair_required:
        return RouteChoice.NO_AI, "no_repair_required -> NO_AI"
    applicability = _applicability(scenario.context)
    candidates = [
        strategy
        for strategy in REPAIR_STRATEGIES
        if applicability[strategy].startswith("applicable")
        and math.isfinite(float(scores.get(strategy, float("nan"))))
    ]
    if not candidates:
        return (
            RouteChoice.NO_FEASIBLE_STRATEGY,
            "no applicable strategy has a finite score",
        )
    order = {strategy: index for index, strategy in enumerate(STRATEGY_ORDER)}
    selected = min(
        candidates, key=lambda strategy: (-float(scores[strategy]), order[strategy])
    )
    return (
        RouteChoice(selected.value),
        f"highest uncalibrated score -> {selected.value}",
    )


def _random_applicable_policy(seed: int) -> Any:
    generator = random.Random(seed)

    def choose(
        scenario: RouteForgeScenario, _scores: Mapping[RouteForgeStrategy, float]
    ) -> tuple[RouteChoice, str]:
        if scenario.context.no_repair_required:
            return RouteChoice.NO_AI, "no_repair_required -> NO_AI"
        applicability = _applicability(scenario.context)
        candidates = tuple(
            strategy
            for strategy in REPAIR_STRATEGIES
            if applicability[strategy].startswith("applicable")
        )
        if not candidates:
            return RouteChoice.NO_FEASIBLE_STRATEGY, "no applicable random strategy"
        selected = generator.choice(candidates)
        return (
            RouteChoice(selected.value),
            f"seeded random applicable choice ({seed}) -> {selected.value}",
        )

    return choose


def _fit_xgb(
    train_rows: Sequence[RouteForgeDatasetRow], seed: int
) -> tuple[RouteForgeFeatureEncoder, Any, dict[str, object]]:
    eligible = tuple(row for row in train_rows if _eligible(row))
    encoder = RouteForgeFeatureEncoder().fit(eligible)
    matrix = encoder.transform(eligible)
    labels = np.asarray(
        [row.outcome is StrategyOutcomeStatus.SUCCESS for row in eligible], dtype=int
    )
    parameters: dict[str, object] = {
        "n_estimators": 8,
        "max_depth": 2,
        "learning_rate": 0.2,
        "subsample": 1.0,
        "colsample_bytree": 1.0,
        "reg_lambda": 1.0,
        "tree_method": "hist",
        "random_state": seed,
        "n_jobs": 1,
        "eval_metric": "logloss",
        "verbosity": 0,
    }
    model = XGBClassifier(**parameters).fit(matrix, labels)
    return encoder, model, parameters


def _scores_for_rows(
    encoder: RouteForgeFeatureEncoder, model: Any, rows: Sequence[RouteForgeDatasetRow]
) -> tuple[dict[str, float], dict[str, dict[RouteForgeStrategy, float]], str, float]:
    scores, score_kind, threshold = _score(model, encoder.transform(rows))
    by_id = {row.id: float(score) for row, score in zip(rows, scores, strict=True)}
    by_group: dict[str, dict[RouteForgeStrategy, float]] = {}
    for row in rows:
        by_group.setdefault(row.decision_group_id, {})[row.strategy] = by_id[row.id]
    return by_id, by_group, score_kind, threshold


def _rows_by_group(
    rows: Sequence[RouteForgeDatasetRow],
) -> dict[str, dict[RouteForgeStrategy, RouteForgeDatasetRow]]:
    result: dict[str, dict[RouteForgeStrategy, RouteForgeDatasetRow]] = {}
    for row in rows:
        result.setdefault(row.decision_group_id, {})[row.strategy] = row
    return result


def _router_run(
    router: RouteForgeRouter,
    scenarios: Sequence[RouteForgeScenario],
    rows: Sequence[RouteForgeDatasetRow],
    objective: RoutingObjective,
) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, object]]:
    grouped = _rows_by_group(rows)
    decisions: list[dict[str, object]] = []
    evaluations: list[dict[str, object]] = []
    for scenario in scenarios:
        decision = router.route(
            RoutingRequest(context=scenario.context, objective=objective)
        )
        decisions.append(decision.model_dump(mode="json"))
        evaluations.append(
            _validation_evaluation(
                decision, scenario, grouped[scenario.decision_group_id], objective
            )
        )
    return decisions, evaluations, _policy_metrics(evaluations)


def _artifact_scores_for_rows(
    router: RouteForgeRouter,
    scenarios: Sequence[RouteForgeScenario],
    rows: Sequence[RouteForgeDatasetRow],
) -> np.ndarray:
    contexts = {scenario.decision_group_id: scenario.context for scenario in scenarios}
    eligible = tuple(row for row in rows if _eligible(row))
    return np.asarray(
        [
            router._score(contexts[row.decision_group_id], row.strategy)
            for row in eligible
        ],
        dtype=float,
    )


def _policy_bundle(
    scenarios: Sequence[RouteForgeScenario],
    rows: Sequence[RouteForgeDatasetRow],
    objective: RoutingObjective,
    policies: Mapping[str, object],
    scores: (
        Mapping[str, Mapping[str, Mapping[RouteForgeStrategy, float]]] | None
    ) = None,
) -> tuple[dict[str, dict[str, object]], list[dict[str, object]]]:
    metrics: dict[str, dict[str, object]] = {}
    records: list[dict[str, object]] = []
    for name, policy in policies.items():
        score_map = None if scores is None else scores.get(name)
        decisions, result = _evaluate_policy(
            scenarios,
            rows,
            cast(Any, policy),
            objective,
            score_map,
        )
        metrics[name] = cast(dict[str, object], result["metrics"])
        decision_records = cast(Sequence[Mapping[str, object]], result["decisions"])
        records.extend(
            {"policy": name, **dict(decision)} for decision in decision_records
        )
    return metrics, records


def _label_shuffle_sanity(
    train_rows: Sequence[RouteForgeDatasetRow],
    validation_rows: Sequence[RouteForgeDatasetRow],
    seed: int,
) -> dict[str, object]:
    eligible_train = tuple(row for row in train_rows if _eligible(row))
    eligible_validation = tuple(row for row in validation_rows if _eligible(row))
    encoder = RouteForgeFeatureEncoder().fit(eligible_train)
    labels = [row.outcome is StrategyOutcomeStatus.SUCCESS for row in eligible_train]
    random.Random(seed).shuffle(labels)
    model = LogisticRegression(
        C=1.0,
        class_weight="balanced",
        max_iter=500,
        solver="liblinear",
        random_state=seed,
    ).fit(encoder.transform(eligible_train), np.asarray(labels, dtype=int))
    scores = _score(model, encoder.transform(eligible_validation))[0]
    return {
        "seed": seed,
        "train_rows": len(eligible_train),
        "validation_rows": len(eligible_validation),
        "metrics": _outcome_metrics(eligible_validation, scores, 0.0),
        "test_accessed": False,
    }


def _split_fingerprint(
    dataset: RouteForgeDataset,
    train_rows: Sequence[RouteForgeDatasetRow],
    validation_rows: Sequence[RouteForgeDatasetRow],
) -> str:
    payload = {
        "train_groups": sorted({row.decision_group_id for row in train_rows}),
        "validation_groups": sorted({row.decision_group_id for row in validation_rows}),
        "test_group_count": GATE_C_TEST_GROUPS,
        "dataset_checksum": dataset.manifest.content_sha256,
    }
    return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()


def prepare_gate_c_evidence(
    dataset_directory: Path | str = Path("data/routeforge-v2"),
    output_directory: Path | str = Path("data/routeforge-gate-c"),
) -> dict[str, object]:
    output = Path(output_directory)
    if output.joinpath("formal-test-access.json").exists():
        raise ValueError(
            "formal Gate C TEST has already been accessed; preparation is sealed"
        )
    dataset = read_artifacts(Path(dataset_directory))
    train_rows = _partition_rows(dataset, "TRAIN")
    validation_rows = _partition_rows(dataset, "VALIDATION")
    train_scenarios = _scenario_by_group(dataset, train_rows)
    validation_scenarios = _scenario_by_group(dataset, validation_rows)
    objective = dataset.manifest.objective
    artifact = _fit_primary_artifact(dataset, train_rows, GATE_C_SEED)
    output.mkdir(parents=True, exist_ok=True)
    model_checksum = save_model_artifact(artifact, output / "model.json")
    router = RouteForgeRouter.from_artifact(output / "model.json")
    router_decisions, router_evaluations, router_metrics = _router_run(
        router, validation_scenarios, validation_rows, objective
    )
    xgb_encoder, xgb_model, xgb_parameters = _fit_xgb(train_rows, GATE_C_SEED)
    validation_eligible = tuple(row for row in validation_rows if _eligible(row))
    xgb_scores_by_id, xgb_scores, xgb_score_kind, xgb_threshold = _scores_for_rows(
        xgb_encoder, xgb_model, validation_rows
    )
    xgb_decisions, xgb_result = _evaluate_policy(
        validation_scenarios,
        validation_rows,
        _score_policy_v2,
        objective,
        xgb_scores,
    )
    xgb_metrics = cast(dict[str, object], xgb_result["metrics"])
    policies: dict[str, object] = {
        "Always Small": _always(RouteForgeStrategy.SMALL),
        "Always Strong": _always(RouteForgeStrategy.STRONG),
        "Random": _random_applicable_policy(GATE_C_RANDOM_SEED),
        "Rule": _rule_policy,
    }
    baseline_metrics, baseline_records = _policy_bundle(
        validation_scenarios,
        validation_rows,
        objective,
        policies,
    )
    logistic_eligible_scores = _artifact_scores_for_rows(
        router, validation_scenarios, validation_rows
    )
    xgb_eligible_scores = np.asarray(
        [xgb_scores_by_id[row.id] for row in validation_eligible], dtype=float
    )
    validation_payload = {
        "dataset_version": dataset.manifest.dataset_version,
        "dataset_checksum": dataset.manifest.content_sha256,
        "split": {
            "train_groups": len(train_scenarios),
            "validation_groups": len(validation_scenarios),
            "test_groups": GATE_C_TEST_GROUPS,
        },
        "model": {
            "id": ROUTEFORGE_MODEL_ID,
            "checksum": model_checksum,
            "artifact_schema": ROUTEFORGE_ROUTER_ARTIFACT_SCHEMA,
        },
        "policy": ROUTEFORGE_DECISION_POLICY_VERSION,
        "policies": {
            **baseline_metrics,
            "Logistic": router_metrics,
            "XGBoost": xgb_metrics,
        },
        "model_diagnostics": {
            "Logistic": _outcome_metrics(
                validation_eligible, logistic_eligible_scores, 0.0
            ),
            "XGBoost": _outcome_metrics(
                validation_eligible, xgb_eligible_scores, xgb_threshold
            ),
        },
        "xgboost": {
            "parameters": xgb_parameters,
            "score_kind": xgb_score_kind,
            "fit_partition": "TRAIN",
        },
        "test_accessed": False,
    }
    _write_json(output / "validation_metrics.json", validation_payload)
    _write_jsonl(
        output / "validation_decisions.jsonl",
        baseline_records
        + [
            {"policy": "XGBoost", **dict(decision)}
            for decision in cast(
                Sequence[Mapping[str, object]], xgb_result["decisions"]
            )
        ]
        + [{"policy": "Logistic", **item} for item in router_decisions],
    )
    _write_jsonl(
        output / "validation_evaluation.jsonl",
        [{"policy": "Logistic", **item} for item in router_evaluations]
        + [
            {"policy": "XGBoost", **dict(decision)}
            for decision in cast(
                Sequence[Mapping[str, object]], xgb_result["decisions"]
            )
        ],
    )
    _write_json(
        output / "label-shuffle-sanity.json",
        _label_shuffle_sanity(train_rows, validation_rows, GATE_C_LABEL_SHUFFLE_SEED),
    )
    pretest = {
        "protocol_version": GATE_C_PROTOCOL_VERSION,
        "dataset_version": dataset.manifest.dataset_version,
        "dataset_checksum": dataset.manifest.content_sha256,
        "dataset_path": str(Path(dataset_directory)),
        "split_fingerprint": _split_fingerprint(dataset, train_rows, validation_rows),
        "model_id": ROUTEFORGE_MODEL_ID,
        "model_checksum": model_checksum,
        "router_artifact_schema": ROUTEFORGE_ROUTER_ARTIFACT_SCHEMA,
        "router_version": ROUTEFORGE_ROUTER_VERSION,
        "scorer_version": ROUTEFORGE_SCORER_VERSION,
        "decision_policy_version": ROUTEFORGE_DECISION_POLICY_VERSION,
        "objective_version": objective.version,
        "comparison_models": ["RF-M13-LOGISTIC-V1", "XGBoost bounded comparator"],
        "metric_definitions": [
            "decision-group satisfaction",
            "constraint violation",
            "synthetic cost/latency",
            "cost per oracle-satisfied decision",
            "STRONG usage",
            "NO_FEASIBLE handling",
            "regret",
            "ROC-AUC",
            "PR-AUC",
            "F1",
        ],
        "bootstrap": {
            "unit": "decision_group",
            "replicates": GATE_C_BOOTSTRAP_REPLICATES,
            "confidence": 0.95,
            "seed": GATE_C_BOOTSTRAP_SEED,
        },
        "seeds": {
            "master": GATE_C_SEED,
            "split": GATE_C_SPLIT_SEED,
            "random_policy": GATE_C_RANDOM_SEED,
            "label_shuffle": GATE_C_LABEL_SHUFFLE_SEED,
            "bootstrap": GATE_C_BOOTSTRAP_SEED,
        },
        "test_group_count": GATE_C_TEST_GROUPS,
        "test_accessed": False,
        "test_access_rule": (
            "TEST is opened exactly once after this manifest is frozen; "
            "no model/configuration selection follows."
        ),
    }
    _write_json(output / "pre-test-manifest.json", pretest)
    _write_json(
        output / "model-provenance.json",
        {
            "model_checksum": model_checksum,
            "dataset_checksum": dataset.manifest.content_sha256,
            "train_row_count": artifact.training_row_count,
            "hyperparameters": artifact.hyperparameters,
            "xgboost_parameters": xgb_parameters,
            "test_accessed": False,
        },
    )
    return {
        "dataset_checksum": dataset.manifest.content_sha256,
        "model_checksum": model_checksum,
        "validation_groups": len(validation_scenarios),
        "test_accessed": False,
    }


def _decision_metrics(records: Sequence[Mapping[str, object]]) -> dict[str, object]:
    count = len(records)
    if not count:
        return {"decision_count": 0}
    costs = [
        float(cast(float | int, item["selected_cost_units"]))
        for item in records
        if item.get("selected_cost_units") is not None
    ]
    latencies = [
        float(cast(float | int, item["selected_latency_units"]))
        for item in records
        if item.get("selected_latency_units") is not None
    ]
    regrets = [
        float(cast(float | int, item["objective_regret_units"]))
        for item in records
        if item.get("objective_regret_units") is not None
    ]
    successes = sum(bool(item.get("objective_satisfied")) for item in records)
    expected = sum(
        bool(item.get("no_feasible_expected"))
        or item.get("oracle_preferred_strategy")
        == RouteChoice.NO_FEASIBLE_STRATEGY.value
        for item in records
    )
    correct = sum(
        expected_item
        and item.get("chosen_strategy", item.get("selected_strategy"))
        == RouteChoice.NO_FEASIBLE_STRATEGY.value
        for item, expected_item in (
            (
                item,
                bool(item.get("no_feasible_expected"))
                or item.get("oracle_preferred_strategy")
                == RouteChoice.NO_FEASIBLE_STRATEGY.value,
            )
            for item in records
        )
    )
    return {
        "decision_count": count,
        "oracle_objective_satisfaction_rate": successes / count,
        "constraint_violation_rate": (count - successes) / count,
        "synthetic_average_cost_units": float(np.mean(costs)) if costs else None,
        "synthetic_average_latency_units": (
            float(np.mean(latencies)) if latencies else None
        ),
        "synthetic_cost_per_oracle_successful_decision_units": (
            float(sum(costs) / successes) if successes else None
        ),
        "strong_strategy_usage_rate": sum(
            item.get("chosen_strategy", item.get("selected_strategy"))
            == RouteForgeStrategy.STRONG.value
            for item in records
        )
        / count,
        "no_feasible_expected_count": expected,
        "no_feasible_correct_count": correct,
        "no_feasible_handling_rate": correct / expected if expected else None,
        "objective_regret_units_mean": float(np.mean(regrets)) if regrets else None,
        "objective_regret_defined_count": len(regrets),
    }


def _bootstrap_intervals(
    records_by_policy: Mapping[str, Sequence[Mapping[str, object]]],
    *,
    seed: int = GATE_C_BOOTSTRAP_SEED,
    replicates: int = GATE_C_BOOTSTRAP_REPLICATES,
) -> dict[str, object]:
    result: dict[str, object] = {}
    rng = random.Random(seed)
    metric_names = {
        "satisfaction": "oracle_objective_satisfaction_rate",
        "violation": "constraint_violation_rate",
        "cost": "synthetic_average_cost_units",
        "latency": "synthetic_average_latency_units",
        "strong_usage": "strong_strategy_usage_rate",
        "no_feasible_handling": "no_feasible_handling_rate",
        "regret": "objective_regret_units_mean",
    }
    for policy, records in records_by_policy.items():
        if not records:
            raise ValueError("bootstrap requires at least one decision-group record")
        canonical = _decision_metrics(records)
        values: dict[str, list[float]] = {
            "satisfaction": [],
            "violation": [],
            "cost": [],
            "latency": [],
            "strong_usage": [],
            "no_feasible_handling": [],
            "regret": [],
        }
        for _ in range(replicates):
            sample = [records[rng.randrange(len(records))] for _ in records]
            metrics = _decision_metrics(sample)
            values["satisfaction"].append(
                float(cast(float | int, metrics["oracle_objective_satisfaction_rate"]))
            )
            values["violation"].append(
                float(cast(float | int, metrics["constraint_violation_rate"]))
            )
            for key, metric_key in (
                ("cost", "synthetic_average_cost_units"),
                ("latency", "synthetic_average_latency_units"),
                ("strong_usage", "strong_strategy_usage_rate"),
                ("no_feasible_handling", "no_feasible_handling_rate"),
                ("regret", "objective_regret_units_mean"),
            ):
                metric = metrics[metric_key]
                if metric is not None:
                    values[key].append(float(cast(float | int, metric)))
        result[policy] = {
            "replicates": replicates,
            "unit": "decision_group",
            "confidence": 0.95,
            "seed": seed,
            "point_estimate_semantics": (
                "canonical held-out decision-group metric; percentile bootstrap intervals "
                "summarize resamples and are not adjusted to contain the point estimate"
            ),
            "intervals": {
                key: {
                    "point": canonical[metric_names[key]],
                    "lower": (
                        float(np.percentile(values[key], 2.5)) if values[key] else None
                    ),
                    "upper": (
                        float(np.percentile(values[key], 97.5)) if values[key] else None
                    ),
                }
                for key in values
            },
        }
    return result


def _generalization_scope(
    train_scenarios: Sequence[RouteForgeScenario],
    test_scenarios: Sequence[RouteForgeScenario],
) -> dict[str, object]:
    fields = {
        "api_family": "api_family_id",
        "repository_family": "repository_family_id",
        "template_family": "template_family_id",
        "mutation_family": "mutation_family",
    }
    result: dict[str, object] = {}
    for name, field in fields.items():
        train = {str(getattr(scenario, field)) for scenario in train_scenarios}
        test = {str(getattr(scenario, field)) for scenario in test_scenarios}
        unseen = sorted(test - train)
        result[name] = {
            "status": "SUPPORTED" if unseen else "PARTIALLY_SUPPORTED",
            "train_unique": len(train),
            "test_unique": len(test),
            "test_unseen": unseen,
        }
    train_shapes = {
        scenario.context.features.source_shape for scenario in train_scenarios
    }
    test_shapes = {
        scenario.context.features.source_shape for scenario in test_scenarios
    }
    result["source_shape"] = {
        "status": "SUPPORTED" if test_shapes - train_shapes else "PARTIALLY_SUPPORTED",
        "train_unique": len(train_shapes),
        "test_unique": len(test_shapes),
        "test_unseen": sorted(test_shapes - train_shapes),
    }
    return result


def run_formal_gate_c_test(
    dataset_directory: Path | str = Path("data/routeforge-v2"),
    output_directory: Path | str = Path("data/routeforge-gate-c"),
) -> dict[str, object]:
    output = Path(output_directory)
    marker_path = output / "formal-test-access.json"
    if marker_path.exists():
        raise ValueError(
            "formal Gate C TEST evaluation already completed; rerun is forbidden"
        )
    pretest_path = output / "pre-test-manifest.json"
    if not pretest_path.exists():
        raise ValueError("pre-test manifest is required before formal TEST access")
    pretest = json.loads(pretest_path.read_text(encoding="utf-8"))
    if pretest.get("test_accessed") is not False:
        raise ValueError("pre-test manifest is already opened")
    dataset = read_artifacts(Path(dataset_directory))
    if dataset.manifest.content_sha256 != pretest.get("dataset_checksum"):
        raise ValueError("dataset changed after pre-test freeze")
    artifact, model_checksum = load_model_artifact(output / "model.json")
    if model_checksum != pretest.get("model_checksum"):
        raise ValueError("model changed after pre-test freeze")
    train_rows = _partition_rows(dataset, "TRAIN")
    test_rows = _partition_rows(dataset, "TEST")
    test_scenarios = _scenario_by_group(dataset, test_rows)
    train_scenarios = _scenario_by_group(dataset, train_rows)
    if len(test_scenarios) != GATE_C_TEST_GROUPS:
        raise ValueError("formal TEST group count does not match frozen protocol")
    access = {
        "seal": GATE_C_TEST_SEAL_MESSAGE,
        "accessed_on": date.today().isoformat(),
        "test_accessed": True,
        "dataset_checksum": dataset.manifest.content_sha256,
        "pre_test_manifest_checksum": hashlib.sha256(
            pretest_path.read_bytes()
        ).hexdigest(),
        "test_group_count": len(test_scenarios),
        "selection_after_access": False,
        "configuration_changed_after_freeze": False,
    }
    _write_json(marker_path, access)
    objective = dataset.manifest.objective
    router = RouteForgeRouter(artifact=artifact, model_artifact_checksum=model_checksum)
    logistic_decisions, logistic_evaluations, logistic_metrics = _router_run(
        router, test_scenarios, test_rows, objective
    )
    xgb_encoder, xgb_model, xgb_parameters = _fit_xgb(train_rows, GATE_C_SEED)
    _, xgb_scores, _, _ = _scores_for_rows(xgb_encoder, xgb_model, test_rows)
    policies: dict[str, object] = {
        "Always Small": _always(RouteForgeStrategy.SMALL),
        "Always Strong": _always(RouteForgeStrategy.STRONG),
        "Random": _random_applicable_policy(GATE_C_RANDOM_SEED),
        "Rule": _rule_policy,
    }
    baseline_metrics, baseline_records = _policy_bundle(
        test_scenarios, test_rows, objective, policies
    )
    _, xgb_result = _evaluate_policy(
        test_scenarios, test_rows, _score_policy_v2, objective, xgb_scores
    )
    xgb_metrics = cast(dict[str, object], xgb_result["metrics"])
    records_by_policy: dict[str, list[dict[str, object]]] = {
        name: [record for record in baseline_records if record["policy"] == name]
        for name in policies
    }
    records_by_policy["Logistic"] = logistic_evaluations
    records_by_policy["XGBoost"] = [
        dict(policy="XGBoost", **dict(record))
        for record in cast(Sequence[Mapping[str, object]], xgb_result["decisions"])
    ]
    metric_table = {
        **baseline_metrics,
        "Logistic": logistic_metrics,
        "XGBoost": xgb_metrics,
    }
    eligible_test = tuple(row for row in test_rows if _eligible(row))
    logistic_scores = _artifact_scores_for_rows(router, test_scenarios, test_rows)
    xgb_scores_by_id, _, xgb_score_kind, xgb_threshold = _scores_for_rows(
        xgb_encoder, xgb_model, test_rows
    )
    formal_metrics = {
        "dataset_version": dataset.manifest.dataset_version,
        "dataset_checksum": dataset.manifest.content_sha256,
        "test_group_count": len(test_scenarios),
        "policies": metric_table,
        "model_diagnostics": {
            "Logistic": _outcome_metrics(eligible_test, logistic_scores, 0.0),
            "XGBoost": _outcome_metrics(
                eligible_test,
                np.asarray(
                    [xgb_scores_by_id[row.id] for row in eligible_test], dtype=float
                ),
                xgb_threshold,
            ),
        },
        "xgboost": {
            "parameters": xgb_parameters,
            "fit_partition": "TRAIN",
            "score_kind": xgb_score_kind,
        },
        "test_accessed": True,
    }
    _write_json(output / "formal_test_metrics.json", formal_metrics)
    _write_jsonl(
        output / "formal_test_decisions.jsonl",
        baseline_records
        + [{"policy": "Logistic", **item} for item in logistic_decisions]
        + records_by_policy["XGBoost"],
    )
    _write_jsonl(
        output / "formal_test_evaluation.jsonl",
        [{"policy": "Logistic", **item} for item in logistic_evaluations]
        + records_by_policy["XGBoost"]
        + baseline_records,
    )
    _write_json(
        output / "bootstrap_intervals.json", _bootstrap_intervals(records_by_policy)
    )
    test_distribution = {
        "preferred_strategy": dict(
            sorted(Counter(s.preferred_strategy.value for s in test_scenarios).items())
        ),
        "outcome_provenance": dict(
            sorted(Counter(row.outcome_provenance.value for row in test_rows).items())
        ),
        "repairability": dict(
            sorted(
                Counter(
                    s.context.features.m10_repairability for s in test_scenarios
                ).items()
            )
        ),
        "mutation_family": dict(
            sorted(Counter(s.mutation_family for s in test_scenarios).items())
        ),
        "api_family": dict(
            sorted(Counter(s.api_family_id for s in test_scenarios).items())
        ),
        "repository_family": dict(
            sorted(Counter(s.repository_family_id for s in test_scenarios).items())
        ),
        "template_family": dict(
            sorted(Counter(s.template_family_id for s in test_scenarios).items())
        ),
        "m10_outcome": dict(
            sorted(
                Counter(s.context.features.m10_outcome for s in test_scenarios).items()
            )
        ),
    }
    selected_distribution = {
        policy: dict(
            sorted(
                Counter(
                    str(item.get("chosen_strategy", item.get("selected_strategy")))
                    for item in records
                ).items()
            )
        )
        for policy, records in records_by_policy.items()
    }
    summary = {
        "status": "EVIDENCE_EXPANDED",
        "generalization_scope": _generalization_scope(train_scenarios, test_scenarios),
        "selected_strategy_distribution": selected_distribution,
        "test_distribution": test_distribution,
        "policies": metric_table,
        "bootstrap": {
            "replicates": GATE_C_BOOTSTRAP_REPLICATES,
            "unit": "decision_group",
            "seed": GATE_C_BOOTSTRAP_SEED,
        },
        "test_accessed": True,
        "gate_c_approval": "NOT_GRANTED; external scientific review remains required",
        "m14_allowed": False,
    }
    _write_json(output / "summary.json", summary)
    _write_json(
        output / "manifest.json",
        {
            "schema_version": "routeforge-gate-c-evidence-v1",
            "dataset_checksum": dataset.manifest.content_sha256,
            "model_checksum": model_checksum,
            "pre_test_manifest_checksum": access["pre_test_manifest_checksum"],
            "formal_test_access": marker_path.name,
            "files": sorted(path.name for path in output.iterdir() if path.is_file()),
            "test_accessed": True,
        },
    )
    (output / "README.md").write_text(
        "# Gate C Evidence\n\n"
        "This directory contains the frozen preparation manifest, one formal fresh "
        "TEST evaluation, group-level bootstrap intervals, and provenance-only "
        "offline metrics. The formal TEST marker prevents reruns. No provider, "
        "database, Redis, validation, or patch-generation service is used.\n",
        encoding="utf-8",
    )
    return {
        "dataset_checksum": dataset.manifest.content_sha256,
        "model_checksum": model_checksum,
        "test_groups": len(test_scenarios),
        "test_accessed": True,
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate and evaluate the frozen Gate C RouteForge evidence revision"
    )
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument(
        "--generate", action="store_true", help="generate the independent v2 dataset"
    )
    actions.add_argument(
        "--prepare",
        action="store_true",
        help="fit frozen models on TRAIN and evaluate VALIDATION",
    )
    actions.add_argument(
        "--formal-test",
        action="store_true",
        help="open and evaluate the fresh TEST exactly once",
    )
    parser.add_argument(
        "--protocol", type=Path, default=Path("data/routeforge-gate-c/protocol.json")
    )
    parser.add_argument("--dataset", type=Path, default=Path("data/routeforge-v2"))
    parser.add_argument("--output", type=Path, default=Path("data/routeforge-gate-c"))
    args = parser.parse_args()
    if args.generate:
        result = generate_gate_c_dataset(args.protocol, args.dataset)
        print(f"dataset_version={result.dataset.manifest.dataset_version}")
        print(f"dataset_checksum={result.dataset.manifest.content_sha256}")
        print(f"decision_groups={result.dataset.manifest.decision_group_count}")
        print(f"strategy_rows={result.dataset.manifest.strategy_outcome_row_count}")
        print(f"cross_partition_audit={_json(result.cross_partition_audit)}")
        print(f"historical_overlap={_json(result.historical_overlap)}")
    elif args.formal_test:
        print(_json(run_formal_gate_c_test(args.dataset, args.output)))
    else:
        print(_json(prepare_gate_c_evidence(args.dataset, args.output)))


if __name__ == "__main__":
    main()
