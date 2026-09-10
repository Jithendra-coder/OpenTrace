"""M13 learned RouteForge router contracts and adversarial checks."""

import json
from pathlib import Path

import pytest
import opentrace.routeforge.router as router_module
from pydantic import ValidationError
from opentrace.routeforge.models import (
    RouteChoice,
    RouteForgeScenario,
    RouteForgeStrategy,
    RoutingObjective,
)
from opentrace.routeforge.router import (
    ROUTEFORGE_SCORER_VERSION,
    RouteForgeRouter,
    RoutingRequest,
    load_model_artifact,
    run_m13_router,
    select_strategy,
)
from opentrace.routeforge.serialization import read_artifacts


@pytest.fixture(scope="module")
def m13_run(tmp_path_factory):
    output = tmp_path_factory.mktemp("m13")
    return run_m13_router(
        Path("data/routeforge-m11"),
        Path("data/routeforge-m12"),
        output,
    )


def _scenario(scenario_id: str) -> RouteForgeScenario:
    dataset = read_artifacts(Path("data/routeforge-m11"))
    return next(item for item in dataset.scenarios if item.scenario_id == scenario_id)


def test_router_contracts_and_special_states(m13_run) -> None:
    decisions = {decision.scenario_id: decision for decision in m13_run.validation_decisions}
    assert decisions["scenario-006"].selected_strategy is RouteChoice.NO_AI

    scenario = _scenario("scenario-007")
    artifact_path = Path("data/routeforge-m13/model.json")
    decision = RouteForgeRouter.from_artifact(artifact_path).route(
        RoutingRequest(context=scenario.context, objective=RoutingObjective())
    )
    assert decision.selected_strategy is not RouteChoice.NO_FEASIBLE_STRATEGY
    scores = {score.strategy: score for score in decision.strategy_scores}
    assert scores[RouteForgeStrategy.DETERMINISTIC].applicable is False
    assert all(scores[strategy].applicable for strategy in (
        RouteForgeStrategy.SMALL,
        RouteForgeStrategy.MEDIUM,
        RouteForgeStrategy.STRONG,
    ))


def test_no_feasible_requires_explicit_no_applicable_condition(monkeypatch) -> None:
    scenario = _scenario("scenario-001")
    router = RouteForgeRouter.from_artifact(Path("data/routeforge-m13/model.json"))

    def no_applicable_strategies(_context):
        return {
            strategy: "excluded: independent pre-decision applicability constraint"
            for strategy in router_module.STRATEGY_ORDER
        }

    monkeypatch.setattr(router_module, "_applicability", no_applicable_strategies)
    decision = router.route(RoutingRequest(context=scenario.context))
    assert decision.selected_strategy is RouteChoice.NO_FEASIBLE_STRATEGY
    assert decision.abstention is not None
    assert decision.abstention.code == "NO_FEASIBLE_STRATEGY"


def test_primary_model_schema_and_train_only_artifact(m13_run) -> None:
    summary = m13_run.summary()
    assert summary["model_id"] == "RF-M13-LOGISTIC-V1"
    assert summary["training_row_count"] == 19
    assert summary["test_used_for_model_selection"] is False
    assert summary["test_evaluated"] is False
    assert summary["test_metrics"] == (
        "TEST METRICS NOT COMPUTED — DATASET INADEQUATE FOR GATE C EVIDENCE"
    )
    artifact, checksum = load_model_artifact(Path("data/routeforge-m13/model.json"))
    manifest = json.loads(
        Path("data/routeforge-m13/manifest.json").read_text(encoding="utf-8")
    )
    assert artifact.model_version == ROUTEFORGE_SCORER_VERSION
    assert artifact.training_partition == "TRAIN"
    assert checksum == manifest["model_artifact_checksum"]
    assert m13_run.model_artifact_checksum


def test_oracle_field_injection_and_version_mismatch_are_rejected() -> None:
    scenario = _scenario("scenario-001")
    payload = scenario.context.model_dump(mode="json")
    payload["preferred_strategy"] = "STRONG"
    payload["synthetic_cost_units"] = 1.0
    with pytest.raises(ValidationError):
        RoutingRequest.model_validate({"context": payload})

    request = RoutingRequest(
        context=scenario.context,
        objective=RoutingObjective().model_copy(update={"version": "routeforge-objective-v2"}),
    )
    with pytest.raises(ValueError, match="objective mismatch"):
        RouteForgeRouter.from_artifact(Path("data/routeforge-m13/model.json")).route(request)


