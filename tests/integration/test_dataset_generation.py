from collections import Counter

import pytest
from opentrace.datasets import (
    GeneratorConfig,
    GroundTruthImpactType,
    GroundTruthLabel,
    ScenarioFamily,
    duplicate_counts,
    generate_dataset,
    validate_dataset,
)
from opentrace.datasets.scenarios import MUTATION_FAMILIES


@pytest.fixture(scope="module")
def dataset():
    return generate_dataset(GeneratorConfig(seed=42, synthetic_scenarios=10))


def test_m7_contains_required_families_mutations_and_labels(dataset) -> None:
    validate_dataset(dataset)
    assert {scenario.family for scenario in dataset.scenarios} == set(ScenarioFamily)
    assert {scenario.mutation_family for scenario in dataset.scenarios} == set(MUTATION_FAMILIES)
    assert {row.ground_truth_label for row in dataset.rows} == {
        GroundTruthLabel.AFFECTED,
        GroundTruthLabel.UNAFFECTED,
    }
    assert {row.ground_truth_impact_type for row in dataset.rows} >= {
        GroundTruthImpactType.DIRECT,
        GroundTruthImpactType.INDIRECT,
        GroundTruthImpactType.UNAFFECTED,
    }
    assert any(row.hard_negative for row in dataset.rows)
    assert any(row.hard_positive for row in dataset.rows)
    assert any(row.error_flags for row in dataset.rows)


def test_m7_manifest_and_coverage_are_inspectable(dataset) -> None:
    manifest = dataset.manifest
    assert manifest.scenario_count == 26
    assert manifest.migration_count == 26
    assert manifest.row_count == len(dataset.rows) > 0
    assert manifest.positive_count + manifest.negative_count == manifest.row_count
    assert manifest.direct_count + manifest.indirect_count <= manifest.positive_count
    assert manifest.evidence_exact + manifest.evidence_partial + manifest.evidence_unresolved == (
        manifest.row_count
    )
    assert manifest.scenario_duplicates == 0
    assert manifest.row_duplicates == 0
    assert duplicate_counts(dataset) == (0, 0)
    assert Counter(row.family for row in dataset.rows)
