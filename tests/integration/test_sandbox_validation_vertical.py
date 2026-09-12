"""Integration test: real vertical slice with sandbox validation."""

from __future__ import annotations

from pathlib import Path

from opentrace.ai_migration import (
    DeterministicFakeProvider,
    GenerationConfiguration,
    GenerationStatus,
)
from opentrace.routeforge.models import RouteChoice, RouteForgeStrategy
from opentrace.routeforge.router import (
    ROUTEFORGE_DECISION_POLICY_VERSION,
    ROUTEFORGE_ROUTER_VERSION,
    RoutingDecision,
    RoutingExplanation,
    StrategyScore,
)
from opentrace.validation import (
    ValidationStatus,
    analyze_and_validate_vertical_slice,
)

ROOT = Path(__file__).parents[2]
DEMO = ROOT / "demo" / "ecommerce"


def _governed_m13_small_fixture() -> RoutingDecision:
    return RoutingDecision(
        decision_id="m13-governed-payment-small-m16",
        context_id="m13-payment-context-m16",
        scenario_id="m13-payment-scenario-m16",
        decision_group_id="m13-payment-group-m16",
        migration_id="m10-payment-m16",
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
        model_artifact_checksum="m13-governed-fixture-m16",
        context_fingerprint="m13-payment-context-fingerprint-m16",
        explanation=RoutingExplanation(
            summary="Governed routing fixture for validation test.",
            applicability=("SMALL applicable",),
            selection_basis="Pre-decision fixture evidence only.",
            evidence_features=("m10_outcome=DETERMINISTIC_CANDIDATE",),
        ),
        warnings=(),
    )


def test_real_m1_to_m16_generates_and_validates_without_source_mutation() -> None:
    """Real migration path: generation + sandbox validation, no source repo mutation."""
    before = {p.name: p.read_text(encoding="utf-8") for p in DEMO.glob("*.py")}

    provider = DeterministicFakeProvider()
    generation_result, evidence = analyze_and_validate_vertical_slice(
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
    after = {p.name: p.read_text(encoding="utf-8") for p in DEMO.glob("*.py")}

    # Source repository must not have changed.
    assert before == after, "Source repository was mutated — isolation failure"

    # Generation must have succeeded.
    assert generation_result.status is GenerationStatus.GENERATED
    assert generation_result.patch is not None

    # Validation evidence must exist and have required fields.
    assert evidence is not None
    assert evidence.patch_id == generation_result.patch.id
    assert evidence.patch_applied is True
    assert evidence.workspace_created is True
    assert evidence.workspace_cleaned is True
    assert evidence.workspace_path_hint is not None
    assert evidence.duration_ms is not None and evidence.duration_ms >= 0
    assert evidence.schema_version == "validation-evidence-v1"
    assert len(evidence.limitations) >= 1

    # Status must be one of the documented outcomes.
    assert evidence.status in {
        ValidationStatus.TESTS_PASSED,
        ValidationStatus.TESTS_FAILED,
        ValidationStatus.NO_TESTS_COLLECTED,
        ValidationStatus.RUNNER_ERROR,
    }, f"Unexpected status: {evidence.status}"


def test_no_ai_route_produces_no_validation_evidence() -> None:
    """Non-AI routes do not produce a patch and therefore no validation evidence."""
    from opentrace.routeforge.router import RoutingAbstention

    no_ai_decision = RoutingDecision(
        decision_id="m13-no-ai-fixture",
        context_id="m13-context-no-ai",
        scenario_id="m13-scenario-no-ai",
        decision_group_id="m13-group-no-ai",
        migration_id="m10-payment-no-ai",
        selected_strategy=RouteChoice.NO_AI,
        strategy_scores=(
            StrategyScore(
                strategy=RouteForgeStrategy.SMALL,
                score=0.1,
                applicable=False,
                reason="fixture no-ai",
            ),
        ),
        feature_schema_version="routeforge-features-v1",
        strategy_taxonomy_version="routeforge-strategies-v1",
        objective_version="routeforge-objective-v1",
        model_id="RF-M13-LOGISTIC-V1",
        scorer_version="routeforge-logistic-scorer-v1",
        router_version=ROUTEFORGE_ROUTER_VERSION,
        decision_policy_version=ROUTEFORGE_DECISION_POLICY_VERSION,
        model_artifact_checksum="fixture-no-ai",
        context_fingerprint="fixture-fingerprint-no-ai",
        explanation=RoutingExplanation(
            summary="No-AI fixture.",
            applicability=("SMALL not applicable",),
            selection_basis="NO_AI fixture.",
            evidence_features=(),
        ),
        warnings=(),
    )

    provider = DeterministicFakeProvider()
    generation_result, evidence = analyze_and_validate_vertical_slice(
        ROOT / "demo" / "payment_api_v1.yaml",
        ROOT / "demo" / "payment_api_v2.yaml",
        DEMO,
        no_ai_decision,
        GenerationConfiguration(
            ai_enabled=True,
            provider_id=provider.adapter_id,
            model_by_strategy={RouteChoice.SMALL: "small-configured-model"},
        ),
        provider,
    )

    assert generation_result.status is GenerationStatus.NOT_REQUIRED
    assert evidence is None
    assert not provider.requests
