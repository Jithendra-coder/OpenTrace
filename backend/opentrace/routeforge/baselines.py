"""Offline RouteForge baselines for M12.

This module deliberately stops at development experiments.  It trains simple
strategy-outcome models on TRAIN, evaluates policy decisions on VALIDATION,
and never exposes a runtime router or reads TEST for model selection.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import shutil
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, cast

import numpy as np
from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]
from sklearn.metrics import (  # type: ignore[import-untyped]
    average_precision_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.preprocessing import OneHotEncoder, StandardScaler  # type: ignore[import-untyped]
from xgboost import XGBClassifier

from opentrace.routeforge.models import (
    ROUTEFORGE_FEATURE_SCHEMA_VERSION,
    ROUTEFORGE_OBJECTIVE_VERSION,
    ROUTEFORGE_STRATEGY_TAXONOMY_VERSION,
    RouteChoice,
    RouteForgeDataset,
    RouteForgeDatasetRow,
    RouteForgeFeatures,
    RouteForgeScenario,
    RouteForgeStrategy,
    RoutingObjective,
    StrategyOutcomeStatus,
)
from opentrace.routeforge.serialization import read_artifacts

BASELINE_RUN_SCHEMA_VERSION = "routeforge-baselines-v1"
BASELINE_SEED = 1201
LABEL_SHUFFLE_SEED = 1202
M11_HISTORICAL_CHECKSUM = (
    "28714d0cfc636c1861b8be451437ddc857a2572151f58132884431d0116d60a5"
)
M7_V3_CHECKSUM = "551e1e5e496c2166e71826179c01205d3f3da83c37ffe8facda4e0c0b7d50203"
M9_V3_METRIC_CHECKSUM = (
    "72102bda7b5e3b415ee4ca9a12fa7d6ebadca15f8a9938d8f217da52c01934e5"
)
REPAIR_STRATEGIES: tuple[RouteForgeStrategy, ...] = (
    RouteForgeStrategy.DETERMINISTIC,
    RouteForgeStrategy.SMALL,
    RouteForgeStrategy.MEDIUM,
    RouteForgeStrategy.STRONG,
)
STRATEGY_ORDER: tuple[RouteForgeStrategy, ...] = (
    RouteForgeStrategy.NO_AI,
    RouteForgeStrategy.DETERMINISTIC,
    RouteForgeStrategy.SMALL,
    RouteForgeStrategy.MEDIUM,
    RouteForgeStrategy.STRONG,
)

NUMERIC_FEATURES: tuple[str, ...] = (
    "direct_impact_count",
    "indirect_exposure_count",
    "maximum_graph_distance",
    "direct_caller_count",
    "upstream_caller_count",
    "coverage_unresolved_calls",
    "coverage_failed_files",
    "supported_rule_count",
    "expected_edit_count",
    "target_file_count",
    "repair_conflict_count",
    "ambiguity_flag_count",
)
BOOLEAN_FEATURES: tuple[str, ...] = (
    "direct_reference",
    "deterministic_rule_available",
    "shared_payload_ambiguity",
    "dynamic_payload",
    "nested_literal",
)
CATEGORICAL_FEATURES: tuple[str, ...] = (
    "change_category",
    "change_severity",
    "change_certainty",
    "breaking_classification",
    "compatibility_direction",
    "url_resolution_state",
    "request_resolution_state",
    "response_resolution_state",
    "m10_outcome",
    "m10_repairability",
    "source_shape",
)
MODEL_FEATURE_ALLOWLIST = RouteForgeFeatures.ALLOWLIST
FORBIDDEN_FEATURE_NAMES = (
    "preferred_strategy",
    "oracle_strategy",
    "outcome_status",
    "oracle_success",
    "synthetic_cost_units",
    "synthetic_latency_units",
    "quality_units",
    "scenario_id",
    "row_id",
    "partition_id",
    "template_family_id",
    "clone_fingerprint",
)


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _write_json(path: Path, value: object) -> None:
    path.write_text(_json(value) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, values: Iterable[object]) -> None:
    path.write_text("".join(f"{_json(value)}\n" for value in values), encoding="utf-8")


def _enum_value(value: object) -> str:
    return str(getattr(value, "value", value))


def _eligible(row: RouteForgeDatasetRow) -> bool:
    """Only ordinary SUCCESS/FAILURE oracle rows are supervised targets."""

    return (
        row.strategy is not RouteForgeStrategy.NO_AI
        and row.outcome in {StrategyOutcomeStatus.SUCCESS, StrategyOutcomeStatus.FAILURE}
    )


def _partition_rows(
    dataset: RouteForgeDataset, partition: str
) -> tuple[RouteForgeDatasetRow, ...]:
    rows = tuple(
        sorted(
            (
                row
                for row in dataset.rows
                if row.split_partition.value == partition
            ),
            key=lambda row: (row.decision_group_id, STRATEGY_ORDER.index(row.strategy)),
        )
    )
    groups: dict[str, list[RouteForgeDatasetRow]] = {}
    for row in rows:
        groups.setdefault(row.decision_group_id, []).append(row)
    expected_strategies = set(STRATEGY_ORDER)
    if any(
        len(group) != len(STRATEGY_ORDER)
        or {row.strategy for row in group} != expected_strategies
        for group in groups.values()
    ):
        raise ValueError("RouteForge strategy rows must remain grouped by decision")
    if any(len({row.split_partition for row in group}) != 1 for group in groups.values()):
        raise ValueError("RouteForge strategy rows crossed partitions")
    return rows


def _scenario_by_group(
    dataset: RouteForgeDataset, rows: Sequence[RouteForgeDatasetRow]
) -> tuple[RouteForgeScenario, ...]:
    scenarios = {scenario.decision_group_id: scenario for scenario in dataset.scenarios}
    group_ids = sorted({row.decision_group_id for row in rows})
    return tuple(scenarios[group_id] for group_id in group_ids)


@dataclass
class RouteForgeFeatureEncoder:
    """Train-fitted encoder for M11 pre-decision features plus strategy identity."""

    _categorical: OneHotEncoder | None = None
    _scaler: StandardScaler | None = None
    _feature_names: tuple[str, ...] = ()
    _fit_rows: int = 0

    def fit(self, rows: Sequence[RouteForgeDatasetRow]) -> RouteForgeFeatureEncoder:
        if not rows:
            raise ValueError("RouteForge preprocessing requires non-empty TRAIN rows")
        matrices = [self._values(row) for row in rows]
        numeric_names = NUMERIC_FEATURES + BOOLEAN_FEATURES
        self._scaler = StandardScaler().fit(
            np.asarray(
                [
                    [float(cast(float | int | bool, values[name])) for name in numeric_names]
                    for values in matrices
                ]
            )
        )
        categorical = np.asarray(
            [
                [str(values[name]) for name in CATEGORICAL_FEATURES + ("strategy_identity",)]
                for values in matrices
            ],
            dtype=object,
        )
        category_names = CATEGORICAL_FEATURES + ("strategy_identity",)
        categories = [
            np.asarray(
                sorted({str(values[name]) for values in matrices}),
                dtype=object,
            )
            for name in CATEGORICAL_FEATURES
        ]
        categories.append(
            np.asarray(
                [strategy.value for strategy in STRATEGY_ORDER],
                dtype=object,
            )
        )
        self._categorical = OneHotEncoder(
            categories=categories,
            handle_unknown="ignore",
            sparse_output=False,
            dtype=float,
        ).fit(categorical)
        self._feature_names = numeric_names + tuple(
            self._categorical.get_feature_names_out(
                category_names
            )
        )
        self._fit_rows = len(rows)
        return self

    def transform(self, rows: Sequence[RouteForgeDatasetRow]) -> np.ndarray:
        if self._categorical is None or self._scaler is None:
            raise ValueError("RouteForge preprocessing must be fitted on TRAIN first")
        matrices = [self._values(row) for row in rows]
        numeric_names = NUMERIC_FEATURES + BOOLEAN_FEATURES
        numeric = np.asarray(
            [
                [float(cast(float | int | bool, values[name])) for name in numeric_names]
                for values in matrices
            ],
            dtype=float,
        )
        categorical = np.asarray(
            [
                [str(values[name]) for name in CATEGORICAL_FEATURES + ("strategy_identity",)]
                for values in matrices
            ],
            dtype=object,
        )
        return np.column_stack(
            (self._scaler.transform(numeric), self._categorical.transform(categorical))
        )

    @staticmethod
    def _values(row: RouteForgeDatasetRow) -> dict[str, object]:
        raw = row.features.model_dump(mode="json")
        if set(raw) != set(MODEL_FEATURE_ALLOWLIST):
            raise ValueError("RouteForge model input does not match the M11 feature allowlist")
        values = dict(raw)
        values["strategy_identity"] = row.strategy.value
        return values

    @property
    def output_feature_names(self) -> tuple[str, ...]:
        if not self._feature_names:
            raise ValueError("RouteForge encoder is not fitted")
        return self._feature_names

    def metadata(self) -> dict[str, object]:
        return {
            "schema_version": ROUTEFORGE_FEATURE_SCHEMA_VERSION,
            "allowlist": list(MODEL_FEATURE_ALLOWLIST),
            "strategy_identity": [strategy.value for strategy in STRATEGY_ORDER],
            "expanded_feature_names": list(self.output_feature_names),
            "fit_partition": "TRAIN",
            "fit_row_count": self._fit_rows,
            "forbidden_features_absent": list(FORBIDDEN_FEATURE_NAMES),
        }


def _score(model: Any, matrix: np.ndarray) -> tuple[np.ndarray, str, float]:
    if hasattr(model, "decision_function"):
        return np.asarray(model.decision_function(matrix), dtype=float), "decision_function", 0.0
    return (
        np.asarray(model.predict_proba(matrix)[:, 1], dtype=float),
        "uncalibrated_success_score",
        0.5,
    )


def _diagnostics(
    model: Any, encoder: RouteForgeFeatureEncoder
) -> dict[str, object]:
    if hasattr(model, "coef_"):
        coefficients = np.asarray(model.coef_[0], dtype=float)
        order = np.argsort(np.abs(coefficients))[::-1]
        return {
            "kind": "logistic_coefficients",
            "values": {
                encoder.output_feature_names[index]: float(coefficients[index])
                for index in order[:10]
            },
            "interpretation": "Diagnostic coefficients, not causal effects.",
        }
    if hasattr(model, "feature_importances_"):
        importance = np.asarray(model.feature_importances_, dtype=float)
        order = np.argsort(importance)[::-1]
        return {
            "kind": "xgboost_feature_importance",
            "values": {
                encoder.output_feature_names[index]: float(importance[index])
                for index in order[:10]
            },
            "interpretation": "Diagnostic feature importance, not causal effects.",
        }
    return {"kind": "none", "values": {}}


def _outcome_metrics(
    rows: Sequence[RouteForgeDatasetRow], scores: np.ndarray, threshold: float
) -> dict[str, object]:
    labels = np.asarray([row.outcome is StrategyOutcomeStatus.SUCCESS for row in rows], dtype=int)
    predictions = (scores >= threshold).astype(int)
    result: dict[str, object] = {
        "eligible_rows": len(rows),
        "success_rows": int(labels.sum()),
        "failure_rows": int(len(labels) - labels.sum()),
        "precision": float(precision_score(labels, predictions, zero_division=0)),
        "recall": float(recall_score(labels, predictions, zero_division=0)),
        "f1": float(f1_score(labels, predictions, zero_division=0)),
        "score_threshold": threshold,
        "score_terminology": "uncalibrated oracle-success score",
    }
    if len(np.unique(labels)) == 2:
        result["roc_auc"] = float(roc_auc_score(labels, scores))
        result["pr_auc"] = float(average_precision_score(labels, scores))
    else:
        result["roc_auc"] = None
        result["pr_auc"] = None
        result["single_class_warning"] = True
    return result


@dataclass(frozen=True)
class _Decision:
    decision_group_id: str
    scenario_id: str
    chosen_strategy: str
    explanation: str
    oracle_preferred_strategy: str
    selected_outcome: str | None
    selected_cost_units: float | None
    selected_latency_units: float | None
    selected_quality_units: float | None
    objective_satisfied: bool
    constraint_violation: bool
    selected_unknown: bool
    selected_not_applicable: bool
    no_feasible_expected: bool
    objective_regret_units: float | None
    scores: dict[str, float]

    def as_dict(self) -> dict[str, object]:
        return {
            "decision_group_id": self.decision_group_id,
            "scenario_id": self.scenario_id,
            "chosen_strategy": self.chosen_strategy,
            "explanation": self.explanation,
            "oracle_preferred_strategy": self.oracle_preferred_strategy,
            "selected_outcome": self.selected_outcome,
            "selected_cost_units": self.selected_cost_units,
            "selected_latency_units": self.selected_latency_units,
            "selected_quality_units": self.selected_quality_units,
            "objective_satisfied": self.objective_satisfied,
            "constraint_violation": self.constraint_violation,
            "selected_unknown": self.selected_unknown,
            "selected_not_applicable": self.selected_not_applicable,
            "no_feasible_expected": self.no_feasible_expected,
            "objective_regret_units": self.objective_regret_units,
            "scores": self.scores,
        }


def _objective_satisfied(
    scenario: RouteForgeScenario,
    chosen: RouteChoice,
    outcome_by_strategy: Mapping[RouteForgeStrategy, RouteForgeDatasetRow],
    objective: RoutingObjective,
) -> bool:
    if scenario.context.no_repair_required:
        return chosen is RouteChoice.NO_AI
    if chosen is RouteChoice.NO_FEASIBLE_STRATEGY:
        return scenario.preferred_strategy is RouteChoice.NO_FEASIBLE_STRATEGY
    strategy = RouteForgeStrategy(chosen.value)
    row = outcome_by_strategy[strategy]
    return (
        row.outcome is objective.required_outcome
        and row.synthetic_cost_units is not None
        and row.synthetic_latency_units is not None
        and row.quality_units is not None
        and row.synthetic_latency_units <= objective.max_latency_units
        and row.quality_units >= objective.minimum_quality_units
    )


def _route_cost(
    chosen: RouteChoice,
    rows: Mapping[RouteForgeStrategy, RouteForgeDatasetRow],
) -> float:
    if chosen is RouteChoice.NO_FEASIBLE_STRATEGY:
        return 0.0
    row = rows[RouteForgeStrategy(chosen.value)]
    return float(row.synthetic_cost_units or 0.0)


Policy = Callable[[RouteForgeScenario, Mapping[RouteForgeStrategy, float]], tuple[RouteChoice, str]]


def _always(strategy: RouteForgeStrategy) -> Policy:
    def choose(
        scenario: RouteForgeScenario, _scores: Mapping[RouteForgeStrategy, float]
    ) -> tuple[RouteChoice, str]:
        if scenario.context.no_repair_required:
            return RouteChoice.NO_AI, "no_repair_required -> NO_AI"
        return RouteChoice(strategy.value), f"fixed strategy -> {strategy.value}"

    return choose


def _random_policy(seed: int) -> Policy:
    generator = random.Random(seed)

    def choose(
        scenario: RouteForgeScenario, _scores: Mapping[RouteForgeStrategy, float]
    ) -> tuple[RouteChoice, str]:
        if scenario.context.no_repair_required:
            return RouteChoice.NO_AI, "no_repair_required -> NO_AI"
        strategy = generator.choice(REPAIR_STRATEGIES)
        return RouteChoice(strategy.value), f"seeded random choice ({seed}) -> {strategy.value}"

    return choose


RULE_POLICY_ID = "RF-B3-RULE-V1"
RULE_POLICY_VERSION = "routeforge-rule-v1"
RULE_FEATURES_USED: tuple[str, ...] = (
    "no_repair_required",
    "m10_repairability",
    "deterministic_rule_available",
    "expected_edit_count",
    "repair_conflict_count",
    "coverage_unresolved_calls",
    "ambiguity_flag_count",
    "maximum_graph_distance",
    "dynamic_payload",
    "shared_payload_ambiguity",
)
SPECIAL_STATE_SEMANTICS = {
    "NO_AI": (
        "no_repair_required routes to NO_AI; repair-required rows do not treat NO_AI as success"
    ),
    "NO_FEASIBLE_STRATEGY": (
        "policies may abstain; fixed strategies are penalized when the selected route is infeasible"
    ),
    "UNKNOWN": "retained as UNKNOWN and excluded from ordinary supervised targets",
    "NOT_APPLICABLE": "retained as NOT_APPLICABLE and excluded from ordinary supervised targets",
}
RULES: tuple[dict[str, object], ...] = (
    {
        "order": 1,
        "when": "context.no_repair_required",
        "route": "NO_AI",
        "explanation": "No repair is required.",
    },
    {
        "order": 2,
        "when": "m10_repairability == UNSUPPORTED and deterministic_rule_available == false",
        "route": "NO_FEASIBLE_STRATEGY",
        "explanation": "No supported deterministic rule and M10 marked the repair unsupported.",
    },
    {
        "order": 3,
        "when": "SUPPORTED deterministic rule with one edit, no conflicts, and complete coverage",
        "route": "DETERMINISTIC",
        "explanation": "A bounded deterministic repair is directly supported.",
    },
    {
        "order": 4,
        "when": "conflict or high ambiguity or graph distance >= 3",
        "route": "STRONG",
        "explanation": "Evidence indicates a high-complexity or conflicting repair.",
    },
    {
        "order": 5,
        "when": "dynamic/shared payload or unresolved coverage",
        "route": "MEDIUM",
        "explanation": "Partial evidence requires a middle strategy.",
    },
    {
        "order": 6,
        "when": "otherwise",
        "route": "SMALL",
        "explanation": "Default bounded repair strategy.",
    },
)


def _rule_policy(
    scenario: RouteForgeScenario, _scores: Mapping[RouteForgeStrategy, float]
) -> tuple[RouteChoice, str]:
    if scenario.context.no_repair_required:
        return RouteChoice.NO_AI, "rule-1: no repair is required"
    features = scenario.context.features
    if features.m10_repairability == "UNSUPPORTED" and not features.deterministic_rule_available:
        return RouteChoice.NO_FEASIBLE_STRATEGY, "rule-2: unsupported with no deterministic rule"
    if (
        features.m10_repairability == "SUPPORTED"
        and features.deterministic_rule_available
        and features.expected_edit_count <= 1
        and features.repair_conflict_count == 0
        and features.coverage_unresolved_calls == 0
    ):
        return RouteChoice.DETERMINISTIC, "rule-3: bounded deterministic repair"
    if (
        features.repair_conflict_count > 0
        or features.ambiguity_flag_count >= 2
        or features.maximum_graph_distance >= 3
    ):
        return RouteChoice.STRONG, "rule-4: conflict/high ambiguity/deep graph"
    if (
        features.dynamic_payload
        or features.shared_payload_ambiguity
        or features.coverage_unresolved_calls > 0
    ):
        return RouteChoice.MEDIUM, "rule-5: partial or dynamic evidence"
    return RouteChoice.SMALL, "rule-6: bounded default"


def _predecision_no_feasible(scenario: RouteForgeScenario) -> bool:
    features = scenario.context.features
    return (
        not scenario.context.no_repair_required
        and features.m10_repairability == "UNSUPPORTED"
        and not features.deterministic_rule_available
    )


def _model_policy(
    scenario: RouteForgeScenario, scores: Mapping[RouteForgeStrategy, float]
) -> tuple[RouteChoice, str]:
    if scenario.context.no_repair_required:
        return RouteChoice.NO_AI, "no_repair_required -> NO_AI"
    if _predecision_no_feasible(scenario):
        return (
            RouteChoice.NO_FEASIBLE_STRATEGY,
            "pre-decision unsupported repair -> NO_FEASIBLE_STRATEGY",
        )
    candidates = [
        (strategy, score)
        for strategy, score in scores.items()
        if strategy in REPAIR_STRATEGIES and math.isfinite(score)
    ]
    if not candidates:
        return RouteChoice.NO_FEASIBLE_STRATEGY, "no finite learned strategy score"
    order = {strategy: index for index, strategy in enumerate(STRATEGY_ORDER)}
    selected = min(candidates, key=lambda item: (-item[1], order[item[0]]))
    return RouteChoice(selected[0].value), f"highest uncalibrated score -> {selected[0].value}"


def _evaluate_policy(
    scenarios: Sequence[RouteForgeScenario],
    validation_rows: Sequence[RouteForgeDatasetRow],
    policy: Policy,
    objective: RoutingObjective,
    score_by_group: Mapping[str, Mapping[RouteForgeStrategy, float]] | None = None,
) -> tuple[tuple[_Decision, ...], dict[str, object]]:
    grouped_rows: dict[str, dict[RouteForgeStrategy, RouteForgeDatasetRow]] = {}
    for row in validation_rows:
        grouped_rows.setdefault(row.decision_group_id, {})[row.strategy] = row
    decisions: list[_Decision] = []
    for scenario in scenarios:
        rows = grouped_rows[scenario.decision_group_id]
        scores = dict((score_by_group or {}).get(scenario.decision_group_id, {}))
        chosen, explanation = policy(scenario, scores)
        selectable = {
            RouteChoice.NO_AI,
            RouteChoice.DETERMINISTIC,
            RouteChoice.SMALL,
            RouteChoice.MEDIUM,
            RouteChoice.STRONG,
        }
        selected_row = rows.get(RouteForgeStrategy(chosen.value)) if chosen in selectable else None
        objective_satisfied = _objective_satisfied(scenario, chosen, rows, objective)
        oracle_cost = _route_cost(scenario.preferred_strategy, rows)
        selected_cost = None if selected_row is None else selected_row.synthetic_cost_units
        selected_cost_for_regret = (
            0.0
            if chosen is RouteChoice.NO_FEASIBLE_STRATEGY and objective_satisfied
            else float(selected_cost)
            if selected_cost is not None and objective_satisfied
            else None
        )
        decisions.append(
            _Decision(
                decision_group_id=scenario.decision_group_id,
                scenario_id=scenario.scenario_id,
                chosen_strategy=chosen.value,
                explanation=explanation,
                oracle_preferred_strategy=scenario.preferred_strategy.value,
                selected_outcome=None if selected_row is None else selected_row.outcome.value,
                selected_cost_units=selected_cost,
                selected_latency_units=(
                    None if selected_row is None else selected_row.synthetic_latency_units
                ),
                selected_quality_units=None if selected_row is None else selected_row.quality_units,
                objective_satisfied=objective_satisfied,
                constraint_violation=not objective_satisfied,
                selected_unknown=(
                    selected_row is not None
                    and selected_row.outcome is StrategyOutcomeStatus.UNKNOWN
                ),
                selected_not_applicable=(
                    selected_row is not None
                    and selected_row.outcome is StrategyOutcomeStatus.NOT_APPLICABLE
                ),
                no_feasible_expected=(
                    scenario.preferred_strategy is RouteChoice.NO_FEASIBLE_STRATEGY
                ),
                objective_regret_units=(
                    None
                    if selected_cost_for_regret is None
                    else selected_cost_for_regret - oracle_cost
                ),
                scores={strategy.value: float(score) for strategy, score in scores.items()},
            )
        )
    decision_dicts = [decision.as_dict() for decision in decisions]
    costs = [
        decision.selected_cost_units
        for decision in decisions
        if decision.selected_cost_units is not None
    ]
    latencies = [
        decision.selected_latency_units
        for decision in decisions
        if decision.selected_latency_units is not None
    ]
    objective_successes = sum(decision.objective_satisfied for decision in decisions)
    expected_no_feasible = sum(decision.no_feasible_expected for decision in decisions)
    correct_no_feasible = sum(
        decision.no_feasible_expected
        and decision.chosen_strategy == RouteChoice.NO_FEASIBLE_STRATEGY.value
        for decision in decisions
    )
    metrics: dict[str, object] = {
        "decision_count": len(decisions),
        "oracle_objective_satisfaction_rate": objective_successes / len(decisions),
        "constraint_violation_rate": sum(decision.constraint_violation for decision in decisions)
        / len(decisions),
        "synthetic_average_cost_units": float(np.mean(costs)) if costs else None,
        "synthetic_average_latency_units": float(np.mean(latencies)) if latencies else None,
        "synthetic_cost_per_oracle_successful_decision_units": (
            float(sum(costs) / objective_successes) if objective_successes else None
        ),
        "strong_strategy_usage_rate": sum(
            decision.chosen_strategy == RouteForgeStrategy.STRONG.value for decision in decisions
        )
        / len(decisions),
        "no_feasible_expected_count": expected_no_feasible,
        "no_feasible_correct_count": correct_no_feasible,
        "no_feasible_handling_rate": (
            correct_no_feasible / expected_no_feasible if expected_no_feasible else None
        ),
        "objective_regret_units_mean": (
            float(
                np.mean(
                    [
                        decision.objective_regret_units
                        for decision in decisions
                        if decision.objective_regret_units is not None
                    ]
                )
            )
            if any(decision.objective_regret_units is not None for decision in decisions)
            else None
        ),
        "objective_regret_defined_count": sum(
            decision.objective_regret_units is not None for decision in decisions
        ),
        "unknown_selected_count": sum(decision.selected_unknown for decision in decisions),
        "not_applicable_selected_count": sum(
            decision.selected_not_applicable for decision in decisions
        ),
        "offline_only": True,
        "cost_semantics": "SYNTHETIC_RELATIVE_UNITS",
        "latency_semantics": "SYNTHETIC_RELATIVE_UNITS",
    }
    return tuple(decisions), {"metrics": metrics, "decisions": decision_dicts}


def _upstream_integrity(dataset_directory: Path) -> dict[str, object]:
    root = dataset_directory.parents[1]
    m7_manifest = json.loads(
        (root / "data" / "m7-v3" / "manifest.json").read_text(encoding="utf-8")
    )
    m9_manifest = json.loads(
        (root / "artifacts" / "m9-v3" / "manifests" / "formal.json").read_text(encoding="utf-8")
    )
    scenario_lines = dataset_directory.joinpath("scenarios.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    canonical = next(
        s for s in scenario_lines if '"scenario_id":"scenario-001"' in s
    )
    canonical_data = json.loads(canonical)
    m10 = next(
        outcome for outcome in canonical_data["outcomes"] if outcome["strategy"] == "DETERMINISTIC"
    )
    return {
        "m7_v3_checksum_actual": m7_manifest["content_sha256"],
        "m7_v3_checksum_expected": M7_V3_CHECKSUM,
        "m7_v3_unchanged": m7_manifest["content_sha256"] == M7_V3_CHECKSUM,
        "m9_v3_metric_checksum_actual": m9_manifest["metric_artifact_checksum"],
        "m9_v3_metric_checksum_expected": M9_V3_METRIC_CHECKSUM,
        "m9_v3_unchanged": m9_manifest["metric_artifact_checksum"] == M9_V3_METRIC_CHECKSUM,
        "m10_deterministic_outcome": m10["outcome"],
        "m10_rule_id": canonical_data["context"]["m10_evidence"]["rule_id"],
        "m10_candidate_generated": m10["candidate_generated"],
        "m10_observed_not_validated": m10["outcome"] == "UNKNOWN",
    }


def _train_support(rows: Sequence[RouteForgeDatasetRow]) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for strategy in STRATEGY_ORDER:
        counts = Counter(row.outcome.value for row in rows if row.strategy is strategy)
        result[strategy.value] = {
            status.value: int(counts.get(status.value, 0))
            for status in StrategyOutcomeStatus
        }
    return result


def _artifact_paths(experiment_id: str) -> dict[str, str]:
    return {
        "experiment": f"experiments/{experiment_id}.json",
        "predictions": f"predictions/{experiment_id}.jsonl",
        "decisions": f"decisions/{experiment_id}.jsonl",
        "model_provenance": f"models/{experiment_id}.json",
    }


def _model_record(
    experiment_id: str,
    hypothesis: str,
    model_name: str,
    model: Any,
    encoder: RouteForgeFeatureEncoder,
    train_rows: Sequence[RouteForgeDatasetRow],
    validation_rows: Sequence[RouteForgeDatasetRow],
    validation_scores: Mapping[str, float],
    score_kind: str,
    score_threshold: float,
    decisions: Sequence[_Decision],
    policy_metrics: dict[str, object],
    dataset: RouteForgeDataset,
    parameters: dict[str, object],
    seed: int,
) -> dict[str, object]:
    predictions = [
        {
            "row_id": row.id,
            "scenario_id": row.scenario_id,
            "decision_group_id": row.decision_group_id,
            "strategy": row.strategy.value,
            "outcome": row.outcome.value,
            "target_eligible": _eligible(row),
            "score": validation_scores[row.id],
            "score_kind": score_kind,
        }
        for row in validation_rows
    ]
    eligible_validation = [row for row in validation_rows if _eligible(row)]
    outcome_scores = np.asarray(
        [validation_scores[row.id] for row in eligible_validation], dtype=float
    )
    outcome_diagnostics = _outcome_metrics(eligible_validation, outcome_scores, score_threshold)
    return {
        "experiment_id": experiment_id,
        "artifact_paths": _artifact_paths(experiment_id),
        "date": date.today().isoformat(),
        "hypothesis": hypothesis,
        "dataset_version": dataset.manifest.dataset_version,
        "dataset_checksum": dataset.manifest.content_sha256,
        "split_strategy": "M11 decision_group_id partition; TRAIN fit, VALIDATION diagnostics",
        "feature_schema_version": ROUTEFORGE_FEATURE_SCHEMA_VERSION,
        "strategy_taxonomy_version": ROUTEFORGE_STRATEGY_TAXONOMY_VERSION,
        "objective_version": ROUTEFORGE_OBJECTIVE_VERSION,
        "baseline": model_name,
        "model_provenance": {
            "model_type": model_name,
            "parameters": parameters,
            "seed": seed,
            "fit_partition": "TRAIN",
            "fit_row_count": len(train_rows),
            "preprocessing": encoder.metadata(),
            "trusted_local_artifact_only": True,
        },
        "special_state_semantics": SPECIAL_STATE_SEMANTICS,
        "policy_metrics": policy_metrics,
        "learned_outcome_diagnostics": outcome_diagnostics,
        "feature_diagnostics": _diagnostics(model, encoder),
        "validation_predictions": predictions,
        "validation_decisions": [decision.as_dict() for decision in decisions],
        "limitations": [
            "Validation and offline synthetic/curated oracle metrics only.",
            "Scores are uncalibrated and not validated repair probabilities.",
            "TEST is sealed and was not evaluated or used for model selection.",
        ],
        "reproduction_command": (
            "python -m opentrace.routeforge.baselines --output data/routeforge-m12"
        ),
    }


@dataclass(frozen=True)
class BaselineRunResult:
    """In-memory result returned by the real M12 development run."""

    dataset_checksum: str
    split_counts: dict[str, dict[str, int]]
    train_support: dict[str, dict[str, int]]
    experiments: tuple[dict[str, object], ...]
    label_shuffle_sanity: dict[str, object]
    upstream_integrity: dict[str, object]
    reproducibility_fingerprint: str

    def summary(self) -> dict[str, object]:
        return {
            "schema_version": BASELINE_RUN_SCHEMA_VERSION,
            "dataset_checksum": self.dataset_checksum,
            "split_counts": self.split_counts,
            "train_support": self.train_support,
            "experiment_ids": [record["experiment_id"] for record in self.experiments],
            "test_used_for_model_selection": False,
            "test_evaluated": False,
            "upstream_integrity": self.upstream_integrity,
            "label_shuffle_sanity": self.label_shuffle_sanity,
            "reproducibility_fingerprint": self.reproducibility_fingerprint,
            "m13_data_adequacy": "INADEQUATE FOR GATE C EVIDENCE",
            "m13_data_adequacy_reason": (
                "Only five TRAIN and three VALIDATION decision groups exist; "
                "this run is pipeline-only."
            ),
        }


def _split_counts(dataset: RouteForgeDataset) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for partition in ("TRAIN", "VALIDATION", "TEST"):
        rows = [row for row in dataset.rows if row.split_partition.value == partition]
        counts[partition] = {
            "decision_groups": len({row.decision_group_id for row in rows}),
            "strategy_rows": len(rows),
        }
    return counts


def _clear_output(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for child in output.iterdir():
        if child.name == "README.md":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def _write_artifacts(result: BaselineRunResult, output: Path) -> None:
    _clear_output(output)
    for directory in ("experiments", "predictions", "decisions", "models"):
        (output / directory).mkdir(parents=True, exist_ok=True)
    for record in result.experiments:
        experiment_id = str(record["experiment_id"])
        _write_json(output / "experiments" / f"{experiment_id}.json", record)
        predictions = cast(list[object], record.get("validation_predictions", []))
        decisions = cast(list[object], record.get("validation_decisions", []))
        _write_jsonl(
            output / "predictions" / f"{experiment_id}.jsonl",
            predictions,
        )
        _write_jsonl(
            output / "decisions" / f"{experiment_id}.jsonl",
            decisions,
        )
        if record.get("model_provenance") is not None:
            _write_json(
                output / "models" / f"{experiment_id}.json",
                record["model_provenance"],
            )
    _write_json(output / "label_shuffle_sanity.json", result.label_shuffle_sanity)
    _write_json(output / "summary.json", result.summary())
    _write_jsonl(output / "experiments.jsonl", result.experiments)
    _write_json(
        output / "manifest.json",
        {
            **result.summary(),
            "artifact_directories": ["experiments", "predictions", "decisions", "models"],
            "test_metrics": "SEALED_NOT_COMPUTED",
        },
    )


def run_m12_baselines(
    dataset_directory: Path | str = Path("data/routeforge-m11"),
    output_directory: Path | str | None = Path("data/routeforge-m12"),
    *,
    seed: int = BASELINE_SEED,
) -> BaselineRunResult:
    """Run all required M12 baselines on M11 TRAIN/VALIDATION only."""

    dataset_path = Path(dataset_directory)
    dataset = read_artifacts(dataset_path)
    if dataset.manifest.content_sha256 != M11_HISTORICAL_CHECKSUM:
        raise ValueError("M11 canonical checksum differs from the frozen historical checksum")
    train_rows = _partition_rows(dataset, "TRAIN")
    validation_rows = _partition_rows(dataset, "VALIDATION")
    _partition_rows(dataset, "TEST")
    validation_scenarios = _scenario_by_group(dataset, validation_rows)
    objective = dataset.manifest.objective
    split_counts = _split_counts(dataset)
    train_support = _train_support(train_rows)
    upstream = _upstream_integrity(dataset_path)
    if not upstream["m7_v3_unchanged"] or not upstream["m9_v3_unchanged"]:
        raise ValueError("M7 or M9 upstream evidence changed")

    experiments: list[dict[str, object]] = []
    policy_specs: tuple[tuple[str, str, Policy, dict[str, object]], ...] = (
        (
            "RF-B0-ALWAYS-SMALL",
            "Always Small is a minimal repair-strategy floor when repair is required.",
            _always(RouteForgeStrategy.SMALL),
            {"policy": "always", "strategy": "SMALL"},
        ),
        (
            "RF-B1-ALWAYS-STRONG",
            "Always Strong is the fixed expensive-strategy comparison baseline.",
            _always(RouteForgeStrategy.STRONG),
            {"policy": "always", "strategy": "STRONG"},
        ),
        (
            "RF-B2-RANDOM",
            "Seeded random selection provides a provider-independent stochastic floor.",
            _random_policy(seed),
            {
                "policy": "random",
                "seed": seed,
                "candidate_strategies": [
                    strategy.value for strategy in REPAIR_STRATEGIES
                ],
            },
        ),
        (
            RULE_POLICY_ID,
            "A frozen pre-decision rule policy can route without oracle outcomes.",
            _rule_policy,
            {
                "policy": "ordered_rules",
                "policy_id": RULE_POLICY_ID,
                "version": RULE_POLICY_VERSION,
                "rules": list(RULES),
                "frozen_before_validation": True,
                "features_used": list(RULE_FEATURES_USED),
            },
        ),
    )
    for experiment_id, hypothesis, policy, parameters in policy_specs:
        decisions, evaluated = _evaluate_policy(
            validation_scenarios, validation_rows, policy, objective
        )
        record = {
            "experiment_id": experiment_id,
            "artifact_paths": _artifact_paths(experiment_id),
            "date": date.today().isoformat(),
            "hypothesis": hypothesis,
            "dataset_version": dataset.manifest.dataset_version,
            "dataset_checksum": dataset.manifest.content_sha256,
            "split_strategy": "M11 decision_group_id partition; VALIDATION policy diagnostics",
            "feature_schema_version": ROUTEFORGE_FEATURE_SCHEMA_VERSION,
            "strategy_taxonomy_version": ROUTEFORGE_STRATEGY_TAXONOMY_VERSION,
            "objective_version": objective.version,
            "baseline": parameters["policy"],
            "model_provenance": parameters,
            "special_state_semantics": SPECIAL_STATE_SEMANTICS,
            "policy_metrics": evaluated["metrics"],
            "validation_predictions": [],
            "validation_decisions": evaluated["decisions"],
            "limitations": [
                "Validation and offline synthetic/curated oracle metrics only.",
                "TEST is sealed and was not evaluated or used for model selection.",
            ],
            "reproduction_command": (
                "python -m opentrace.routeforge.baselines --output data/routeforge-m12"
            ),
        }
        experiments.append(record)

    random_first = experiments[2]["validation_decisions"]
    random_second, _ = _evaluate_policy(
        validation_scenarios,
        validation_rows,
        _random_policy(seed),
        objective,
    )
    random_repeat_match = random_first == [decision.as_dict() for decision in random_second]
    if not random_repeat_match:
        raise ValueError("random baseline is not deterministic for the fixed seed")
    experiments[2]["reproducibility"] = {"seed": seed, "repeat_match": True}

    train_eligible = tuple(row for row in train_rows if _eligible(row))
    if not train_eligible:
        raise ValueError("no eligible TRAIN outcomes are available for learned baselines")
    encoder = RouteForgeFeatureEncoder().fit(train_eligible)
    train_matrix = encoder.transform(train_eligible)
    train_labels = np.asarray(
        [row.outcome is StrategyOutcomeStatus.SUCCESS for row in train_eligible], dtype=int
    )
    validation_candidates = tuple(
        row for row in validation_rows if row.strategy in REPAIR_STRATEGIES
    )
    validation_matrix = encoder.transform(validation_candidates)
    model_specs: tuple[tuple[str, str, str, dict[str, object], Any], ...] = (
        (
            "RF-B4-LOGISTIC",
            "Logistic Regression estimates an interpretable strategy-conditional "
            "oracle-success score.",
            "LOGISTIC_REGRESSION",
            {"C": 1.0, "class_weight": "balanced", "max_iter": 500, "solver": "liblinear"},
            LogisticRegression(
                C=1.0,
                class_weight="balanced",
                max_iter=500,
                solver="liblinear",
                random_state=seed,
            ),
        ),
        (
            "RF-B5-XGBOOST",
            "A bounded shallow XGBoost model tests a small nonlinear strategy-outcome baseline.",
            "XGBOOST",
            {
                "n_estimators": 8,
                "max_depth": 2,
                "learning_rate": 0.2,
                "subsample": 1.0,
                "colsample_bytree": 1.0,
                "reg_lambda": 1.0,
                "tree_method": "hist",
            },
            XGBClassifier(
                n_estimators=8,
                max_depth=2,
                learning_rate=0.2,
                subsample=1.0,
                colsample_bytree=1.0,
                reg_lambda=1.0,
                random_state=seed,
                n_jobs=1,
                eval_metric="logloss",
                tree_method="hist",
                verbosity=0,
            ),
        ),
    )
    for experiment_id, hypothesis, model_name, parameters, model in model_specs:
        model.fit(train_matrix, train_labels)
        validation_scores_array, score_kind, score_threshold = _score(model, validation_matrix)
        scores_by_row = {
            row.id: float(score)
            for row, score in zip(validation_candidates, validation_scores_array, strict=True)
        }
        scores_by_group: dict[str, dict[RouteForgeStrategy, float]] = {}
        for row in validation_candidates:
            scores_by_group.setdefault(row.decision_group_id, {})[row.strategy] = (
                scores_by_row[row.id]
            )
        decisions, evaluated = _evaluate_policy(
            validation_scenarios,
            validation_rows,
            _model_policy,
            objective,
            scores_by_group,
        )
        experiments.append(
            _model_record(
                experiment_id,
                hypothesis,
                model_name,
                model,
                encoder,
                train_eligible,
                validation_candidates,
                scores_by_row,
                score_kind,
                score_threshold,
                decisions,
                cast(dict[str, object], evaluated["metrics"]),
                dataset,
                parameters,
                seed,
            )
        )

    shuffled_values = train_labels.tolist()
    random.Random(LABEL_SHUFFLE_SEED).shuffle(shuffled_values)
    shuffled = np.asarray(shuffled_values, dtype=int)
    shuffle_model = LogisticRegression(
        C=1.0,
        class_weight="balanced",
        max_iter=500,
        solver="liblinear",
        random_state=LABEL_SHUFFLE_SEED,
    )
    shuffle_model.fit(train_matrix, shuffled)
    shuffled_scores_array, shuffled_score_kind, shuffled_threshold = _score(
        shuffle_model, validation_matrix
    )
    shuffled_scores = {
        row.id: float(score)
        for row, score in zip(validation_candidates, shuffled_scores_array, strict=True)
    }
    shuffled_by_group: dict[str, dict[RouteForgeStrategy, float]] = {}
    for row in validation_candidates:
        shuffled_by_group.setdefault(row.decision_group_id, {})[row.strategy] = (
            shuffled_scores[row.id]
        )
    shuffled_decisions, shuffled_evaluation = _evaluate_policy(
        validation_scenarios,
        validation_rows,
        _model_policy,
        objective,
        shuffled_by_group,
    )
    eligible_validation = tuple(row for row in validation_candidates if _eligible(row))
    label_shuffle_sanity: dict[str, object] = {
        "experiment_id": "RF-SANITY-LABEL-SHUFFLE",
        "seed": LABEL_SHUFFLE_SEED,
        "fit_partition": "TRAIN",
        "validation_partition": "VALIDATION",
        "used_for_model_selection": False,
        "score_kind": shuffled_score_kind,
        "outcome_diagnostics": _outcome_metrics(
            eligible_validation,
            np.asarray([shuffled_scores[row.id] for row in eligible_validation], dtype=float),
            shuffled_threshold,
        ),
        "policy_metrics": shuffled_evaluation["metrics"],
        "validation_decisions": [decision.as_dict() for decision in shuffled_decisions],
        "interpretation": (
            "Exploratory sanity check on TRAIN/VALIDATION only; tiny data limits inference."
        ),
    }

    fingerprint_payload = [
        {
            "experiment_id": record["experiment_id"],
            "policy_metrics": record["policy_metrics"],
            "validation_predictions": record["validation_predictions"],
            "validation_decisions": record["validation_decisions"],
        }
        for record in experiments
    ]
    reproducibility_fingerprint = hashlib.sha256(
        _json(fingerprint_payload).encode("utf-8")
    ).hexdigest()
    result = BaselineRunResult(
        dataset_checksum=dataset.manifest.content_sha256,
        split_counts=split_counts,
        train_support=train_support,
        experiments=tuple(experiments),
        label_shuffle_sanity=label_shuffle_sanity,
        upstream_integrity=upstream,
        reproducibility_fingerprint=reproducibility_fingerprint,
    )
    if output_directory is not None:
        _write_artifacts(result, Path(output_directory))
    return result


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run offline RouteForge M12 baselines")
    parser.add_argument("--dataset", default="data/routeforge-m11")
    parser.add_argument("--output", default="data/routeforge-m12")
    parser.add_argument("--seed", type=int, default=BASELINE_SEED)
    args = parser.parse_args()
    result = run_m12_baselines(args.dataset, args.output, seed=args.seed)
    print(f"dataset_checksum={result.dataset_checksum}")
    print(f"experiments={len(result.experiments)}")
    print(f"validation_groups={result.split_counts['VALIDATION']['decision_groups']}")
    print(f"reproducibility_fingerprint={result.reproducibility_fingerprint}")
    print(f"output={Path(args.output)}")


if __name__ == "__main__":
    main()
