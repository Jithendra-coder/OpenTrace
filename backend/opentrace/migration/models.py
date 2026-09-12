"""Typed, immutable deterministic migration artifacts."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CanonicalModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    def canonical_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json", exclude_none=True),
            sort_keys=True,
            separators=(",", ":"),
        )


class MigrationOutcome(StrEnum):
    NO_CHANGE = "NO_CHANGE"
    DETERMINISTIC_CANDIDATE = "DETERMINISTIC_CANDIDATE"
    AI_REQUIRED = "AI_REQUIRED"
    UNSUPPORTED = "UNSUPPORTED"


class Repairability(StrEnum):
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"


class RepairStrategy(StrEnum):
    NO_AI = "NO_AI"
    DETERMINISTIC = "DETERMINISTIC"


class EditKind(StrEnum):
    REMOVE_REQUEST_PROPERTY = "REMOVE_REQUEST_PROPERTY"


class MigrationConflict(CanonicalModel):
    id: str
    kind: str
    file: str
    edit_ids: tuple[str, ...] = ()
    reason: str
    ranges: tuple[tuple[int, int], ...] = ()


class SourcePrecondition(CanonicalModel):
    file: str
    source_hash: str
    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=0)
    expected_text_hash: str
    expected_text: str


class MigrationEdit(CanonicalModel):
    id: str
    file: str
    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=0)
    start_line: int = Field(ge=1)
    start_column: int = Field(ge=0)
    end_line: int = Field(ge=1)
    end_column: int = Field(ge=0)
    original_text_hash: str
    original_text: str
    replacement_text: str
    edit_kind: EditKind
    reason: str
    change_id: str
    direct_impact_id: str
    call_site_id: str
    rule_id: str
    rule_version: str


class GeneratedPatch(CanonicalModel):
    id: str
    plan_id: str
    strategy: RepairStrategy = RepairStrategy.DETERMINISTIC
    unified_diff: str
    files: tuple[str, ...] = ()
    source_hashes: dict[str, str] = Field(default_factory=dict)


class DeterministicMigrationPlan(CanonicalModel):
    id: str
    change_id: str
    direct_impact_id: str
    call_site_id: str
    target_file: str
    target_symbol: str
    target_line: int = Field(ge=1)
    target_column: int = Field(ge=0)
    strategy: RepairStrategy
    rule_id: str | None = None
    rule_version: str | None = None
    outcome: MigrationOutcome
    repairability: Repairability
    explanation: str
    assumptions: tuple[str, ...] = ()
    required_evidence: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    edits: tuple[MigrationEdit, ...] = ()
    preconditions: tuple[SourcePrecondition, ...] = ()
    conflicts: tuple[MigrationConflict, ...] = ()


MigrationPlan = DeterministicMigrationPlan


class MigrationCandidate(CanonicalModel):
    id: str
    plan_id: str
    outcome: MigrationOutcome
    repairability: Repairability
    patch: GeneratedPatch | None = None
    explanation: str
    warnings: tuple[str, ...] = ()


class UnsupportedMigration(CanonicalModel):
    id: str
    change_id: str
    direct_impact_id: str
    call_site_id: str
    outcome: MigrationOutcome = MigrationOutcome.UNSUPPORTED
    repairability: Repairability = Repairability.UNSUPPORTED
    reason: str
    assumptions: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


class MigrationSummary(CanonicalModel):
    changes_analyzed: int = 0
    deterministically_repairable: int = 0
    unsupported: int = 0
    partial_or_ambiguous: int = 0
    edits_generated: int = 0
    files_targeted: int = 0
    conflicts: int = 0
    warnings: tuple[str, ...] = ()


class MigrationResult(CanonicalModel):
    id: str
    outcome: MigrationOutcome
    repairability: Repairability
    plan: DeterministicMigrationPlan
    candidate: MigrationCandidate | None = None
    unsupported: UnsupportedMigration | None = None
    conflicts: tuple[MigrationConflict, ...] = ()
    summary: MigrationSummary = Field(default_factory=MigrationSummary)


class MigrationBatchResult(CanonicalModel):
    id: str
    results: tuple[MigrationResult, ...] = ()
    summary: MigrationSummary = Field(default_factory=MigrationSummary)


def json_object(value: Any) -> str:
    """Stable JSON helper for deterministic identity material."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
