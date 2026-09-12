"""Validation sandbox: ephemeral workspace creation, patch application, and cleanup."""

from __future__ import annotations

import ast
import shutil
import tempfile
import time
from pathlib import Path, PurePosixPath, PureWindowsPath

from opentrace.ai_migration.models import ProposedMigrationPatch
from opentrace.validation.models import SandboxConfig, ValidationStatus


# Files that must never be read from or written to in any sandbox workspace.
_SENSITIVE_FILE_NAMES = frozenset(
    {
        "credentials",
        "credentials.json",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "id_rsa",
        "known_hosts",
    }
)
_SENSITIVE_PARTS = frozenset({".aws", ".git", ".ssh", "credentials", "secrets"})
_SENSITIVE_SUFFIXES = frozenset({".key", ".pem", ".p12", ".pfx"})


def _is_safe_relative_path(raw: str) -> bool:
    """Return True only if raw resolves to a safe relative path.

    Rejects: absolute paths, path-traversal sequences, sensitive filenames,
    sensitive directory components, and sensitive file suffixes.
    """
    # Normalise platform separators before checking.
    try:
        posix = PurePosixPath(raw)
        win = PureWindowsPath(raw)
    except Exception:
        return False

    # Must not be absolute on either platform.
    if posix.is_absolute() or win.is_absolute():
        return False

    # Must not traverse upward.
    parts = posix.parts
    if ".." in parts:
        return False

    # Check every path component.
    for part in parts:
        part_lower = part.lower()
        if part_lower in _SENSITIVE_PARTS:
            return False

    # Check filename.
    name_lower = posix.name.lower()
    if name_lower in _SENSITIVE_FILE_NAMES:
        return False
    if posix.suffix.lower() in _SENSITIVE_SUFFIXES:
        return False

    return True


class _PatchApplicationError(Exception):
    pass


class _SyntaxCheckError(Exception):
    def __init__(self, file: str, message: str) -> None:
        self.file = file
        self.message = message
        super().__init__(message)


