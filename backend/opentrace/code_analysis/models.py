"""Canonical, deterministic static-analysis models."""

import json
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class CanonicalModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    def canonical_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json", exclude_none=True),
            sort_keys=True,
            separators=(",", ":"),
        )


class ResolutionState(StrEnum):
    EXACT = "EXACT"
    PARTIAL = "PARTIAL"
    UNRESOLVED = "UNRESOLVED"


class FileAnalysisState(StrEnum):
    PARSED = "PARSED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class SymbolKind(StrEnum):
    MODULE = "MODULE"
    FUNCTION = "FUNCTION"
    ASYNC_FUNCTION = "ASYNC_FUNCTION"
    METHOD = "METHOD"
    ASYNC_METHOD = "ASYNC_METHOD"
    CLASS = "CLASS"


class RepositoryFile(CanonicalModel):
    id: str
    path: str
    language: str = "python"
    state: FileAnalysisState
    source_hash: str | None = None
    error_category: str | None = None
    error_line: int | None = None
    error_column: int | None = None
    reason: str | None = None
    warnings: tuple[str, ...] = ()

    @property
    def relative_path(self) -> str:
        return self.path


class CodeSymbol(CanonicalModel):
    id: str
    file: str
    qualified_name: str
    kind: SymbolKind
    line: int
    end_line: int
    column: int
    end_column: int


class APICallSite(CanonicalModel):
    id: str
    file: str
    owning_symbol: str
    owning_symbol_id: str
    class_name: str | None = None
    line: int
    column: int
    end_line: int
    end_column: int
    library: str
    invocation_kind: str
    method: str
    raw_url_expression: str | None = None
    resolved_host: str | None = None
    resolved_path: str | None = None
    url_resolution_state: ResolutionState = ResolutionState.UNRESOLVED
    request_fields: tuple[str, ...] = ()
    request_field_resolution_state: ResolutionState = ResolutionState.UNRESOLVED
    query_parameters: tuple[str, ...] = ()
    headers: tuple[str, ...] = ()
    response_fields_used: tuple[str, ...] = ()
    response_field_resolution_state: ResolutionState = ResolutionState.UNRESOLVED
    resolution_state: ResolutionState = ResolutionState.UNRESOLVED
    evidence: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def url_resolution(self) -> ResolutionState:
        return self.url_resolution_state

    @property
    def request_field_resolution(self) -> ResolutionState:
        return self.request_field_resolution_state

    @property
    def response_field_resolution(self) -> ResolutionState:
        return self.response_field_resolution_state


class RepositoryAnalysis(CanonicalModel):
    root_name: str
    files: tuple[RepositoryFile, ...] = ()
    symbols: tuple[CodeSymbol, ...] = ()
    call_sites: tuple[APICallSite, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def failed_files(self) -> tuple[RepositoryFile, ...]:
        return tuple(file for file in self.files if file.state is FileAnalysisState.FAILED)

    @property
    def skipped_files(self) -> tuple[RepositoryFile, ...]:
        return tuple(file for file in self.files if file.state is FileAnalysisState.SKIPPED)
