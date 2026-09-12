"""Typed, versioned dataset artifacts and provenance models."""

from __future__ import annotations

import json
import math
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from opentrace.code_analysis.models import ResolutionState

DATASET_SCHEMA_VERSION = "impact-dataset-v1"
DATASET_VERSION = "impact-dataset-v1"
DATASET_REMEDIATION_VERSION = "impact-dataset-v2"
DATASET_V3_VERSION = "impact-dataset-v3"
GENERATOR_VERSION = "synthetic-impact-generator-v1"
GENERATOR_REMEDIATION_VERSION = "synthetic-impact-generator-v2"
GENERATOR_V3_VERSION = "synthetic-impact-generator-v3"


class CanonicalModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    def canonical_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json", exclude_none=True),
            sort_keys=True,
            separators=(",", ":"),
        )


class ScenarioFamily(StrEnum):
    SYNTHETIC = "SYNTHETIC"
    CURATED = "CURATED"
    REALISTIC = "REALISTIC"


class GroundTruthLabel(StrEnum):
    AFFECTED = "AFFECTED"
    UNAFFECTED = "UNAFFECTED"


class GroundTruthImpactType(StrEnum):
    DIRECT = "DIRECT"
    INDIRECT = "INDIRECT"
    UNAFFECTED = "UNAFFECTED"


class SplitPartition(StrEnum):
    TRAIN = "TRAIN"
    VALIDATION = "VALIDATION"
    TEST = "TEST"


class GeneratorConfig(CanonicalModel):
    seed: int = 42
    synthetic_scenarios: int = Field(default=10, ge=1, le=500)
    include_curated: bool = True
    include_realistic: bool = True
    candidate_rule: str = "all analyzed CodeSymbol nodes"


class ScenarioSource(CanonicalModel):
    path: str
    content: str


class GroundTruthTarget(CanonicalModel):
    symbol: str
    impact_type: GroundTruthImpactType
    distance: int = Field(ge=0)
    path: tuple[str, ...]
    rationale: str


class ScenarioDefinition(CanonicalModel):
    scenario_id: str
    scenario_fingerprint: str
    family: ScenarioFamily
    repository_id: str
    repository_family_id: str
    api_family_id: str
    migration_id: str
    mutation_family: str
    seed: int | None = None
    old_spec: str
    new_spec: str
    sources: tuple[ScenarioSource, ...]
    ground_truth: tuple[GroundTruthTarget, ...]
    provenance: str
    intended_role: str
    hard_negative: bool = False
    hard_positive: bool = False
    tags: tuple[str, ...] = ()
    source_fingerprint: str | None = None
    candidate_fingerprint: str | None = None
    structural_input_fingerprint: str | None = None
    heuristic_input_fingerprint: str | None = None
    template_family_id: str | None = None


class FeatureEvidence(CanonicalModel):
    name: str
    observed_value: str
    contribution: float = Field(ge=0.0, le=1.0)
    resolution_state: ResolutionState
    explanation: str


class DatasetFeatures(CanonicalModel):
    """Observed analysis features; no ground-truth fields are included."""

    change_category: str
    change_severity: str
    change_certainty: str
    breaking_classification: str
    compatibility_direction: str
    evidence: tuple[FeatureEvidence, ...] = ()
    endpoint_path_match: bool | None = None
    host_match: bool | None = None
    method_match: bool | None = None
    request_field_overlap: tuple[str, ...] = ()
    response_field_overlap: tuple[str, ...] = ()
    parameter_overlap: tuple[str, ...] = ()
    direct_reference: bool | None = None
    url_resolution_state: ResolutionState | None = None
    request_resolution_state: ResolutionState | None = None
    response_resolution_state: ResolutionState | None = None
    graph_distance: int | None = Field(default=None, ge=0)
    direct_caller_count: int | None = Field(default=None, ge=0)
    upstream_caller_count: int | None = Field(default=None, ge=0)
    coverage_unresolved_calls: int = Field(ge=0)
    coverage_failed_files: int = Field(ge=0)
    m4_impact_score: float | None = Field(default=None, ge=0.0, le=1.0)
    m6_risk_score: float | None = Field(default=None, ge=0.0, le=100.0)
    m6_risk_level: str | None = None

    @model_validator(mode="after")
    def finite_scores(self) -> DatasetFeatures:
        for value in (self.m4_impact_score, self.m6_risk_score):
            if value is not None and not math.isfinite(value):
                raise ValueError("dataset feature scores must be finite")
        return self


