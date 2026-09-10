"""Typed handles for immutable M9 evaluation artifacts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class M9RunResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    evaluation_id: str
    dataset_version: str
    dataset_checksum: str
    primary_model: str
    pre_test_manifest: str
    test_metrics: str
    predictions: str
    calibration: str
    formal_manifest: str
    output_directory: str
