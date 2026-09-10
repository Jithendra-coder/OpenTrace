"""Canonical real M1→M14 MigrationContext vertical slice."""

from pathlib import Path

from opentrace.migration_context import (
    ContextItemRole,
    ContextSelectionStatus,
    analyze_migration_context_vertical_slice,
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
    """A non-oracle M13 decision fixture; M14 must consume it without rerouting."""

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
            summary="Governed M13 fixture.",
            applicability=("SMALL applicable",),
            selection_basis="Pre-decision fixture evidence only.",
            evidence_features=("m10_outcome=DETERMINISTIC_CANDIDATE",),
        ),
        warnings=(),
    )


def test_real_m1_to_m14_context_selects_payment_evidence_only() -> None:
    result = analyze_migration_context_vertical_slice(
        ROOT / "demo" / "payment_api_v1.yaml",
        ROOT / "demo" / "payment_api_v2.yaml",
        DEMO,
        _governed_m13_small_fixture(),
    )

    assert result.status is ContextSelectionStatus.CONTEXT_READY
    assert result.context is not None
    items = {item.role: item for item in result.context.items}
    assert '"category":"request_property_removed"' in items[ContextItemRole.API_CHANGE].content
    assert "requests.post" in items[ContextItemRole.DIRECT_API_CALL].content
    assert "def create_payment" in items[ContextItemRole.TARGET_SYMBOL].content
    assert '"request_fields":["amount","currency"]' in (
        items[ContextItemRole.REQUEST_EVIDENCE].content
    )
    assert "remove-request-property-v1" in items[ContextItemRole.MIGRATION_EVIDENCE].content
    assert items[ContextItemRole.ROUTING_EVIDENCE].content.startswith('{"abstention":null')
    assert all("refund" not in (item.file or "") for item in result.context.items)
    assert all("user" not in (item.file or "") for item in result.context.items)
