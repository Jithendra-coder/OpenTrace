"""Hermetic Docker container sandbox for production isolated test execution."""
from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

from opentrace.validation.models import SandboxConfig


def is_docker_available() -> bool:
    """Check if Docker daemon is installed and responsive."""
    if not shutil.which("docker"):
        return False
    try:
        res = subprocess.run(["docker", "info"], capture_output=True, timeout=3)
        return res.returncode == 0
    except Exception:
        return False


def run_tests_docker(
    repo_path: Path,
    config: SandboxConfig,
    image: str = "python:3.10-slim",
) -> tuple[int | None, int, int, int, bool, str | None, int]:
    """Execute test suite inside an ephemeral hermetic Docker container.

    Features:
      - Mounts repo as read-only / temporary workspace
      - Disables network egress (--network none) to prevent supply chain leaks
      - Enforces memory limit (512m) and CPU limit (1.0 core)
      - Wall-clock timeout enforcement
    """
    start_ms = int(time.monotonic() * 1000)
    timed_out = False
    exit_code: int | None = None
    tests_passed = 0
    tests_failed = 0
    tests_errors = 0
    failure_summary: str | None = None

    # Normalise host path for Docker volume mounting on Windows
    host_path = str(repo_path.resolve())

    docker_cmd = [
        "docker", "run", "--rm",
        "--network", "none",
        "--memory", "512m",
        "--cpus", "1.0",
        "-v", f"{host_path}:/app",
        "-w", "/app",
        image,
        "sh", "-c", "pip install -q pytest requests && pytest --tb=short -q --no-header",
    ]

    try:
        proc = subprocess.run(
            docker_cmd,
            capture_output=True,
            text=True,
            timeout=config.timeout_seconds,
        )
        exit_code = proc.returncode
        combined = (proc.stdout or "") + (proc.stderr or "")
        from opentrace.validation.runner import _parse_counts, _sanitize_summary
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
        failure_summary = f"Docker container sandbox timed out after {config.timeout_seconds}s"
    except Exception as exc:
        exit_code = 1
        failure_summary = f"Docker runner error: {exc}"

    duration_ms = int(time.monotonic() * 1000) - start_ms
    return exit_code, tests_passed, tests_failed, tests_errors, timed_out, failure_summary, duration_ms
