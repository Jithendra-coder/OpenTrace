"""Validation models: ValidationEvidence, ValidationStatus, SandboxConfig."""

from __future__ import annotations

import json
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


VALIDATION_SCHEMA_VERSION = "validation-evidence-v1"
SANDBOX_CONFIG_VERSION = "sandbox-config-v1"


class CanonicalModel(BaseModel):
    """Frozen, inspectable validation artifacts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    def canonical_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json", exclude_none=True),
            sort_keys=True,
            separators=(",", ":"),
        )


class ValidationStatus(StrEnum):
    # Patch applied cleanly and all collected tests passed.
    TESTS_PASSED = "TESTS_PASSED"
    # Patch applied but one or more tests failed.
    TESTS_FAILED = "TESTS_FAILED"
    # Patch applied but no tests were collected.
    NO_TESTS_COLLECTED = "NO_TESTS_COLLECTED"
    # Patch application failed — file not found or precondition mismatch.
    PATCH_FAILED = "PATCH_FAILED"
    # Edited file(s) have a syntax error after patch application.
    SYNTAX_ERROR = "SYNTAX_ERROR"
    # Subprocess exceeded the configured timeout.
    TIMEOUT = "TIMEOUT"
    # Subprocess returned a non-zero exit code for a non-test reason
    # (import error, missing dependency, etc.).
    RUNNER_ERROR = "RUNNER_ERROR"
    # Sandbox setup or teardown failed (workspace could not be created/destroyed).
    SANDBOX_ERROR = "SANDBOX_ERROR"


class SandboxConfig(CanonicalModel):
    """Configurable limits for an isolated validation run."""

    version: str = SANDBOX_CONFIG_VERSION
    # Maximum wall-clock seconds for the subprocess.
    timeout_seconds: int = Field(default=60, ge=5, le=300)
    # Maximum number of lines in the sanitized failure summary.
    max_failure_summary_lines: int = Field(default=50, ge=1, le=500)
    # Maximum characters per failure summary line.
    max_failure_summary_line_chars: int = Field(default=200, ge=40, le=2000)


class ValidationEvidence(CanonicalModel):
    """Structured, immutable evidence from one isolated validation run.

    Matches the validation spec output contract:
      patch_applied, syntax_ok, tests_collected, tests_passed,
      tests_failed, timeout, exit_code, failure_summary.

    Additional audit fields: schema_version, patch_id,
    workspace_created, workspace_cleaned, duration_ms, status,
    sandbox_config_version, limitations.
    """

    schema_version: str = VALIDATION_SCHEMA_VERSION
    patch_id: str
    status: ValidationStatus

    # Patch application
    patch_applied: bool
    patch_failure_reason: str | None = None

    # Syntax check (ast.parse on each edited file)
    syntax_ok: bool | None = None
    syntax_failure_file: str | None = None

    # Test execution
    tests_collected: int | None = None
    tests_passed: int | None = None
    tests_failed: int | None = None
    tests_errors: int | None = None
    exit_code: int | None = None
    timeout: bool = False
    failure_summary: str | None = None

    # Workspace audit
    workspace_created: bool = False
    workspace_cleaned: bool = False
    workspace_path_hint: str | None = None  # last 8 chars of temp path only

    # Timing
    duration_ms: int | None = Field(default=None, ge=0)

    # Documented limitation for V1 (subprocess, not Docker)
    limitations: tuple[str, ...] = (
        "V1: subprocess isolation in temp directory — not Docker-isolated. "
        "Not suitable for untrusted repository code without container boundary.",
    )

    @model_validator(mode="after")
    def status_is_consistent(self) -> ValidationEvidence:
        if self.status is ValidationStatus.TESTS_PASSED:
            if not self.patch_applied or not self.syntax_ok:
                raise ValueError("TESTS_PASSED requires patch_applied and syntax_ok")
            if self.tests_failed is not None and self.tests_failed > 0:
                raise ValueError("TESTS_PASSED cannot have tests_failed > 0")
        if self.status is ValidationStatus.PATCH_FAILED and self.patch_applied:
            raise ValueError("PATCH_FAILED must have patch_applied=False")
        if self.status is ValidationStatus.TIMEOUT and not self.timeout:
            raise ValueError("TIMEOUT status requires timeout=True")
        return self
