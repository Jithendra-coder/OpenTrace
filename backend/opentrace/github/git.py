"""Git subprocess helpers for OpenTrace PR workflow."""

from __future__ import annotations

import subprocess
from pathlib import Path

from opentrace.validation.sandbox import is_safe_relative_path


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


def working_tree_is_clean(repo_root: Path) -> bool:
    """Return whether tracked and untracked files are all committed."""
    return not _git(
        ["status", "--porcelain", "--untracked-files=all"], repo_root
    ).stdout.strip()


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
    root = repo_root.resolve()
    prepared: dict[Path, tuple[str, str]] = {}
    display_paths: dict[Path, str] = {}
    for edit in edits:
        try:
            file = edit["file"]
        except (KeyError, TypeError) as exc:
            raise GitError("Patch edit is missing its file path") from exc
        if not isinstance(file, str) or not is_safe_relative_path(file):
            raise GitError(f"Refusing to modify an unsafe repository path: {file}")
        normalized = file.replace("\\", "/")
        try:
            target = (root / Path(normalized)).resolve()
        except (OSError, RuntimeError, ValueError) as exc:
            raise GitError(f"Invalid repository path: {file}") from exc
        if target == root or not target.is_relative_to(root):
            raise GitError(f"Refusing to modify a path outside the repository: {file}")
        if not target.is_file():
            raise GitError(f"File not found in repository: {file}")
        try:
            if target in prepared:
                content, original_content = prepared[target]
            else:
                content = target.read_text(encoding="utf-8", errors="replace")
                original_content = content
            original = edit["expected_original_text"]
            replacement = edit["replacement_text"]
        except (KeyError, OSError, TypeError) as exc:
            raise GitError(f"Invalid edit or unreadable file: {file}") from exc
        if original not in content:
            raise GitError(
                f"Precondition mismatch in {file}: "
                "expected_original_text not found. "
                "Re-run  opentrace analyze && opentrace migrate  to regenerate the patch."
            )
        prepared[target] = (
            content.replace(original, replacement, 1),
            original_content,
        )
        display_paths[target] = file

    written: list[Path] = []
    try:
        for target, (content, _) in prepared.items():
            written.append(target)
            target.write_text(content, encoding="utf-8", newline="\n")
    except OSError as exc:
        for target in written:
            try:
                target.write_text(
                    prepared[target][1], encoding="utf-8", newline="\n"
                )
            except OSError:
                pass
        raise GitError(f"Could not write the patch to the working tree: {exc}") from exc
    return [display_paths[target] for target in prepared]


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
