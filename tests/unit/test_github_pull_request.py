"""GitHub PR integration tests — git helpers, PR template, CLI --dry-run."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from opentrace.github.client import GitHubClient, GitHubClientError
from opentrace.github.git import (
    GitError,
    apply_edits_to_working_tree,
    find_git_root,
    parse_github_owner_repo,
    stage_and_commit,
)
from opentrace.github.pr_template import build_pr_body, build_pr_title

ROOT = Path(__file__).parents[2]


# ---------------------------------------------------------------------------
# parse_github_owner_repo
# ---------------------------------------------------------------------------


def test_parse_https_url() -> None:
    owner, repo = parse_github_owner_repo("https://github.com/acme/my-repo.git")
    assert owner == "acme"
    assert repo == "my-repo"


def test_parse_https_url_without_git_suffix() -> None:
    owner, repo = parse_github_owner_repo("https://github.com/acme/my-repo")
    assert owner == "acme"
    assert repo == "my-repo"


def test_parse_ssh_url() -> None:
    owner, repo = parse_github_owner_repo("git@github.com:acme/my-repo.git")
    assert owner == "acme"
    assert repo == "my-repo"


def test_parse_unknown_url_raises() -> None:
    with pytest.raises(GitError, match="Cannot parse GitHub owner/repo"):
        parse_github_owner_repo("https://gitlab.com/acme/repo.git")


# ---------------------------------------------------------------------------
# find_git_root
# ---------------------------------------------------------------------------


def test_find_git_root_from_nested_dir(tmp_path: Path) -> None:
    """find_git_root walks up to locate the .git directory."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    nested_dir = tmp_path / "src" / "pkg" / "sub"
    nested_dir.mkdir(parents=True)
    root = find_git_root(nested_dir)
    assert (root / ".git").exists()
    assert root == tmp_path


def test_find_git_root_from_non_git_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(GitError, match="No git repository found"):
        find_git_root(tmp_path)


# ---------------------------------------------------------------------------
# apply_edits_to_working_tree (on tmp copy)
# ---------------------------------------------------------------------------


def _make_repo(tmp_path: Path) -> Path:
    """Create a minimal temp directory with a Python file."""
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / "service.py"
    target.write_text(
        "def call_api(amount):\n    return requests.post('/v1/pay', json={'amount': amount})\n",
        encoding="utf-8",
    )
    return repo


