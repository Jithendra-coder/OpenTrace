from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from opentrace.cli.commands import apply, validate as validate_command
from opentrace.validation.models import (
    SandboxConfig,
    ValidationEvidence,
    ValidationStatus,
    patch_data_checksum,
)


def _passing_evidence(patch_data: dict | None = None) -> dict[str, object]:
    return {
        "schema_version": "validation-result-v1",
        "status": "TESTS_PASSED",
        "patch_id": "test",
        "patch_checksum": patch_data_checksum(patch_data or {}),
        "patch_applied": True,
        "syntax_ok": True,
        "tests_collected": 1,
        "tests_passed": 1,
        "tests_failed": 0,
        "tests_errors": 0,
        "exit_code": 0,
        "timeout": False,
        "workspace_created": True,
        "workspace_cleaned": True,
    }


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
        lambda path: plan
        if path.name == "migration-plan.json"
        else _passing_evidence(plan["patch"]),
    )
    monkeypatch.setattr(apply, "migration_plan_path", lambda _: tmp_path / "migration-plan.json")
    monkeypatch.setattr(
        apply, "validation_result_path", lambda _: tmp_path / "validation-result.json"
    )

    with pytest.raises(SystemExit):
        apply.run_apply(tmp_path / "workspace", yes=True)

    assert first_file.read_text(encoding="utf-8") == "value = 'old'\n"
    assert outside_file.read_text(encoding="utf-8") == "value = 'outside'\n"


@pytest.mark.parametrize(
    "evidence",
    [
        {"status": "UNKNOWN"},
        {"patch_id": "stale-patch"},
        {"status": "TESTS_FAILED"},
        {"tests_collected": 0, "tests_passed": 0},
        {"tests_collected": 2},
        {"workspace_cleaned": False},
        {"timeout": True},
    ],
)
def test_apply_refuses_incomplete_or_stale_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, evidence: dict[str, object]
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / "safe.py"
    target.write_text("value = 'old'\n", encoding="utf-8")
    plan = {
        "repo": str(repo),
        "patch": {
            "id": "test",
            "edits": [
                {"file": "safe.py", "expected_original_text": "old", "replacement_text": "new"}
            ],
        },
    }
    monkeypatch.setattr(apply, "migration_plan_exists", lambda _: True)
    monkeypatch.setattr(
        apply,
        "read_json",
        lambda path: plan
        if path.name == "migration-plan.json"
        else {**_passing_evidence(plan["patch"]), **evidence},
    )
    monkeypatch.setattr(apply, "migration_plan_path", lambda _: tmp_path / "migration-plan.json")
    monkeypatch.setattr(apply, "validation_result_path", lambda _: tmp_path / "validation.json")

    with pytest.raises(SystemExit):
        apply.run_apply(tmp_path / "workspace", yes=True)

    assert target.read_text(encoding="utf-8") == "value = 'old'\n"


def test_apply_accepts_complete_evidence_for_exact_patch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / "safe.py"
    target.write_text("value = 'old'\n", encoding="utf-8")
    plan = {
        "repo": str(repo),
        "patch": {
            "id": "test",
            "edits": [
                {"file": "safe.py", "expected_original_text": "old", "replacement_text": "new"}
            ],
        },
    }
    monkeypatch.setattr(apply, "migration_plan_exists", lambda _: True)
    monkeypatch.setattr(
        apply,
        "read_json",
        lambda path: plan
        if path.name == "migration-plan.json"
        else _passing_evidence(plan["patch"]),
    )
    monkeypatch.setattr(apply, "migration_plan_path", lambda _: tmp_path / "migration-plan.json")
    monkeypatch.setattr(apply, "validation_result_path", lambda _: tmp_path / "validation.json")
    monkeypatch.setattr(apply, "_write_feedback", lambda *args, **kwargs: None)

    apply.run_apply(tmp_path / "workspace", yes=True)

    assert target.read_text(encoding="utf-8") == "value = 'new'\n"


def test_apply_rejects_a_plan_changed_after_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / "safe.py"
    target.write_text("value = 'old'\n", encoding="utf-8")
    original_patch = {
        "id": "test",
        "edits": [
            {"file": "safe.py", "expected_original_text": "old", "replacement_text": "new"}
        ],
    }
    plan = {"repo": str(repo), "patch": original_patch}
    evidence = _passing_evidence(original_patch)
    plan["patch"] = {
        **original_patch,
        "edits": [
            {"file": "safe.py", "expected_original_text": "old", "replacement_text": "evil"}
        ],
    }
    monkeypatch.setattr(apply, "migration_plan_exists", lambda _: True)
    monkeypatch.setattr(
        apply,
        "read_json",
        lambda path: plan if path.name == "migration-plan.json" else evidence,
    )
    monkeypatch.setattr(apply, "migration_plan_path", lambda _: tmp_path / "migration-plan.json")
    monkeypatch.setattr(apply, "validation_result_path", lambda _: tmp_path / "validation.json")

    with pytest.raises(SystemExit):
        apply.run_apply(tmp_path / "workspace", yes=True)

    assert target.read_text(encoding="utf-8") == "value = 'old'\n"


def test_validate_persists_complete_apply_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    patch_data = {
        "id": "test",
        "edits": [
            {
                "id": "edit-1",
                "file": "safe.py",
                "start_line": 1,
                "end_line": 1,
                "original_text_hash": "x" * 64,
                "expected_original_text": "old",
                "replacement_text": "new",
                "reason": "test patch",
            }
        ],
    }
    plan = {"repo": str(tmp_path), "patch": patch_data}
    evidence = ValidationEvidence(
        patch_id="test",
        status=ValidationStatus.TESTS_PASSED,
        patch_applied=True,
        syntax_ok=True,
        tests_collected=2,
        tests_passed=2,
        tests_failed=0,
        tests_errors=0,
        exit_code=0,
        workspace_created=True,
        workspace_cleaned=True,
    )
    output = tmp_path / "workspace" / "validation-result.json"
    monkeypatch.setattr(validate_command, "migration_plan_exists", lambda _: True)
    monkeypatch.setattr(validate_command, "migration_plan_path", lambda _: tmp_path / "plan.json")
    monkeypatch.setattr(validate_command, "validation_result_path", lambda _: output)
    monkeypatch.setattr(validate_command, "read_json", lambda _: plan)
    monkeypatch.setattr(validate_command, "validate_patch", lambda *args: evidence)

    validate_command.run_validate(tmp_path / "workspace", timeout=60)

    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["schema_version"] == "validation-result-v1"
    assert result["patch_checksum"] == patch_data_checksum(patch_data)
    assert result["tests_errors"] == 0


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
