from pathlib import Path

import pytest
from opentrace.datasets.generator import assign_group_partitions
from opentrace.datasets.models import DatasetManifest, ImpactDataset, ScenarioDefinition
from opentrace.datasets.remediation import (
    RemediationConfig,
    annotate_leakage_fingerprints,
    generate_remediation_dataset,
    validate_remediation_partitions,
)
from opentrace.datasets.serialization import parse_rows, write_artifacts


def _historical_dataset() -> ImpactDataset:
    root = Path("data/m7")
    manifest = DatasetManifest.model_validate_json((root / "manifest.json").read_text())
    rows = parse_rows((root / "canonical.jsonl").read_text())
    scenarios = tuple(
        ScenarioDefinition.model_validate_json(line)
        for line in (root / "scenarios.jsonl").read_text().splitlines()
        if line.strip()
    )
    return ImpactDataset(manifest=manifest, scenarios=scenarios, rows=rows)


def test_historical_webhook_clone_is_detected_by_model_input_fingerprints() -> None:
    dataset = annotate_leakage_fingerprints(
        assign_group_partitions(_historical_dataset(), seed=42)
    )
    validation = next(
        scenario
        for scenario in dataset.scenarios
        if scenario.scenario_id == "27ce99e6ae2d6db887e54876"
    )
    test = next(
        scenario
        for scenario in dataset.scenarios
        if scenario.scenario_id == "da838712a7906ae8ba82cbbd"
    )
    assert validation.source_fingerprint == test.source_fingerprint
    assert validation.candidate_fingerprint == test.candidate_fingerprint
    assert validation.structural_input_fingerprint == test.structural_input_fingerprint
    assert validation.heuristic_input_fingerprint == test.heuristic_input_fingerprint

    dataset = dataset.model_copy(
        update={
            "manifest": dataset.manifest.model_copy(
                update={"split_strategy": "clone-safe-component-round-robin-v2"}
            )
        }
    )
    with pytest.raises(ValueError, match="crosses partitions"):
        validate_remediation_partitions(dataset)


def test_revised_dataset_is_deterministic_and_clone_safe() -> None:
    first = generate_remediation_dataset(RemediationConfig())
    second = generate_remediation_dataset(RemediationConfig())
    assert first.manifest.content_sha256 == second.manifest.content_sha256
    assert first.manifest.split_fingerprint == second.manifest.split_fingerprint
    assert (
        first.manifest.content_sha256
        == "bfe2696c05e76b479c87210301638bab8323c8405aa1755aba8d73e2e99cf231"
    )
    validate_remediation_partitions(first)


def test_clone_safe_artifacts_validate_after_serialization(tmp_path: Path) -> None:
    dataset = generate_remediation_dataset(RemediationConfig())
    write_artifacts(dataset, tmp_path)
    manifest = DatasetManifest.model_validate_json((tmp_path / "manifest.json").read_text())
    rows = parse_rows((tmp_path / "canonical.jsonl").read_text())
    scenarios = tuple(
        ScenarioDefinition.model_validate_json(line)
        for line in (tmp_path / "scenarios.jsonl").read_text().splitlines()
        if line.strip()
    )
    loaded = ImpactDataset(manifest=manifest, scenarios=scenarios, rows=rows)
    assert loaded.manifest.dataset_version == "impact-dataset-v2"


def test_canonical_scenario_order_matches_serialization(tmp_path: Path) -> None:
    dataset = generate_remediation_dataset(RemediationConfig())
    write_artifacts(dataset, tmp_path)
    serialized = tuple(
        ScenarioDefinition.model_validate_json(line)
        for line in (tmp_path / "scenarios.jsonl").read_text().splitlines()
        if line.strip()
    )
    assert tuple(scenario.scenario_id for scenario in dataset.scenarios) == tuple(
        scenario.scenario_id for scenario in serialized
    )