def test_unknown_categories_are_safe_and_ai_required_keeps_ai_strategies_applicable() -> None:
    dataset = read_artifacts(Path("data/routeforge-m11"))
    scenarios = {scenario.scenario_id: scenario for scenario in dataset.scenarios}
    router = RouteForgeRouter.from_artifact(Path("data/routeforge-m13/model.json"))

    altered = scenarios["scenario-001"].context.model_dump(mode="json")
    altered["features"]["change_category"] = "UNSEEN_CATEGORY"
    unknown_context = scenarios["scenario-001"].context.__class__.model_validate(altered)
    decision = router.route(RoutingRequest(context=unknown_context))
    assert decision.selected_strategy in {
        RouteChoice.DETERMINISTIC,
        RouteChoice.SMALL,
        RouteChoice.MEDIUM,
        RouteChoice.STRONG,
    }

    def ai_required_context(context):
        return context.model_copy(
            update={
                "features": context.features.model_copy(
                    update={
                        "m10_outcome": "AI_REQUIRED",
                        "m10_repairability": "UNSUPPORTED",
                        "deterministic_rule_available": False,
                    }
                ),
                "m10_evidence": context.m10_evidence.model_copy(
                    update={
                        "outcome": "AI_REQUIRED",
                        "repairability": "UNSUPPORTED",
                        "rule_id": None,
                        "candidate_generated": False,
                    }
                ),
                "no_repair_required": False,
            }
        )

    ai_required = [
        ai_required_context(scenarios[item].context)
        for item in ("scenario-003", "scenario-005", "scenario-008")
    ]
    decisions = [router.route(RoutingRequest(context=context)) for context in ai_required]
    assert all(context.features.m10_outcome == "AI_REQUIRED" for context in ai_required)
    assert all(
        decision.selected_strategy is not RouteChoice.NO_FEASIBLE_STRATEGY
        for decision in decisions
    )
    profiles = []
    for decision in decisions:
        scores = {item.strategy: item for item in decision.strategy_scores}
        assert scores[RouteForgeStrategy.DETERMINISTIC].applicable is False
        assert all(scores[strategy].applicable for strategy in (
            RouteForgeStrategy.SMALL,
            RouteForgeStrategy.MEDIUM,
            RouteForgeStrategy.STRONG,
        ))
        profiles.append(
            tuple((item.strategy.value, item.score) for item in decision.strategy_scores)
        )
    assert len(set(profiles)) == 3


def test_route_has_no_oracle_evaluation_fields_and_documents_score_only_policy() -> None:
    scenario = _scenario("scenario-007")
    router = RouteForgeRouter.from_artifact(Path("data/routeforge-m13/model.json"))
    decision = router.route(RoutingRequest(context=scenario.context))
    payload = decision.model_dump(mode="json")
    serialized = json.dumps(payload)
    assert "selected_outcome" not in serialized
    assert "synthetic_cost_units" not in serialized
    assert "synthetic_latency_units" not in serialized
    assert "score-only M13 prototype policy" in decision.explanation.selection_basis
    assert "post-selection" in decision.explanation.selection_basis
    assert "cost-aware" in " ".join(decision.warnings).lower()


def test_score_ties_and_strong_remain_representable() -> None:
    objective = RoutingObjective()
    scores = {
        strategy: 1.0
        for strategy in RouteForgeStrategy
        if strategy is not RouteForgeStrategy.NO_AI
    }
    assert select_strategy(scores, objective, tuple(scores)) is RouteChoice.DETERMINISTIC
    assert (
        select_strategy(
            {RouteForgeStrategy.SMALL: 0.1, RouteForgeStrategy.STRONG: 0.9},
            objective,
            (RouteForgeStrategy.SMALL, RouteForgeStrategy.STRONG),
        )
        is RouteChoice.STRONG
    )


def test_repeated_run_and_explanation_determinism(m13_run, tmp_path_factory) -> None:
    repeat = run_m13_router(
        Path("data/routeforge-m11"),
        Path("data/routeforge-m12"),
        tmp_path_factory.mktemp("m13-repeat"),
    )
    assert repeat.reproducibility_fingerprint == m13_run.reproducibility_fingerprint
    assert [item.model_dump(mode="json") for item in repeat.validation_decisions] == [
        item.model_dump(mode="json") for item in m13_run.validation_decisions
    ]
    for decision in m13_run.validation_decisions:
        assert "selected_outcome" not in decision.explanation.model_dump()
        assert all("succeeds" not in item for item in decision.explanation.evidence_features)


def test_checked_in_m13_artifact_has_no_test_predictions() -> None:
    root = Path("data/routeforge-m13")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["validation_decision_count"] == 3
    assert manifest["test_evaluated"] is False
    assert manifest["test_used_for_model_selection"] is False
    assert not list(root.glob("*test*"))
