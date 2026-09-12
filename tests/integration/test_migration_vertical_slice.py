"""Canonical real migration path."""

from pathlib import Path

from opentrace.migration import MigrationOutcome, analyze_migration_vertical_slice

ROOT = Path(__file__).parents[2]
DEMO = ROOT / "demo" / "ecommerce"


def test_real_upstream_evidence_produces_only_payment_request_candidate() -> None:
    before = {
        path.name: path.read_text(encoding="utf-8")
        for path in DEMO.glob("*.py")
    }
    result = analyze_migration_vertical_slice(
        ROOT / "demo" / "payment_api_v1.yaml",
        ROOT / "demo" / "payment_api_v2.yaml",
        DEMO,
    )
    after = {path.name: path.read_text(encoding="utf-8") for path in DEMO.glob("*.py")}

    candidates = [
        item for item in result.results if item.outcome is MigrationOutcome.DETERMINISTIC_CANDIDATE
    ]
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.plan.target_file == "payment_service.py"
    assert candidate.plan.target_symbol == "payment_service.py::create_payment"
    assert candidate.candidate is not None
    assert '"amount": price' in candidate.candidate.patch.unified_diff
    assert '"currency": currency' in candidate.candidate.patch.unified_diff
    assert before == after
    assert all(
        path not in candidate.candidate.patch.files
        for path in ("checkout.py", "orders.py", "refunds.py", "users.py")
    )
