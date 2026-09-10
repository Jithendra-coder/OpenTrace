import json
from pathlib import Path

import pytest
from opentrace.ml import load_development_splits, run_m8_experiments


@pytest.fixture(scope="module")
def m8_run(tmp_path_factory):
    return run_m8_experiments(output_directory=tmp_path_factory.mktemp("m8-artifacts"))


def test_real_m8_experiments_train_and_persist_validation_artifacts(m8_run) -> None:
    assert [record.experiment_id for record in m8_run.experiments] == [
        "E1-heuristic-v1",
        "E2-logistic-structural-v1",
        "E3-logistic-heuristics-v1",
        "E4-random-forest-v1",
        "E5-xgboost-v1",
    ]
    assert all(not record.test_used for record in m8_run.experiments)
    assert all(Path(path).exists() for path in m8_run.validation_prediction_files)
    assert all(Path(path).exists() for path in m8_run.model_files)

    validation = json.loads(Path(m8_run.metrics_file).read_text(encoding="utf-8"))
    assert validation["test_metrics"] == "SEALED_FOR_M9_NOT_COMPUTED"
    assert set(validation["validation_development_metrics"]) >= {
        "E1-heuristic-v1",
        "E2-logistic-structural-v1",
        "E3-logistic-heuristics-v1",
        "E4-random-forest-v1",
        "E5-xgboost-v1",
    }
    assert validation["label_shuffle_sanity"]["roc_auc"] < validation[
        "validation_development_metrics"
    ]["E2-logistic-structural-v1"]["roc_auc"]


def test_test_partition_is_not_loaded_by_m8_selection_logic() -> None:
    splits = load_development_splits()

    assert splits.integrity.test.rows > 0
    assert splits.integrity.test.positives is None
    assert splits.integrity.test.negatives is None


def test_reproduction_preserves_artifact_documentation(tmp_path) -> None:
    output = tmp_path / "m8"
    output.mkdir()
    readme = output / "README.md"
    readme.write_text("documentation", encoding="utf-8")

    run_m8_experiments(output_directory=output)

    assert readme.read_text(encoding="utf-8") == "documentation"
