"""Deterministic TypeScript and JavaScript HTTP call-site scanner."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from opentrace.code_analysis.models import (
    APICallSite,
    CodeSymbol,
    FileAnalysisState,
    RepositoryFile,
    ResolutionState,
    SymbolKind,
)


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


AXIOS_CALL = re.compile(
    r'(?:axios|client|apiClient)\.(get|post|put|patch|delete)\s*\(\s*([`\'"][^`\'"]+[`\'"])'
    r'(?:\s*,\s*(\{.*?\})|\s*,\s*([a-zA-Z0-9_]+))?',
    re.DOTALL,
)

FETCH_CALL = re.compile(
    r'fetch\s*\(\s*([`\'"][^`\'"]+[`\'"])(?:\s*,\s*(\{[^}]+\}))?',
    re.DOTALL,
)

TS_FUNCTION = re.compile(
    r'(?:export\s+)?(?:async\s+)?function\s+([a-zA-Z0-9_]+)\s*\(([^)]*)\)|'
    r'(?:export\s+)?const\s+([a-zA-Z0-9_]+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>',
)


def scan_ts_file(
    relative_path: str,
    source: str,
) -> tuple[RepositoryFile, list[CodeSymbol], list[APICallSite]]:
    """Extract code symbols and HTTP call sites from TypeScript/JavaScript source."""
    symbols: list[CodeSymbol] = []
    call_sites: list[APICallSite] = []
    lines = source.splitlines()

    # 1. Discover top-level functions
    for i, line in enumerate(lines, 1):
        fn_match = TS_FUNCTION.search(line)
        if fn_match:
            fn_name = fn_match.group(1) or fn_match.group(3)
            if fn_name:
                sym_id = f"sym-{_sha256(f'{relative_path}::{fn_name}')[:24]}"
                symbols.append(
                    CodeSymbol(
                        id=sym_id,
                        file=relative_path,
                        qualified_name=f"{relative_path}::{fn_name}",
                        kind=SymbolKind.FUNCTION,
                        line=i,
                        end_line=min(len(lines), i + 25),
                        column=0,
                        end_column=len(line),
                    )
                )

    default_sym = symbols[0] if symbols else CodeSymbol(
        id=f"sym-{_sha256(relative_path)[:24]}",
        file=relative_path,
        qualified_name=f"{relative_path}::module",
        kind=SymbolKind.MODULE,
        line=1,
        end_line=max(1, len(lines)),
        column=0,
        end_column=0,
    )
    if not symbols:
        symbols.append(default_sym)

    # 2. Extract axios / client calls
    for match in AXIOS_CALL.finditer(source):
        method = match.group(1).upper()
        raw_url = match.group(2).strip("'\"`")
        body_str = match.group(3) or ""

        keys: list[str] = []
        if body_str:
            key_matches = re.findall(r'([a-zA-Z0-9_]+)\s*:', body_str)
            keys = [k for k in key_matches if k not in ("headers", "params", "timeout")]

        line_no = source[: match.start()].count("\n") + 1
        call_id = f"call-{_sha256(f'{relative_path}:{line_no}:{raw_url}')[:24]}"

        call_sites.append(
            APICallSite(
                id=call_id,
                file=relative_path,
                owning_symbol=default_sym.qualified_name,
                owning_symbol_id=default_sym.id,
                line=line_no,
                column=0,
                end_line=line_no + source[match.start(): match.end()].count("\n"),
                end_column=0,
                library="axios",
                invocation_kind="CALL",
                method=method,
                raw_url_expression=raw_url,
                resolved_path=raw_url,
                url_resolution_state=ResolutionState.EXACT,
                request_fields=tuple(keys),
                request_field_resolution_state=ResolutionState.EXACT if keys else ResolutionState.UNRESOLVED,
            )
        )

    # 3. Extract fetch calls
    for match in FETCH_CALL.finditer(source):
        raw_url = match.group(1).strip("'\"`")
        opts = match.group(2) or ""
        method = "GET"
        method_match = re.search(r'method\s*:\s*[`\'"](GET|POST|PUT|PATCH|DELETE)[`\'"]', opts, re.IGNORECASE)
        if method_match:
            method = method_match.group(1).upper()

        keys: list[str] = []
        body_match = re.search(r'body\s*:\s*(?:JSON\.stringify\s*\()?\s*(\{.*?\})', opts, re.DOTALL)
        if body_match:
            key_matches = re.findall(r'([a-zA-Z0-9_]+)\s*:', body_match.group(1))
            keys = [k for k in key_matches if k not in ("headers", "params")]

        line_no = source[: match.start()].count("\n") + 1
        call_id = f"call-{_sha256(f'{relative_path}:{line_no}:{raw_url}')[:24]}"

        call_sites.append(
            APICallSite(
                id=call_id,
                file=relative_path,
                owning_symbol=default_sym.qualified_name,
                owning_symbol_id=default_sym.id,
                line=line_no,
                column=0,
                end_line=line_no + source[match.start(): match.end()].count("\n"),
                end_column=0,
                library="fetch",
                invocation_kind="CALL",
                method=method,
                raw_url_expression=raw_url,
                resolved_path=raw_url,
                url_resolution_state=ResolutionState.EXACT,
                request_fields=tuple(keys),
                request_field_resolution_state=ResolutionState.EXACT if keys else ResolutionState.UNRESOLVED,
            )
        )

    repo_file = RepositoryFile(
        id=f"file-{_sha256(relative_path)[:24]}",
        path=relative_path,
        language="typescript" if relative_path.endswith((".ts", ".tsx")) else "javascript",
        state=FileAnalysisState.PARSED,
        source_hash=_sha256(source),
    )

    return repo_file, symbols, call_sites
