"""Typed, immutable M14 bounded migration-context artifacts."""

from __future__ import annotations

import json
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from opentrace.routeforge.models import RouteChoice

MIGRATION_CONTEXT_SCHEMA_VERSION = "migration-context-v1"
MIGRATION_CONTEXT_SELECTION_POLICY_VERSION = "migration-context-selection-v1"


class CanonicalModel(BaseModel):
    """Frozen models with stable serialization for provenance and repeatability."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    def canonical_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json", exclude_none=True),
            sort_keys=True,
            separators=(",", ":"),
        )


class ContextItemRole(StrEnum):
    API_CHANGE = "API_CHANGE"
    DIRECT_API_CALL = "DIRECT_API_CALL"
    TARGET_SYMBOL = "TARGET_SYMBOL"
    REQUEST_EVIDENCE = "REQUEST_EVIDENCE"
    RESPONSE_EVIDENCE = "RESPONSE_EVIDENCE"
    CALLER_SYMBOL = "CALLER_SYMBOL"
    MIGRATION_EVIDENCE = "MIGRATION_EVIDENCE"
    ROUTING_EVIDENCE = "ROUTING_EVIDENCE"


class ContextOmissionReason(StrEnum):
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    FILE_LIMIT_EXCEEDED = "FILE_LIMIT_EXCEEDED"
    LOWER_PRIORITY = "LOWER_PRIORITY"
    DUPLICATE = "DUPLICATE"
    UNRESOLVED_SOURCE = "UNRESOLVED_SOURCE"
    UNSAFE_FILE = "UNSAFE_FILE"
    OUTSIDE_REPOSITORY = "OUTSIDE_REPOSITORY"
    MISSING_EVIDENCE = "MISSING_EVIDENCE"


class ContextSelectionStatus(StrEnum):
    CONTEXT_READY = "CONTEXT_READY"
    NOT_REQUIRED = "NOT_REQUIRED"
    NO_FEASIBLE_STRATEGY = "NO_FEASIBLE_STRATEGY"
    INSUFFICIENT_CONTEXT_BUDGET = "INSUFFICIENT_CONTEXT_BUDGET"
    INCOMPLETE_EVIDENCE = "INCOMPLETE_EVIDENCE"


class ContextBudget(CanonicalModel):
    """Provider-independent content-only character accounting."""

    unit: str = "CHARACTERS"
    limit_characters: int = Field(ge=1)
    used_characters: int = Field(ge=0)
    remaining_characters: int = Field(ge=0)
    file_limit: int = Field(ge=1)
    files_used: int = Field(ge=0)
    truncated: bool = False

    @model_validator(mode="after")
    def accounting_is_exact(self) -> ContextBudget:
        if self.used_characters + self.remaining_characters != self.limit_characters:
            raise ValueError("context budget accounting must equal its limit")
        if self.files_used > self.file_limit:
            raise ValueError("context file accounting exceeds its limit")
        return self


class ContextSelectionPolicy(CanonicalModel):
    version: str = MIGRATION_CONTEXT_SELECTION_POLICY_VERSION
    default_budget_characters: int = Field(default=8000, ge=1)
    minimum_budget_characters: int = Field(default=1, ge=1)
    maximum_files: int = Field(default=8, ge=1)
    maximum_caller_distance: int = Field(default=2, ge=0)

    @model_validator(mode="after")
    def budget_range_is_valid(self) -> ContextSelectionPolicy:
        if self.minimum_budget_characters > self.default_budget_characters:
            raise ValueError("minimum context budget cannot exceed its default")
        return self


class ContextItem(CanonicalModel):
    id: str
    role: ContextItemRole
    file: str | None = None
    symbol: str | None = None
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    content: str
    content_hash: str
    reason_selected: str
    provenance_ids: tuple[str, ...] = ()
    priority: int = Field(ge=1)
    rank: int = Field(ge=1)
    graph_distance: int | None = Field(default=None, ge=0)


class ContextOmission(CanonicalModel):
    id: str
    role: ContextItemRole
    file: str | None = None
    symbol: str | None = None
    provenance_ids: tuple[str, ...] = ()
    reason: ContextOmissionReason
    priority: int = Field(ge=1)
    content_characters: int = Field(ge=0)
    detail: str


class ContextSelectionSummary(CanonicalModel):
    required_items_selected: int = Field(ge=0)
    optional_items_selected: int = Field(ge=0)
    files_represented: tuple[str, ...] = ()
    symbols_represented: tuple[str, ...] = ()
    graph_distances_represented: tuple[int, ...] = ()
    budget_used_characters: int = Field(ge=0)
    omitted_items: int = Field(ge=0)
    uncertainty_warnings: tuple[str, ...] = ()
    completeness: ContextSelectionStatus


class ContextManifest(CanonicalModel):
    schema_version: str = MIGRATION_CONTEXT_SCHEMA_VERSION
    context_id: str
    selection_policy_version: str
    repository_fingerprint: str
    api_change_ids: tuple[str, ...] = ()
    target_ids: tuple[str, ...] = ()
    route_identity: str
    budget: ContextBudget
    selected_item_hashes: tuple[str, ...] = ()
    checksum: str


class MigrationContext(CanonicalModel):
    id: str
    schema_version: str = MIGRATION_CONTEXT_SCHEMA_VERSION
    selection_policy_version: str
    repository_fingerprint: str
    api_change_ids: tuple[str, ...] = ()
    target_ids: tuple[str, ...] = ()
    route_identity: str
    selected_strategy: RouteChoice
    items: tuple[ContextItem, ...] = ()
    omissions: tuple[ContextOmission, ...] = ()
    budget: ContextBudget
    warnings: tuple[str, ...] = ()
    summary: ContextSelectionSummary
    manifest: ContextManifest


class ContextSelection(CanonicalModel):
    status: ContextSelectionStatus
    context: MigrationContext | None = None
    budget: ContextBudget
    omissions: tuple[ContextOmission, ...] = ()
    summary: ContextSelectionSummary
    warnings: tuple[str, ...] = ()
