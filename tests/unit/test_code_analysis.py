from pathlib import Path

from opentrace.code_analysis import analyze_repository
from opentrace.code_analysis.models import FileAnalysisState, ResolutionState, SymbolKind
from opentrace.code_analysis.repository import discover_python_files

FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "python" / "sample_repo"


def test_repository_discovery_is_relative_deterministic_and_excludes_generated_dirs(
    tmp_path: Path,
) -> None:
    (tmp_path / "valid.py").write_text("value = 1\n")
    generated = tmp_path / "__pycache__"
    generated.mkdir()
    (generated / "ignored.py").write_text("import requests\nrequests.get('/ignored')\n")
    files = discover_python_files(tmp_path)

    paths = tuple(path.relative_to(tmp_path).as_posix() for path in files)
    assert paths == tuple(sorted(paths))
    assert paths == ("valid.py",)
    assert all(not path.startswith("C:") for path in paths)


def test_ast_analysis_extracts_supported_clients_and_preserves_ownership() -> None:
    analysis = analyze_repository(FIXTURE_ROOT)

    methods = {(call.library, call.method) for call in analysis.call_sites}
    assert {("requests", method) for method in ("GET", "POST", "PATCH")} <= methods
    assert {("httpx", method) for method in ("PUT", "DELETE", "POST")} <= methods
    assert any(call.invocation_kind == "FROM_IMPORT" for call in analysis.call_sites)
    assert any(call.invocation_kind == "CLIENT_INSTANCE" for call in analysis.call_sites)
    assert any(call.invocation_kind == "SESSION_INSTANCE" for call in analysis.call_sites)
    assert any(
        call.owning_symbol.endswith("::PaymentService.create") for call in analysis.call_sites
    )
    assert any(
        call.owning_symbol.endswith("::PaymentService.fetch") for call in analysis.call_sites
    )
    assert any(call.owning_symbol.endswith("::outer.inner") for call in analysis.call_sites)
    assert any(symbol.kind is SymbolKind.ASYNC_FUNCTION for symbol in analysis.symbols)
    assert any(symbol.kind is SymbolKind.ASYNC_METHOD for symbol in analysis.symbols)


def test_false_positives_are_not_emitted_and_parse_failures_are_visible(tmp_path: Path) -> None:
    broken = tmp_path / "broken_syntax.py"
    broken.write_text("def broken(:\n    pass\n")
    analysis = analyze_repository(FIXTURE_ROOT)
    failure_analysis = analyze_repository(tmp_path)

    paths = {call.resolved_path for call in analysis.call_sites}
    assert "/comment" not in paths
    assert "/string" not in paths
    assert "/shadowed" not in paths
    assert "/lookalike" not in paths
    assert "/local-function" not in paths
    assert "/parameter-shadow" not in paths
    assert "/from-shadow" not in paths
    failed = next(file for file in failure_analysis.files if file.path == "broken_syntax.py")
    assert failed.state is FileAnalysisState.FAILED
    assert failed.error_category == "SYNTAX_ERROR"
    assert failed.error_line == 1


def test_url_resolution_preserves_hosts_paths_queries_and_dynamic_uncertainty() -> None:
    analysis = analyze_repository(FIXTURE_ROOT)
    calls = {call.raw_url_expression: call for call in analysis.call_sites}

    absolute = next(
        call for call in analysis.call_sites if call.resolved_host == "identity.example.com"
    )
    assert absolute.resolved_host == "identity.example.com"
    assert absolute.resolved_path == "/orders"
    assert absolute.url_resolution_state is ResolutionState.EXACT

    query = calls["local + '?status=pending'"]
    assert query.resolved_host == "payments.example.com"
    assert query.resolved_path == "/orders"
    assert query.url_resolution_state is ResolutionState.EXACT

    dynamic = next(
        call for call in analysis.call_sites if call.raw_url_expression == "build_url(order)"
    )
    assert dynamic.resolved_path is None
    assert dynamic.url_resolution_state is ResolutionState.UNRESOLVED

    partial = next(
        call for call in analysis.call_sites if "order_id" in (call.raw_url_expression or "")
    )
    assert partial.resolved_host == "payments.example.com"
    assert partial.resolved_path == "/orders/{dynamic}"
    assert partial.url_resolution_state is ResolutionState.PARTIAL


def test_request_and_response_field_evidence_is_context_specific() -> None:
    analysis = analyze_repository(FIXTURE_ROOT)
    payment_calls = [call for call in analysis.call_sites if call.resolved_path == "/payments"]
    inline = next(call for call in payment_calls if "customer.name" in call.request_fields)
    assert {
        "amount",
        "customer",
        "customer.name",
        "customer.address",
        "customer.address.zip",
    } <= set(inline.request_fields)
    assert inline.request_field_resolution_state is ResolutionState.EXACT
    assert inline.query_parameters == ("limit", "status")
    assert inline.headers == ("Authorization", "X-Client-ID")

    response_calls = [call for call in analysis.call_sites if call.file == "responses.py"]
    fields = next(call for call in response_calls if call.response_fields_used)
    assert {"name"} <= set(fields.response_fields_used)
    nested = next(call for call in response_calls if "customer.phone" in call.response_fields_used)
    assert nested.response_field_resolution_state is ResolutionState.EXACT
    metadata = next(call for call in response_calls if call.response_fields_used == ())
    assert "status_code" not in metadata.response_fields_used


def test_partial_payload_and_determinism_are_explicit() -> None:
    first = analyze_repository(FIXTURE_ROOT)
    second = analyze_repository(FIXTURE_ROOT)

    partial = next(
        call
        for call in first.call_sites
        if call.request_field_resolution_state is ResolutionState.PARTIAL
    )
    assert "known" in partial.request_fields
    assert partial.resolution_state is ResolutionState.PARTIAL
    assert first.canonical_json() == second.canonical_json()
    assert [call.id for call in first.call_sites] == [call.id for call in second.call_sites]


def test_ast_analysis_never_executes_repository_source(tmp_path: Path) -> None:
    marker = tmp_path / "executed.txt"
    source = (
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('executed')\n"
        "import requests\n"
        "requests.options('/safe')\n"
        "requests.head('/safe')\n"
    )
    (tmp_path / "untrusted.py").write_text(source)

    analysis = analyze_repository(tmp_path)

    assert not marker.exists()
    assert {call.method for call in analysis.call_sites} == {"HEAD", "OPTIONS"}
