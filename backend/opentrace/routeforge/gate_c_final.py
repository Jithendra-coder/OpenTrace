"""Sealed Gate C v3 evidence with learned abstention and fresh route diversity."""

from __future__ import annotations

import hashlib
import json
import random
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any, cast

import numpy as np
from xgboost import XGBClassifier

from opentrace.routeforge.baselines import (
    REPAIR_STRATEGIES,
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
from opentrace.routeforge.gate_c_evidence import (
    _bootstrap_intervals,
    _features_for,
    _m10_evidence,
    _outcomes_for,
)
from opentrace.routeforge.generator import (
    RouteForgeDatasetGenerator,
    _OutcomeSpec,
    _ScenarioPlan,
)
from opentrace.routeforge.models import (
    DatasetFamily,
    FeatureOrigin,
    OutcomeProvenance,
    RouteChoice,
    RouteForgeConfig,
    RouteForgeDataset,
    RouteForgeDatasetRow,
    RouteForgeManifest,
    RouteForgeScenario,
    RouteForgeStrategy,
    RoutingObjective,
    SplitPartition,
    StrategyOutcomeStatus,
    stable_id,
)
from opentrace.routeforge.router import (
    ROUTEFORGE_LEARNED_ABSTENTION_POLICY_VERSION,
    RouteForgeRouter,
    RoutingRequest,
    _fit_primary_artifact,
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

PROTOCOL_VERSION = "routeforge-gate-c-v3-protocol"
DATASET_VERSION = "routeforge-dataset-v3"
GENERATOR_VERSION = "routeforge-gate-c-final-generator-v1"
MASTER_SEED = 3301
RANDOM_SEED = 3303
BOOTSTRAP_SEED = 3305
BOOTSTRAP_REPLICATES = 1000
PARTITION_COUNTS = {
    SplitPartition.TRAIN: 60,
    SplitPartition.VALIDATION: 18,
    SplitPartition.TEST: 18,
}
PREFERRED_ORDER = (
    RouteChoice.NO_AI,
    RouteChoice.DETERMINISTIC,
    RouteChoice.SMALL,
    RouteChoice.MEDIUM,
    RouteChoice.STRONG,
    RouteChoice.NO_FEASIBLE_STRATEGY,
)


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json(value) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, values: Sequence[Mapping[str, object]]) -> None:
    path.write_text("".join(_json(value) + "\n" for value in values), encoding="utf-8")


def _partition_for_index(index: int) -> SplitPartition:
    if index < PARTITION_COUNTS[SplitPartition.TRAIN]:
        return SplitPartition.TRAIN
    if index < PARTITION_COUNTS[SplitPartition.TRAIN] + PARTITION_COUNTS[SplitPartition.VALIDATION]:
        return SplitPartition.VALIDATION
    return SplitPartition.TEST


def _preferred_for_index(index: int) -> RouteChoice:
    return PREFERRED_ORDER[index % len(PREFERRED_ORDER)]


def _family_value(kind: str, index: int, partition: SplitPartition) -> str:
    starts = {
        SplitPartition.TRAIN: 0,
        SplitPartition.VALIDATION: 20,
        SplitPartition.TEST: 40,
    }
    span = 20 if kind == "template" else 8
    return f"v3-{kind}-{starts[partition] + index % span:02d}"


def _plan(index: int) -> _ScenarioPlan:
    partition = _partition_for_index(index)
    preferred = _preferred_for_index(index)
    # The plan is fully authored before model fitting; preferred outcome is never a feature.
    features = _features_for(index + 96, preferred, partition)
    provenance = (
        OutcomeProvenance.CURATED_ORACLE if index % 3 == 0 else OutcomeProvenance.SYNTHETIC_ORACLE
    )
    outcome_specs = tuple(
        _OutcomeSpec(
            status=item.status,
            provenance=item.provenance,
            producer="routeforge-gate-c-v3-oracle-v1",
            cost=item.cost,
            latency=item.latency,
            quality=item.quality,
            candidate_generated=item.candidate_generated,
            no_repair_required=item.no_repair_required,
            notes=(
                f"Frozen v3 offline outcome for independent scenario {index + 1}; "
                "not provider execution or validated repair success."
            ),
        )
        for item in _outcomes_for(preferred, index + 97, provenance, features)
    )
    return _ScenarioPlan(
        scenario_id=f"v3-scenario-{index + 1:03d}",
        family=(
            DatasetFamily.SYNTHETIC,
            DatasetFamily.CURATED_ADVERSARIAL,
            DatasetFamily.REALISTIC,
        )[index % 3],
        repository_family_id=_family_value("repository", index, partition),
        api_family_id=_family_value("api", index, partition),
        migration_id=f"v3-migration-{index + 1:03d}",
        mutation_family=features.change_category,
        template_family_id=_family_value("template", index, partition),
        feature_origin=FeatureOrigin.SCENARIO_AUTHORED,
        features=features,
        m10_evidence=_m10_evidence(features, index + 97),
        no_repair_required=preferred is RouteChoice.NO_AI,
        outcomes=outcome_specs,
        provenance="Predeclared v3 Gate C offline scenario policy; no provider execution.",
        tags=(
            "v3-fresh-instance",
            f"partition-{partition.value.lower()}",
            f"preferred-{preferred.value.lower()}",
            f"pair-{index // len(PREFERRED_ORDER):02d}",
        ),
    )


def _materialize(plan: _ScenarioPlan, config: RouteForgeConfig) -> RouteForgeScenario:
    generated = RouteForgeDatasetGenerator(config)._materialize(plan)
    source = stable_id(
        "routeforge-v3-source",
        plan.scenario_id,
        plan.repository_family_id,
        plan.api_family_id,
        plan.mutation_family,
        plan.features.source_shape,
    )
    routing = stable_id("routeforge-v3-routing", plan.scenario_id, plan.features.canonical_json())
    template = stable_id("routeforge-v3-template", plan.scenario_id, plan.template_family_id)
    scenario = stable_id("routeforge-v3-scenario", plan.scenario_id, source, routing, template)
    return generated.model_copy(
        update={
            "source_fingerprint": source,
            "routing_feature_fingerprint": routing,
            "template_fingerprint": template,
            "scenario_fingerprint": scenario,
        }
    )


def _rows(scenarios: Sequence[RouteForgeScenario]) -> tuple[RouteForgeDatasetRow, ...]:
    rows: list[RouteForgeDatasetRow] = []
    for scenario in scenarios:
        index = int(scenario.scenario_id.rsplit("-", maxsplit=1)[1]) - 1
        partition = _partition_for_index(index)
        outcomes = {item.strategy: item for item in scenario.outcomes}
        for strategy in RouteForgeStrategy:
            outcome = outcomes[strategy]
            rows.append(
                RouteForgeDatasetRow(
                    id=stable_id("routeforge-v3-row", scenario.decision_group_id, strategy.value),
                    schema_version=DATASET_VERSION,
                    dataset_version=DATASET_VERSION,
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
    return tuple(sorted(rows, key=lambda item: item.id))


def _manifest(
    generator: RouteForgeDatasetGenerator,
    scenarios: tuple[RouteForgeScenario, ...],
    rows: tuple[RouteForgeDatasetRow, ...],
) -> RouteForgeManifest:
    base = generator._manifest(scenarios, rows)
    preliminary = base.model_copy(
        update={
            "schema_version": DATASET_VERSION,
            "dataset_version": DATASET_VERSION,
            "generator_version": GENERATOR_VERSION,
            "content_sha256": "PENDING",
        }
    )
    checksum = content_checksum(
        RouteForgeDataset(manifest=preliminary, scenarios=scenarios, rows=rows)
    )
    return preliminary.model_copy(update={"content_sha256": checksum})


def _fingerprint_sets(dataset: RouteForgeDataset) -> dict[str, set[str]]:
    return {
        "scenario": {item.scenario_fingerprint for item in dataset.scenarios},
        "migration": {item.migration_id for item in dataset.scenarios},
        "source": {item.source_fingerprint for item in dataset.scenarios},
        "routing_feature": {item.routing_feature_fingerprint for item in dataset.scenarios},
        "template": {item.template_fingerprint for item in dataset.scenarios},
        "outcome_table": {item.outcome_table_fingerprint for item in dataset.scenarios},
    }


def _clone_audit(dataset: RouteForgeDataset) -> dict[str, object]:
    by_partition = {
        partition.value: _fingerprint_sets(
            RouteForgeDataset(
                manifest=dataset.manifest,
                scenarios=tuple(
                    item
                    for item in dataset.scenarios
                    if any(
                        row.scenario_id == item.scenario_id and row.split_partition is partition
                        for row in dataset.rows
                    )
                ),
                rows=(),
            )
        )
        for partition in SplitPartition
    }
    pairs = (("TRAIN", "VALIDATION"), ("TRAIN", "TEST"), ("VALIDATION", "TEST"))
    overlap = {
        name: sum(
            len(by_partition[left][name] & by_partition[right][name]) for left, right in pairs
        )
        for name in (
            "scenario",
            "migration",
            "source",
            "routing_feature",
            "template",
            "outcome_table",
        )
    }
    return {
        "cross_partition_overlap": overlap,
        "all_zero": all(value == 0 for value in overlap.values()),
    }


def generate_dataset(
    protocol_path: Path | str = Path("data/routeforge-gate-c-v3/protocol.json"),
    output_directory: Path | str = Path("data/routeforge-v3"),
) -> dict[str, object]:
    protocol_file = Path(protocol_path)
    protocol = json.loads(protocol_file.read_text(encoding="utf-8"))
    if (
        protocol.get("protocol_version") != PROTOCOL_VERSION
        or not protocol.get("created_before_generation")
        or protocol.get("dataset_checksum") != "PENDING_GENERATION"
    ):
        raise ValueError("v3 generation requires the frozen pre-generation protocol")
    config = RouteForgeConfig(
        seed=MASTER_SEED,
        dataset_version=DATASET_VERSION,
        generator_version=GENERATOR_VERSION,
        include_canonical_m10=False,
    )
    generator = RouteForgeDatasetGenerator(config)
    scenarios = tuple(
        _materialize(_plan(index), config) for index in range(sum(PARTITION_COUNTS.values()))
    )
    rows = _rows(scenarios)
    dataset = RouteForgeDataset(
        manifest=_manifest(generator, scenarios, rows), scenarios=scenarios, rows=rows
    )
    validate_dataset(dataset)
    write_artifacts(dataset, output_directory)
    current = _fingerprint_sets(dataset)
    historical_paths = (Path("data/routeforge-m11"), Path("data/routeforge-v2"))
    historical = [read_artifacts(path) for path in historical_paths]
    historical_overlap = {
        name: sum(len(current[name] & _fingerprint_sets(item)[name]) for item in historical)
        for name in current
    }
    if any(historical_overlap.values()):
        raise ValueError("v3 dataset overlaps a forbidden historical dataset")
    audit = _clone_audit(dataset)
    if not audit["all_zero"]:
        raise ValueError("v3 clone-safe split audit failed")
    preferred = {
        partition.value: dict(
            sorted(
                Counter(
                    item.preferred_strategy.value
                    for item in scenarios
                    if _partition_for_index(int(item.scenario_id[-3:]) - 1) is partition
                ).items()
            )
        )
        for partition in SplitPartition
    }
    if any(preferred["TEST"].get(item.value, 0) < 2 for item in PREFERRED_ORDER):
        raise ValueError("v3 TEST preferred-route diversity requirement failed")
    return {
        "dataset_checksum": dataset.manifest.content_sha256,
        "decision_groups": len(scenarios),
        "strategy_rows": len(rows),
        "protocol_checksum": hashlib.sha256(protocol_file.read_bytes()).hexdigest(),
        "clone_audit": audit,
        "historical_overlap": historical_overlap,
        "preferred_distribution": preferred,
    }


def _random_applicable_policy(seed: int) -> Any:
    generator = random.Random(seed)

    def choose(
        scenario: RouteForgeScenario, _scores: Mapping[RouteForgeStrategy, float]
    ) -> tuple[RouteChoice, str]:
        if scenario.context.no_repair_required:
            return RouteChoice.NO_AI, "no_repair_required -> NO_AI"
        candidates = tuple(
            strategy
            for strategy in REPAIR_STRATEGIES
            if strategy is not RouteForgeStrategy.DETERMINISTIC
            or scenario.context.features.deterministic_rule_available
        )
        selected = generator.choice(candidates)
        return RouteChoice(selected.value), f"seeded random applicable choice ({seed})"

    return choose


def _score_policy(
    scenario: RouteForgeScenario, scores: Mapping[RouteForgeStrategy, float]
) -> tuple[RouteChoice, str]:
    if scenario.context.no_repair_required:
        return RouteChoice.NO_AI, "no_repair_required -> NO_AI"
    candidates = [(strategy, score) for strategy, score in scores.items() if np.isfinite(score)]
    if not candidates:
        return RouteChoice.NO_FEASIBLE_STRATEGY, "no finite learned score"
    strategy = max(candidates, key=lambda item: (item[1], item[0].value))[0]
    return RouteChoice(strategy.value), "highest uncalibrated score"


def _fit_xgb(
    rows: Sequence[RouteForgeDatasetRow],
) -> tuple[RouteForgeFeatureEncoder, Any, dict[str, object]]:
    eligible = tuple(row for row in rows if _eligible(row))
    encoder = RouteForgeFeatureEncoder().fit(eligible)
    parameters: dict[str, object] = {
        "n_estimators": 8,
        "max_depth": 2,
        "learning_rate": 0.2,
        "subsample": 1.0,
        "colsample_bytree": 1.0,
        "reg_lambda": 1.0,
        "tree_method": "hist",
        "random_state": MASTER_SEED,
        "n_jobs": 1,
        "eval_metric": "logloss",
        "verbosity": 0,
    }
    labels = np.asarray(
        [row.outcome is StrategyOutcomeStatus.SUCCESS for row in eligible], dtype=int
    )
    return encoder, XGBClassifier(**parameters).fit(encoder.transform(eligible), labels), parameters


def _xgb_checksum(model: Any) -> str:
    return hashlib.sha256(model.get_booster().save_raw(raw_format="json")).hexdigest()


def _scores_for_rows(
    encoder: RouteForgeFeatureEncoder, model: Any, rows: Sequence[RouteForgeDatasetRow]
) -> tuple[dict[str, float], dict[str, dict[RouteForgeStrategy, float]], float]:
    values, _, threshold = _score(model, encoder.transform(rows))
    by_id = {row.id: float(score) for row, score in zip(rows, values, strict=True)}
    by_group: dict[str, dict[RouteForgeStrategy, float]] = {}
    for row in rows:
        by_group.setdefault(row.decision_group_id, {})[row.strategy] = by_id[row.id]
    return by_id, by_group, threshold


def _router_records(
    router: RouteForgeRouter,
    scenarios: Sequence[RouteForgeScenario],
    rows: Sequence[RouteForgeDatasetRow],
    objective: RoutingObjective,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    grouped: dict[str, dict[RouteForgeStrategy, RouteForgeDatasetRow]] = {}
    for row in rows:
        grouped.setdefault(row.decision_group_id, {})[row.strategy] = row
    decisions: list[dict[str, object]] = []
    evaluations: list[dict[str, object]] = []
    for scenario in scenarios:
        decision = router.route(RoutingRequest(context=scenario.context, objective=objective))
        decision_data = decision.model_dump(mode="json")
        evaluation = _validation_evaluation(
            decision, scenario, grouped[scenario.decision_group_id], objective
        )
        evaluation["abstention_code"] = (
            None if decision.abstention is None else decision.abstention.code
        )
        decisions.append(decision_data)
        evaluations.append(evaluation)
    return decisions, evaluations


def _enhance_metrics(records: Sequence[Mapping[str, object]]) -> dict[str, object]:
    count = len(records)
    expected = sum(
        item["oracle_preferred_strategy"] == RouteChoice.NO_FEASIBLE_STRATEGY.value
        for item in records
    )
    selected = [
        item
        for item in records
        if item.get("selected_strategy", item.get("chosen_strategy"))
        == RouteChoice.NO_FEASIBLE_STRATEGY.value
    ]
    correct = sum(
        item["oracle_preferred_strategy"] == RouteChoice.NO_FEASIBLE_STRATEGY.value
        for item in selected
    )
    learned = [item for item in records if item.get("abstention_code") == "LEARNED_ABSTENTION"]
    structural = [
        item for item in records if item.get("abstention_code") == "STRUCTURAL_NO_FEASIBLE"
    ]
    metrics: dict[str, object] = {
        "decision_count": count,
        "oracle_objective_satisfaction_rate": sum(
            bool(item["objective_satisfied"]) for item in records
        )
        / count,
        "constraint_violation_rate": sum(bool(item["constraint_violation"]) for item in records)
        / count,
        "synthetic_average_cost_units": _mean(records, "selected_cost_units"),
        "synthetic_average_latency_units": _mean(records, "selected_latency_units"),
        "synthetic_cost_per_oracle_successful_decision_units": _cost_per_success(records),
        "strong_strategy_usage_rate": sum(
            item.get("selected_strategy", item.get("chosen_strategy")) == "STRONG"
            for item in records
        )
        / count,
        "no_feasible_expected_count": expected,
        "no_feasible_correct_count": correct,
        "no_feasible_handling_rate": correct / expected if expected else None,
        "no_feasible_precision": correct / len(selected) if selected else None,
        "no_feasible_recall": correct / expected if expected else None,
        "learned_abstention_count": len(learned),
        "correct_learned_abstention_count": sum(
            item["oracle_preferred_strategy"] == RouteChoice.NO_FEASIBLE_STRATEGY.value
            for item in learned
        ),
        "false_learned_abstention_count": sum(
            item["oracle_preferred_strategy"] != RouteChoice.NO_FEASIBLE_STRATEGY.value
            for item in learned
        ),
        "structural_no_feasible_count": len(structural),
        "objective_regret_units_mean": _mean(records, "objective_regret_units"),
        "objective_regret_defined_count": sum(
            item.get("objective_regret_units") is not None for item in records
        ),
        "offline_only": True,
    }
    return metrics


def _mean(records: Sequence[Mapping[str, object]], key: str) -> float | None:
    values = [float(cast(float | int, item[key])) for item in records if item.get(key) is not None]
    return float(np.mean(values)) if values else None


def _cost_per_success(records: Sequence[Mapping[str, object]]) -> float | None:
    successes = sum(bool(item["objective_satisfied"]) for item in records)
    values = [
        float(cast(float | int, item["selected_cost_units"]))
        for item in records
        if item.get("selected_cost_units") is not None
    ]
    return float(sum(values) / successes) if successes else None


def _split_fingerprint(dataset: RouteForgeDataset) -> str:
    return hashlib.sha256(
        _json(
            {
                partition.value: sorted(
                    row.decision_group_id
                    for row in dataset.rows
                    if row.split_partition is partition
                )
                for partition in SplitPartition
            }
        ).encode("utf-8")
    ).hexdigest()


def prepare(
    dataset_directory: Path | str = Path("data/routeforge-v3"),
    output_directory: Path | str = Path("data/routeforge-gate-c-v3"),
) -> dict[str, object]:
    output = Path(output_directory)
    if (output / "formal-test-access.json").exists():
        raise ValueError("v3 TEST has already been opened; preparation is sealed")
    dataset = read_artifacts(dataset_directory)
    train = _partition_rows(dataset, "TRAIN")
    validation = _partition_rows(dataset, "VALIDATION")
    objective = dataset.manifest.objective
    artifact = _fit_primary_artifact(dataset, train, MASTER_SEED)
    output.mkdir(parents=True, exist_ok=True)
    model_checksum = save_model_artifact(artifact, output / "model.json")
    router = RouteForgeRouter.from_artifact(
        output / "model.json", ROUTEFORGE_LEARNED_ABSTENTION_POLICY_VERSION
    )
    validation_scenarios = _scenario_by_group(dataset, validation)
    logistic_decisions, logistic_records = _router_records(
        router, validation_scenarios, validation, objective
    )
    xgb_encoder, xgb_model, xgb_parameters = _fit_xgb(train)
    xgb_by_id, xgb_scores, xgb_threshold = _scores_for_rows(xgb_encoder, xgb_model, validation)
    xgb_decisions, xgb_result = _evaluate_policy(
        validation_scenarios, validation, _score_policy, objective, xgb_scores
    )
    baseline_policies = {
        "Always Small": _always(RouteForgeStrategy.SMALL),
        "Always Strong": _always(RouteForgeStrategy.STRONG),
        "Random": _random_applicable_policy(RANDOM_SEED),
        "Rule": _rule_policy,
    }
    baseline: dict[str, list[dict[str, object]]] = {}
    for name, policy in baseline_policies.items():
        _, result = _evaluate_policy(validation_scenarios, validation, policy, objective)
        baseline[name] = [
            dict(item) for item in cast(Sequence[Mapping[str, object]], result["decisions"])
        ]
    eligible = tuple(row for row in validation if _eligible(row))
    logistic_scores = np.asarray(
        [
            router._score(
                next(
                    item.context
                    for item in validation_scenarios
                    if item.decision_group_id == row.decision_group_id
                ),
                row.strategy,
            )
            for row in eligible
        ],
        dtype=float,
    )
    metrics = {name: _enhance_metrics(records) for name, records in baseline.items()}
    metrics["Logistic"] = _enhance_metrics(logistic_records)
    metrics["XGBoost"] = _enhance_metrics(
        cast(Sequence[Mapping[str, object]], xgb_result["decisions"])
    )
    protocol = Path("data/routeforge-gate-c-v3/protocol.json")
    pretest = {
        "protocol_version": PROTOCOL_VERSION,
        "protocol_checksum": hashlib.sha256(protocol.read_bytes()).hexdigest(),
        "dataset_checksum": dataset.manifest.content_sha256,
        "split_fingerprint": _split_fingerprint(dataset),
        "feature_schema_version": dataset.manifest.feature_schema_version,
        "strategy_taxonomy_version": dataset.manifest.strategy_taxonomy_version,
        "router_policy": ROUTEFORGE_LEARNED_ABSTENTION_POLICY_VERSION,
        "logistic_model_checksum": model_checksum,
        "xgboost_model_checksum": _xgb_checksum(xgb_model),
        "baseline_definitions": list(baseline_policies) + ["Logistic", "XGBoost"],
        "metric_definitions": list(next(iter(metrics.values())).keys()),
        "bootstrap": {
            "unit": "decision_group",
            "replicates": BOOTSTRAP_REPLICATES,
            "seed": BOOTSTRAP_SEED,
            "confidence": 0.95,
        },
        "test_accessed": False,
        "test_access_rule": "exactly one canonical formal TEST access after this freeze",
    }
    _write_json(
        output / "validation_metrics.json",
        {
            "policies": metrics,
            "model_diagnostics": {
                "Logistic": _outcome_metrics(eligible, logistic_scores, 0.0),
                "XGBoost": _outcome_metrics(
                    eligible, np.asarray([xgb_by_id[row.id] for row in eligible]), xgb_threshold
                ),
            },
            "development_only": True,
            "test_accessed": False,
        },
    )
    _write_jsonl(
        output / "validation_decisions.jsonl",
        [{"policy": name, **record} for name, records in baseline.items() for record in records]
        + [{"policy": "Logistic", **item} for item in logistic_decisions]
        + [
            {"policy": "XGBoost", **dict(item)}
            for item in cast(Sequence[Mapping[str, object]], xgb_result["decisions"])
        ],
    )
    _write_jsonl(
        output / "validation_evaluation.jsonl",
        [{"policy": name, **record} for name, records in baseline.items() for record in records]
        + [{"policy": "Logistic", **item} for item in logistic_records]
        + [
            {"policy": "XGBoost", **dict(item)}
            for item in cast(Sequence[Mapping[str, object]], xgb_result["decisions"])
        ],
    )
    _write_json(output / "pre-test-manifest.json", pretest)
    _write_json(
        output / "model-provenance.json",
        {
            "logistic_model_checksum": model_checksum,
            "xgboost_model_checksum": pretest["xgboost_model_checksum"],
            "logistic_hyperparameters": artifact.hyperparameters,
            "xgboost_hyperparameters": xgb_parameters,
            "fit_partition": "TRAIN",
            "test_accessed": False,
        },
    )
    return {
        "dataset_checksum": dataset.manifest.content_sha256,
        "model_checksum": model_checksum,
        "xgb_checksum": pretest["xgboost_model_checksum"],
        "validation_groups": len(validation_scenarios),
        "test_accessed": False,
    }


def _test_distribution(
    scenarios: Sequence[RouteForgeScenario], rows: Sequence[RouteForgeDatasetRow]
) -> dict[str, object]:
    eligible = [row for row in rows if _eligible(row)]
    return {
        "preferred_strategy": dict(
            sorted(Counter(item.preferred_strategy.value for item in scenarios).items())
        ),
        "eligible_outcomes": dict(sorted(Counter(item.outcome.value for item in eligible).items())),
        "api_family": dict(sorted(Counter(item.api_family_id for item in scenarios).items())),
        "repository_family": dict(
            sorted(Counter(item.repository_family_id for item in scenarios).items())
        ),
        "template_family": dict(
            sorted(Counter(item.template_family_id for item in scenarios).items())
        ),
        "mutation_family": dict(
            sorted(Counter(item.mutation_family for item in scenarios).items())
        ),
    }


def formal_test(
    dataset_directory: Path | str = Path("data/routeforge-v3"),
    output_directory: Path | str = Path("data/routeforge-gate-c-v3"),
) -> dict[str, object]:
    output = Path(output_directory)
    marker = output / "formal-test-access.json"
    if marker.exists():
        raise ValueError("canonical v3 formal TEST has already been accessed")
    pretest_path = output / "pre-test-manifest.json"
    if not pretest_path.exists():
        raise ValueError("pre-test manifest is required before TEST access")
    pretest = json.loads(pretest_path.read_text(encoding="utf-8"))
    dataset = read_artifacts(dataset_directory)
    if (
        dataset.manifest.content_sha256 != pretest["dataset_checksum"]
        or _split_fingerprint(dataset) != pretest["split_fingerprint"]
    ):
        raise ValueError("dataset or split changed after pre-test freeze")
    train = _partition_rows(dataset, "TRAIN")
    artifact, checksum = load_model_artifact(output / "model.json")
    if checksum != pretest["logistic_model_checksum"]:
        raise ValueError("frozen Logistic artifact changed")
    xgb_encoder, xgb_model, xgb_parameters = _fit_xgb(train)
    if _xgb_checksum(xgb_model) != pretest["xgboost_model_checksum"]:
        raise ValueError("frozen XGBoost comparator changed")
    test = _partition_rows(dataset, "TEST")
    scenarios = _scenario_by_group(dataset, test)
    distribution = _test_distribution(scenarios, test)
    preferred = cast(dict[str, int], distribution["preferred_strategy"])
    if any(preferred.get(item.value, 0) < 2 for item in PREFERRED_ORDER):
        raise ValueError("formal TEST lacks predeclared preferred-route diversity")
    outcomes = cast(dict[str, int], distribution["eligible_outcomes"])
    if not outcomes.get("SUCCESS") or not outcomes.get("FAILURE"):
        raise ValueError("formal TEST lacks eligible outcome-class diversity")
    _write_json(
        marker,
        {
            "seal": "FORMAL TEST ACCESSED ONCE AFTER PRE-TEST MANIFEST FREEZE",
            "accessed_on": date.today().isoformat(),
            "test_accessed": True,
            "dataset_checksum": dataset.manifest.content_sha256,
            "pre_test_manifest_checksum": hashlib.sha256(pretest_path.read_bytes()).hexdigest(),
            "test_group_count": len(scenarios),
            "selection_after_access": False,
            "configuration_changed_after_freeze": False,
        },
    )
    router = RouteForgeRouter(artifact, checksum, ROUTEFORGE_LEARNED_ABSTENTION_POLICY_VERSION)
    logistic_decisions, logistic_records = _router_records(
        router, scenarios, test, dataset.manifest.objective
    )
    xgb_by_id, xgb_scores, xgb_threshold = _scores_for_rows(xgb_encoder, xgb_model, test)
    xgb_decisions, xgb_result = _evaluate_policy(
        scenarios, test, _score_policy, dataset.manifest.objective, xgb_scores
    )
    policies = {
        "Always Small": _always(RouteForgeStrategy.SMALL),
        "Always Strong": _always(RouteForgeStrategy.STRONG),
        "Random": _random_applicable_policy(RANDOM_SEED),
        "Rule": _rule_policy,
    }
    records: dict[str, list[dict[str, object]]] = {}
    for name, policy in policies.items():
        _, result = _evaluate_policy(scenarios, test, policy, dataset.manifest.objective)
        records[name] = [
            dict(item) for item in cast(Sequence[Mapping[str, object]], result["decisions"])
        ]
    records["Logistic"] = logistic_records
    records["XGBoost"] = [
        dict(item) for item in cast(Sequence[Mapping[str, object]], xgb_result["decisions"])
    ]
    metrics = {name: _enhance_metrics(item) for name, item in records.items()}
    eligible = tuple(row for row in test if _eligible(row))
    logistic_scores = np.asarray(
        [
            router._score(
                next(
                    item.context
                    for item in scenarios
                    if item.decision_group_id == row.decision_group_id
                ),
                row.strategy,
            )
            for row in eligible
        ]
    )
    diagnostics = {
        "Logistic": _outcome_metrics(eligible, logistic_scores, 0.0),
        "XGBoost": _outcome_metrics(
            eligible, np.asarray([xgb_by_id[row.id] for row in eligible]), xgb_threshold
        ),
    }
    _write_json(
        output / "formal_test_metrics.json",
        {
            "dataset_checksum": dataset.manifest.content_sha256,
            "test_group_count": len(scenarios),
            "policies": metrics,
            "model_diagnostics": diagnostics,
            "xgboost": {"parameters": xgb_parameters, "fit_partition": "TRAIN"},
            "test_accessed": True,
        },
    )
    _write_jsonl(
        output / "formal_test_decisions.jsonl",
        [{"policy": name, **record} for name, values in records.items() for record in values],
    )
    _write_jsonl(
        output / "formal_test_evaluation.jsonl",
        [{"policy": name, **record} for name, values in records.items() for record in values],
    )
    _write_json(
        output / "bootstrap_intervals.json",
        _bootstrap_intervals(records, seed=BOOTSTRAP_SEED, replicates=BOOTSTRAP_REPLICATES),
    )
    selection = {
        name: dict(
            sorted(
                Counter(
                    str(item.get("selected_strategy", item.get("chosen_strategy")))
                    for item in values
                ).items()
            )
        )
        for name, values in records.items()
    }
    ai_required = [
        item
        for item, record in zip(scenarios, logistic_records, strict=True)
        if item.context.features.m10_outcome == "AI_REQUIRED"
    ]
    ai_records = [
        record
        for item, record in zip(scenarios, logistic_records, strict=True)
        if item.context.features.m10_outcome == "AI_REQUIRED"
    ]
    deterministic_records = [
        record
        for item, record in zip(scenarios, logistic_records, strict=True)
        if item.context.features.deterministic_rule_available
    ]
    learned_value = (
        "PARTIALLY SUPPORTED"
        if cast(float, metrics["Logistic"]["oracle_objective_satisfaction_rate"])
        >= cast(float, metrics["Always Small"]["oracle_objective_satisfaction_rate"])
        else "NOT SUPPORTED"
    )
    summary = {
        "status": "EVIDENCE_EXPANDED",
        "test_distribution": distribution,
        "selected_strategy_distribution": selection,
        "policies": metrics,
        "model_diagnostics": diagnostics,
        "learned_abstention": {
            key: metrics["Logistic"][key]
            for key in (
                "learned_abstention_count",
                "correct_learned_abstention_count",
                "false_learned_abstention_count",
                "structural_no_feasible_count",
                "no_feasible_precision",
                "no_feasible_recall",
            )
        },
        "ai_required_diagnostics": {
            "groups": len(ai_required),
            "selections": dict(
                sorted(Counter(str(item["selected_strategy"]) for item in ai_records).items())
            ),
            "deterministic_selected": sum(
                item["selected_strategy"] == "DETERMINISTIC" for item in ai_records
            ),
        },
        "deterministic_diagnostics": {
            "groups": len(deterministic_records),
            "selections": dict(
                sorted(
                    Counter(
                        str(item["selected_strategy"]) for item in deterministic_records
                    ).items()
                )
            ),
        },
        "learned_routing_value": learned_value,
        "cost_aware_inference": "NOT IMPLEMENTED — future versioned architecture/research item",
        "generalization_scope": (
            "PARTIALLY SUPPORTED — fresh held-out migration/template/repository/API "
            "families; synthetic evidence only"
        ),
        "bootstrap": {
            "replicates": BOOTSTRAP_REPLICATES,
            "seed": BOOTSTRAP_SEED,
            "unit": "decision_group",
        },
        "test_accessed": True,
        "gate_c_approval": "NOT_GRANTED; external scientific review remains required",
        "m14_allowed": False,
    }
    _write_json(output / "summary.json", summary)
    _write_json(
        output / "manifest.json",
        {
            "schema_version": PROTOCOL_VERSION,
            "dataset_checksum": dataset.manifest.content_sha256,
            "logistic_model_checksum": checksum,
            "xgboost_model_checksum": _xgb_checksum(xgb_model),
            "pre_test_manifest_checksum": hashlib.sha256(pretest_path.read_bytes()).hexdigest(),
            "formal_test_access": marker.name,
            "files": sorted(path.name for path in output.iterdir() if path.is_file()),
            "test_accessed": True,
        },
    )
    return {
        "dataset_checksum": dataset.manifest.content_sha256,
        "test_groups": len(scenarios),
        "learned_routing_value": learned_value,
        "test_accessed": True,
    }


def reproduce(
    dataset_directory: Path | str = Path("data/routeforge-v3"),
    output_directory: Path | str = Path("data/routeforge-gate-c-v3"),
    reproduction_directory: Path | str = Path("data/routeforge-gate-c-v3-repro"),
) -> dict[str, object]:
    """Verify independent generation/model determinism without reopening canonical TEST."""

    dataset = read_artifacts(dataset_directory)
    canonical = Path(output_directory)
    repro = Path(reproduction_directory)
    if repro.exists():
        raise ValueError("reproduction destination must be a new separate path")
    generated = generate_dataset(output_directory=Path("data/routeforge-v3-repro"))
    reproduced = read_artifacts(Path("data/routeforge-v3-repro"))
    if (
        generated["dataset_checksum"] != dataset.manifest.content_sha256
        or reproduced.manifest.content_sha256 != dataset.manifest.content_sha256
    ):
        raise ValueError("v3 dataset reproduction checksum mismatch")
    result = prepare(Path("data/routeforge-v3-repro"), repro)
    pretest = json.loads((canonical / "pre-test-manifest.json").read_text(encoding="utf-8"))
    canonical_formal = {
        name: hashlib.sha256((canonical / name).read_bytes()).hexdigest()
        for name in (
            "formal_test_metrics.json",
            "formal_test_decisions.jsonl",
            "bootstrap_intervals.json",
        )
    }
    report = {
        "dataset_checksum_match": True,
        "split_fingerprint_match": _split_fingerprint(reproduced) == pretest["split_fingerprint"],
        "logistic_model_checksum_match": result["model_checksum"]
        == pretest["logistic_model_checksum"],
        "xgboost_model_checksum_match": result["xgb_checksum"] == pretest["xgboost_model_checksum"],
        "canonical_formal_artifact_checksums": canonical_formal,
        "canonical_formal_test_rerun": False,
        "reproduction_test_accessed": False,
    }
    _write_json(repro / "reproducibility.json", report)
    return report


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run frozen RouteForge Gate C v3 evidence")
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--generate", action="store_true")
    actions.add_argument("--prepare", action="store_true")
    actions.add_argument("--formal-test", action="store_true")
    actions.add_argument("--reproduce", action="store_true")
    parser.add_argument(
        "--protocol", type=Path, default=Path("data/routeforge-gate-c-v3/protocol.json")
    )
    parser.add_argument("--dataset", type=Path, default=Path("data/routeforge-v3"))
    parser.add_argument("--output", type=Path, default=Path("data/routeforge-gate-c-v3"))
    args = parser.parse_args()
    if args.generate:
        result = generate_dataset(args.protocol, args.dataset)
    elif args.prepare:
        result = prepare(args.dataset, args.output)
    elif args.formal_test:
        result = formal_test(args.dataset, args.output)
    else:
        result = reproduce(args.dataset, args.output)
    print(_json(result))


if __name__ == "__main__":
    main()
