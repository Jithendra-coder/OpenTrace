"""opentrace validate — test the proposed patch in an isolated sandbox."""

from __future__ import annotations

import sys
from pathlib import Path

from opentrace.cli.output import (
    bold, cyan, dim, green, print_banner, print_error,
    print_info, print_ok, print_section, print_warn, red, yellow,
)
from opentrace.cli.workspace import (
    migration_plan_exists, migration_plan_path,
    read_json, validation_result_path, write_json,
)
from opentrace.validation import SandboxConfig, ValidationStatus, validate_patch


def run_validate(workspace: Path, timeout: int) -> None:
    """Run M16 sandbox validation on the generated patch."""

    if not migration_plan_exists(workspace):
        print_error("No migration plan found. Run  opentrace migrate  first.")
        sys.exit(1)

    plan = read_json(migration_plan_path(workspace))
    if not plan:
        print_error("Could not read migration-plan.json.")
        sys.exit(1)

    patch_data = plan.get("patch")
    if not patch_data:
        status = plan.get("generation_status", "UNKNOWN")
        print_error(f"No patch in migration plan (status: {status}).")
        print_warn("Try running  opentrace migrate  again or review the migration plan.")
        sys.exit(1)

    repo = Path(plan["repo"])

    print_banner("OpenTrace  Validate")
    print_info(f"Repo   : {repo}")
    print_info(f"Timeout: {timeout}s")
    print()

    # --- Reconstruct patch from JSON ---
    try:
        patch = _reconstruct_patch(patch_data)
    except Exception as exc:
        print_error(f"Could not reconstruct patch: {exc}")
        sys.exit(1)

    # --- Run sandbox ---
    print(f"  Creating isolated sandbox workspace...")
    config = SandboxConfig(timeout_seconds=timeout)

    try:
        evidence = validate_patch(patch, repo, config)
    except Exception as exc:
        print_error(f"Validation failed unexpectedly: {exc}")
        sys.exit(1)

    # --- Display results ---
    print_section("Validation Results")

    _print_evidence(evidence)

    # --- Save result ---
    result = {
        "schema_version": "validation-result-v1",
        "patch_id": evidence.patch_id,
        "status": evidence.status.value,
        "patch_applied": evidence.patch_applied,
        "syntax_ok": evidence.syntax_ok,
        "tests_collected": evidence.tests_collected,
        "tests_passed": evidence.tests_passed,
        "tests_failed": evidence.tests_failed,
        "exit_code": evidence.exit_code,
        "timeout": evidence.timeout,
        "failure_summary": evidence.failure_summary,
        "workspace_created": evidence.workspace_created,
        "workspace_cleaned": evidence.workspace_cleaned,
        "duration_ms": evidence.duration_ms,
        "limitations": list(evidence.limitations),
    }
    out = validation_result_path(workspace)
    write_json(out, result)

    print_section("Next Step")
    print_ok(f"Validation result written → {out}")

    if evidence.status is ValidationStatus.TESTS_PASSED:
        print_info("Run  opentrace apply  to apply the patch to the repository.")
    elif evidence.status is ValidationStatus.NO_TESTS_COLLECTED:
        print_warn("No tests were collected in the sandbox.")
        print_info("You may still run  opentrace apply  to apply the patch manually.")
    elif evidence.status is ValidationStatus.TESTS_FAILED:
        print_warn("Some tests failed. Review the failure summary above before applying.")
        print_info("Run  opentrace apply  to apply anyway (with confirmation).")
    else:
        print_warn(f"Validation status: {evidence.status.value} — review before applying.")
    print()


