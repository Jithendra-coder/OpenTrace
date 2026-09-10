import pytest
from opentrace.datasets.models import GroundTruthImpactType, GroundTruthLabel
from opentrace.ml.metrics import compute_ranking_metrics, predictions
from opentrace.ml.pipeline import load_development_splits


def _toy_rows():
    base = load_development_splits().validation[0]
    labels = (
        GroundTruthLabel.AFFECTED,
        GroundTruthLabel.UNAFFECTED,
        GroundTruthLabel.AFFECTED,
        GroundTruthLabel.UNAFFECTED,
    )
    return tuple(
        base.model_copy(
            update={
                "id": f"toy-{index}",
                "candidate_symbol_id": f"symbol-{3 - index}",
                "candidate_symbol": f"toy.py::symbol_{index}",
                "migration_id": "toy-migration",
                "ground_truth_label": label,
                "ground_truth_impact_type": (
                    GroundTruthImpactType.DIRECT
                    if label is GroundTruthLabel.AFFECTED
                    else GroundTruthImpactType.UNAFFECTED
                ),
                "ground_truth_distance": 0 if label is GroundTruthLabel.AFFECTED else None,
                "ground_truth_path": (
                    (f"toy.py::symbol_{index}",)
                    if label is GroundTruthLabel.AFFECTED
                    else ()
                ),
            }
        )
        for index, label in enumerate(labels)
    )


def test_grouped_ranking_metrics_are_hand_computable() -> None:
    rows = _toy_rows()
    metrics = compute_ranking_metrics(rows, [0.9, 0.8, 0.7, 0.6])

    assert metrics.precision_at_5 == 0.5
    assert metrics.recall_at_5 == 1.0
    assert metrics.precision_at_10 == 0.5
    assert metrics.recall_at_10 == 1.0
    assert metrics.mrr == 1.0
    assert metrics.ndcg_at_5 == pytest.approx(0.9197207891)
    assert metrics.ndcg_at_10 == pytest.approx(0.9197207891)


def test_ties_use_candidate_symbol_id_not_input_order() -> None:
    rows = _toy_rows()
    ranked = predictions("E-test", rows, [1.0, 1.0, 1.0, 1.0])

    assert [item.row_id for item in ranked] == ["toy-3", "toy-2", "toy-1", "toy-0"]
    assert [item.rank for item in ranked] == [1, 2, 3, 4]
