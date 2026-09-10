import numpy as np
import pytest
from opentrace.evaluation.metrics import (
    expected_calibration_error,
    group_bootstrap_intervals,
    probabilistic_metrics,
    reliability_bins,
)
from opentrace.ml.pipeline import load_development_splits


def _rows():
    validation = load_development_splits().validation
    base = next(row for row in validation if row.ground_truth_label.value == "AFFECTED")
    return tuple(
        base.model_copy(
            update={
                "id": f"m9-toy-{index}",
                "migration_id": f"m9-migration-{index // 2}",
                "ground_truth_label": label,
                "ground_truth_impact_type": (
                    base.ground_truth_impact_type
                    if label.value == "AFFECTED"
                    else base.ground_truth_impact_type.__class__.UNAFFECTED
                ),
                "ground_truth_distance": 0 if label.value == "AFFECTED" else None,
                "ground_truth_path": (base.ground_truth_path if label.value == "AFFECTED" else ()),
            }
        )
        for index, label in enumerate(
            (
                base.ground_truth_label.__class__.UNAFFECTED,
                base.ground_truth_label.__class__.AFFECTED,
                base.ground_truth_label.__class__.UNAFFECTED,
                base.ground_truth_label.__class__.AFFECTED,
            )
        )
    )


def test_reliability_bins_and_ece_are_hand_computable() -> None:
    y_true = np.asarray([0, 0, 1, 1])
    probabilities = np.asarray([0.05, 0.15, 0.85, 0.95])

    bins = reliability_bins(y_true, probabilities, bin_count=2)

    assert [item.count for item in bins] == [2, 2]
    assert bins[0].mean_predicted_probability == pytest.approx(0.1)
    assert bins[0].observed_positive_rate == pytest.approx(0.0)
    assert expected_calibration_error(y_true, probabilities, bin_count=2) == pytest.approx(0.1)


def test_probability_metrics_reject_invalid_values_and_report_pr_auc() -> None:
    rows = _rows()
    metrics = probabilistic_metrics(rows, [0.1, 0.4, 0.2, 0.9])

    assert set(("brier", "ece", "log_loss", "pr_auc", "roc_auc")) <= metrics.keys()
    with pytest.raises(ValueError, match=r"within \[0, 1\]"):
        probabilistic_metrics(rows, [0.1, 1.2, 0.2, 0.9])


def test_group_bootstrap_is_migration_grouped_and_deterministic() -> None:
    rows = _rows()
    scores = np.asarray([0.1, 0.9, 0.8, 0.2])

    first = group_bootstrap_intervals(rows, scores, replicates=40, seed=7)
    second = group_bootstrap_intervals(rows, scores, replicates=40, seed=7)

    assert first == second
    assert first["recall_at_5"]["group_by"] == "migration_id"
    assert first["recall_at_5"]["replicates"] == 40