def _print_evidence(evidence: object) -> None:
    from opentrace.validation.models import ValidationEvidence, ValidationStatus
    if not isinstance(evidence, ValidationEvidence):
        print_warn("Unknown evidence type.")
        return

    # Workspace
    ws_ok = evidence.workspace_created and evidence.workspace_cleaned
    ws_str = green("created + cleaned ✓") if ws_ok else red("cleanup issue ✗")
    print(f"  Sandbox workspace : {ws_str}")
    if evidence.workspace_path_hint:
        print(f"  Workspace hint    : {dim('...' + evidence.workspace_path_hint)}")

    # Patch application
    if evidence.patch_applied:
        print(f"  Patch applied     : {green('✓')}")
    else:
        print(f"  Patch applied     : {red('✗')}  {dim(evidence.patch_failure_reason or '')}")

    # Syntax
    if evidence.syntax_ok is True:
        print(f"  Syntax check      : {green('✓')}")
    elif evidence.syntax_ok is False:
        print(f"  Syntax check      : {red('✗')}  {dim(evidence.syntax_failure_file or '')}")

    # Tests
    if evidence.tests_collected is not None:
        passed = evidence.tests_passed or 0
        failed = evidence.tests_failed or 0
        errors = evidence.tests_errors or 0
        collected = evidence.tests_collected
        print(f"  Tests collected   : {collected}")
        print(f"  Tests passed      : {green(str(passed))}")
        if failed > 0:
            print(f"  Tests failed      : {red(str(failed))}")
        if errors > 0:
            print(f"  Tests errors      : {red(str(errors))}")

    # Timeout
    if evidence.timeout:
        print(f"  Timeout           : {red('YES — subprocess exceeded time limit')}")

    # Duration
    if evidence.duration_ms is not None:
        print(f"  Duration          : {evidence.duration_ms}ms")

    # Status
    status_str = _status_display(evidence.status)
    print(f"\n  {bold('Result')}            : {status_str}")

    # Failure summary
    if evidence.failure_summary:
        print(f"\n  {bold('Failure summary:')}")
        for line in evidence.failure_summary.splitlines()[-20:]:
            print(f"    {dim(line)}")


def _status_display(status: "ValidationStatus") -> str:
    from opentrace.validation.models import ValidationStatus
    mapping = {
        ValidationStatus.TESTS_PASSED: green("TESTS_PASSED ✓"),
        ValidationStatus.TESTS_FAILED: red("TESTS_FAILED ✗"),
        ValidationStatus.NO_TESTS_COLLECTED: yellow("NO_TESTS_COLLECTED ⚠"),
        ValidationStatus.PATCH_FAILED: red("PATCH_FAILED ✗"),
        ValidationStatus.SYNTAX_ERROR: red("SYNTAX_ERROR ✗"),
        ValidationStatus.TIMEOUT: red("TIMEOUT ✗"),
        ValidationStatus.RUNNER_ERROR: yellow("RUNNER_ERROR ⚠"),
        ValidationStatus.SANDBOX_ERROR: red("SANDBOX_ERROR ✗"),
    }
    return mapping.get(status, dim(status.value))


def _reconstruct_patch(data: dict) -> object:
    """Reconstruct a ProposedMigrationPatch from JSON dict."""
    from opentrace.ai_migration.models import ProposedFileEdit, ProposedMigrationPatch
    from opentrace.routeforge.models import RouteChoice

    edits = tuple(
        ProposedFileEdit(
            id=e["id"],
            file=e["file"],
            context_item_id=e.get("context_item_id", "cli-ctx"),
            symbol=e.get("symbol"),
            start_line=e["start_line"],
            end_line=e["end_line"],
            source_item_hash=e.get("source_item_hash", "x" * 64),
            original_text_hash=e["original_text_hash"],
            expected_original_text=e["expected_original_text"],
            replacement_text=e["replacement_text"],
            reason=e["reason"],
            response_item_indexes=(0,),
        )
        for e in data.get("edits", [])
    )

    return ProposedMigrationPatch(
        id=data["id"],
        migration_context_id=data.get("migration_context_id", "cli-ctx-id"),
        migration_context_checksum=data.get("migration_context_checksum", "cli-checksum"),
        routing_decision_id=data.get("routing_decision_id", "cli-decision"),
        selected_strategy=RouteChoice(data.get("selected_strategy", "SMALL")),
        provider_adapter_id=data.get("provider_adapter_id", "cli-provider"),
        model_id=data.get("model_id", "cli-model"),
        generation_policy_version=data.get(
            "generation_policy_version", "migration-generation-policy-v1"
        ),
        generation_fingerprint=data.get("generation_fingerprint", "cli-fingerprint"),
        provider_response_hash=data.get("provider_response_hash", "cli-response-hash"),
        edits=edits,
        explanation=data.get("explanation", ""),
        warnings=tuple(data.get("warnings", [])),
    )
