"""Git subprocess helpers for OpenTrace PR workflow."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


class GitError(Exception):
    pass


def _git(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if check and result.returncode != 0:
        raise GitError(
            f"git {args[0]} failed (exit {result.returncode}):\n"
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return result


def find_git_root(start: Path) -> Path:
    """Walk up from start to find the .git directory. Raises GitError if not found."""
    current = start.resolve()
    while True:
        if (current / ".git").exists():
            return current
        parent = current.parent
        if parent == current:
            raise GitError(
                f"No git repository found at or above: {start}\n"
                "Ensure the repository is a git repo before using  opentrace pr."
            )
        current = parent


def get_remote_url(repo_root: Path) -> str:
    """Return the 'origin' remote URL."""
    result = _git(["remote", "get-url", "origin"], repo_root)
    return result.stdout.strip()


def parse_github_owner_repo(remote_url: str) -> tuple[str, str]:
    """Parse owner/repo from a GitHub remote URL (HTTPS or SSH).

    Supports:
      https://github.com/owner/repo.git
      git@github.com:owner/repo.git
    """
    url = remote_url.strip().removesuffix(".git")
    if url.startswith("https://github.com/"):
        parts = url.removeprefix("https://github.com/").split("/")
    elif url.startswith("git@github.com:"):
        parts = url.removeprefix("git@github.com:").split("/")
    else:
        raise GitError(
            f"Cannot parse GitHub owner/repo from remote URL: {remote_url!r}\n"
            "Only GitHub HTTPS (https://github.com/...) and SSH (git@github.com:...) "
            "remotes are supported."
        )
    if len(parts) < 2:
        raise GitError(f"Unexpected remote URL format: {remote_url!r}")
    return parts[0], parts[1]


def current_branch(repo_root: Path) -> str:
    result = _git(["rev-parse", "--abbrev-ref", "HEAD"], repo_root)
    return result.stdout.strip()


def create_branch(repo_root: Path, branch_name: str) -> None:
    """Create and check out a new branch from current HEAD."""
    _git(["checkout", "-b", branch_name], repo_root)


def apply_edits_to_working_tree(
    repo_root: Path,
    edits: list[dict],
) -> list[str]:
    """Apply patch edits to the real working tree files.

    Returns list of modified file paths (relative to repo_root).
    Raises GitError if a precondition is not met.
    """
    modified: list[str] = []
    for edit in edits:
        file = edit["file"]
        target = repo_root / file
        if not target.exists():
            raise GitError(f"File not found in repository: {file}")
        content = target.read_text(encoding="utf-8", errors="replace")
        original = edit["expected_original_text"]
        replacement = edit["replacement_text"]
        if original not in content:
            raise GitError(
                f"Precondition mismatch in {file}: "
                "expected_original_text not found. "
                "Re-run  opentrace analyze && opentrace migrate  to regenerate the patch."
            )
        new_content = content.replace(original, replacement, 1)
        target.write_text(new_content, encoding="utf-8", newline="\n")
        modified.append(file)
    return modified


def stage_and_commit(
    repo_root: Path,
    files: list[str],
    message: str,
) -> str:
    """Stage specific files and commit. Returns the commit SHA."""
    _git(["add", "--", *files], repo_root)
    _git(["commit", "-m", message], repo_root)
    result = _git(["rev-parse", "HEAD"], repo_root)
    return result.stdout.strip()


def push_branch(repo_root: Path, branch_name: str) -> None:
    """Push branch to origin."""
    _git(["push", "origin", branch_name], repo_root)


def restore_files(repo_root: Path, files: list[str]) -> None:
    """Restore files from HEAD (undo working tree changes) — used on error."""
    try:
        _git(["checkout", "HEAD", "--", *files], repo_root, check=False)
    except Exception:
        pass


def delete_local_branch(repo_root: Path, branch: str, original_branch: str) -> None:
    """Switch back to original_branch and delete the PR branch — used on error."""
    try:
        _git(["checkout", original_branch], repo_root, check=False)
        _git(["branch", "-D", branch], repo_root, check=False)
    except Exception:
        pass
