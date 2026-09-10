import json
from pathlib import Path

import pytest
from opentrace.evaluation import run_m9_evaluation
from opentrace.ml import load_development_splits


@pytest.fixture(scope="module")
def m9_run(tmp_path_factory):
    return run_m9_evaluation(output_directory=tmp_path_factory.mktemp("m9-artifacts"))


def test_formal_m9_artifacts_cover_frozen_test_evaluation(m9_run) -> None:
    metrics = json.loads(Path(m9_run.test_metrics).read_text(encoding="utf-8"))
    pre_test = json.loads(Path(m9_run.pre_test_manifest).read_text(encoding="utf-8"))
    formal = json.loads(Path(m9_run.formal_manifest).read_text(encoding="utf-8"))

    assert metrics["test_distribution"]["rows"] == 70
    assert metrics["test_distribution"]["positives"] == 21
    assert metrics["split_integrity"]["migration_overlap"] == {
        "TRAIN_TEST": 0,
        "TRAIN_VALIDATION": 0,
        "VALIDATION_TEST": 0,
    }
    assert set(metrics["test_ranking_metrics"]) == {
        "B0_HEURISTIC",
        "B1_LOGISTIC_A",
        "B2_LOGISTIC_B",
        "B3_RANDOM_FOREST",
        "B4_XGBOOST",
    }
    assert pre_test["test_accessed"] is False
    assert pre_test["primary_model"]["experiment_id"] == "E2-logistic-structural-v1"
    assert formal["test_accessed"] is True
    assert metrics["calibration"]["fit_partition"] == "VALIDATION"
    assert metrics["calibration"]["test_used_for_fit"] is False
    assert metrics["calibration"]["raw_uncalibrated"]["brier"] >= 0.0
    assert metrics["calibration"]["calibrated"]["ece"] >= 0.0
    assert all(
        "top_ranked_candidates" in group for group in metrics["per_group_results"]["B1_LOGISTIC_A"]
    )


def test_formal_predictions_have_no_source_contents_and_m8_stays_sealed(m9_run) -> None:
    prediction_lines = Path(m9_run.predictions).read_text(encoding="utf-8").splitlines()
    assert len(prediction_lines) == 70 * 5
    first = json.loads(prediction_lines[0])
    assert set(first) >= {
        "row_id",
        "ranking_group_id",
        "ground_truth_label",
        "raw_model_score",
        "rank",
    }
    assert "source" not in first
    splits = load_development_splits()
    assert splits.integrity.test.positives is None
    with pytest.raises(RuntimeError, match="sealed"):
        _ = splits.test_rows


def test_formal_m9_artifacts_are_immutable(m9_run) -> None:
    with pytest.raises(FileExistsError, match="immutable"):
        run_m9_evaluation(output_directory=m9_run.output_directory)
