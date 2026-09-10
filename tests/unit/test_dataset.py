from hashlib import sha256
from pathlib import Path

from opentrace.datasets import (
    GeneratorConfig,
    GroundTruthLabel,
    assign_group_partitions,
    duplicate_counts,
    generate_dataset,
    parse_rows,
    read_manifest,
    rows_jsonl,
    validate_dataset,
    write_artifacts,
)


def test_generation_is_deterministic_and_seeded() -> None:
    config = GeneratorConfig(seed=17, synthetic_scenarios=2, include_realistic=False)
    first = generate_dataset(config)
    second = generate_dataset(config)

    assert first.canonical_json() == second.canonical_json()
    assert first.manifest.content_sha256 == second.manifest.content_sha256

    changed = generate_dataset(
        config.model_copy(update={"seed": 18})
    )
    assert changed.manifest.content_sha256 != first.manifest.content_sha256


def test_jsonl_round_trip_and_manifest_validation(tmp_path: Path) -> None:
    dataset = generate_dataset(
        GeneratorConfig(seed=19, synthetic_scenarios=1, include_realistic=False)
    )
    validate_dataset(dataset)
    rows_path, scenarios_path, manifest_path = write_artifacts(dataset, tmp_path)

    assert parse_rows(rows_path.read_text(encoding="utf-8")) == dataset.rows
    assert scenarios_path.read_text(encoding="utf-8").count("\n") == len(dataset.scenarios)
    assert read_manifest(manifest_path)["content_sha256"] == dataset.manifest.content_sha256
    assert rows_jsonl(dataset.rows) == rows_path.read_text(encoding="utf-8")
    assert sha256(rows_path.read_bytes()).hexdigest() == dataset.manifest.content_sha256
    assert duplicate_counts(dataset) == (0, 0)


def test_labels_are_independent_from_engine_observations() -> None:
    dataset = generate_dataset(GeneratorConfig(seed=42, synthetic_scenarios=3))
    disagreement = [
        row
        for row in dataset.rows
        if row.ground_truth_label is GroundTruthLabel.AFFECTED
        and not row.observation.direct_match
    ]
    hard_negatives = [
        row
        for row in dataset.rows
        if row.hard_negative and row.ground_truth_label is GroundTruthLabel.UNAFFECTED
    ]

    assert disagreement
    assert hard_negatives


def test_group_partitions_never_split_a_migration() -> None:
    dataset = generate_dataset(
        GeneratorConfig(seed=23, synthetic_scenarios=2, include_realistic=False)
    )
    partitioned = assign_group_partitions(dataset, seed=5)
    by_group: dict[str, set[object]] = {}
    for row in partitioned.rows:
        by_group.setdefault(row.migration_id, set()).add(row.split_partition)

    assert all(len(partitions) == 1 for partitions in by_group.values())
    assert all(row.split_group_id == row.migration_id for row in partitioned.rows)
