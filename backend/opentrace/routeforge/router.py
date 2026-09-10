"""M13 learned RouteForge router over the frozen M12 Logistic scorer."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np
from pydantic import Field
from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]

from opentrace.routeforge.baselines import (
    BASELINE_SEED,
    BOOLEAN_FEATURES,
    CATEGORICAL_FEATURES,
    M11_HISTORICAL_CHECKSUM,
    MODEL_FEATURE_ALLOWLIST,
    NUMERIC_FEATURES,
    REPAIR_STRATEGIES,
    STRATEGY_ORDER,
    _eligible,
    _objective_satisfied,
    _outcome_metrics,
    _partition_rows,
    _route_cost,
)
from opentrace.routeforge.models import (
    ROUTEFORGE_FEATURE_SCHEMA_VERSION,
    ROUTEFORGE_OBJECTIVE_VERSION,
    ROUTEFORGE_STRATEGY_TAXONOMY_VERSION,
    CanonicalModel,
    RouteChoice,
    RouteForgeDataset,
    RouteForgeDatasetRow,
    RouteForgeScenario,
    RouteForgeStrategy,
    RoutingDecisionContext,
    RoutingObjective,
)
from opentrace.routeforge.serialization import read_artifacts

ROUTEFORGE_ROUTER_ARTIFACT_SCHEMA = "routeforge-router-v1"
ROUTEFORGE_SCORER_VERSION = "routeforge-logistic-scorer-v1"
ROUTEFORGE_ROUTER_VERSION = "routeforge-router-v1"
ROUTEFORGE_DECISION_POLICY_VERSION = "routeforge-score-routing-v2"
ROUTEFORGE_LEARNED_ABSTENTION_POLICY_VERSION = "routeforge-score-routing-v3"
ROUTEFORGE_MODEL_ID = "RF-M13-LOGISTIC-V1"
ROUTEFORGE_EXPERIMENT_ID = "RF-M13-LOGISTIC-ROUTER-V1"
M12_LOGISTIC_EXPERIMENT_ID = "RF-B4-LOGISTIC"
TEST_SEAL_MESSAGE = "TEST METRICS NOT COMPUTED — DATASET INADEQUATE FOR GATE C EVIDENCE"


class RoutingRequest(CanonicalModel):
    """Strict provider-independent request containing pre-decision evidence only."""

    context: RoutingDecisionContext
    objective: RoutingObjective = RoutingObjective()
    strategy_taxonomy_version: str = ROUTEFORGE_STRATEGY_TAXONOMY_VERSION


class StrategyScore(CanonicalModel):
    strategy: RouteForgeStrategy
    score: float | None = None
    applicable: bool
    reason: str


class RoutingAbstention(CanonicalModel):
    code: str
    reason: str


class RoutingExplanation(CanonicalModel):
    summary: str
    applicability: tuple[str, ...]
    selection_basis: str
    evidence_features: tuple[str, ...]
    rejected_alternatives: tuple[str, ...] = ()


class RoutingDecision(CanonicalModel):
    decision_id: str
    context_id: str
    scenario_id: str
    decision_group_id: str
    migration_id: str
    selected_strategy: RouteChoice
    strategy_scores: tuple[StrategyScore, ...]
    feature_schema_version: str
    strategy_taxonomy_version: str
    objective_version: str
    model_id: str
    scorer_version: str
    router_version: str
    decision_policy_version: str
    model_artifact_checksum: str
    context_fingerprint: str
    explanation: RoutingExplanation
    warnings: tuple[str, ...]
    abstention: RoutingAbstention | None = None


class RouterModelArtifact(CanonicalModel):
    """JSON-safe frozen Logistic scorer and preprocessing state."""

    artifact_schema_version: str = ROUTEFORGE_ROUTER_ARTIFACT_SCHEMA
    model_id: str
    model_version: str
    scorer_version: str
    dataset_version: str
    dataset_checksum: str
    m12_experiment_id: str
    training_partition: str
    training_row_count: int = Field(ge=1)
    feature_schema_version: str
    strategy_taxonomy_version: str
    objective_version: str
    seed: int
    hyperparameters: dict[str, object]
    allowlist: tuple[str, ...]
    numeric_feature_names: tuple[str, ...]
    categorical_feature_names: tuple[str, ...]
    category_values: tuple[tuple[str, ...], ...]
    scaler_mean: tuple[float, ...]
    scaler_scale: tuple[float, ...]
    expanded_feature_names: tuple[str, ...]
    coefficients: tuple[float, ...]
    intercept: float


class RouterModelEnvelope(CanonicalModel):
    artifact: RouterModelArtifact
    checksum: str


@dataclass(frozen=True)
class M13RunResult:
    dataset_checksum: str
    model_artifact_checksum: str
    validation_decisions: tuple[RoutingDecision, ...]
    validation_evaluations: tuple[dict[str, object], ...]
    comparison_metrics: tuple[dict[str, object], ...]
    summary_data: dict[str, object]
    reproducibility_fingerprint: str

    def summary(self) -> dict[str, object]:
        return self.summary_data


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _write_json(path: Path, value: object) -> None:
    path.write_text(_json(value) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, values: Iterable[object]) -> None:
    path.write_text("".join(f"{_json(value)}\n" for value in values), encoding="utf-8")


def _artifact_checksum(artifact: RouterModelArtifact) -> str:
    return hashlib.sha256(_json(artifact.model_dump(mode="json")).encode("utf-8")).hexdigest()


def _validate_artifact_identity(artifact: RouterModelArtifact) -> None:
    if artifact.artifact_schema_version != ROUTEFORGE_ROUTER_ARTIFACT_SCHEMA:
        raise ValueError("unsupported RouteForge router artifact schema")
    if artifact.model_id != ROUTEFORGE_MODEL_ID:
        raise ValueError("unsupported RouteForge router model id")
    if artifact.model_version != ROUTEFORGE_SCORER_VERSION:
        raise ValueError("unsupported RouteForge scorer version")
    if artifact.scorer_version != ROUTEFORGE_SCORER_VERSION:
        raise ValueError("unsupported RouteForge scorer identity")
    if artifact.feature_schema_version != ROUTEFORGE_FEATURE_SCHEMA_VERSION:
        raise ValueError("RouteForge feature schema mismatch")
    if artifact.strategy_taxonomy_version != ROUTEFORGE_STRATEGY_TAXONOMY_VERSION:
        raise ValueError("RouteForge strategy taxonomy mismatch")
    if artifact.objective_version != ROUTEFORGE_OBJECTIVE_VERSION:
        raise ValueError("RouteForge objective mismatch")
    if artifact.training_partition != "TRAIN":
        raise ValueError("RouteForge scorer must be trained on TRAIN")
    if artifact.m12_experiment_id != M12_LOGISTIC_EXPERIMENT_ID:
        raise ValueError("RouteForge scorer is not the frozen M12 Logistic experiment")
    if tuple(artifact.allowlist) != tuple(MODEL_FEATURE_ALLOWLIST):
        raise ValueError("RouteForge model allowlist mismatch")
    if tuple(artifact.numeric_feature_names) != NUMERIC_FEATURES + BOOLEAN_FEATURES:
        raise ValueError("RouteForge numeric feature schema mismatch")
    expected_categorical = CATEGORICAL_FEATURES + ("strategy_identity",)
    if tuple(artifact.categorical_feature_names) != expected_categorical:
        raise ValueError("RouteForge categorical feature schema mismatch")
    if len(artifact.category_values) != len(expected_categorical):
        raise ValueError("RouteForge category vocabulary mismatch")
    if len(artifact.scaler_mean) != len(artifact.numeric_feature_names):
        raise ValueError("RouteForge scaler mean mismatch")
    if len(artifact.scaler_scale) != len(artifact.numeric_feature_names):
        raise ValueError("RouteForge scaler scale mismatch")
    if len(artifact.coefficients) != len(artifact.expanded_feature_names):
        raise ValueError("RouteForge coefficient schema mismatch")


def save_model_artifact(artifact: RouterModelArtifact, path: Path | str) -> str:
    _validate_artifact_identity(artifact)
    checksum = _artifact_checksum(artifact)
    envelope = RouterModelEnvelope(artifact=artifact, checksum=checksum)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    _write_json(destination, envelope.model_dump(mode="json"))
    return checksum


def load_model_artifact(path: Path | str) -> tuple[RouterModelArtifact, str]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    envelope = RouterModelEnvelope.model_validate(payload)
    _validate_artifact_identity(envelope.artifact)
    checksum = _artifact_checksum(envelope.artifact)
    if checksum != envelope.checksum:
        raise ValueError("RouteForge model artifact checksum mismatch")
    return envelope.artifact, checksum


def _context_values(
    context: RoutingDecisionContext, strategy: RouteForgeStrategy
) -> dict[str, object]:
    values = context.features.model_dump(mode="json")
    if set(values) != set(MODEL_FEATURE_ALLOWLIST):
        raise ValueError("routing context does not match the M11 feature allowlist")
    values["strategy_identity"] = strategy.value
    return values


def _transform_context(
    context: RoutingDecisionContext,
    strategy: RouteForgeStrategy,
    artifact: RouterModelArtifact,
) -> np.ndarray:
    values = _context_values(context, strategy)
    numeric = np.asarray(
        [float(cast(float | int | bool, values[name])) for name in artifact.numeric_feature_names],
        dtype=float,
    )
    means = np.asarray(artifact.scaler_mean, dtype=float)
    scales = np.asarray(artifact.scaler_scale, dtype=float)
    scaled = (numeric - means) / scales
    expanded: list[float] = scaled.tolist()
    for name, categories in zip(
        artifact.categorical_feature_names, artifact.category_values, strict=True
    ):
        value = str(values[name])
        expanded.extend(1.0 if value == category else 0.0 for category in categories)
    matrix = np.asarray(expanded, dtype=float)
    if len(matrix) != len(artifact.coefficients):
        raise ValueError("routing feature expansion does not match the model artifact")
    return matrix


def _applicability(context: RoutingDecisionContext) -> dict[RouteForgeStrategy, str]:
    if context.no_repair_required:
        return {
            RouteForgeStrategy.NO_AI: "applicable: no repair is required",
            **{strategy: "excluded: no repair is required" for strategy in REPAIR_STRATEGIES},
        }
    result: dict[RouteForgeStrategy, str] = {
        RouteForgeStrategy.NO_AI: "excluded: repair is required"
    }
    features = context.features
    if not features.deterministic_rule_available or features.m10_repairability == "UNSUPPORTED":
        result[RouteForgeStrategy.DETERMINISTIC] = (
            "excluded: M10 cannot safely provide deterministic repair; AI_REQUIRED is evidence only"
        )
    else:
        result[RouteForgeStrategy.DETERMINISTIC] = "applicable: deterministic candidate evidence"
    for strategy in (
        RouteForgeStrategy.SMALL,
        RouteForgeStrategy.MEDIUM,
        RouteForgeStrategy.STRONG,
    ):
        result[strategy] = (
            f"applicable: abstract {strategy.value} strategy; independent of "
            "M10 AI_REQUIRED evidence"
        )
    return result


def select_strategy(
    scores: Mapping[RouteForgeStrategy, float],
    objective: RoutingObjective,
    applicable: Iterable[RouteForgeStrategy],
) -> RouteChoice | None:
    """Select the highest finite score with deterministic objective-order ties."""

    order = {strategy: index for index, strategy in enumerate(objective.tie_break_order)}
    candidates = [
        (strategy, score)
        for strategy, score in scores.items()
        if strategy in set(applicable) and math.isfinite(score)
    ]
    if not candidates:
        return None
    strategy, _ = min(candidates, key=lambda item: (-item[1], order[item[0]]))
    return RouteChoice(strategy.value)


def select_classified_strategy(
    context: RoutingDecisionContext,
    scores: Mapping[RouteForgeStrategy, float],
    objective: RoutingObjective,
    *,
    classifier_boundary: float = 0.0,
) -> tuple[RouteChoice, str | None]:
    """Apply v3 learned abstention using only pre-decision applicability and scores."""

    if context.no_repair_required:
        return RouteChoice.NO_AI, None
    applicability = _applicability(context)
    applicable = tuple(
        strategy
        for strategy in REPAIR_STRATEGIES
        if applicability[strategy].startswith("applicable")
    )
    if not applicable:
        return RouteChoice.NO_FEASIBLE_STRATEGY, "STRUCTURAL_NO_FEASIBLE"
    predicted_success = tuple(
        strategy
        for strategy in applicable
        if math.isfinite(float(scores.get(strategy, float("nan"))))
        and float(scores[strategy]) >= classifier_boundary
    )
    if not predicted_success:
        return RouteChoice.NO_FEASIBLE_STRATEGY, "LEARNED_ABSTENTION"
    selected = select_strategy(scores, objective, predicted_success)
    if selected is None:
        raise ValueError("predicted-success strategy did not produce a finite score")
    return selected, None


def _evidence_features(context: RoutingDecisionContext) -> tuple[str, ...]:
    features = context.features
    return (
        f"m10_repairability={features.m10_repairability}",
        f"deterministic_rule_available={features.deterministic_rule_available}",
        f"expected_edit_count={features.expected_edit_count}",
        f"target_file_count={features.target_file_count}",
        f"maximum_graph_distance={features.maximum_graph_distance}",
        f"coverage_unresolved_calls={features.coverage_unresolved_calls}",
        f"dynamic_payload={features.dynamic_payload}",
    )


def _context_fingerprint(context: RoutingDecisionContext) -> str:
    return hashlib.sha256(context.canonical_json().encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RouteForgeRouter:
    artifact: RouterModelArtifact
    model_artifact_checksum: str
    decision_policy_version: str = ROUTEFORGE_DECISION_POLICY_VERSION

    def __post_init__(self) -> None:
        _validate_artifact_identity(self.artifact)
        if _artifact_checksum(self.artifact) != self.model_artifact_checksum:
            raise ValueError("RouteForge router model checksum mismatch")
        if self.decision_policy_version not in {
            ROUTEFORGE_DECISION_POLICY_VERSION,
            ROUTEFORGE_LEARNED_ABSTENTION_POLICY_VERSION,
        }:
            raise ValueError("unsupported RouteForge decision policy")

    @classmethod
    def from_artifact(
        cls,
        path: Path | str,
        decision_policy_version: str = ROUTEFORGE_DECISION_POLICY_VERSION,
    ) -> RouteForgeRouter:
        artifact, checksum = load_model_artifact(path)
        return cls(
            artifact=artifact,
            model_artifact_checksum=checksum,
            decision_policy_version=decision_policy_version,
        )

    def _validate_request(self, request: RoutingRequest) -> None:
        if request.context.feature_schema_version != self.artifact.feature_schema_version:
            raise ValueError("routing context feature schema mismatch")
        if request.strategy_taxonomy_version != self.artifact.strategy_taxonomy_version:
            raise ValueError("routing request strategy taxonomy mismatch")
        if request.objective.version != self.artifact.objective_version:
            raise ValueError("routing request objective mismatch")

    def _score(self, context: RoutingDecisionContext, strategy: RouteForgeStrategy) -> float:
        matrix = _transform_context(context, strategy, self.artifact)
        score = float(
            np.dot(matrix, np.asarray(self.artifact.coefficients)) + self.artifact.intercept
        )
        if not math.isfinite(score):
            raise ValueError("RouteForge scorer produced a non-finite score")
        return score

    def route(self, request: RoutingRequest) -> RoutingDecision:
        if not isinstance(request, RoutingRequest):
            raise TypeError("RouteForgeRouter.route requires RoutingRequest")
        self._validate_request(request)
        context = request.context
        applicability = _applicability(context)
        scores: dict[RouteForgeStrategy, float] = {}
        records: list[StrategyScore] = []
        for strategy in STRATEGY_ORDER:
            reason = applicability[strategy]
            applicable = reason.startswith("applicable")
            score = None
            if applicable and strategy is not RouteForgeStrategy.NO_AI:
                score = self._score(context, strategy)
                scores[strategy] = score
            records.append(
                StrategyScore(
                    strategy=strategy,
                    score=score,
                    applicable=applicable,
                    reason=reason,
                )
            )

        abstention: RoutingAbstention | None = None
        if context.no_repair_required:
            selected = RouteChoice.NO_AI
            selection_basis = "NO_AI is required by the no-repair applicability rule."
            summary = "Selected NO_AI because no repair is required."
        else:
            applicable_strategies = tuple(
                strategy
                for strategy in REPAIR_STRATEGIES
                if applicability[strategy].startswith("applicable")
            )
            if not applicable_strategies:
                abstention = RoutingAbstention(
                    code=(
                        "STRUCTURAL_NO_FEASIBLE"
                        if self.decision_policy_version
                        == ROUTEFORGE_LEARNED_ABSTENTION_POLICY_VERSION
                        else "NO_FEASIBLE_STRATEGY"
                    ),
                    reason=(
                        "No pre-decision strategy is applicable under the router "
                        "applicability rules."
                    ),
                )
                selected = RouteChoice.NO_FEASIBLE_STRATEGY
                selection_basis = "Abstained because no pre-decision strategy is applicable."
                summary = "Abstained with NO_FEASIBLE_STRATEGY under explicit applicability rules."
            elif (
                self.decision_policy_version
                == ROUTEFORGE_LEARNED_ABSTENTION_POLICY_VERSION
            ):
                selected, abstention_code = select_classified_strategy(
                    context,
                    scores,
                    request.objective,
                )
                if abstention_code is not None:
                    abstention = RoutingAbstention(
                        code=abstention_code,
                        reason=(
                            "Applicable repair strategies were all classified as "
                            "offline-oracle FAILURE by the frozen uncalibrated scorer."
                        ),
                    )
                    selection_basis = (
                        "Abstained because no applicable strategy reached the frozen "
                        "offline-oracle success class boundary (decision_function >= 0)."
                    )
                    summary = "Abstained with NO_FEASIBLE_STRATEGY by learned abstention."
                else:
                    selection_basis = (
                        "Selected the highest finite uncalibrated offline-oracle success "
                        "score among strategies classified SUCCESS by the frozen "
                        "decision_function >= 0 boundary. Ties use canonical objective order."
                    )
                    summary = (
                        f"Selected {selected.value} from predicted-success applicable strategies."
                    )
            else:
                selected_candidate = select_strategy(
                    scores, request.objective, applicable_strategies
                )
                if selected_candidate is None:
                    raise ValueError("no applicable strategy produced a finite learned score")
                selected = selected_candidate
                selection_basis = (
                    "Selected the highest finite uncalibrated offline oracle-success score "
                    "under the score-only M13 prototype policy; routeforge-objective-v1 is "
                    "evaluated post-selection. Ties use its canonical tie_break_order."
                )
                summary = f"Selected {selected.value} from applicable pre-decision strategies."
        selected_score = scores.get(RouteForgeStrategy(selected.value)) if selected in {
            RouteChoice.DETERMINISTIC,
            RouteChoice.SMALL,
            RouteChoice.MEDIUM,
            RouteChoice.STRONG,
        } else None
        rejected = tuple(
            (
                f"{strategy.value}: tie resolved by objective order"
                if selected_score is not None and score == selected_score
                else f"{strategy.value}: lower learned score"
            )
            for strategy, score in scores.items()
            if selected.value != strategy.value
        )
        explanation = RoutingExplanation(
            summary=summary,
            applicability=tuple(
                f"{strategy.value}: {applicability[strategy]}" for strategy in STRATEGY_ORDER
            ),
            selection_basis=selection_basis,
            evidence_features=_evidence_features(context),
            rejected_alternatives=rejected,
        )
        decision_id = _stable_decision_id(
            context,
            selected,
            tuple((record.strategy.value, record.score, record.applicable) for record in records),
            self.artifact,
            self.decision_policy_version,
        )
        return RoutingDecision(
            decision_id=decision_id,
            context_id=context.id,
            scenario_id=context.scenario_id,
            decision_group_id=context.decision_group_id,
            migration_id=context.migration_id,
            selected_strategy=selected,
            strategy_scores=tuple(records),
            feature_schema_version=self.artifact.feature_schema_version,
            strategy_taxonomy_version=self.artifact.strategy_taxonomy_version,
            objective_version=request.objective.version,
            model_id=self.artifact.model_id,
            scorer_version=self.artifact.scorer_version,
            router_version=ROUTEFORGE_ROUTER_VERSION,
            decision_policy_version=self.decision_policy_version,
            model_artifact_checksum=self.model_artifact_checksum,
            context_fingerprint=_context_fingerprint(context),
            explanation=explanation,
            warnings=(
                "Scores are uncalibrated offline oracle-success scores.",
                "The v3 classifier boundary denotes an offline-oracle success class, "
                "not a calibrated probability or validated repair chance.",
                "No provider call, patch generation, or validation is performed.",
                "Synthetic relative objective units are not measured runtime cost or latency.",
                "Cost-aware route selection is deferred: no governed pre-decision strategy "
                "cost/latency attributes exist.",
            ),
            abstention=abstention,
        )


def _stable_decision_id(
    context: RoutingDecisionContext,
    selected: RouteChoice,
    scores: tuple[tuple[str, float | None, bool], ...],
    artifact: RouterModelArtifact,
    decision_policy_version: str = ROUTEFORGE_DECISION_POLICY_VERSION,
) -> str:
    payload = _json(
        {
            "context": _context_fingerprint(context),
            "context_id": context.id,
            "selected": selected.value,
            "scores": scores,
            "model": artifact.model_id,
            "model_version": artifact.model_version,
            "objective": artifact.objective_version,
            "taxonomy": artifact.strategy_taxonomy_version,
            "decision_policy": decision_policy_version,
        }
    )
    return f"routeforge-decision-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def _fit_primary_artifact(
    dataset: RouteForgeDataset, train_rows: Sequence[RouteForgeDatasetRow], seed: int
) -> RouterModelArtifact:
    eligible_rows = tuple(row for row in train_rows if _eligible(row))
    if not eligible_rows:
        raise ValueError("M13 requires eligible TRAIN outcomes")
    from opentrace.routeforge.baselines import RouteForgeFeatureEncoder

    encoder = RouteForgeFeatureEncoder().fit(eligible_rows)
    matrix = encoder.transform(eligible_rows)
    labels = np.asarray(
        [row.outcome.value == "SUCCESS" for row in eligible_rows],
        dtype=int,
    )
    model = LogisticRegression(
        C=1.0,
        class_weight="balanced",
        max_iter=500,
        solver="liblinear",
        random_state=seed,
    ).fit(matrix, labels)
    scaler = cast(Any, encoder._scaler)
    categorical = cast(Any, encoder._categorical)
    return RouterModelArtifact(
        model_id=ROUTEFORGE_MODEL_ID,
        model_version=ROUTEFORGE_SCORER_VERSION,
        scorer_version=ROUTEFORGE_SCORER_VERSION,
        dataset_version=dataset.manifest.dataset_version,
        dataset_checksum=dataset.manifest.content_sha256,
        m12_experiment_id=M12_LOGISTIC_EXPERIMENT_ID,
        training_partition="TRAIN",
        training_row_count=len(eligible_rows),
        feature_schema_version=ROUTEFORGE_FEATURE_SCHEMA_VERSION,
        strategy_taxonomy_version=ROUTEFORGE_STRATEGY_TAXONOMY_VERSION,
        objective_version=dataset.manifest.objective.version,
        seed=seed,
        hyperparameters={
            "C": 1.0,
            "class_weight": "balanced",
            "max_iter": 500,
            "solver": "liblinear",
        },
        allowlist=tuple(MODEL_FEATURE_ALLOWLIST),
        numeric_feature_names=NUMERIC_FEATURES + BOOLEAN_FEATURES,
        categorical_feature_names=CATEGORICAL_FEATURES + ("strategy_identity",),
        category_values=tuple(
            tuple(str(value) for value in categories) for categories in categorical.categories_
        ),
        scaler_mean=tuple(float(value) for value in scaler.mean_),
        scaler_scale=tuple(float(value) for value in scaler.scale_),
        expanded_feature_names=encoder.output_feature_names,
        coefficients=tuple(float(value) for value in model.coef_[0]),
        intercept=float(model.intercept_[0]),
    )


def _validation_evaluation(
    decision: RoutingDecision,
    scenario: RouteForgeScenario,
    rows: Mapping[RouteForgeStrategy, RouteForgeDatasetRow],
    objective: RoutingObjective,
) -> dict[str, object]:
    selected_row = (
        rows.get(RouteForgeStrategy(decision.selected_strategy.value))
        if decision.selected_strategy
        in {
            RouteChoice.NO_AI,
            RouteChoice.DETERMINISTIC,
            RouteChoice.SMALL,
            RouteChoice.MEDIUM,
            RouteChoice.STRONG,
        }
        else None
    )
    satisfied = _objective_satisfied(scenario, decision.selected_strategy, rows, objective)
    selected_cost = None if selected_row is None else selected_row.synthetic_cost_units
    selected_latency = None if selected_row is None else selected_row.synthetic_latency_units
    oracle_cost = _route_cost(scenario.preferred_strategy, rows)
    regret = (
        (float(selected_cost) if selected_cost is not None else 0.0) - oracle_cost
        if satisfied
        else None
    )
    return {
        "decision_id": decision.decision_id,
        "scenario_id": scenario.scenario_id,
        "decision_group_id": scenario.decision_group_id,
        "oracle_preferred_strategy": scenario.preferred_strategy.value,
        "selected_strategy": decision.selected_strategy.value,
        "selected_outcome": None if selected_row is None else selected_row.outcome.value,
        "objective_satisfied": satisfied,
        "constraint_violation": not satisfied,
        "selected_cost_units": selected_cost,
        "selected_latency_units": selected_latency,
        "objective_regret_units": regret,
        "strong_strategy_selected": decision.selected_strategy is RouteChoice.STRONG,
        "selected_unknown": selected_row is not None and selected_row.outcome.value == "UNKNOWN",
        "selected_not_applicable": selected_row is not None
        and selected_row.outcome.value == "NOT_APPLICABLE",
        "offline_evaluation_only": True,
        "cost_semantics": objective.cost_semantics.value,
        "latency_semantics": objective.latency_semantics.value,
    }


def _policy_metrics(evaluations: Sequence[Mapping[str, object]]) -> dict[str, object]:
    count = len(evaluations)
    successes = sum(bool(item["objective_satisfied"]) for item in evaluations)
    costs = [
        float(cast(float | int, item["selected_cost_units"]))
        for item in evaluations
        if item["selected_cost_units"] is not None
    ]
    latencies = [
        float(cast(float | int, item["selected_latency_units"]))
        for item in evaluations
        if item["selected_latency_units"] is not None
    ]
    regrets = [
        float(cast(float | int, item["objective_regret_units"]))
        for item in evaluations
        if item["objective_regret_units"] is not None
    ]
    expected_no_feasible = sum(
        item["oracle_preferred_strategy"] == RouteChoice.NO_FEASIBLE_STRATEGY.value
        for item in evaluations
    )
    correct_no_feasible = sum(
        item["oracle_preferred_strategy"] == RouteChoice.NO_FEASIBLE_STRATEGY.value
        and item["selected_strategy"] == RouteChoice.NO_FEASIBLE_STRATEGY.value
        for item in evaluations
    )
    return {
        "decision_count": count,
        "oracle_objective_satisfaction_rate": successes / count,
        "constraint_violation_rate": (count - successes) / count,
        "synthetic_average_cost_units": float(np.mean(costs)) if costs else None,
        "synthetic_average_latency_units": float(np.mean(latencies)) if latencies else None,
        "synthetic_cost_per_oracle_successful_decision_units": (
            float(sum(costs) / successes) if successes else None
        ),
        "strong_strategy_usage_rate": sum(
            item["selected_strategy"] == RouteForgeStrategy.STRONG.value for item in evaluations
        )
        / count,
        "no_feasible_expected_count": expected_no_feasible,
        "no_feasible_correct_count": correct_no_feasible,
        "no_feasible_handling_rate": (
            correct_no_feasible / expected_no_feasible if expected_no_feasible else None
        ),
        "objective_regret_units_mean": float(np.mean(regrets)) if regrets else None,
        "objective_regret_defined_count": len(regrets),
        "unknown_selected_count": sum(bool(item["selected_unknown"]) for item in evaluations),
        "not_applicable_selected_count": sum(
            bool(item["selected_not_applicable"]) for item in evaluations
        ),
        "offline_only": True,
        "cost_semantics": "SYNTHETIC_RELATIVE_UNITS",
        "latency_semantics": "SYNTHETIC_RELATIVE_UNITS",
        "evaluation_phase": "POST_SELECTION_OFFLINE_LOOKUP",
    }


def _clear_output(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for child in output.iterdir():
        if child.name == "README.md":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def _m12_integrity(m12_directory: Path, dataset: RouteForgeDataset) -> dict[str, object]:
    manifest = json.loads((m12_directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest["dataset_checksum"] != dataset.manifest.content_sha256:
        raise ValueError("M12 dataset checksum differs from M11")
    if manifest["test_used_for_model_selection"] or manifest["test_evaluated"]:
        raise ValueError("M12 TEST seal is not intact")
    experiment_ids = tuple(str(value) for value in manifest["experiment_ids"])
    required = {
        "RF-B0-ALWAYS-SMALL",
        "RF-B1-ALWAYS-STRONG",
        "RF-B2-RANDOM",
        "RF-B3-RULE-V1",
        "RF-B4-LOGISTIC",
        "RF-B5-XGBOOST",
    }
    if set(experiment_ids) != required:
        raise ValueError("M12 required experiment set is incomplete")
    return {
        "dataset_checksum": manifest["dataset_checksum"],
        "experiment_ids": list(experiment_ids),
        "test_used_for_model_selection": False,
        "test_evaluated": False,
        "upstream_integrity": manifest["upstream_integrity"],
        "label_shuffle_sanity": manifest["label_shuffle_sanity"],
        "m13_data_adequacy": manifest["m13_data_adequacy"],
        "m13_data_adequacy_reason": manifest["m13_data_adequacy_reason"],
    }


def run_m13_router(
    dataset_directory: Path | str = Path("data/routeforge-m11"),
    m12_directory: Path | str = Path("data/routeforge-m12"),
    output_directory: Path | str = Path("data/routeforge-m13"),
    *,
    seed: int = BASELINE_SEED,
) -> M13RunResult:
    dataset = read_artifacts(Path(dataset_directory))
    if dataset.manifest.content_sha256 != M11_HISTORICAL_CHECKSUM:
        raise ValueError("M11 canonical checksum differs from the frozen historical checksum")
    m12_path = Path(m12_directory)
    m12_integrity = _m12_integrity(m12_path, dataset)
    train_rows = _partition_rows(dataset, "TRAIN")
    validation_rows = _partition_rows(dataset, "VALIDATION")
    _partition_rows(dataset, "TEST")
    train_eligible = tuple(row for row in train_rows if _eligible(row))
    artifact = _fit_primary_artifact(dataset, train_rows, seed)
    output = Path(output_directory)
    _clear_output(output)
    model_path = output / "model.json"
    model_checksum = save_model_artifact(artifact, model_path)
    router = RouteForgeRouter.from_artifact(model_path)
    scenarios = tuple(
        sorted(
            (
                scenario
                for scenario in dataset.scenarios
                if scenario.decision_group_id in {row.decision_group_id for row in validation_rows}
            ),
            key=lambda scenario: scenario.scenario_id,
        )
    )
    requests = tuple(
        RoutingRequest(context=scenario.context, objective=dataset.manifest.objective)
        for scenario in scenarios
    )
    decisions = tuple(router.route(request) for request in requests)
    rows_by_group: dict[str, dict[RouteForgeStrategy, RouteForgeDatasetRow]] = {}
    for row in validation_rows:
        rows_by_group.setdefault(row.decision_group_id, {})[row.strategy] = row
    evaluations = tuple(
        _validation_evaluation(
            decision,
            scenario,
            rows_by_group[scenario.decision_group_id],
            dataset.manifest.objective,
        )
        for decision, scenario in zip(decisions, scenarios, strict=True)
    )
    validation_candidates = tuple(
        row for row in validation_rows if row.strategy in REPAIR_STRATEGIES
    )
    score_by_row = {
        row.id: router._score(
            next(
                scenario.context
                for scenario in scenarios
                if scenario.scenario_id == row.scenario_id
            ),
            row.strategy,
        )
        for row in validation_candidates
    }
    eligible_validation = tuple(row for row in validation_candidates if _eligible(row))
    score_diagnostics = _outcome_metrics(
        eligible_validation,
        np.asarray([score_by_row[row.id] for row in eligible_validation], dtype=float),
        0.0,
    )
    m12_records = {
        str(record["experiment_id"]): record
        for record in (
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted((m12_path / "experiments").glob("*.json"))
        )
    }
    comparison_metrics = tuple(
        {
            "experiment_id": experiment_id,
            "baseline": m12_records[experiment_id]["baseline"],
            "policy_metrics": m12_records[experiment_id]["policy_metrics"],
            "source": "M12_CANONICAL_ARTIFACT",
        }
        for experiment_id in (
            "RF-B0-ALWAYS-SMALL",
            "RF-B1-ALWAYS-STRONG",
            "RF-B2-RANDOM",
            "RF-B3-RULE-V1",
            "RF-B5-XGBOOST",
        )
    ) + (
        {
            "experiment_id": ROUTEFORGE_EXPERIMENT_ID,
            "baseline": "LEARNED_LOGISTIC_ROUTER",
            "policy_metrics": _policy_metrics(evaluations),
            "source": "M13_REAL_ROUTER_RUN",
        },
    )
    fingerprint_payload = {
        "model_artifact_checksum": model_checksum,
        "decisions": [decision.model_dump(mode="json") for decision in decisions],
        "evaluations": list(evaluations),
        "comparison_metrics": list(comparison_metrics),
    }
    fingerprint = hashlib.sha256(_json(fingerprint_payload).encode("utf-8")).hexdigest()
    summary: dict[str, object] = {
        "schema_version": ROUTEFORGE_ROUTER_ARTIFACT_SCHEMA,
        "experiment_id": ROUTEFORGE_EXPERIMENT_ID,
        "dataset_version": dataset.manifest.dataset_version,
        "dataset_checksum": dataset.manifest.content_sha256,
        "m12_experiment_id": M12_LOGISTIC_EXPERIMENT_ID,
        "model_id": artifact.model_id,
        "model_artifact_checksum": model_checksum,
        "split_counts": {
            partition: {
                "decision_groups": len(
                    {
                        row.decision_group_id
                        for row in dataset.rows
                        if row.split_partition.value == partition
                    }
                ),
                "strategy_rows": sum(
                    row.split_partition.value == partition for row in dataset.rows
                ),
            }
            for partition in ("TRAIN", "VALIDATION", "TEST")
        },
        "training_row_count": len(train_eligible),
        "validation_decision_count": len(decisions),
        "test_used_for_model_selection": False,
        "test_evaluated": False,
        "test_metrics": TEST_SEAL_MESSAGE,
        "primary_score_diagnostics": score_diagnostics,
        "comparison_metrics": list(comparison_metrics),
        "label_shuffle_sanity": m12_integrity["label_shuffle_sanity"],
        "upstream_integrity": m12_integrity["upstream_integrity"],
        "m13_data_adequacy": (
            "INADEQUATE — ROUTEFORGE DATA EXPANSION REQUIRED BEFORE GATE C CAN PASS"
        ),
        "m13_data_adequacy_reason": (
            "Nine decision groups provide only five TRAIN groups, three VALIDATION groups, "
            "and one sealed TEST group; this is implementation evidence, not Gate C evidence."
        ),
        "gate_c_evidence_gap": [
            "More independent migration groups and clone-safe holdouts",
            "More template, mutation, API, and repository families",
            "Meaningful NO_FEASIBLE_STRATEGY coverage",
            "More independent deterministic/SMALL/MEDIUM/STRONG cases",
            "Held-out calibration and routing-performance evidence",
            "COST-AWARE ROUTING POLICY requires governed pre-decision strategy "
            "cost/latency attributes or a reviewed score-to-objective design",
        ],
        "reproducibility_fingerprint": fingerprint,
    }
    _write_json(
        output / "router-config.json",
        {
            "router_version": ROUTEFORGE_ROUTER_VERSION,
            "scorer_version": ROUTEFORGE_SCORER_VERSION,
            "decision_policy_version": ROUTEFORGE_DECISION_POLICY_VERSION,
            "objective_version": ROUTEFORGE_OBJECTIVE_VERSION,
            "strategy_taxonomy_version": ROUTEFORGE_STRATEGY_TAXONOMY_VERSION,
            "feature_schema_version": ROUTEFORGE_FEATURE_SCHEMA_VERSION,
            "score_policy": (
                "score-only prototype: maximum finite uncalibrated score; canonical objective "
                "tie order; no threshold; objective evaluated post-selection"
            ),
            "model_artifact": "model.json",
        },
    )
    _write_jsonl(
        output / "validation_decisions.jsonl",
        (decision.model_dump(mode="json") for decision in decisions),
    )
    _write_jsonl(output / "validation_evaluation.jsonl", evaluations)
    _write_json(output / "comparison_metrics.json", comparison_metrics)
    _write_json(
        output / "gate-c-evidence-gap.json",
        {
            "status": summary["m13_data_adequacy"],
            "reason": summary["m13_data_adequacy_reason"],
            "required_before_gate_c": summary["gate_c_evidence_gap"],
        },
    )
    _write_json(output / "summary.json", summary)
    _write_json(
        output / "manifest.json",
        {
            **summary,
            "artifacts": [
                "model.json",
                "router-config.json",
                "validation_decisions.jsonl",
                "validation_evaluation.jsonl",
                "comparison_metrics.json",
                "gate-c-evidence-gap.json",
            ],
        },
    )
    _write_json(
        output / "experiment.json",
        {
            "experiment_id": ROUTEFORGE_EXPERIMENT_ID,
            "hypothesis": (
                "A frozen Logistic strategy-success scorer can make deterministic "
                "provider-independent RouteForge decisions."
            ),
            "dataset_version": dataset.manifest.dataset_version,
            "dataset_checksum": dataset.manifest.content_sha256,
            "split_strategy": (
                "M11 decision-group split; TRAIN fit, VALIDATION routing diagnostics, "
                "TEST sealed"
            ),
            "features": list(MODEL_FEATURE_ALLOWLIST) + ["strategy_identity"],
            "baseline": "LEARNED_LOGISTIC_ROUTER",
            "model": artifact.model_id,
            "hyperparameters": artifact.hyperparameters,
            "primary_metric": "post-selection offline objective satisfaction",
            "secondary_metrics": [
                "constraint violation",
                "synthetic relative cost",
                "synthetic relative latency",
                "objective regret",
                "STRONG usage",
            ],
            "result": _policy_metrics(evaluations),
            "interpretation": (
                "Development-only score-based routing evidence; routeforge-objective-v1 is "
                "evaluated post-selection; no calibration or production claim."
            ),
            "limitations": [summary["m13_data_adequacy_reason"], TEST_SEAL_MESSAGE],
            "artifacts": [
                "model.json",
                "router-config.json",
                "validation_decisions.jsonl",
                "validation_evaluation.jsonl",
                "comparison_metrics.json",
            ],
            "reproduction_command": (
                "python -m opentrace.routeforge.router --output data/routeforge-m13"
            ),
        },
    )
    return M13RunResult(
        dataset_checksum=dataset.manifest.content_sha256,
        model_artifact_checksum=model_checksum,
        validation_decisions=decisions,
        validation_evaluations=evaluations,
        comparison_metrics=comparison_metrics,
        summary_data=summary,
        reproducibility_fingerprint=fingerprint,
    )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run the offline M13 RouteForge router")
    parser.add_argument("--dataset", default="data/routeforge-m11")
    parser.add_argument("--m12", default="data/routeforge-m12")
    parser.add_argument("--output", default="data/routeforge-m13")
    parser.add_argument("--seed", type=int, default=BASELINE_SEED)
    args = parser.parse_args()
    result = run_m13_router(args.dataset, args.m12, args.output, seed=args.seed)
    print(f"dataset_checksum={result.dataset_checksum}")
    print(f"model_artifact_checksum={result.model_artifact_checksum}")
    print(f"validation_decisions={len(result.validation_decisions)}")
    print(f"reproducibility_fingerprint={result.reproducibility_fingerprint}")
    print(f"output={Path(args.output)}")


if __name__ == "__main__":
    main()