class AnalyzerObservation(CanonicalModel):
    """What the deterministic engine actually observed for this candidate."""

    direct_match: bool
    indirect_match: bool
    impact_type: str | None = None
    certainty: ResolutionState | None = None
    distance: int | None = Field(default=None, ge=0)
    propagation_path: tuple[str, ...] = ()
    unmatched_change: bool = False
    coverage_state: ResolutionState
    warnings: tuple[str, ...] = ()


class ImpactDatasetRow(CanonicalModel):
    """One APIChange × candidate CodeSymbol training/evaluation candidate."""

    id: str
    schema_version: str = DATASET_SCHEMA_VERSION
    dataset_version: str = DATASET_VERSION
    scenario_id: str
    scenario_fingerprint: str
    repository_id: str
    repository_family_id: str
    api_family_id: str
    migration_id: str
    mutation_family: str
    api_change_id: str
    candidate_symbol_id: str
    candidate_symbol: str
    candidate_file: str
    ground_truth_label: GroundTruthLabel
    ground_truth_impact_type: GroundTruthImpactType
    ground_truth_distance: int | None = Field(default=None, ge=0)
    ground_truth_path: tuple[str, ...] = ()
    ground_truth_rationale: str
    features: DatasetFeatures
    observation: AnalyzerObservation
    family: ScenarioFamily
    provenance: str
    hard_negative: bool = False
    hard_positive: bool = False
    error_flags: tuple[str, ...] = ()
    split_group_id: str
    split_partition: SplitPartition | None = None
    source_fingerprint: str | None = None
    candidate_fingerprint: str | None = None
    structural_input_fingerprint: str | None = None
    heuristic_input_fingerprint: str | None = None
    template_family_id: str | None = None

    @model_validator(mode="after")
    def validate_label_shape(self) -> ImpactDatasetRow:
        if self.ground_truth_label is GroundTruthLabel.UNAFFECTED:
            if self.ground_truth_impact_type is not GroundTruthImpactType.UNAFFECTED:
                raise ValueError("unaffected rows must use UNAFFECTED impact type")
            if self.ground_truth_distance is not None or self.ground_truth_path:
                raise ValueError("unaffected rows cannot carry affected distance/path")
        else:
            if self.ground_truth_impact_type is GroundTruthImpactType.UNAFFECTED:
                raise ValueError("affected rows need DIRECT or INDIRECT impact type")
            if self.ground_truth_distance is None or not self.ground_truth_path:
                raise ValueError("affected rows need independent ground-truth path evidence")
        return self


class DatasetManifest(CanonicalModel):
    dataset_name: str = "OpenTrace impact candidates"
    dataset_version: str = DATASET_VERSION
    schema_version: str = DATASET_SCHEMA_VERSION
    generator_version: str = GENERATOR_VERSION
    seed: int
    config: GeneratorConfig
    scenario_count: int = Field(ge=0)
    migration_count: int = Field(ge=0)
    row_count: int = Field(ge=0)
    positive_count: int = Field(ge=0)
    negative_count: int = Field(ge=0)
    direct_count: int = Field(ge=0)
    indirect_count: int = Field(ge=0)
    mutation_families: tuple[str, ...] = ()
    api_family_ids: tuple[str, ...] = ()
    repository_family_ids: tuple[str, ...] = ()
    evidence_exact: int = Field(ge=0)
    evidence_partial: int = Field(ge=0)
    evidence_unresolved: int = Field(ge=0)
    scenario_duplicates: int = Field(ge=0)
    row_duplicates: int = Field(ge=0)
    content_sha256: str
    source_commit: str | None = None
    generation_timestamp: str | None = None
    split_strategy: str | None = None
    split_fingerprint: str | None = None
    revision_reason: str | None = None


class ImpactDataset(CanonicalModel):
    manifest: DatasetManifest
    scenarios: tuple[ScenarioDefinition, ...]
    rows: tuple[ImpactDatasetRow, ...]

    @model_validator(mode="after")
    def validate_manifest_counts(self) -> ImpactDataset:
        if self.manifest.row_count != len(self.rows):
            raise ValueError("manifest row_count does not match dataset rows")
        if self.manifest.scenario_count != len(self.scenarios):
            raise ValueError("manifest scenario_count does not match scenarios")
        return self
