from pathlib import Path

import pytest
from opentrace.datasets.models import ImpactDataset, ScenarioDefinition
from opentrace.datasets.remediation import generate_v3_dataset, validate_remediation_partitions
from opentrace.datasets.serialization import parse_rows, rows_jsonl, scenarios_jsonl
from opentrace.evaluation.chronology import ChronologyLog, ChronologyState
from opentrace.evaluation.v3_protocol import write_protocol


def _v3_dataset() -> ImpactDataset:
    root = Path("data/m7-v3")
    from opentrace.datasets.models import DatasetManifest

    manifest = DatasetManifest.model_validate_json((root / "manifest.json").read_text())
    rows = parse_rows((root / "canonical.jsonl").read_text())
    scenarios = tuple(
        ScenarioDefinition.model_validate_json(line)
        for line in (root / "scenarios.jsonl").read_text().splitlines()
        if line.strip()
    )
    return ImpactDataset(manifest=manifest, scenarios=scenarios, rows=rows)


def _historical_templates() -> frozenset[str]:
    values: set[str] = set()
    for directory in (Path("data/m7"), Path("data/m7-remediation")):
        values.update(
            ScenarioDefinition.model_validate_json(line).template_family_id
            for line in (directory / "scenarios.jsonl").read_text().splitlines()
            if line.strip()
        )
    return frozenset(values)


def test_v3_generation_matches_canonical_order_and_repeats() -> None:
    generated = generate_v3_dataset(forbidden_test_templates=_historical_templates())
    second = generate_v3_dataset(forbidden_test_templates=_historical_templates())
    assert scenarios_jsonl(generated.scenarios) == Path(
        "data/m7-v3/scenarios.jsonl"
    ).read_text()
    assert rows_jsonl(generated.rows) == Path("data/m7-v3/canonical.jsonl").read_text()
    assert scenarios_jsonl(generated.scenarios) == scenarios_jsonl(second.scenarios)
    assert rows_jsonl(generated.rows) == rows_jsonl(second.rows)
    assert generated.manifest.content_sha256 == second.manifest.content_sha256


@pytest.mark.parametrize(
    "field",
    (
        "source_fingerprint",
        "candidate_fingerprint",
        "structural_input_fingerprint",
        "heuristic_input_fingerprint",
        "template_family_id",
    ),
)
def test_each_clone_guard_individually_rejects_cross_partition(field: str) -> None:
    dataset = _v3_dataset()
    left, right = dataset.scenarios[:2]
    distinct = "distinct-" + field
    updates_left = {name: distinct + "-left" for name in (
        "source_fingerprint",
        "candidate_fingerprint",
        "structural_input_fingerprint",
        "heuristic_input_fingerprint",
        "template_family_id",
    )}
    updates_right = {name: distinct + "-right" for name in updates_left}
    updates_left[field] = "shared-guard-value"
    updates_right[field] = "shared-guard-value"
    scenarios = (left.model_copy(update=updates_left), right.model_copy(update=updates_right))
    source_rows = tuple(
        next(row for row in dataset.rows if row.scenario_id == scenario.scenario_id)
        for scenario in (left, right)
    )
    rows = tuple(
        row.model_copy(
            update={
                "scenario_id": scenario.scenario_id,
                **{
                    name: getattr(scenario, name)
                    for name in (
                        "source_fingerprint",
                        "candidate_fingerprint",
                        "structural_input_fingerprint",
                        "heuristic_input_fingerprint",
                        "template_family_id",
                    )
                },
                "split_partition": "TRAIN" if index == 0 else "TEST",
            }
        )
        for index, (scenario, row) in enumerate(zip(scenarios, source_rows, strict=True))
    )
    manifest = dataset.manifest.model_copy(
        update={
            "scenario_count": len(scenarios),
            "migration_count": len(scenarios),
            "row_count": len(rows),
        }
    )
    with pytest.raises(ValueError, match=f"{field} crosses partitions"):
        validate_remediation_partitions(
            ImpactDataset(manifest=manifest, scenarios=scenarios, rows=rows)
        )


def test_chronology_accepts_forward_sequence_and_rejects_rollback(tmp_path: Path) -> None:
    log = ChronologyLog.create(tmp_path / "chronology.jsonl")
    for event in (
        ChronologyState.PROTOCOL_FROZEN,
        ChronologyState.DATASET_GENERATED,
        ChronologyState.DATASET_VALIDATED,
        ChronologyState.SPLIT_SEALED,
        ChronologyState.DEVELOPMENT_COMPLETE,
    ):
        log.append(event, artifact_digests={}, configuration_digest="protocol")
    with pytest.raises(ValueError, match="illegal chronology transition"):
        log.append(
            ChronologyState.DATASET_GENERATED,
            artifact_digests={},
            configuration_digest="protocol",
        )


def test_chronology_rejects_formal_access_before_pretest(tmp_path: Path) -> None:
    log = ChronologyLog.create(tmp_path / "chronology.jsonl")
    log.append(
        ChronologyState.PROTOCOL_FROZEN,
        artifact_digests={},
        configuration_digest="protocol",
    )
    with pytest.raises(ValueError, match="illegal chronology transition"):
        log.append(
            ChronologyState.TEST_ACCESSED,
            artifact_digests={},
            configuration_digest="protocol",
        )


def test_chronology_allows_only_formal_completion_after_test_and_detects_tampering(
    tmp_path: Path,
) -> None:
    log = ChronologyLog.create(tmp_path / "chronology.jsonl")
    for event in (
        ChronologyState.PROTOCOL_FROZEN,
        ChronologyState.DATASET_GENERATED,
        ChronologyState.DATASET_VALIDATED,
        ChronologyState.SPLIT_SEALED,
        ChronologyState.DEVELOPMENT_COMPLETE,
        ChronologyState.PRE_TEST_FROZEN,
        ChronologyState.TEST_ACCESSED,
    ):
        log.append(event, artifact_digests={}, configuration_digest="protocol")
    with pytest.raises(ValueError, match="illegal chronology transition"):
        log.append(
            ChronologyState.PRE_TEST_FROZEN,
            artifact_digests={},
            configuration_digest="protocol",
        )
    with pytest.raises(ValueError, match="illegal chronology transition"):
        log.append(
            ChronologyState.TEST_ACCESSED,
            artifact_digests={},
            configuration_digest="protocol",
        )
    log.append(
        ChronologyState.FORMAL_EVALUATION_COMPLETE,
        artifact_digests={},
        configuration_digest="protocol",
    )
    lines = log.path.read_text().splitlines()
    tampered = lines[-1].replace(
        '"configuration_digest":"protocol"', '"configuration_digest":"tampered"'
    )
    log.path.write_text("\n".join((*lines[:-1], tampered, "")), encoding="utf-8")
    with pytest.raises(ValueError, match="chronology event digest mismatch"):
        ChronologyLog.load(log.path)


def test_protocol_seal_rejects_digest_mismatch(tmp_path: Path) -> None:
    protocol_path, _ = write_protocol(Path.cwd(), tmp_path)
    protocol_path.write_text(
        protocol_path.read_text(encoding="utf-8").replace(
            '"protocol_id":"gate-b-v3-protocol-v3"',
            '"protocol_id":"tampered"',
        ),
        encoding="utf-8",
    )
    with pytest.raises(FileExistsError, match="different content"):
        write_protocol(Path.cwd(), tmp_path)
