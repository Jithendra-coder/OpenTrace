"""Deterministic, non-executing Python repository analysis."""

import hashlib
from pathlib import Path

from opentrace.code_analysis.ast_parser import parse_source
from opentrace.code_analysis.models import (
    APICallSite,
    CodeSymbol,
    FileAnalysisState,
    RepositoryAnalysis,
    RepositoryFile,
)

_EXCLUDED_DIRECTORIES = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "build",
        "dist",
    }
)


def discover_python_files(root: Path | str) -> tuple[Path, ...]:
    """Return in-boundary Python files in deterministic repository-relative order."""
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError(f"repository root is not a directory: {root}")
    files: list[Path] = []
    for path in root.rglob("*.py"):
        if path.is_symlink() or any(
            part in _EXCLUDED_DIRECTORIES for part in path.relative_to(root).parts
        ):
            continue
        files.append(path)
    return tuple(sorted(files, key=lambda path: path.relative_to(root).as_posix()))


def discover_source_files(root: Path | str) -> tuple[Path, ...]:
    """Return in-boundary Python and TypeScript/JavaScript source files."""
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError(f"repository root is not a directory: {root}")
    files: list[Path] = []
    for ext in ("*.py", "*.ts", "*.tsx", "*.js", "*.jsx"):
        for path in root.rglob(ext):
            if path.is_symlink() or any(
                part in _EXCLUDED_DIRECTORIES for part in path.relative_to(root).parts
            ):
                continue
            files.append(path)
    return tuple(sorted(set(files), key=lambda path: path.relative_to(root).as_posix()))


class RepositoryAnalyzer:
    """Analyze Python syntax only; no repository module is imported or executed."""

    def __init__(self, root: Path | str | None = None) -> None:
        self._root = root

    def analyze(self, root: Path | str | None = None) -> RepositoryAnalysis:
        if root is None:
            if self._root is None:
                raise ValueError("repository root is required")
            root = self._root
        root = Path(root).resolve()
        files: list[RepositoryFile] = []
        symbols: list[CodeSymbol] = []
        call_sites: list[APICallSite] = []
        warnings: list[str] = []
        for path in discover_source_files(root):
            relative = path.relative_to(root).as_posix()
            raw: bytes | None = None
            try:
                raw = path.read_bytes()
                source = raw.decode("utf-8")
            except UnicodeDecodeError as error:
                files.append(
                    _failed_file(
                        relative,
                        source_hash=hashlib.sha256(raw).hexdigest() if raw is not None else None,
                        category="ENCODING_ERROR",
                        reason=str(error),
                    )
                )
                continue
            except OSError as error:
                files.append(_failed_file(relative, category="READ_ERROR", reason=str(error)))
                continue
            source_hash = hashlib.sha256(raw).hexdigest()

            if relative.endswith((".ts", ".tsx", ".js", ".jsx")):
                from opentrace.code_analysis.ts_scanner import scan_ts_file
                ts_file, ts_symbols, ts_calls = scan_ts_file(relative, source)
                files.append(ts_file)
                symbols.extend(ts_symbols)
                call_sites.extend(ts_calls)
                continue
            try:
                file_symbols, file_calls, file_warnings = parse_source(relative, source)
            except SyntaxError as error:
                files.append(
                    _failed_file(
                        relative,
                        source_hash=source_hash,
                        category="SYNTAX_ERROR",
                        line=error.lineno,
                        column=error.offset,
                        reason=error.msg,
                    )
                )
                continue
            except (ValueError, TypeError) as error:
                files.append(
                    _failed_file(
                        relative,
                        source_hash=source_hash,
                        category="AST_ERROR",
                        reason=str(error),
                    )
                )
                continue
            state = FileAnalysisState.PARTIAL if file_warnings else FileAnalysisState.PARSED
            files.append(
                RepositoryFile(
                    id=_file_id(relative),
                    path=relative,
                    state=state,
                    source_hash=source_hash,
                    warnings=tuple(sorted(set(file_warnings))),
                )
            )
            symbols.extend(file_symbols)
            call_sites.extend(file_calls)
            warnings.extend(f"{relative}: {warning}" for warning in file_warnings)
        return RepositoryAnalysis(
            root_name=root.name,
            files=tuple(sorted(files, key=lambda value: value.path)),
            symbols=tuple(
                sorted(symbols, key=lambda value: (value.file, value.line, value.column, value.id))
            ),
            call_sites=tuple(
                sorted(
                    call_sites, key=lambda value: (value.file, value.line, value.column, value.id)
                )
            ),
            warnings=tuple(sorted(set(warnings))),
        )


def analyze_repository(root: Path | str) -> RepositoryAnalysis:
    return RepositoryAnalyzer().analyze(root)


def _file_id(path: str) -> str:
    return f"file-{hashlib.sha256(path.encode('utf-8')).hexdigest()[:24]}"


def _failed_file(
    path: str,
    *,
    category: str,
    reason: str,
    source_hash: str | None = None,
    line: int | None = None,
    column: int | None = None,
) -> RepositoryFile:
    return RepositoryFile(
        id=_file_id(path),
        path=path,
        state=FileAnalysisState.FAILED,
        source_hash=source_hash,
        error_category=category,
        error_line=line,
        error_column=column,
        reason=reason,
    )
