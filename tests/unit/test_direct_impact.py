from pathlib import Path

from opentrace.code_analysis import analyze_repository
from opentrace.code_analysis.models import ResolutionState
from opentrace.contracts.models import (
    APIChange,
    BreakingClassification,
    ChangeCategory,
    ChangeCertainty,
    ChangeSeverity,
    CompatibilityDirection,
)
from opentrace.impact import DirectImpactMatcher

FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "python" / "m3_repository"
DEMO_ROOT = Path(__file__).parents[2] / "demo" / "ecommerce"


def _change(category: ChangeCategory, path: str, location: str) -> APIChange:
    return APIChange(
        id=f"change-{category.value}-{path}-{location}",
        category=category,
        path=path,
        method="POST",
        location=location,
        severity=ChangeSeverity.HIGH,
        breaking_classification=BreakingClassification.CLIENT_BREAKING,
        compatibility_direction=CompatibilityDirection.CLIENT_TO_SERVER,
        certainty=ChangeCertainty.EXACT,
        reason="test contract change",
    )


def test_exact_request_change_matches_host_path_method_and_field() -> None:
    calls = analyze_repository(DEMO_ROOT).call_sites
    call = next(call for call in calls if call.file == "payment_service.py")
    change = _change(
        ChangeCategory.REQUEST_PROPERTY_REMOVED,
        "/payments",
        "request.body[application/json].amount",
    )

    result = DirectImpactMatcher(api_hosts=("payments.example.com",)).match((change,), (call,))

    assert len(result.direct_impacts) == 1
    impact = result.direct_impacts[0]
    assert impact.impact_score == 1.0
    assert impact.certainty is ResolutionState.EXACT
    assert impact.matched_request_fields == ("amount",)
    assert {
        "endpoint_path_match",
        "api_identity",
        "http_method_match",
        "changed_request_field_used",
    } <= set(impact.match_features)
    assert sum(item.contribution for item in impact.evidence) == 1.0


def test_host_method_endpoint_and_context_collisions_are_rejected() -> None:
    calls = analyze_repository(DEMO_ROOT).call_sites
    refund = next(call for call in calls if call.file == "refunds.py")
    payment_request = next(call for call in calls if call.file == "payment_service.py")
    request_change = _change(
        ChangeCategory.REQUEST_PROPERTY_REMOVED,
        "/payments",
        "request.body[application/json].amount",
    )

    result = DirectImpactMatcher(api_hosts=("payments.example.com",)).match(
        (request_change,), (refund, payment_request)
    )

    assert [impact.file for impact in result.direct_impacts] == ["payment_service.py"]
    assert result.direct_impacts[0].matched_host == "payments.example.com"


def test_relative_and_partial_paths_are_retained_with_reduced_certainty() -> None:
    calls = analyze_repository(FIXTURE_ROOT).call_sites
    partial = next(
        call
        for call in calls
        if call.file == "urls.py" and "order_id" in (call.raw_url_expression or "")
    )
    change = _change(
        ChangeCategory.SECURITY_REQUIREMENT_CHANGED, "/orders/{order_id}", "security"
    ).model_copy(update={"method": "GET"})

    result = DirectImpactMatcher(api_hosts=("payments.example.com",)).match((change,), (partial,))

    assert len(result.direct_impacts) == 1
    assert result.direct_impacts[0].certainty is ResolutionState.PARTIAL
    assert result.direct_impacts[0].impact_score < 1.0


def test_query_body_and_request_response_fields_do_not_collide() -> None:
    calls = analyze_repository(FIXTURE_ROOT).call_sites
    body_call = next(call for call in calls if call.file == "payloads.py" and call.line == 13)
    response_call = next(
        call for call in calls if call.file == "responses.py" and call.response_fields_used
    )
    query_change = APIChange(
        id="query-change",
        category=ChangeCategory.REQUIRED_PARAMETER_ADDED,
        path="/payments",
        method="POST",
        location="parameter.query.status",
        severity=ChangeSeverity.HIGH,
        breaking_classification=BreakingClassification.CLIENT_BREAKING,
        compatibility_direction=CompatibilityDirection.CLIENT_TO_SERVER,
        certainty=ChangeCertainty.EXACT,
        reason="test query change",
    )
    request_change = _change(
        ChangeCategory.REQUEST_PROPERTY_REMOVED,
        "/users/42",
        "request.body[application/json].name",
    )

    query_result = DirectImpactMatcher(api_hosts=("payments.example.com",)).match(
        (query_change,), (body_call,)
    )
    context_result = DirectImpactMatcher().match((request_change,), (response_call,))

    assert query_result.direct_impacts == ()
    assert context_result.direct_impacts == ()
    assert query_result.unmatched[0].change_id == "query-change"


def test_unresolved_url_is_not_guessed_and_output_is_deterministic() -> None:
    calls = analyze_repository(FIXTURE_ROOT).call_sites
    unresolved = next(
        call for call in calls if call.file == "urls.py" and call.resolved_path is None
    )
    change = _change(
        ChangeCategory.REQUEST_PROPERTY_REMOVED,
        "/payments",
        "request.body[application/json].amount",
    )
    matcher = DirectImpactMatcher(api_hosts=("payments.example.com",))

    first = matcher.match((change,), (unresolved,))
    second = matcher.match((change,), (unresolved,))

    assert first.direct_impacts == ()
    assert first.canonical_json() == second.canonical_json()
