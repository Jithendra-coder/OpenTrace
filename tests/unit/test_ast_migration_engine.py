"""Deterministic patch and safety tests."""

from pathlib import Path

import pytest
from opentrace.blast_radius.vertical import analyze_vertical_slice as analyze_blast_slice
from opentrace.contracts.models import ChangeCategory
from opentrace.migration import (
    DeterministicMigrationEngine,
    MigrationOutcome,
    apply_plan,
    detect_edit_conflicts,
    migration_support_matrix,
)

ROOT = Path(__file__).parents[2]
OLD_SPEC = ROOT / "demo" / "payment_api_v1.yaml"
NEW_SPEC = ROOT / "demo" / "payment_api_v2.yaml"
DEMO = ROOT / "demo" / "ecommerce"


@pytest.fixture(scope="module")
def evidence():
    blast = analyze_blast_slice(OLD_SPEC, NEW_SPEC, DEMO)
    change = next(
        item
        for item in blast.changes
        if item.category is ChangeCategory.REQUEST_PROPERTY_REMOVED
    )
    impact = next(item for item in blast.direct_impacts if item.change_id == change.id)
    call = next(item for item in blast.call_sites if item.id == impact.call_site_id)
    source = (DEMO / call.file).read_text(encoding="utf-8")
    return change, impact, call, source


def test_canonical_request_property_removal_is_narrow_and_deterministic(evidence) -> None:
    change, impact, call, source = evidence
    engine = DeterministicMigrationEngine()
    first = engine.plan(change, impact, call, source)
    second = engine.plan(change, impact, call, source)

    assert first.outcome is MigrationOutcome.DETERMINISTIC_CANDIDATE
    assert first.canonical_json() == second.canonical_json()
    assert first.candidate is not None
    diff = first.candidate.patch.unified_diff
    assert '-        json={"amount": price, "currency": currency},' in diff
    assert '+        json={"currency": currency},' in diff
    assert diff.count('"amount": price') == 1
    assert '"amount": amount' not in source.replace('"amount": price', '')


def test_plan_application_is_in_memory_and_idempotent(evidence) -> None:
    change, impact, call, source = evidence
    result = DeterministicMigrationEngine().plan(change, impact, call, source)
    assert result.candidate is not None
    patched = apply_plan(source, result.plan)
    assert patched != source
    assert source == (DEMO / call.file).read_text(encoding="utf-8")

    again = DeterministicMigrationEngine().plan(change, impact, call, patched)
    assert again.outcome is MigrationOutcome.NO_CHANGE
    assert not again.plan.edits


def test_stale_source_hash_is_rejected(evidence) -> None:
    change, impact, call, source = evidence
    result = DeterministicMigrationEngine().plan(change, impact, call, source)
    assert result.candidate is not None
    with pytest.raises(ValueError, match="stale source"):
        apply_plan(source + "\n# changed after analysis\n", result.plan)


def test_dynamic_and_shared_payloads_are_not_guessed(evidence) -> None:
    change, impact, call, _ = evidence
    dynamic = """import requests

BASE_URL = "https://payments.example.com"


def create_payment(price: float, currency: str) -> object:
    return requests.post(
        BASE_URL + "/payments",
        json=build_payload(price, currency),
    )
"""
    dynamic_call = call.model_copy(update={"end_line": 10})
    dynamic_result = DeterministicMigrationEngine().plan(
        change, impact, dynamic_call, dynamic
    )
    assert dynamic_result.outcome is MigrationOutcome.AI_REQUIRED
    assert not dynamic_result.plan.edits

    shared = """import requests

BASE_URL = "https://payments.example.com"


def create_payment(price: float, currency: str) -> object:
    payload = {"amount": price, "currency": currency}
    log_payload(payload)
    return requests.post(
        BASE_URL + "/payments",
        json=payload,
    )
"""
    shared_call = call.model_copy(update={"line": 9, "end_line": 12})
    shared_result = DeterministicMigrationEngine().plan(
        change, impact, shared_call, shared
    )
    assert shared_result.outcome is MigrationOutcome.AI_REQUIRED
    assert not shared_result.plan.edits


