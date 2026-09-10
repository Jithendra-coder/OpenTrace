"""Canonical M6 blast-radius and heuristic-risk models."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from opentrace.code_analysis.call_models import GraphCoverage, StaticCallGraph
from opentrace.code_analysis.models import APICallSite, RepositoryFile, ResolutionState
from opentrace.contracts.models import APIChange
from opentrace.impact.models import DirectImpact


class CanonicalModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    def canonical_json(self) -> str:
        import json

        return json.dumps(
            self.model_dump(mode="json", exclude_none=True),
            sort_keys=True,
            separators=(",", ":"),
        )


class ImpactType(StrEnum):
    DIRECT = "DIRECT"
    INDIRECT = "INDIRECT"


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class PropagationEvidence(CanonicalModel):
    id: str
    source_direct_impact_id: str
    source_change_id: str
    path: tuple[str, ...]
    edge_ids: tuple[str, ...] = ()
    distance: int = Field(ge=0)
    resolution_state: ResolutionState
    explanation: str


class ImpactedSymbol(CanonicalModel):
    id: str
    symbol_id: str
    file: str
    symbol: str
    impact_type: ImpactType
    distance: int = Field(ge=0)
    source_direct_impact_ids: tuple[str, ...] = ()
    source_change_ids: tuple[str, ...] = ()
    propagation: tuple[PropagationEvidence, ...] = ()
    direct_impact_score: float | None = Field(default=None, ge=0.0, le=1.0)
    certainty: ResolutionState
    warnings: tuple[str, ...] = ()


class RiskContribution(CanonicalModel):
    feature: str
    observed_value: JsonValue | None = None
    contribution: float
    explanation: str


class RiskAssessment(CanonicalModel):
    id: str
    target_id: str
    policy_version: str
    change_ids: tuple[str, ...] = ()
    risk_score: float = Field(ge=0.0, le=100.0)
    risk_level: RiskLevel
    contributions: tuple[RiskContribution, ...] = ()
    certainty: ResolutionState
    warnings: tuple[str, ...] = ()


class BlastRadius(CanonicalModel):
    id: str
    policy_version: str
    changes: tuple[APIChange, ...] = ()
    call_sites: tuple[APICallSite, ...] = ()
    files: tuple[RepositoryFile, ...] = ()
    direct_impacts: tuple[DirectImpact, ...] = ()
    graph: StaticCallGraph | None = None
    impacted_symbols: tuple[ImpactedSymbol, ...] = ()
    unmatched_change_ids: tuple[str, ...] = ()
    source_direct_impact_ids: tuple[str, ...] = ()
    source_change_ids: tuple[str, ...] = ()
    direct_symbol_count: int = Field(ge=0)
    indirect_symbol_count: int = Field(ge=0)
    maximum_distance: int = Field(ge=0)
    coverage: GraphCoverage
    risk_assessment: RiskAssessment | None = None
    warnings: tuple[str, ...] = ()

    @property
    def total_symbol_count(self) -> int:
        return self.direct_symbol_count + self.indirect_symbol_count
