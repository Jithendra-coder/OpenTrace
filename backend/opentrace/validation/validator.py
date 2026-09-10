"""M16 patch validator: orchestrates sandbox + runner → ValidationEvidence."""

from __future__ import annotations

import time
from pathlib import Path

from opentrace.ai_migration.models import ProposedMigrationPatch
from opentrace.validation.models import (
    SandboxConfig,
    ValidationEvidence,
    ValidationStatus,
)
from opentrace.validation.sandbox import SandboxWorkspace, _PatchApplicationError, _SyntaxCheckError
from opentrace.validation.runner import run_tests


def validate_patch(
    patch: ProposedMigrationPatch,
    repository_root: Path | str,
    config: SandboxConfig | None = None,
) -> ValidationEvidence:
    """Run the full M16 validation flow for one proposed patch.

    Flow:
      1. Create ephemeral temp workspace (copy of repository_root)
      2. Apply patch edits to workspace copy
      3. Syntax-check edited Python files
      4. Run pytest inside workspace with timeout
      5. Return structured ValidationEvidence
      6. Destroy workspace (guaranteed in finally)

    No files in repository_root are ever modified.
    """
    if config is None:
        config = SandboxConfig()

    root = Path(repository_root).resolve()
    start_ms = _now_ms()

    workspace_created = False
    workspace_cleaned = False
    workspace_hint: str | None = None

    patch_applied = False
    patch_failure_reason: str | None = None
    syntax_ok: bool | None = None
    syntax_failure_file: str | None = None
    exit_code: int | None = None
    tests_passed = 0
    tests_failed = 0
    tests_errors = 0
    timed_out = False
    failure_summary: str | None = None

    try:
        workspace = SandboxWorkspace(root, config)
        try:
            workspace.__enter__()
            workspace_created = workspace.workspace_created
            workspace_hint = workspace.workspace_path_hint

            # --- Step 1: Apply patch ---
            try:
                workspace.apply_patch(patch)
                patch_applied = True
            except _PatchApplicationError as exc:
                patch_failure_reason = str(exc)
                duration_ms = _now_ms() - start_ms
                workspace.__exit__(None, None, None)
                workspace_cleaned = workspace.workspace_cleaned
                return ValidationEvidence(
                    patch_id=patch.id,
                    status=ValidationStatus.PATCH_FAILED,
                    patch_applied=False,
                    patch_failure_reason=patch_failure_reason,
                    workspace_created=workspace_created,
                    workspace_cleaned=workspace_cleaned,
                    workspace_path_hint=workspace_hint,
                    duration_ms=duration_ms,
                )

            # --- Step 2: Syntax check ---
            try:
                workspace.check_syntax(patch)
                syntax_ok = True
            except _SyntaxCheckError as exc:
                syntax_ok = False
                syntax_failure_file = exc.file
                duration_ms = _now_ms() - start_ms
                workspace.__exit__(None, None, None)
                workspace_cleaned = workspace.workspace_cleaned
                return ValidationEvidence(
                    patch_id=patch.id,
                    status=ValidationStatus.SYNTAX_ERROR,
                    patch_applied=patch_applied,
                    syntax_ok=False,
                    syntax_failure_file=syntax_failure_file,
                    workspace_created=workspace_created,
                    workspace_cleaned=workspace_cleaned,
                    workspace_path_hint=workspace_hint,
                    duration_ms=duration_ms,
                )

            # --- Step 3: Run tests ---
            (
                exit_code,
                tests_passed,
                tests_failed,
                tests_errors,
                timed_out,
                failure_summary,
                runner_ms,
            ) = run_tests(workspace.repo_path, config)

        finally:
            workspace.__exit__(None, None, None)
            workspace_cleaned = workspace.workspace_cleaned

    except Exception as exc:
        duration_ms = _now_ms() - start_ms
        return ValidationEvidence(
            patch_id=patch.id,
            status=ValidationStatus.SANDBOX_ERROR,
            patch_applied=False,
            patch_failure_reason=f"sandbox setup error: {exc}",
            workspace_created=workspace_created,
            workspace_cleaned=workspace_cleaned,
            workspace_path_hint=workspace_hint,
            duration_ms=duration_ms,
        )

    duration_ms = _now_ms() - start_ms

    # --- Determine status ---
    if timed_out:
        status = ValidationStatus.TIMEOUT
    elif not patch_applied:
        status = ValidationStatus.PATCH_FAILED
    elif not syntax_ok:
        status = ValidationStatus.SYNTAX_ERROR
    elif exit_code is not None and exit_code != 0 and tests_passed == 0 and tests_failed == 0:
        status = ValidationStatus.RUNNER_ERROR
    elif tests_passed == 0 and tests_failed == 0 and tests_errors == 0:
        status = ValidationStatus.NO_TESTS_COLLECTED
    elif tests_failed > 0 or tests_errors > 0:
        status = ValidationStatus.TESTS_FAILED
    else:
        status = ValidationStatus.TESTS_PASSED

    return ValidationEvidence(
        patch_id=patch.id,
        status=status,
        patch_applied=patch_applied,
        patch_failure_reason=patch_failure_reason,
        syntax_ok=syntax_ok,
        syntax_failure_file=syntax_failure_file,
        tests_collected=(tests_passed + tests_failed + tests_errors)
        if patch_applied and syntax_ok
        else None,
        tests_passed=tests_passed if patch_applied and syntax_ok else None,
        tests_failed=tests_failed if patch_applied and syntax_ok else None,
        tests_errors=tests_errors if patch_applied and syntax_ok else None,
        exit_code=exit_code,
        timeout=timed_out,
        failure_summary=failure_summary,
        workspace_created=workspace_created,
        workspace_cleaned=workspace_cleaned,
        workspace_path_hint=workspace_hint,
        duration_ms=duration_ms,
    )


def _now_ms() -> int:
    return int(time.monotonic() * 1000)
