"""Inspectably serialize and validate dataset JSONL artifacts."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from opentrace.datasets.models import (
    DATASET_REMEDIATION_VERSION,
    DATASET_SCHEMA_VERSION,
    DATASET_V3_VERSION,
    DATASET_VERSION,
    ImpactDataset,
    ImpactDatasetRow,
    ScenarioDefinition,
)


def rows_jsonl(rows: tuple[ImpactDatasetRow, ...] | list[ImpactDatasetRow]) -> str:
    """Return canonical JSONL with one deterministic row per line."""

    return "".join(f"{row.canonical_json()}\n" for row in sorted(rows, key=lambda row: row.id))


def scenarios_jsonl(scenarios: tuple[ScenarioDefinition, ...] | list[ScenarioDefinition]) -> str:
    return "".join(
        f"{scenario.canonical_json()}\n"
        for scenario in sorted(scenarios, key=lambda scenario: scenario.scenario_id)
    )


def parse_rows(content: str) -> tuple[ImpactDatasetRow, ...]:
    rows: list[ImpactDatasetRow] = []
    for line_number, line in enumerate(content.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(ImpactDatasetRow.model_validate_json(line))
        except ValueError as error:
            raise ValueError(f"invalid dataset row at line {line_number}") from error
    return tuple(sorted(rows, key=lambda row: row.id))


def validate_dataset(dataset: ImpactDataset) -> None:
    """Reject malformed versions, IDs, duplicates, bounds, or hidden omissions."""

    if dataset.manifest.schema_version != DATASET_SCHEMA_VERSION:
        raise ValueError("unknown dataset schema version")
    if dataset.manifest.dataset_version not in {
        DATASET_VERSION,
        DATASET_REMEDIATION_VERSION,
        DATASET_V3_VERSION,
    }:
        raise ValueError("unknown dataset version")
    scenario_ids = [scenario.scenario_id for scenario in dataset.scenarios]
    if any(not value for value in scenario_ids) or len(set(scenario_ids)) != len(scenario_ids):
        raise ValueError("scenario IDs must be present and unique")
    row_ids = [row.id for row in dataset.rows]
    if any(not value for value in row_ids) or len(set(row_ids)) != len(row_ids):
        raise ValueError("row IDs must be present and unique")
    scenario_index = {scenario.scenario_id: scenario for scenario in dataset.scenarios}
    for row in dataset.rows:
        scenario = scenario_index.get(row.scenario_id)
        if scenario is None:
            raise ValueError(f"row references unknown scenario {row.scenario_id}")
        if row.migration_id != scenario.migration_id:
            raise ValueError("row migration grouping does not match scenario")
        if row.scenario_fingerprint != scenario.scenario_fingerprint:
            raise ValueError("row scenario fingerprint does not match scenario")
        if row.ground_truth_path and row.ground_truth_path[0] != row.candidate_symbol:
            raise ValueError("ground-truth path must begin at its candidate symbol")
    if dataset.manifest.split_strategy == "clone-safe-component-round-robin-v2":
        _validate_clone_safe_fields(dataset, scenario_index)
    content = rows_jsonl(dataset.rows).encode("utf-8")
    if hashlib.sha256(content).hexdigest() != dataset.manifest.content_sha256:
        raise ValueError("manifest content checksum does not match rows")


def _validate_clone_safe_fields(
    dataset: ImpactDataset, scenario_index: dict[str, ScenarioDefinition]
) -> None:
    fields = (
        "source_fingerprint",
        "candidate_fingerprint",
        "structural_input_fingerprint",
        "heuristic_input_fingerprint",
        "template_family_id",
    )
    owners: dict[str, dict[str, str]] = {field: {} for field in fields}
    for scenario in dataset.scenarios:
        if any(getattr(scenario, field) is None for field in fields):
            raise ValueError("clone-safe dataset scenarios require all leakage fingerprints")
    for row in dataset.rows:
        scenario = scenario_index[row.scenario_id]
        if row.split_partition is None:
            raise ValueError("clone-safe dataset rows require sealed split assignments")
        for field in fields:
            scenario_value = getattr(scenario, field)
            row_value = getattr(row, field)
            if row_value != scenario_value:
                raise ValueError(f"row {field} does not match its scenario")
            previous = owners[field].setdefault(str(scenario_value), row.split_partition.value)
            if previous != row.split_partition.value:
                raise ValueError(f"{field} crosses partitions: {scenario_value}")


def duplicate_counts(dataset: ImpactDataset) -> tuple[int, int]:
    scenario_counts = Counter(scenario.scenario_fingerprint for scenario in dataset.scenarios)
    row_counts = Counter(row.id for row in dataset.rows)
    return (
        sum(max(0, count - 1) for count in scenario_counts.values()),
        sum(max(0, count - 1) for count in row_counts.values()),
    )


def write_artifacts(
    dataset: ImpactDataset,
    output_directory: Path | str,
) -> tuple[Path, Path, Path]:
    """Write canonical rows, scenario provenance, and manifest files."""

    validate_dataset(dataset)
    directory = Path(output_directory)
    directory.mkdir(parents=True, exist_ok=True)
    rows_path = directory / "canonical.jsonl"
    scenarios_path = directory / "scenarios.jsonl"
    manifest_path = directory / "manifest.json"
    rows_path.write_bytes(rows_jsonl(dataset.rows).encode("utf-8"))
    scenarios_path.write_bytes(scenarios_jsonl(dataset.scenarios).encode("utf-8"))
    manifest_path.write_bytes((dataset.manifest.canonical_json() + "\n").encode("utf-8"))
    return rows_path, scenarios_path, manifest_path


def read_manifest(path: Path | str) -> dict[str, object]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("manifest must be a JSON object")
    return value
