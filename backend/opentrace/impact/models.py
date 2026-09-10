"""Canonical M4 direct-impact result models."""

import json

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from opentrace.code_analysis.models import APICallSite, RepositoryFile, ResolutionState
from opentrace.contracts.models import APIChange


class CanonicalModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    def canonical_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json", exclude_none=True),
            sort_keys=True,
            separators=(",", ":"),
        )


class ImpactEvidence(CanonicalModel):
    feature: str
    observed_value: JsonValue | None = None
    contribution: float = 0.0
    resolution_state: ResolutionState
    explanation: str


class DirectImpact(CanonicalModel):
    id: str
    change_id: str
    call_site_id: str
    file: str
    symbol: str
    line: int
    match_features: tuple[str, ...] = ()
    impact_score: float = Field(ge=0.0, le=1.0)
    evidence: tuple[ImpactEvidence, ...] = ()
    reasons: tuple[str, ...] = ()
    certainty: ResolutionState
    warnings: tuple[str, ...] = ()
    matched_host: str | None = None
    matched_path: str | None = None
    matched_method: str | None = None
    matched_request_fields: tuple[str, ...] = ()
    matched_response_fields: tuple[str, ...] = ()
    matched_parameter_locations: tuple[str, ...] = ()
    policy_version: str


ImpactCandidate = DirectImpact


class UnmatchedImpact(CanonicalModel):
    change_id: str
    evaluated_call_site_ids: tuple[str, ...] = ()
    reason: str
    warnings: tuple[str, ...] = ()


class ImpactAnalysis(CanonicalModel):
    policy_version: str
    changes: tuple[APIChange, ...] = ()
    call_sites: tuple[APICallSite, ...] = ()
    files: tuple[RepositoryFile, ...] = ()
    direct_impacts: tuple[DirectImpact, ...] = ()
    unmatched: tuple[UnmatchedImpact, ...] = ()
    warnings: tuple[str, ...] = ()