def test_inline_nested_and_comment_preservation(evidence) -> None:
    change, impact, call, _ = evidence
    inline = """import requests

BASE_URL = "https://payments.example.com"


def create_payment(price: float, currency: str) -> object:
    return requests.post(BASE_URL + "/payments", json={"amount": price, "currency": currency})
"""
    inline_call = call.model_copy(update={"end_line": 7})
    inline_result = DeterministicMigrationEngine().plan(
        change, impact, inline_call, inline
    )
    assert inline_result.outcome is MigrationOutcome.DETERMINISTIC_CANDIDATE
    assert 'json={"currency": currency}' in apply_plan(inline, inline_result.plan)

    commented = """import requests

BASE_URL = "https://payments.example.com"


def create_payment(price: float, currency: str) -> object:
    return requests.post(
        BASE_URL + "/payments",
        json={"amount": price,  # keep this comment
              "currency": currency},
    )
"""
    comment_call = call.model_copy(update={"end_line": 10})
    comment_result = DeterministicMigrationEngine().plan(
        change, impact, comment_call, commented
    )
    assert comment_result.candidate is not None
    commented_patched = apply_plan(commented, comment_result.plan)
    assert "# keep this comment" in commented_patched
    assert '"amount": price' not in commented_patched

    nested_change = change.model_copy(
        update={
            "location": "request.body[application/json].payment.amount",
            "evidence": {"property": "amount"},
        }
    )
    nested = """import requests

BASE_URL = "https://payments.example.com"


def create_payment(price: float, currency: str) -> object:
    return requests.post(
        BASE_URL + "/payments",
        json={"payment": {"amount": price, "currency": currency}},
    )
"""
    nested_call = call.model_copy(
        update={"end_line": 10, "request_fields": ("payment.amount",)}
    )
    nested_impact = impact.model_copy(
        update={"matched_request_fields": ("payment.amount",)}
    )
    nested_result = DeterministicMigrationEngine().plan(
        nested_change, nested_impact, nested_call, nested
    )
    assert nested_result.outcome is MigrationOutcome.DETERMINISTIC_CANDIDATE
    assert '"payment": {"currency": currency}' in apply_plan(
        nested, nested_result.plan
    )


def test_unsupported_category_is_explicit(evidence) -> None:
    change, impact, call, source = evidence
    unsupported = change.model_copy(update={"category": ChangeCategory.ENDPOINT_REMOVED})
    result = DeterministicMigrationEngine().plan(unsupported, impact, call, source)
    assert result.outcome is MigrationOutcome.UNSUPPORTED
    assert result.unsupported is not None
    assert not result.plan.edits
    matrix = migration_support_matrix()
    assert matrix[ChangeCategory.ENDPOINT_REMOVED.value]["status"] == "UNSUPPORTED"


def test_overlapping_edits_are_conflicts(evidence) -> None:
    change, impact, call, source = evidence
    result = DeterministicMigrationEngine().plan(change, impact, call, source)
    assert result.plan.edits
    edit = result.plan.edits[0]
    duplicate = edit.model_copy(update={"id": "duplicate-edit"})
    conflicts = detect_edit_conflicts((edit, duplicate))
    assert conflicts
    assert conflicts[0].kind == "DUPLICATE_EDIT"


def test_multiple_exact_direct_callsites_are_ordered_independently(evidence) -> None:
    change, impact, call, _ = evidence
    source = """import requests

BASE_URL = "https://payments.example.com"


def create_payment(price: float, currency: str) -> object:
    return requests.post(
        BASE_URL + "/payments",
        json={"amount": price, "currency": currency},
    )


def create_second(price: float, currency: str) -> object:
    return requests.post(
        BASE_URL + "/payments",
        json={"amount": price, "currency": currency},
    )
"""
    second_call = call.model_copy(
        update={
            "id": "call-second",
            "owning_symbol": "payment_service.py::create_second",
            "line": 14,
            "end_line": 17,
        }
    )
    second_impact = impact.model_copy(
        update={"id": "impact-second", "call_site_id": second_call.id, "line": 14}
    )
    batch = DeterministicMigrationEngine().plan_many(
        change,
        (second_impact, impact),
        (second_call, call),
        {"payment_service.py": source},
    )
    assert [item.outcome for item in batch.results] == [
        MigrationOutcome.DETERMINISTIC_CANDIDATE,
        MigrationOutcome.DETERMINISTIC_CANDIDATE,
    ]
    edits = tuple(item.plan.edits[0] for item in batch.results)
    patched = apply_plan(
        source,
        batch.results[0].plan.model_copy(update={"edits": edits}),
    )
    assert patched.count('"amount": price') == 0