class SandboxWorkspace:
    """Ephemeral temp-directory workspace for one validation run.

    Usage::

        with SandboxWorkspace(repository_root, config) as ws:
            ws.apply_patch(patch)
            result = ws.check_syntax(patch)
            ...

    The temp directory is always deleted on __exit__, even on error.
    Cleanup is verified and recorded in the returned audit flags.
    """

    def __init__(self, repository_root: Path, config: SandboxConfig) -> None:
        self._root = repository_root.resolve()
        self._config = config
        self._workspace: Path | None = None
        self._created = False
        self._cleaned = False

    # ------------------------------------------------------------------ #
    # Context manager
    # ------------------------------------------------------------------ #

    def __enter__(self) -> SandboxWorkspace:
        self._workspace = Path(
            tempfile.mkdtemp(prefix="opentrace-sandbox-")
        )
        self._created = True
        # Copy the entire repository tree into the workspace.
        dest = self._workspace / "repo"
        shutil.copytree(self._root, dest, symlinks=False)
        return self

    def __exit__(self, *_: object) -> None:
        self._cleanup()

    def _cleanup(self) -> None:
        if self._workspace is not None and self._workspace.exists():
            shutil.rmtree(self._workspace, ignore_errors=True)
        # Verify deletion.
        self._cleaned = (
            self._workspace is None or not self._workspace.exists()
        )

    # ------------------------------------------------------------------ #
    # Patch application
    # ------------------------------------------------------------------ #

    def apply_patch(self, patch: ProposedMigrationPatch) -> None:
        """Apply all edits in the patch to the sandboxed repository copy.

        Raises _PatchApplicationError if any edit cannot be applied safely.
        """
        repo = self._workspace_repo()
        for edit in patch.edits:
            if not _is_safe_relative_path(edit.file):
                raise _PatchApplicationError(
                    f"edit targets an unsafe path: {edit.file!r}"
                )
            target = repo / edit.file
            if not target.exists():
                raise _PatchApplicationError(
                    f"target file does not exist in sandbox: {edit.file!r}"
                )
            # Resolve inside repo — must stay within sandbox.
            try:
                target.resolve().relative_to(repo.resolve())
            except ValueError:
                raise _PatchApplicationError(
                    f"resolved path escapes sandbox: {edit.file!r}"
                )
            content = target.read_text(encoding="utf-8", errors="replace")
            if edit.expected_original_text not in content:
                raise _PatchApplicationError(
                    f"expected original text not found in {edit.file!r} (Stale Baseline Drift: file has changed on disk since analysis was created. Run 'opentrace analyze' to re-sync)."
                )
            content = content.replace(
                edit.expected_original_text, edit.replacement_text, 1
            )
            target.write_text(content, encoding="utf-8", newline="\n")

    # ------------------------------------------------------------------ #
    # Syntax validation
    # ------------------------------------------------------------------ #

    def check_syntax(self, patch: ProposedMigrationPatch) -> None:
        """Run ast.parse on each edited .py file.

        Raises _SyntaxCheckError on the first file that fails.
        """
        repo = self._workspace_repo()
        seen: set[str] = set()
        for edit in patch.edits:
            if edit.file in seen:
                continue
            seen.add(edit.file)
            if not edit.file.endswith(".py"):
                continue
            target = repo / edit.file
            if not target.exists():
                continue
            source = target.read_text(encoding="utf-8", errors="replace")
            try:
                ast.parse(source, filename=edit.file)
            except SyntaxError as exc:
                raise _SyntaxCheckError(
                    file=edit.file,
                    message=f"SyntaxError in {edit.file}: {exc}",
                )

    # ------------------------------------------------------------------ #
    # Accessors
    # ------------------------------------------------------------------ #

    @property
    def repo_path(self) -> Path:
        return self._workspace_repo()

    @property
    def workspace_created(self) -> bool:
        return self._created

    @property
    def workspace_cleaned(self) -> bool:
        return self._cleaned

    @property
    def workspace_path_hint(self) -> str | None:
        """Last 8 hex characters of the temp path name — for audit only."""
        if self._workspace is None:
            return None
        return self._workspace.name[-8:]

    def _workspace_repo(self) -> Path:
        if self._workspace is None:
            raise RuntimeError("SandboxWorkspace not entered")
        return self._workspace / "repo"


def apply_patch_to_sandbox(
    repository_root: Path,
    patch: ProposedMigrationPatch,
    config: SandboxConfig,
) -> tuple[bool, str | None, bool | None, str | None, str | None, bool, bool]:
    """Apply patch and syntax-check inside a fresh sandbox.

    Returns:
        patch_applied, patch_failure_reason,
        syntax_ok, syntax_failure_file,
        workspace_path_hint, workspace_created, workspace_cleaned
    """
    try:
        with SandboxWorkspace(repository_root, config) as ws:
            patch_applied = False
            patch_failure_reason: str | None = None
            syntax_ok: bool | None = None
            syntax_failure_file: str | None = None

            try:
                ws.apply_patch(patch)
                patch_applied = True
            except _PatchApplicationError as exc:
                patch_failure_reason = str(exc)
                return (
                    False,
                    patch_failure_reason,
                    None,
                    None,
                    ws.workspace_path_hint,
                    ws.workspace_created,
                    ws.workspace_cleaned,
                )

            try:
                ws.check_syntax(patch)
                syntax_ok = True
            except _SyntaxCheckError as exc:
                syntax_ok = False
                syntax_failure_file = exc.file
                return (
                    patch_applied,
                    None,
                    False,
                    syntax_failure_file,
                    ws.workspace_path_hint,
                    ws.workspace_created,
                    ws.workspace_cleaned,
                )

            return (
                patch_applied,
                None,
                syntax_ok,
                None,
                ws.workspace_path_hint,
                ws.workspace_created,
                ws.workspace_cleaned,
            )
    except Exception as exc:
        return False, f"sandbox error: {exc}", None, None, None, False, False
