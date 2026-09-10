from pathlib import Path

from opentrace.contracts.models import ChangeCategory
from opentrace.impact import analyze_vertical_slice

ROOT = Path(__file__).parents[2]


def test_canonical_m4_vertical_slice_finds_only_the_real_direct_usage() -> None:
    result = analyze_vertical_slice(
        ROOT / "demo" / "payment_api_v1.yaml",
        ROOT / "demo" / "payment_api_v2.yaml",
        ROOT / "demo" / "ecommerce",
    )

    assert {change.category for change in result.changes} == {
        ChangeCategory.REQUEST_PROPERTY_REMOVED,
        ChangeCategory.RESPONSE_PROPERTY_TYPE_CHANGED,
    }
    assert len(result.call_sites) == 2
    assert len(result.direct_impacts) == 1
    impact = result.direct_impacts[0]
    assert impact.file == "payment_service.py"
    assert impact.symbol == "payment_service.py::create_payment"
    assert impact.matched_request_fields == ("amount",)
    assert impact.matched_host == "payments.example.com"
    assert impact.impact_score == 1.0
    assert any(
        item.change_id in {change.id for change in result.changes} for item in result.unmatched
    )
    assert all("refunds.py" not in item.file for item in result.direct_impacts)
    assert all("users.py" not in item.file for item in result.direct_impacts)
