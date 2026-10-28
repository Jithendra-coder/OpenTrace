"""opentrace apply — apply validated patches to the repository with confirmation."""

from __future__ import annotations

import sys
from pathlib import Path

from opentrace.cli.output import (
    bold,
    cyan,
    dim,
    green,
    print_banner,
    print_error,
    print_info,
    print_ok,
    print_section,
    print_warn,
    red,
    yellow,
)
from opentrace.cli.workspace import (
    migration_plan_exists,
    migration_plan_path,
    read_json,
    validation_result_path,
)
from opentrace.escalation import UserAction, write_feedback_record
from opentrace.github.git import GitError, apply_edits_to_working_tree
from opentrace.validation.models import (
    VALIDATION_RESULT_SCHEMA_VERSION,
    patch_data_checksum,
)


def run_apply(workspace: Path, yes: bool) -> None:
    """Apply the generated patch to the real repository after explicit confirmation."""

    if not migration_plan_exists(workspace):
        print_error("No migration plan found. Run  opentrace migrate  first.")
        sys.exit(1)

    plan = read_json(migration_plan_path(workspace))
    if not plan:
        print_error("Could not read migration-plan.json.")
        sys.exit(1)

    patch_data = plan.get("patch")
    if not patch_data:
        print_error("No patch in migration plan. Nothing to apply.")
        sys.exit(1)

    repo = Path(plan["repo"]).resolve()
    val_data = read_json(validation_result_path(workspace)) or {}
    val_status = val_data.get("status", "UNKNOWN")

    print_banner("OpenTrace  Apply")
    print_info(f"Repo           : {repo}")
    print_info(f"Patch ID       : {patch_data.get('id', '?')}")
    print_info(f"Validation     : {_status_display(val_status)}")
    print()

    # Apply only the exact patch with complete passing evidence from the sandbox.
    evidence_checks = {
        "schema_version": val_data.get("schema_version") == VALIDATION_RESULT_SCHEMA_VERSION,
        "patch_id": val_data.get("patch_id") == patch_data.get("id"),
        "patch_checksum": val_data.get("patch_checksum")
        == patch_data_checksum(patch_data),
        "patch_applied": val_data.get("patch_applied") is True,
        "syntax_ok": val_data.get("syntax_ok") is True,
        "tests_collected": type(val_data.get("tests_collected")) is int
        and val_data["tests_collected"] > 0,
        "tests_passed": type(val_data.get("tests_passed")) is int
        and val_data["tests_passed"] > 0,
        "tests_failed": val_data.get("tests_failed") == 0,
        "tests_errors": val_data.get("tests_errors") == 0,
        "exit_code": val_data.get("exit_code") == 0,
        "timeout": val_data.get("timeout") is False,
        "workspace_created": val_data.get("workspace_created") is True,
        "workspace_cleaned": val_data.get("workspace_cleaned") is True,
        "test_counts": (
            type(val_data.get("tests_collected")) is int
            and type(val_data.get("tests_passed")) is int
            and type(val_data.get("tests_failed")) is int
            and type(val_data.get("tests_errors")) is int
            and val_data["tests_collected"]
            == val_data["tests_passed"]
            + val_data["tests_failed"]
            + val_data["tests_errors"]
        ),
    }
    if val_status != "TESTS_PASSED" or not all(evidence_checks.values()):
        print_error(
            "Patch cannot be applied without complete passing validation evidence for this patch."
        )
        print_warn(
            "Run  opentrace validate  again and apply only after tests pass in the sandbox."
        )
        sys.exit(1)

    # --- Show what will change ---
    edits = patch_data.get("edits", [])
    print_section(f"Files to Modify ({len(edits)} edit(s))")
    for edit in edits:
        file = edit.get("file", "?")
        symbol = edit.get("symbol", "")
        reason = edit.get("reason", "")
        sym_str = f"  {dim(symbol)}" if symbol else ""
        print(f"  {cyan(file)}{sym_str}")
        print(f"    {dim(reason)}")
        print()

    # --- Confirm ---
    if not yes:
        print(bold("  ⚠  This will modify files in your repository."))
        print(f"  Repository: {repo}")
        print()
        try:
            answer = input("  Apply patch? [yes/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            print_warn("Aborted.")
            _write_feedback(workspace, plan, patch_data, UserAction.SKIPPED)
            sys.exit(0)

        if answer != "yes":
            print_warn("Aborted. No files were modified.")
            _write_feedback(
                workspace,
                plan,
                patch_data,
                UserAction.REJECTED,
                rejection_reason="User declined at apply prompt.",
            )
            sys.exit(0)

    print(f"\n  Applying {len(edits)} edit(s) to {repo}...")
    try:
        applied = apply_edits_to_working_tree(repo, edits)
        for file in applied:
            print_ok(f"Applied → {file}")
    except GitError as exc:
        print_error(str(exc))
        _write_feedback(
            workspace,
            plan,
            patch_data,
            UserAction.REJECTED,
            rejection_reason=str(exc),
        )
        sys.exit(1)
    except Exception as exc:
        print_error(f"Apply failed: {exc}")
        sys.exit(1)

    _write_feedback(workspace, plan, patch_data, UserAction.ACCEPTED)

    print_section("Done")
    print_ok(f"{len(applied)} file(s) modified.")
    print_info("Review the changes with  git diff  before committing.")
    print_warn("AI-generated patches require human review before merging.")
    print()


def _status_display(status: str) -> str:
    mapping = {
        "TESTS_PASSED": green("TESTS_PASSED ✓"),
        "TESTS_FAILED": red("TESTS_FAILED ✗"),
        "NO_TESTS_COLLECTED": yellow("NO_TESTS_COLLECTED ⚠"),
        "PATCH_FAILED": red("PATCH_FAILED ✗"),
        "SYNTAX_ERROR": red("SYNTAX_ERROR ✗"),
        "TIMEOUT": red("TIMEOUT ✗"),
        "RUNNER_ERROR": yellow("RUNNER_ERROR ⚠"),
        "SANDBOX_ERROR": red("SANDBOX_ERROR ✗"),
        "UNKNOWN": dim("not validated"),
    }
    return mapping.get(status, dim(status))


def _write_feedback(
    workspace: Path,
    plan: dict,
    patch_data: dict,
    action: UserAction,
    rejection_reason: str | None = None,
) -> None:
    """Write a feedback record after a human apply/reject decision."""
    try:
        # Reconstruct a minimal generation result for feedback provenance.
        from opentrace.ai_migration.models import GenerationStatus, MigrationGenerationResult
        from opentrace.cli.commands.validate import _reconstruct_patch

        patch = _reconstruct_patch(patch_data)
        gen_result = MigrationGenerationResult(
            id=f"cli-gen-{patch_data.get('id', 'unknown')}",
            status=GenerationStatus.GENERATED,
            migration_context_id=plan.get("routing_decision_id", "cli-ctx"),
            patch=patch,
        )
        write_feedback_record(
            gen_result,
            None,
            None,
            action,
            workspace,
            rejection_reason=rejection_reason,
        )
    except Exception:
        pass  # Feedback write failure must never abort the apply flow.
