"""Deterministic grouped validation ranking metrics."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

import numpy as np
from sklearn.metrics import (  # type: ignore[import-untyped]
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

from opentrace.datasets.models import ImpactDatasetRow
from opentrace.ml.models import ValidationPrediction


@dataclass(frozen=True)
class RankingMetrics:
    precision_at_5: float
    recall_at_5: float
    precision_at_10: float
    recall_at_10: float
    mrr: float
    ndcg_at_5: float
    ndcg_at_10: float
    groups: int

    def as_dict(self) -> dict[str, float]:
        return {
            "precision_at_5": self.precision_at_5,
            "recall_at_5": self.recall_at_5,
            "precision_at_10": self.precision_at_10,
            "recall_at_10": self.recall_at_10,
            "mrr": self.mrr,
            "ndcg_at_5": self.ndcg_at_5,
            "ndcg_at_10": self.ndcg_at_10,
            "ranking_groups": float(self.groups),
        }


def _ordered(rows: list[tuple[ImpactDatasetRow, float]]) -> list[tuple[ImpactDatasetRow, float]]:
    return sorted(rows, key=lambda item: (-item[1], item[0].candidate_symbol_id, item[0].id))


def _ndcg(labels: list[int], k: int) -> float:
    observed = labels[:k]
    dcg = sum(label / math.log2(index + 2) for index, label in enumerate(observed))
    ideal = sum(1 / math.log2(index + 2) for index in range(min(k, sum(labels))))
    return dcg / ideal if ideal else 0.0


def compute_ranking_metrics(
    rows: tuple[ImpactDatasetRow, ...], scores: np.ndarray
) -> RankingMetrics:
    if len(rows) != len(scores) or not rows:
        raise ValueError("ranking metrics need equally sized, non-empty validation rows and scores")
    groups: dict[str, list[tuple[ImpactDatasetRow, float]]] = defaultdict(list)
    for row, score in zip(rows, scores, strict=True):
        groups[row.migration_id].append((row, float(score)))
    p5: list[float] = []
    r5: list[float] = []
    p10: list[float] = []
    r10: list[float] = []
    mrr: list[float] = []
    ndcg5: list[float] = []
    ndcg10: list[float] = []
    for candidates in groups.values():
        ordered = _ordered(candidates)
        labels = [int(row.ground_truth_label.value == "AFFECTED") for row, _ in ordered]
        positives = sum(labels)
        top5 = labels[: min(5, len(labels))]
        top10 = labels[: min(10, len(labels))]
        p5.append(sum(top5) / len(top5))
        p10.append(sum(top10) / len(top10))
        r5.append(sum(top5) / positives if positives else 0.0)
        r10.append(sum(top10) / positives if positives else 0.0)
        first = next((index + 1 for index, label in enumerate(labels) if label), None)
        mrr.append(1 / first if first is not None else 0.0)
        ndcg5.append(_ndcg(labels, 5))
        ndcg10.append(_ndcg(labels, 10))
    return RankingMetrics(
        precision_at_5=float(np.mean(p5)),
        recall_at_5=float(np.mean(r5)),
        precision_at_10=float(np.mean(p10)),
        recall_at_10=float(np.mean(r10)),
        mrr=float(np.mean(mrr)),
        ndcg_at_5=float(np.mean(ndcg5)),
        ndcg_at_10=float(np.mean(ndcg10)),
        groups=len(groups),
    )


def predictions(
    experiment_id: str,
    rows: tuple[ImpactDatasetRow, ...],
    scores: np.ndarray,
) -> tuple[ValidationPrediction, ...]:
    grouped: dict[str, list[tuple[ImpactDatasetRow, float]]] = defaultdict(list)
    for row, score in zip(rows, scores, strict=True):
        grouped[row.migration_id].append((row, float(score)))
    output: list[ValidationPrediction] = []
    for group in sorted(grouped):
        for rank, (row, score) in enumerate(_ordered(grouped[group]), start=1):
            output.append(
                ValidationPrediction(
                    experiment_id=experiment_id,
                    row_id=row.id,
                    ranking_group=group,
                    ground_truth_label=row.ground_truth_label.value,
                    score=score,
                    rank=rank,
                )
            )
    return tuple(output)


def classification_metrics(
    rows: tuple[ImpactDatasetRow, ...], scores: np.ndarray
) -> dict[str, float]:
    y_true = np.array([row.ground_truth_label.value == "AFFECTED" for row in rows], dtype=int)
    y_pred = (scores >= 0.5).astype(int)
    result = {
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
    }
    if len(np.unique(y_true)) == 2:
        result["roc_auc"] = float(roc_auc_score(y_true, scores))
    return result
