"""Typed experiment, split, and prediction records."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

M8_FEATURE_SCHEMA_VERSION = "impact-ml-features-v1"
M8_EXPERIMENT_SCHEMA_VERSION = "impact-ml-experiment-v1"
M8_SPLIT_VERSION = "migration-id-hash-v1"


class FeatureSet(StrEnum):
    STRUCTURAL = "A_STRUCTURAL"
    STRUCTURAL_HEURISTICS = "B_STRUCTURAL_PLUS_HEURISTICS"


class M8ModelName(StrEnum):
    HEURISTIC = "HEURISTIC"
    LOGISTIC_REGRESSION = "LOGISTIC_REGRESSION"
    RANDOM_FOREST = "RANDOM_FOREST"
    XGBOOST = "XGBOOST"


class M8Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: M8ModelName
    feature_set: FeatureSet | None = None
    parameters: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    seed: int


class SplitCounts(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    partition: str
    rows: int = Field(ge=0)
    migrations: int = Field(ge=0)
    positives: int | None = Field(default=None, ge=0)
    negatives: int | None = Field(default=None, ge=0)
    api_families: int = Field(ge=0)
    mutation_families: int = Field(ge=0)


class SplitIntegrity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    split_version: str = M8_SPLIT_VERSION
    group_by: str = "migration_id"
    split_seed: int = 42
    train: SplitCounts
    validation: SplitCounts
    test: SplitCounts
    train_validation_migration_overlap: int = Field(ge=0)
    train_test_migration_overlap: int = Field(ge=0)
    validation_test_migration_overlap: int = Field(ge=0)
    train_validation_repository_overlap: int = Field(ge=0)
    train_validation_api_overlap: int = Field(ge=0)
    train_validation_scenario_overlap: int = Field(ge=0)


class ValidationPrediction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    experiment_id: str
    row_id: str
    ranking_group: str
    ground_truth_label: str
    score: float
    rank: int = Field(ge=1)


class ExperimentRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = M8_EXPERIMENT_SCHEMA_VERSION
    experiment_id: str
    date: str
    hypothesis: str
    dataset_version: str
    dataset_checksum: str
    split_strategy: str
    feature_schema_version: str
    feature_set: FeatureSet | None = None
    model: M8Model
    hyperparameters: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    seed: int
    split_seed: int
    training_partition: str = "TRAIN"
    evaluation_partition: str = "VALIDATION"
    test_used: bool = False
    metrics: dict[str, float] = Field(default_factory=dict)
    interpretation: str
    limitations: tuple[str, ...] = ()
    artifact_locations: tuple[str, ...] = ()
    reproduction_command: str = "python -m opentrace.ml"


class M8RunResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset_version: str
    dataset_checksum: str
    split_integrity: SplitIntegrity
    experiments: tuple[ExperimentRecord, ...]
    validation_prediction_files: tuple[str, ...]
    model_files: tuple[str, ...]
    metrics_file: str
