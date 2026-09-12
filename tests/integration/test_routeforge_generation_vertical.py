"""RouteForge real canonical feature extraction and artifact generation."""

from pathlib import Path

from opentrace.routeforge import (
    FeatureOrigin,
    RouteForgeDatasetGenerator,
    RouteForgeStrategy,
    StrategyOutcomeStatus,
    read_artifacts,
)

ROOT = Path(__file__).parents[2]


def test_canonical_routeforge_artifact_consumes_real_m10_evidence() -> None:
    dataset = RouteForgeDatasetGenerator().generate()
    scenario = next(item for item in dataset.scenarios if item.scenario_id == "scenario-001")
    assert scenario.context.feature_origin is FeatureOrigin.OBSERVED_M1_M10
    assert scenario.context.features.m10_outcome == "DETERMINISTIC_CANDIDATE"
    assert scenario.context.features.m10_repairability == "SUPPORTED"
    assert scenario.context.features.expected_edit_count == 1
    assert scenario.context.m10_evidence.rule_id == "remove-request-property-v1"
    deterministic = next(
        item
        for item in scenario.outcomes
        if item.strategy is RouteForgeStrategy.DETERMINISTIC
    )
    assert deterministic.outcome is StrategyOutcomeStatus.UNKNOWN


def test_checked_in_m11_artifact_roundtrips() -> None:
    artifact = read_artifacts(ROOT / "data" / "routeforge_scenarios")
    assert artifact.manifest.dataset_version == "routeforge-dataset-v1"
    assert len(artifact.scenarios) == 9
    assert len(artifact.rows) == 45
