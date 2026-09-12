"""RouteForge baseline policy, leakage, and reproducibility tests."""

from pathlib import Path

import pytest
from opentrace.routeforge.baselines import (
    FORBIDDEN_FEATURE_NAMES,
    MODEL_FEATURE_ALLOWLIST,
    RouteForgeFeatureEncoder,
    run_m12_baselines,
)
from opentrace.routeforge.serialization import read_artifacts


@pytest.fixture(scope="module")
def m12_result():
    return run_m12_baselines(Path("data/routeforge_scenarios"), None)


def test_required_baselines_and_development_semantics(m12_result) -> None:
    ids = [record["experiment_id"] for record in m12_result.experiments]
    assert ids == [
        "RF-B0-ALWAYS-SMALL",
        "RF-B1-ALWAYS-STRONG",
        "RF-B2-RANDOM",
        "RF-B3-RULE-V1",
        "RF-B4-LOGISTIC",
        "RF-B5-XGBOOST",
    ]
    for record in m12_result.experiments:
        metrics = record["policy_metrics"]
        assert metrics["offline_only"] is True
        assert metrics["cost_semantics"] == "SYNTHETIC_RELATIVE_UNITS"
        assert metrics["latency_semantics"] == "SYNTHETIC_RELATIVE_UNITS"
    rule = m12_result.experiments[3]
    assert rule["model_provenance"]["frozen_before_validation"] is True
    assert rule["model_provenance"]["policy_id"] == "RF-B3-RULE-V1"
    random_record = m12_result.experiments[2]
    assert random_record["reproducibility"] == {"repeat_match": True, "seed": 1201}


def test_train_support_and_outcome_states_are_preserved(m12_result) -> None:
    support = m12_result.train_support
    assert support["NO_AI"]["NOT_APPLICABLE"] == 5
    assert support["SMALL"]["UNKNOWN"] == 1
    assert support["SMALL"]["FAILURE"] == 3
    assert support["SMALL"]["SUCCESS"] == 1
    for strategy in ("DETERMINISTIC", "SMALL", "MEDIUM", "STRONG"):
        assert support[strategy]["NOT_APPLICABLE"] == 0


def test_unknown_not_applicable_and_no_feasible_remain_explicit(m12_result) -> None:
    dataset = read_artifacts(Path("data/routeforge_scenarios"))
    no_feasible = next(
        scenario for scenario in dataset.scenarios if scenario.scenario_id == "scenario-007"
    )
    assert no_feasible.preferred_strategy.value == "NO_FEASIBLE_STRATEGY"
    validation_predictions = [
        prediction
        for record in m12_result.experiments
        for prediction in record["validation_predictions"]
    ]
    assert any(
        prediction["outcome"] == "UNKNOWN" and prediction["target_eligible"] is False
        for prediction in validation_predictions
    )
    assert all(
        prediction["outcome"] != "FAILURE" or prediction["target_eligible"] is True
        for prediction in validation_predictions
    )


def test_feature_allowlist_and_train_only_preprocessing() -> None:
    dataset = read_artifacts(Path("data/routeforge_scenarios"))
    train_rows = tuple(
        row
        for row in dataset.rows
        if row.split_partition.value == "TRAIN"
        and row.outcome.value in {"SUCCESS", "FAILURE"}
        and row.strategy.value != "NO_AI"
    )
    encoder = RouteForgeFeatureEncoder().fit(train_rows)
    metadata = encoder.metadata()
    assert tuple(metadata["allowlist"]) == MODEL_FEATURE_ALLOWLIST
    assert metadata["fit_partition"] == "TRAIN"
    names = set(metadata["expanded_feature_names"])
    assert not any(forbidden in names for forbidden in FORBIDDEN_FEATURE_NAMES)
    assert set(metadata["strategy_identity"]) == {
        "NO_AI",
        "DETERMINISTIC",
        "SMALL",
        "MEDIUM",
        "STRONG",
    }


def test_group_safe_splits_test_sealing_and_reproducibility(m12_result) -> None:
    assert m12_result.split_counts == {
        "TRAIN": {"decision_groups": 5, "strategy_rows": 25},
        "VALIDATION": {"decision_groups": 3, "strategy_rows": 15},
        "TEST": {"decision_groups": 1, "strategy_rows": 5},
    }
    summary = m12_result.summary()
    assert summary["test_used_for_model_selection"] is False
    assert summary["test_evaluated"] is False
    repeat = run_m12_baselines(Path("data/routeforge_scenarios"), None)
    assert repeat.reproducibility_fingerprint == m12_result.reproducibility_fingerprint