def test_apply_edits_modifies_file(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    original_text = "return requests.post('/v1/pay', json={'amount': amount})"
    replacement_text = "return requests.post('/v2/pay', json={'amount': amount, 'currency': 'USD'})"

    edits = [
        {
            "file": "service.py",
            "expected_original_text": original_text,
            "replacement_text": replacement_text,
        }
    ]
    modified = apply_edits_to_working_tree(repo, edits)

    assert "service.py" in modified
    content = (repo / "service.py").read_text(encoding="utf-8")
    assert replacement_text in content
    assert original_text not in content


def test_apply_edits_precondition_mismatch_raises(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    edits = [
        {
            "file": "service.py",
            "expected_original_text": "NONEXISTENT_TEXT_THAT_IS_NOT_IN_THE_FILE",
            "replacement_text": "replacement",
        }
    ]
    with pytest.raises(GitError, match="Precondition mismatch"):
        apply_edits_to_working_tree(repo, edits)


def test_apply_edits_missing_file_raises(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    edits = [
        {
            "file": "does_not_exist.py",
            "expected_original_text": "x",
            "replacement_text": "y",
        }
    ]
    with pytest.raises(GitError, match="File not found"):
        apply_edits_to_working_tree(repo, edits)


# ---------------------------------------------------------------------------
# GitHubClient — token checks
# ---------------------------------------------------------------------------


def test_github_client_from_env_raises_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(GitHubClientError, match="GITHUB_TOKEN"):
        GitHubClient.from_env()


def test_github_client_from_env_raises_empty_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "   ")
    with pytest.raises(GitHubClientError, match="GITHUB_TOKEN"):
        GitHubClient.from_env()


def test_github_client_constructed_with_token() -> None:
    client = GitHubClient("ghp_fake_token_for_unit_test")
    assert client._token == "ghp_fake_token_for_unit_test"


# ---------------------------------------------------------------------------
# PR template
# ---------------------------------------------------------------------------


_ANALYSIS = {
    "changes": [
        {
            "method": "post",
            "path": "/payments",
            "change_type": "BREAKING",
            "field": "tax_id",
        }
    ],
    "direct_count": 1,
    "indirect_count": 0,
}

_PATCH = {
    "id": "proposed-patch-abc123",
    "selected_strategy": "SMALL",
    "provider_adapter_id": "deterministic-fake-v1",
    "model_id": "small-model",
    "generation_fingerprint": "fp-abc",
    "explanation": "Adds the missing currency field.",
    "warnings": [],
    "edits": [
        {
            "file": "payment_service.py",
            "symbol": "create_payment",
            "reason": "Add currency field to POST /v2/payments body.",
        }
    ],
}

_PLAN = {"policy": "balanced", "warnings": []}

_VALIDATION = {
    "status": "TESTS_PASSED",
    "patch_applied": True,
    "syntax_ok": True,
    "tests_passed": 5,
    "tests_failed": 0,
    "duration_ms": 1234,
    "limitations": [],
}


def test_pr_title_single_change() -> None:
    title = build_pr_title(_ANALYSIS["changes"], _PATCH)
    assert "POST /payments" in title
    assert "SMALL" in title
    assert "[OpenTrace]" in title


def test_pr_title_multiple_changes() -> None:
    changes = [_ANALYSIS["changes"][0], _ANALYSIS["changes"][0]]
    title = build_pr_title(changes, _PATCH)
    assert "2 API changes" in title


def test_pr_body_contains_required_sections() -> None:
    body = build_pr_body(_ANALYSIS, _PLAN, _VALIDATION, _PATCH, "abc123def456", "opentrace/migration-x")

    assert "Human review" in body
    assert "POST /payments" in body
    assert "BREAKING" in body
    assert "SMALL" in body
    assert "TESTS_PASSED" in body
    assert "proposed-patch-abc123" in body
    assert "abc123def" in body  # truncated commit SHA
    assert "auto-merge" in body.lower()  # must mention auto-merge prohibition


def test_pr_body_without_validation() -> None:
    body = build_pr_body(_ANALYSIS, _PLAN, None, _PATCH, "deadbeef", "opentrace/migration-x")
    assert "Validation was not run" in body


def test_pr_body_never_auto_merge_note_always_present() -> None:
    """The anti-auto-merge note must appear in every PR body."""
    body = build_pr_body(_ANALYSIS, _PLAN, _VALIDATION, _PATCH, "sha123", "branch")
    # Both the warning text and draft labeling must be present.
    assert "not" in body.lower()
    assert "auto-merge" in body.lower() or "auto merge" in body.lower()


# ---------------------------------------------------------------------------
# CLI --dry-run test (no git ops, no GitHub API)
# ---------------------------------------------------------------------------


def test_pr_dry_run_exits_zero(tmp_path: Path) -> None:
    """--dry-run must print what would happen and exit 0 without making any changes."""
    import subprocess, sys

    # Write minimal workspace artifacts.
    ws = tmp_path
    cm_dir = ws / ".opentrace"
    cm_dir.mkdir()

    analysis = {
        "schema_version": "analysis-v1",
        "old_spec": "old.yaml",
        "new_spec": "new.yaml",
        "repo": str(tmp_path),
        "changes_count": 1,
        "direct_count": 1,
        "indirect_count": 0,
        "changes": [{"method": "post", "path": "/payments", "change_type": "BREAKING", "field": "tax_id", "change_id": "c1"}],
        "direct_impacts": [],
    }
    (cm_dir / "analysis.json").write_text(json.dumps(analysis), encoding="utf-8")

    plan = {
        "schema_version": "migration-plan-v1",
        "policy": "balanced",
        "ai_enabled": False,
        "generation_status": "GENERATED",
        "routing_decision_id": "cli-decision",
        "selected_strategy": "SMALL",
        "repo": str(tmp_path),
        "old_spec": "old.yaml",
        "new_spec": "new.yaml",
        "patch": {
            "id": "patch-abc",
            "selected_strategy": "SMALL",
            "provider_adapter_id": "deterministic-fake-v1",
            "model_id": "small-model",
            "generation_fingerprint": "fp",
            "explanation": "test",
            "warnings": [],
            "edits": [
                {
                    "id": "e1",
                    "file": "service.py",
                    "symbol": "func",
                    "start_line": 1,
                    "end_line": 2,
                    "original_text_hash": "x" * 64,
                    "expected_original_text": "old text",
                    "replacement_text": "new text",
                    "reason": "migrate",
                }
            ],
        },
        "failure": None,
        "warnings": [],
    }
    (cm_dir / "migration-plan.json").write_text(json.dumps(plan), encoding="utf-8")

    # The --dry-run flag must cause the command to exit 0 without touching git or GitHub.
    # It will fail at find_git_root (tmp_path has no .git) unless --dry-run skips git ops.
    result = subprocess.run(
        [sys.executable, "-m", "opentrace.cli.main", "pr",
         "--workspace", str(ws), "--dry-run"],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
        cwd=str(ROOT),
    )

    assert result.returncode == 0, f"--dry-run failed:\n{result.stdout}\n{result.stderr}"
    assert "Dry Run" in result.stdout or "dry" in result.stdout.lower()
