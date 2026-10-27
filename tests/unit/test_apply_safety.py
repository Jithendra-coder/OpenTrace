from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from opentrace.cli.commands import apply
from opentrace.validation.models import SandboxConfig


@pytest.mark.parametrize("unsafe_path", ("../outside.py", "..\\outside.py", "C:\\outside.py"))
def test_apply_rejects_paths_outside_repo_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unsafe_path: str
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    first_file = repo / "safe.py"
    outside_file = tmp_path / "outside.py"
    first_file.write_text("value = 'old'\n", encoding="utf-8")
    outside_file.write_text("value = 'outside'\n", encoding="utf-8")
    plan = {
        "repo": str(repo),
        "patch": {
            "id": "test",
            "edits": [
                {"file": "safe.py", "expected_original_text": "old", "replacement_text": "new"},
                {
                    "file": unsafe_path,
                    "expected_original_text": "outside",
                    "replacement_text": "changed",
                },
            ],
        },
    }
    monkeypatch.setattr(apply, "migration_plan_exists", lambda _: True)
    monkeypatch.setattr(
        apply,
        "read_json",
        lambda path: plan if path.name == "migration-plan.json" else {"status": "TESTS_PASSED"},
    )
    monkeypatch.setattr(apply, "migration_plan_path", lambda _: tmp_path / "migration-plan.json")
    monkeypatch.setattr(
        apply, "validation_result_path", lambda _: tmp_path / "validation-result.json"
    )

    with pytest.raises(SystemExit):
        apply.run_apply(tmp_path / "workspace", yes=True)

    assert first_file.read_text(encoding="utf-8") == "value = 'old'\n"
    assert outside_file.read_text(encoding="utf-8") == "value = 'outside'\n"


def test_runner_refuses_host_fallback_without_docker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from opentrace.validation import docker_sandbox, runner

    monkeypatch.delenv("OPENTRACE_SANDBOX_MODE", raising=False)
    monkeypatch.setattr(docker_sandbox, "is_docker_available", lambda: False)

    result = runner.run_tests(tmp_path, SandboxConfig())

    assert result[0] == 1
    assert "Docker is required" in (result[5] or "")


def test_docker_runner_uses_networkless_container_and_read_only_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from opentrace.validation import docker_sandbox

    calls: list[list[str]] = []
    monkeypatch.setattr(docker_sandbox, "_ensure_test_image", lambda _: True)

    def fake_run(command: list[str], **_: object) -> SimpleNamespace:
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="1 passed", stderr="")

    monkeypatch.setattr(docker_sandbox.subprocess, "run", fake_run)
    result = docker_sandbox.run_tests_docker(tmp_path, SandboxConfig())
    command = calls[0]

    assert result[0] == 0
    assert "--network" in command and command[command.index("--network") + 1] == "none"
    assert "--read-only" in command
    assert any(argument.endswith("target=/input,readonly") for argument in command)
