"""M16 runner: subprocess pytest execution with timeout inside sandbox workspace."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from opentrace.validation.models import SandboxConfig


def run_tests(
    repo_path: Path,
    config: SandboxConfig,
) -> tuple[int | None, int, int, int, bool, str | None, int]:
    """Run pytest inside the sandboxed repo copy.

    Args:
        repo_path: The resolved path to the sandboxed repository copy.
        config: Sandbox configuration (timeout, summary limits).

    Returns:
        exit_code, tests_passed, tests_failed, tests_errors,
        timed_out, failure_summary, duration_ms
    """
    start_ms = _now_ms()
    timed_out = False
    exit_code: int | None = None
    tests_passed = 0
    tests_failed = 0
    tests_errors = 0
    failure_summary: str | None = None

    # Check if Docker sandbox isolation is requested and available
    import os
    if os.environ.get("OPENTRACE_SANDBOX_MODE") == "docker":
        from opentrace.validation.docker_sandbox import is_docker_available, run_tests_docker
        if is_docker_available():
            return run_tests_docker(repo_path, config)

    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "--tb=short",
                "-q",
                "--no-header",
                # Note: --timeout=30 requires pytest-timeout; omitted for
                # compatibility. Wall-clock timeout is enforced by subprocess.
            ],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=config.timeout_seconds,
        )
        exit_code = result.returncode
        combined = (result.stdout or "") + (result.stderr or "")
        tests_passed, tests_failed, tests_errors = _parse_counts(combined)
        if exit_code != 0:
            failure_summary = _sanitize_summary(
                combined,
                config.max_failure_summary_lines,
                config.max_failure_summary_line_chars,
            )
    except subprocess.TimeoutExpired:
        timed_out = True
        exit_code = None
    except Exception as exc:
        exit_code = -1
        failure_summary = _sanitize_summary(
            str(exc),
            config.max_failure_summary_lines,
            config.max_failure_summary_line_chars,
        )

    duration_ms = _now_ms() - start_ms
    return (
        exit_code,
        tests_passed,
        tests_failed,
        tests_errors,
        timed_out,
        failure_summary,
        duration_ms,
    )


def _now_ms() -> int:
    return int(time.monotonic() * 1000)


def _parse_counts(output: str) -> tuple[int, int, int]:
    """Parse pytest summary line like '3 passed, 1 failed, 0 errors'."""
    passed = 0
    failed = 0
    errors = 0
    for line in output.splitlines():
        line_lower = line.lower()
        # Look for the final summary line produced by pytest.
        if "passed" in line_lower or "failed" in line_lower or "error" in line_lower:
            import re

            for match in re.finditer(r"(\d+)\s+(passed|failed|error)", line_lower):
                count = int(match.group(1))
                kind = match.group(2)
                if kind == "passed":
                    passed = count
                elif kind == "failed":
                    failed = count
                elif kind == "error":
                    errors = count
    return passed, failed, errors


def _sanitize_summary(
    raw: str,
    max_lines: int,
    max_line_chars: int,
) -> str:
    """Truncate and sanitize subprocess output for the failure summary.

    Strips potential secrets by removing lines that look like env-var
    assignments or token-like strings, then truncates to configured limits.
    """
    lines = raw.splitlines()
    sanitized: list[str] = []
    for line in lines:
        # Skip lines that look like environment variable leakage.
        stripped = line.strip()
        if "=" in stripped and any(
            kw in stripped.upper()
            for kw in ("TOKEN", "SECRET", "PASSWORD", "KEY", "CREDENTIAL", "API_KEY")
        ):
            sanitized.append("[REDACTED]")
            continue
        sanitized.append(line[:max_line_chars])

    # Take last N lines — those are most relevant for pytest failures.
    trimmed = sanitized[-max_lines:]
    return "\n".join(trimmed)
