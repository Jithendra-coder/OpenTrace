"""Canonical real candidate-generation vertical slice."""

from pathlib import Path

from opentrace.ai_migration import (
    DeterministicFakeProvider,
    GenerationConfiguration,
    GenerationStatus,
    analyze_migration_generation_vertical_slice,
)
from opentrace.routeforge.models import RouteChoice, RouteForgeStrategy
from opentrace.routeforge.router import (
    ROUTEFORGE_DECISION_POLICY_VERSION,
    ROUTEFORGE_ROUTER_VERSION,
    RoutingDecision,
    RoutingExplanation,
    StrategyScore,
)

ROOT = Path(__file__).parents[2]
DEMO = ROOT / "demo" / "ecommerce"


def _governed_m13_small_fixture() -> RoutingDecision:
    return RoutingDecision(
        decision_id="m13-governed-payment-small",
        context_id="m13-payment-context",
        scenario_id="m13-payment-scenario",
        decision_group_id="m13-payment-group",
        migration_id="m10-payment",
        selected_strategy=RouteChoice.SMALL,
        strategy_scores=(
            StrategyScore(
                strategy=RouteForgeStrategy.SMALL,
                score=0.5,
                applicable=True,
                reason="fixture pre-decision applicability",
            ),
        ),
        feature_schema_version="routeforge-features-v1",
        strategy_taxonomy_version="routeforge-strategies-v1",
        objective_version="routeforge-objective-v1",
        model_id="RF-M13-LOGISTIC-V1",
        scorer_version="routeforge-logistic-scorer-v1",
        router_version=ROUTEFORGE_ROUTER_VERSION,
        decision_policy_version=ROUTEFORGE_DECISION_POLICY_VERSION,
        model_artifact_checksum="m13-governed-fixture",
        context_fingerprint="m13-payment-context-fingerprint",
        explanation=RoutingExplanation(
            summary="Governed routing fixture.",
            applicability=("SMALL applicable",),
            selection_basis="Pre-decision fixture evidence only.",
            evidence_features=("m10_outcome=DETERMINISTIC_CANDIDATE",),
        ),
        warnings=(),
    )


def test_real_m1_to_m15_generates_unvalidated_candidate_without_repository_mutation() -> None:
    before = {path.name: path.read_text(encoding="utf-8") for path in DEMO.glob("*.py")}
    provider = DeterministicFakeProvider()
    result = analyze_migration_generation_vertical_slice(
        ROOT / "demo" / "payment_api_v1.yaml",
        ROOT / "demo" / "payment_api_v2.yaml",
        DEMO,
        _governed_m13_small_fixture(),
        GenerationConfiguration(
            ai_enabled=True,
            provider_id=provider.adapter_id,
            model_by_strategy={RouteChoice.SMALL: "small-configured-model"},
        ),
        provider,
    )
    after = {path.name: path.read_text(encoding="utf-8") for path in DEMO.glob("*.py")}

    assert result.status is GenerationStatus.GENERATED
    assert result.patch is not None
    assert result.patch.edits[0].file == "payment_service.py"
    assert result.patch.edits[0].replacement_text == ""
    assert result.patch.warnings == (
        "Candidate is unvalidated and was not applied to any repository.",
    )
    assert before == after
