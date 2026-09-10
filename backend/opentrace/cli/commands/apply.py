"""opentrace apply — apply validated patches to the repository with confirmation."""

from __future__ import annotations

import sys
from pathlib import Path

from opentrace.cli.output import (
    bold, cyan, dim, green, print_banner, print_error,
    print_info, print_ok, print_section, print_warn, red, yellow,
)
from opentrace.cli.workspace import (
    migration_plan_path, migration_plan_exists,
    read_json, validation_result_path, write_json,
)
from opentrace.escalation import UserAction, write_feedback_record
from opentrace.validation.models import ValidationStatus


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

    repo = Path(plan["repo"])
    val_data = read_json(validation_result_path(workspace)) or {}
    val_status = val_data.get("status", "UNKNOWN")

    print_banner("OpenTrace  Apply")
    print_info(f"Repo           : {repo}")
    print_info(f"Patch ID       : {patch_data.get('id', '?')}")
    print_info(f"Validation     : {_status_display(val_status)}")
    print()

    # --- Safety check ---
    if val_status in ("PATCH_FAILED", "SYNTAX_ERROR", "SANDBOX_ERROR"):
        print_error(f"Validation status {val_status} — cannot safely apply this patch.")
        print_warn("Fix the patch or re-run  opentrace migrate  before applying.")
        sys.exit(1)

    if val_status == "TESTS_FAILED":
        print_warn("Validation showed test failures. Applying may break the repository.")
    elif val_status == "UNKNOWN":
        print_warn("No validation result found. Run  opentrace validate  first.")

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
            _write_feedback(workspace, plan, patch_data, UserAction.REJECTED,
                            rejection_reason="User declined at apply prompt.")
            sys.exit(0)

    # --- Apply ---
    print(f"\n  Applying {len(edits)} edit(s) to {repo}...")
    applied: list[str] = []
    try:
        for edit in edits:
            file = edit["file"]
            target = repo / file
            if not target.exists():
                print_error(f"File not found: {file}")
                sys.exit(1)
            content = target.read_text(encoding="utf-8", errors="replace")
            original = edit["expected_original_text"]
            replacement = edit["replacement_text"]
            if original not in content:
                print_error(f"Original text no longer present in {file}.")
                print_warn("The file may have changed since the patch was generated.")
                print_warn("Re-run  opentrace analyze && opentrace migrate  to regenerate.")
                _write_feedback(workspace, plan, patch_data, UserAction.REJECTED,
                                rejection_reason="Precondition mismatch at apply time.")
                sys.exit(1)
            new_content = content.replace(original, replacement, 1)
            target.write_text(new_content, encoding="utf-8", newline="\n")
            applied.append(file)
            print_ok(f"Applied → {file}")

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
        from opentrace.ai_migration.models import MigrationGenerationResult, GenerationStatus
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
