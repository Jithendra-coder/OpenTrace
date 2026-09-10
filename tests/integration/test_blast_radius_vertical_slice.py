from pathlib import Path

from opentrace.blast_radius import analyze_vertical_slice
from opentrace.blast_radius.models import ImpactType, RiskLevel


def test_real_m1_to_m6_vertical_slice_propagates_only_real_callers() -> None:
    root = Path(__file__).parents[2]
    result = analyze_vertical_slice(
        root / "demo" / "payment_api_v1.yaml",
        root / "demo" / "payment_api_v2.yaml",
        root / "demo" / "ecommerce",
    )

    assert [(item.symbol, item.impact_type, item.distance) for item in result.impacted_symbols] == [
        ("payment_service.py::create_payment", ImpactType.DIRECT, 0),
        ("checkout.py::checkout", ImpactType.INDIRECT, 1),
        ("orders.py::place_order", ImpactType.INDIRECT, 2),
    ]
    assert result.unmatched_change_ids
    assert result.risk_assessment is not None
    assert result.risk_assessment.risk_level is RiskLevel.CRITICAL
    assert result.risk_assessment.risk_score == 75.0
    assert all("refunds.py" not in item.file for item in result.impacted_symbols)
    assert all("users.py" not in item.file for item in result.impacted_symbols)
