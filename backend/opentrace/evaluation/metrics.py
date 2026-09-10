"""Small, deterministic metrics used only by the formal M9 evaluator."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

import numpy as np
from sklearn.metrics import (  # type: ignore[import-untyped]
    average_precision_score,
    log_loss,
    precision_score,
    recall_score,
    roc_auc_score,
)

from opentrace.datasets.models import GroundTruthLabel, ImpactDatasetRow

ECE_BIN_COUNT = 10


def _probabilities(values: np.ndarray | list[float], *, name: str = "probabilities") -> np.ndarray:
    result = np.asarray(values, dtype=float)
    if result.ndim != 1 or not np.all(np.isfinite(result)):
        raise ValueError(f"{name} must be a finite one-dimensional array")
    if np.any(result < 0.0) or np.any(result > 1.0):
        raise ValueError(f"{name} must be within [0, 1]")
    return result


def _binary_labels(rows: tuple[ImpactDatasetRow, ...] | list[ImpactDatasetRow]) -> np.ndarray:
    return np.asarray(
        [row.ground_truth_label is GroundTruthLabel.AFFECTED for row in rows], dtype=int
    )


@dataclass(frozen=True)
class ReliabilityBin:
    lower: float
    upper: float
    count: int
    mean_predicted_probability: float | None
    observed_positive_rate: float | None

    def as_dict(self) -> dict[str, float | int | None]:
        return {
            "lower": self.lower,
            "upper": self.upper,
            "count": self.count,
            "mean_predicted_probability": self.mean_predicted_probability,
            "observed_positive_rate": self.observed_positive_rate,
        }


def reliability_bins(
    labels: np.ndarray | list[int],
    probabilities: np.ndarray | list[float],
    *,
    bin_count: int = ECE_BIN_COUNT,
) -> tuple[ReliabilityBin, ...]:
    if bin_count < 1:
        raise ValueError("bin_count must be positive")
    y_true = np.asarray(labels, dtype=int)
    probs = _probabilities(probabilities)
    if y_true.ndim != 1 or len(y_true) != len(probs) or np.any(~np.isin(y_true, (0, 1))):
        raise ValueError("labels must be binary and match probabilities")
    edges = np.linspace(0.0, 1.0, bin_count + 1)
    bins: list[ReliabilityBin] = []
    for index in range(bin_count):
        lower = float(edges[index])
        upper = float(edges[index + 1])
        mask = (probs >= lower) & ((probs < upper) if index < bin_count - 1 else (probs <= upper))
        count = int(np.sum(mask))
        bins.append(
            ReliabilityBin(
                lower=lower,
                upper=upper,
                count=count,
                mean_predicted_probability=(float(np.mean(probs[mask])) if count else None),
                observed_positive_rate=(float(np.mean(y_true[mask])) if count else None),
            )
        )
    return tuple(bins)


def expected_calibration_error(
    labels: np.ndarray | list[int],
    probabilities: np.ndarray | list[float],
    *,
    bin_count: int = ECE_BIN_COUNT,
) -> float:
    bins = reliability_bins(labels, probabilities, bin_count=bin_count)
    total = sum(item.count for item in bins)
    if not total:
        raise ValueError("ECE requires at least one observation")
    return float(
        sum(
            item.count * abs(item.mean_predicted_probability - item.observed_positive_rate)
            for item in bins
            if item.count
            and item.mean_predicted_probability is not None
            and item.observed_positive_rate is not None
        )
        / total
    )


def probabilistic_metrics(
    rows: tuple[ImpactDatasetRow, ...] | list[ImpactDatasetRow],
    probabilities: np.ndarray | list[float],
    *,
    bin_count: int = ECE_BIN_COUNT,
) -> dict[str, float]:
    if not rows:
        raise ValueError("probabilistic metrics require non-empty rows")
    probs = _probabilities(probabilities)
    if len(rows) != len(probs):
        raise ValueError("rows and probabilities must have equal lengths")
    y_true = _binary_labels(rows)
    result = {
        "brier": float(np.mean((probs - y_true) ** 2)),
        "ece": expected_calibration_error(y_true, probs, bin_count=bin_count),
        "log_loss": float(log_loss(y_true, probs, labels=(0, 1))),
    }
    if len(np.unique(y_true)) == 2:
        result["roc_auc"] = float(roc_auc_score(y_true, probs))
        result["pr_auc"] = float(average_precision_score(y_true, probs))
    return result


def classification_metrics(
    rows: tuple[ImpactDatasetRow, ...] | list[ImpactDatasetRow],
    scores: np.ndarray | list[float],
    *,
    threshold: float = 0.5,
) -> dict[str, float]:
    if not rows:
        raise ValueError("classification metrics require non-empty rows")
    values = np.asarray(scores, dtype=float)
    if values.ndim != 1 or len(rows) != len(values):
        raise ValueError("rows and scores must have equal one-dimensional lengths")
    y_true = _binary_labels(rows)
    y_pred = (values >= threshold).astype(int)
    result = {
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(
            2
            * precision_score(y_true, y_pred, zero_division=0)
            * recall_score(y_true, y_pred, zero_division=0)
            / (
                precision_score(y_true, y_pred, zero_division=0)
                + recall_score(y_true, y_pred, zero_division=0)
                or 1.0
            )
        ),
    }
    if len(np.unique(y_true)) == 2:
        result["roc_auc"] = float(roc_auc_score(y_true, values))
        result["pr_auc"] = float(average_precision_score(y_true, values))
    return result


def _group_values(
    rows: tuple[ImpactDatasetRow, ...],
    scores: np.ndarray,
) -> tuple[dict[str, float], ...]:
    groups: dict[str, list[tuple[ImpactDatasetRow, float]]] = defaultdict(list)
    for row, score in zip(rows, scores, strict=True):
        groups[row.migration_id].append((row, float(score)))
    result: list[dict[str, float]] = []
    for candidates in groups.values():
        ordered = sorted(
            candidates,
            key=lambda item: (-item[1], item[0].candidate_symbol_id, item[0].id),
        )
        y = [int(row.ground_truth_label is GroundTruthLabel.AFFECTED) for row, _ in ordered]
        positives = sum(y)

        def ndcg(k: int, labels_for_group: list[int] = y, positive_count: int = positives) -> float:
            observed = labels_for_group[:k]
            dcg = sum(label / math.log2(index + 2) for index, label in enumerate(observed))
            ideal = sum(1 / math.log2(index + 2) for index in range(min(k, positive_count)))
            return dcg / ideal if ideal else 0.0

        top5 = y[:5]
        top10 = y[:10]
        first = next((index + 1 for index, label in enumerate(y) if label), None)
        result.append(
            {
                "precision_at_5": sum(top5) / len(top5),
                "recall_at_5": sum(top5) / positives if positives else 0.0,
                "precision_at_10": sum(top10) / len(top10),
                "recall_at_10": sum(top10) / positives if positives else 0.0,
                "mrr": 1 / first if first is not None else 0.0,
                "ndcg_at_5": ndcg(5),
                "ndcg_at_10": ndcg(10),
            }
        )
    return tuple(result)


def group_bootstrap_intervals(
    rows: tuple[ImpactDatasetRow, ...],
    scores: np.ndarray,
    *,
    replicates: int = 1000,
    seed: int = 42,
) -> dict[str, dict[str, float | int | str]]:
    if replicates < 1:
        raise ValueError("replicates must be positive")
    if len(rows) != len(scores) or not rows:
        raise ValueError("bootstrap requires equally sized, non-empty rows and scores")
    values = _group_values(rows, np.asarray(scores, dtype=float))
    if not values:
        raise ValueError("bootstrap requires at least one migration group")
    metric_names = tuple(values[0])
    point = {name: float(np.mean([item[name] for item in values])) for name in metric_names}
    rng = np.random.default_rng(seed)
    samples = np.asarray([[item[name] for item in values] for name in metric_names], dtype=float)
    intervals: dict[str, dict[str, float | int | str]] = {}
    for index, name in enumerate(metric_names):
        draws = np.empty(replicates, dtype=float)
        for replicate in range(replicates):
            sample_indices = rng.integers(0, len(values), size=len(values))
            draws[replicate] = float(np.mean(samples[index, sample_indices]))
        intervals[name] = {
            "estimate": point[name],
            "lower": float(np.quantile(draws, 0.025)),
            "upper": float(np.quantile(draws, 0.975)),
            "replicates": replicates,
            "seed": seed,
            "group_by": "migration_id",
        }
    return intervals
