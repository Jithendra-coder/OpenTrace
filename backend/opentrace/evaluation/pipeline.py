"""M9 formal evaluator: frozen baselines, held-out TEST, and calibration."""

from __future__ import annotations

import hashlib
import json
import pickle
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
try:
    from datetime import UTC
except ImportError:
    UTC = timezone.utc
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]

from opentrace.datasets import assign_group_partitions
from opentrace.datasets.models import (
    DATASET_REMEDIATION_VERSION,
    DATASET_SCHEMA_VERSION,
    DATASET_V3_VERSION,
    DATASET_VERSION,
    DatasetManifest,
    GroundTruthImpactType,
    GroundTruthLabel,
    ImpactDatasetRow,
)
from opentrace.evaluation.chronology import ChronologyLog, ChronologyState
from opentrace.evaluation.metrics import (
    ECE_BIN_COUNT,
    classification_metrics,
    group_bootstrap_intervals,
    probabilistic_metrics,
    reliability_bins,
)
from opentrace.evaluation.models import M9RunResult
from opentrace.ml.features import FeatureEncoder, labels
from opentrace.ml.metrics import compute_ranking_metrics
from opentrace.ml.pipeline import _read_dataset

M9_EVALUATION_SCHEMA_VERSION = "impact-evaluation-m9-v1"
M9_CALIBRATION_SCHEMA_VERSION = "impact-calibration-m9-v1"
FORMAL_EVALUATION_ID = "impact-eval-m9-v1"
PRIMARY_MODEL_ID = "E2-logistic-structural-v1"
BASELINE_IDS = {
    "B0_HEURISTIC": "E1-heuristic-v1",
    "B1_LOGISTIC_A": "E2-logistic-structural-v1",
    "B2_LOGISTIC_B": "E3-logistic-heuristics-v1",
    "B3_RANDOM_FOREST": "E4-random-forest-v1",
    "B4_XGBOOST": "E5-xgboost-v1",
}
BOOTSTRAP_REPLICATES = 1000
BOOTSTRAP_SEED = 42
SPLIT_SEED = 42
MODEL_SEED = 42


@dataclass(frozen=True)
class FormalSplits:
    train: tuple[ImpactDatasetRow, ...]
    validation: tuple[ImpactDatasetRow, ...]
    test: tuple[ImpactDatasetRow, ...]
    integrity: dict[str, Any]


@dataclass(frozen=True)
class FrozenModel:
    model: Any
    encoder: FeatureEncoder
    metadata: dict[str, Any]
    binary_checksum: str


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _write_immutable(path: Path, value: object | bytes) -> None:
    content = value if isinstance(value, bytes) else _json_bytes(value)
    if path.exists():
        if path.read_bytes() != content:
            raise FileExistsError(
                f"immutable M9 artifact already exists with different content: {path}"
            )
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest_only(dataset_directory: Path) -> DatasetManifest:
    manifest = DatasetManifest.model_validate_json(
        (dataset_directory / "manifest.json").read_text(encoding="utf-8")
    )
    if (
        manifest.schema_version != DATASET_SCHEMA_VERSION
        or manifest.dataset_version
        not in {DATASET_VERSION, DATASET_REMEDIATION_VERSION, DATASET_V3_VERSION}
    ):
        raise ValueError("unsupported M7 dataset version")
    return manifest


def _partition(rows: tuple[ImpactDatasetRow, ...], name: str) -> tuple[ImpactDatasetRow, ...]:
    return tuple(
        row for row in rows if row.split_partition is not None and row.split_partition.value == name
    )


def _count(rows: tuple[ImpactDatasetRow, ...], *, include_labels: bool = True) -> dict[str, Any]:
    return {
        "rows": len(rows),
        "migrations": len({row.migration_id for row in rows}),
        "positives": (
            sum(row.ground_truth_label is GroundTruthLabel.AFFECTED for row in rows)
            if include_labels
            else None
        ),
        "negatives": (
            sum(row.ground_truth_label is GroundTruthLabel.UNAFFECTED for row in rows)
            if include_labels
            else None
        ),
        "api_families": len({row.api_family_id for row in rows}),
        "repository_families": len({row.repository_family_id for row in rows}),
        "mutation_families": len({row.mutation_family for row in rows}),
    }


def _overlap(
    rows_a: tuple[ImpactDatasetRow, ...], rows_b: tuple[ImpactDatasetRow, ...], field: str
) -> int:
    return len(
        {getattr(row, field) for row in rows_a if getattr(row, field) is not None}
        & {getattr(row, field) for row in rows_b if getattr(row, field) is not None}
    )


def _formal_splits(dataset_directory: Path, split_seed: int) -> FormalSplits:
    loaded = _read_dataset(dataset_directory)
    dataset = (
        loaded
        if loaded.manifest.split_strategy == "clone-safe-component-round-robin-v2"
        else assign_group_partitions(loaded, seed=split_seed)
    )
    train = _partition(dataset.rows, "TRAIN")
    validation = _partition(dataset.rows, "VALIDATION")
    test = _partition(dataset.rows, "TEST")
    partitions = {"TRAIN": train, "VALIDATION": validation, "TEST": test}
    migration_overlap = {
        f"{left}_{right}": _overlap(partitions[left], partitions[right], "migration_id")
        for left, right in (("TRAIN", "VALIDATION"), ("TRAIN", "TEST"), ("VALIDATION", "TEST"))
    }
    overlap_fields = ["repository_family_id", "api_family_id", "scenario_id", "mutation_family"]
    if loaded.manifest.split_strategy == "clone-safe-component-round-robin-v2":
        overlap_fields.extend(
            [
                "source_fingerprint",
                "candidate_fingerprint",
                "structural_input_fingerprint",
                "heuristic_input_fingerprint",
                "template_family_id",
            ]
        )
    other_overlap = {
        field: {
            f"{left}_{right}": _overlap(partitions[left], partitions[right], field)
            for left, right in (("TRAIN", "VALIDATION"), ("TRAIN", "TEST"), ("VALIDATION", "TEST"))
        }
        for field in overlap_fields
    }
    if any(migration_overlap.values()):
        raise ValueError("M9 migration groups cross partitions")
    return FormalSplits(
        train=train,
        validation=validation,
        test=test,
        integrity={
            "split_version": loaded.manifest.split_strategy or "migration-id-hash-v1",
            "split_fingerprint": loaded.manifest.split_fingerprint,
            "group_by": "migration_id",
            "split_seed": split_seed,
            "TRAIN": _count(train),
            "VALIDATION": _count(validation),
            "TEST": _count(test),
            "migration_overlap": migration_overlap,
            "other_group_overlap": other_overlap,
        },
    )


def _model_metadata(m8_directory: Path, experiment_id: str) -> tuple[dict[str, Any], Path, str]:
    model_path = (m8_directory / "models" / f"{experiment_id}.pkl").resolve()
    metadata_path = (m8_directory / "models" / f"{experiment_id}.json").resolve()
    root = m8_directory.resolve()
    if root not in model_path.parents or root not in metadata_path.parents:
        raise ValueError("M8 artifact path escaped the trusted local artifact directory")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("trusted_local_artifact_only") is not True:
        raise ValueError("M8 model artifact is not marked trusted-local-only")
    if (
        metadata.get("training_partition") != "TRAIN"
        or metadata.get("validation_partition") != "VALIDATION"
    ):
        raise ValueError("M8 model provenance has unexpected partitions")
    if metadata.get("test_used") is not False:
        raise ValueError("M8 model was trained with TEST")
    return metadata, model_path, _sha256(model_path)


def _pre_test_manifest(
    dataset_directory: Path,
    m8_directory: Path,
    output: Path,
    *,
    seed: int,
    split_seed: int,
    evaluation_id: str,
    protocol_checksum: str | None = None,
    historical_exclusion_fingerprint: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    dataset_manifest = _manifest_only(dataset_directory)
    models: dict[str, Any] = {}
    for baseline, experiment_id in BASELINE_IDS.items():
        if baseline == "B0_HEURISTIC":
            models[baseline] = {
                "experiment_id": experiment_id,
                "artifact": "deterministic M4 impact score",
            }
            continue
        metadata, model_path, checksum = _model_metadata(m8_directory, experiment_id)
        metadata_path = (m8_directory / "models" / f"{experiment_id}.json").resolve()
        models[baseline] = {
            "experiment_id": experiment_id,
            "model_type": metadata["model_type"],
            "feature_set": metadata["feature_schema"]["feature_set"],
            "parameters": metadata["parameters"],
            "preprocessor": metadata["feature_schema"],
            "binary_path": str(
                (m8_directory / "models" / f"{experiment_id}.pkl").as_posix()
            ),
            "binary_checksum": checksum,
            "metadata_checksum": _sha256(metadata_path),
        }
    manifest = {
        "schema_version": M9_EVALUATION_SCHEMA_VERSION,
        "evaluation_id": evaluation_id,
        "protocol_checksum": protocol_checksum,
        "historical_exclusion_fingerprint": historical_exclusion_fingerprint,
        "created": date.today().isoformat(),
        "dataset_version": dataset_manifest.dataset_version,
        "dataset_schema": dataset_manifest.schema_version,
        "dataset_checksum": dataset_manifest.content_sha256,
        "split_strategy": dataset_manifest.split_strategy or "migration-id-hash-v1:migration_id",
        "split_fingerprint": dataset_manifest.split_fingerprint,
        "split_seed": split_seed,
        "training_seed": seed,
        "primary_model": {
            "experiment_id": PRIMARY_MODEL_ID,
            "name": "Logistic Regression",
            "feature_set": "A_STRUCTURAL",
            "reason": (
                "Pre-registered before TEST: tied for best M8 validation ranking, "
                "simpler and interpretable."
            ),
        },
        "comparison_baselines": models,
        "calibration": {
            "primary_method": "platt_sigmoid",
            "fit_partition": "VALIDATION",
            "test_partition": "TEST",
            "parameters": {"C": 1.0, "max_iter": 1000, "solver": "lbfgs", "seed": seed},
        },
        "ece_policy": {
            "bin_count": ECE_BIN_COUNT,
            "binning": "equal_width",
            "edges": [index / ECE_BIN_COUNT for index in range(ECE_BIN_COUNT + 1)],
            "acceptance": "calibrated Brier, ECE, and log loss no worse than raw, with ECE <= 0.10",
        },
        "bootstrap_policy": {
            "group_by": "migration_id",
            "replicates": BOOTSTRAP_REPLICATES,
            "seed": BOOTSTRAP_SEED,
            "interval": "percentile_95",
        },
        "test_accessed": False,
    }
    path = output / "manifests" / "pre_test.json"
    _write_immutable(path, manifest)
    return path, manifest


def _load_model(
    m8_directory: Path,
    experiment_id: str,
    expected_checksum: str,
    expected_metadata_checksum: str,
) -> FrozenModel:
    metadata, model_path, checksum = _model_metadata(m8_directory, experiment_id)
    if checksum != expected_checksum:
        raise ValueError(f"M8 model checksum changed after pre-test freeze: {experiment_id}")
    metadata_path = (m8_directory / "models" / f"{experiment_id}.json").resolve()
    if _sha256(metadata_path) != expected_metadata_checksum:
        raise ValueError(f"M8 model metadata changed after pre-test freeze: {experiment_id}")
    import sys
    import opentrace
    import opentrace.ml.features
    sys.modules.setdefault("specimpact", opentrace)
    sys.modules.setdefault("changemesh", opentrace)
    sys.modules.setdefault("specimpact.ml.features", opentrace.ml.features)
    sys.modules.setdefault("specimpact.ml", opentrace.ml)
    sys.modules.setdefault("changemesh.ml.features", opentrace.ml.features)
    sys.modules.setdefault("changemesh.ml", opentrace.ml)
    payload = pickle.loads(model_path.read_bytes())
    encoder = payload.get("encoder") if isinstance(payload, dict) else None
    if not isinstance(payload, dict) or (
        not isinstance(encoder, FeatureEncoder)
        and getattr(encoder, "__class__", None).__name__ != "FeatureEncoder"
    ):
        raise ValueError(f"invalid trusted M8 model payload: {experiment_id}")
    return FrozenModel(payload["model"], encoder, metadata, checksum)


def _scores(frozen: FrozenModel, rows: tuple[ImpactDatasetRow, ...]) -> np.ndarray:
    matrix = frozen.encoder.transform(list(rows))
    model = frozen.model
    if not hasattr(model, "predict_proba"):
        raise ValueError("M9 requires frozen classifiers exposing predict_proba")
    values = np.asarray(model.predict_proba(matrix)[:, 1], dtype=float)
    if not np.all(np.isfinite(values)) or np.any(values < 0.0) or np.any(values > 1.0):
        raise ValueError("frozen model emitted an invalid score")
    return values


def _heuristic_scores(rows: tuple[ImpactDatasetRow, ...]) -> np.ndarray:
    return np.asarray([row.features.m4_impact_score or 0.0 for row in rows], dtype=float)


def _ranking(rows: tuple[ImpactDatasetRow, ...], scores: np.ndarray) -> dict[str, float]:
    return compute_ranking_metrics(rows, scores).as_dict()


def _ranked_rows(
    rows: tuple[ImpactDatasetRow, ...], scores: np.ndarray
) -> dict[str, list[tuple[ImpactDatasetRow, float, int]]]:
    groups: dict[str, list[tuple[ImpactDatasetRow, float]]] = defaultdict(list)
    for row, score in zip(rows, scores, strict=True):
        groups[row.migration_id].append((row, float(score)))
    return {
        migration_id: [
            (row, score, rank)
            for rank, (row, score) in enumerate(
                sorted(
                    values, key=lambda item: (-item[1], item[0].candidate_symbol_id, item[0].id)
                ),
                start=1,
            )
        ]
        for migration_id, values in sorted(groups.items())
    }


def _per_group(rows: tuple[ImpactDatasetRow, ...], scores: np.ndarray) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for migration_id, ranked in _ranked_rows(rows, scores).items():
        positives = sum(row.ground_truth_label is GroundTruthLabel.AFFECTED for row, _, _ in ranked)
        top5 = ranked[:5]
        first = next(
            (
                rank
                for row, _, rank in ranked
                if row.ground_truth_label is GroundTruthLabel.AFFECTED
            ),
            None,
        )
        dcg = sum(
            int(row.ground_truth_label is GroundTruthLabel.AFFECTED) / np.log2(rank + 1)
            for row, _, rank in ranked[:5]
        )
        ideal = sum(1 / np.log2(index + 2) for index in range(min(5, positives)))
        output.append(
            {
                "migration_id": migration_id,
                "candidate_count": len(ranked),
                "positive_count": positives,
                "top_ranked_candidates": [
                    {
                        "candidate_symbol_id": row.candidate_symbol_id,
                        "candidate_symbol": row.candidate_symbol,
                        "score": score,
                        "label": row.ground_truth_label.value,
                        "rank": rank,
                    }
                    for row, score, rank in top5
                ],
                "recall_at_5": float(
                    sum(row.ground_truth_label is GroundTruthLabel.AFFECTED for row, _, _ in top5)
                    / positives
                    if positives
                    else 0.0
                ),
                "mrr": float(1 / first if first is not None else 0.0),
                "ndcg_at_5": float(dcg / ideal if ideal else 0.0),
            }
        )
    return output


def _slice_summary(
    rows: tuple[ImpactDatasetRow, ...], scores: np.ndarray, field: str
) -> dict[str, Any]:
    grouped: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        grouped[str(getattr(row, field))].append(index)
    result: dict[str, Any] = {}
    for key, indices in sorted(grouped.items()):
        subset = tuple(rows[index] for index in indices)
        subset_scores = scores[indices]
        result[key] = {
            "rows": len(subset),
            "migrations": len({row.migration_id for row in subset}),
            "ranking": _ranking(subset, subset_scores) if subset else None,
            "support": "sufficient"
            if len({row.migration_id for row in subset}) >= 2
            else "insufficient_for_stable_comparison",
        }
    return result


def _truth_rank_diagnostics(
    rows: tuple[ImpactDatasetRow, ...], scores: np.ndarray
) -> dict[str, Any]:
    ranked = _ranked_rows(rows, scores)
    result: dict[str, Any] = {}
    for name, predicate in (
        ("DIRECT", lambda row: row.ground_truth_impact_type is GroundTruthImpactType.DIRECT),
        ("INDIRECT", lambda row: row.ground_truth_impact_type is GroundTruthImpactType.INDIRECT),
        ("HARD_POSITIVE", lambda row: row.hard_positive),
        ("HARD_NEGATIVE", lambda row: row.hard_negative),
    ):
        selected = [
            (row, rank) for values in ranked.values() for row, _, rank in values if predicate(row)
        ]
        result[name] = {
            "count": len(selected),
            "top_5_rate": float(sum(rank <= 5 for _, rank in selected) / len(selected))
            if selected
            else None,
            "top_10_rate": float(sum(rank <= 10 for _, rank in selected) / len(selected))
            if selected
            else None,
            "mean_rank": float(np.mean([rank for _, rank in selected])) if selected else None,
        }
    return result


def _distance_diagnostics(rows: tuple[ImpactDatasetRow, ...], scores: np.ndarray) -> dict[str, Any]:
    ranked = _ranked_rows(rows, scores)
    result: dict[str, Any] = {}
    for values in ranked.values():
        for row, _, rank in values:
            if (
                row.ground_truth_label is not GroundTruthLabel.AFFECTED
                or row.ground_truth_distance is None
            ):
                continue
            key = str(row.ground_truth_distance) if row.ground_truth_distance < 3 else "3+"
            bucket = result.setdefault(key, {"count": 0, "top_5": 0, "top_10": 0})
            bucket["count"] += 1
            bucket["top_5"] += int(rank <= 5)
            bucket["top_10"] += int(rank <= 10)
    for bucket in result.values():
        bucket["recall_at_5"] = bucket["top_5"] / bucket["count"]
        bucket["recall_at_10"] = bucket["top_10"] / bucket["count"]
        del bucket["top_5"]
        del bucket["top_10"]
    return dict(sorted(result.items()))


def _test_distribution(rows: tuple[ImpactDatasetRow, ...]) -> dict[str, Any]:
    resolution: dict[str, int] = defaultdict(int)
    for row in rows:
        resolution[row.observation.coverage_state.value] += 1
    return {
        **_count(rows),
        "direct": sum(row.ground_truth_impact_type is GroundTruthImpactType.DIRECT for row in rows),
        "indirect": sum(
            row.ground_truth_impact_type is GroundTruthImpactType.INDIRECT for row in rows
        ),
        "hard_positives": sum(row.hard_positive for row in rows),
        "hard_negatives": sum(row.hard_negative for row in rows),
        "resolution_states": dict(sorted(resolution.items())),
        "api_families_list": sorted({row.api_family_id for row in rows}),
        "repository_families_list": sorted({row.repository_family_id for row in rows}),
        "mutation_families_list": sorted({row.mutation_family for row in rows}),
    }


def _coefficient_diagnostics(frozen: FrozenModel) -> dict[str, Any]:
    model = frozen.model
    if not hasattr(model, "coef_"):
        return {}
    coefficients = np.asarray(model.coef_[0], dtype=float)
    names = frozen.encoder.output_feature_names
    ordered_positive = sorted(
        ((names[index], float(value)) for index, value in enumerate(coefficients) if value > 0),
        key=lambda item: (-item[1], item[0]),
    )[:10]
    ordered_negative = sorted(
        ((names[index], float(value)) for index, value in enumerate(coefficients) if value < 0),
        key=lambda item: (item[1], item[0]),
    )[:10]
    return {
        "largest_positive": [
            {"feature": name, "coefficient": value} for name, value in ordered_positive
        ],
        "largest_negative": [
            {"feature": name, "coefficient": value} for name, value in ordered_negative
        ],
    }


def _load_git_commit() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def run_m9_evaluation(
    dataset_directory: Path | str = Path("data/m7"),
    m8_directory: Path | str = Path("artifacts/m8"),
    output_directory: Path | str = Path("artifacts/m9"),
    *,
    seed: int = MODEL_SEED,
    split_seed: int = SPLIT_SEED,
    bootstrap_replicates: int = BOOTSTRAP_REPLICATES,
    evaluation_id: str = FORMAL_EVALUATION_ID,
    chronology_path: Path | str | None = None,
    protocol_checksum: str | None = None,
    historical_exclusion_fingerprint: str | None = None,
    reproduction_mode: bool = False,
) -> M9RunResult:
    """Run the one formal M9 evaluation, refusing to overwrite final artifacts."""

    dataset_path = Path(dataset_directory)
    m8_path = Path(m8_directory)
    output = Path(output_directory)
    formal_manifest_path = output / "manifests" / "formal.json"
    if formal_manifest_path.exists():
        raise FileExistsError(
            "formal M9 artifacts are immutable; use a new output directory to reproduce"
        )
    chronology = ChronologyLog.load(chronology_path) if chronology_path is not None else None
    if (
        chronology is not None
        and not reproduction_mode
        and chronology.state is not ChronologyState.DEVELOPMENT_COMPLETE
    ):
        raise ValueError(
            "v3 formal evaluation requires DEVELOPMENT_COMPLETE before pre-test freeze"
        )
    pre_test_path, pre_test = _pre_test_manifest(
        dataset_path,
        m8_path,
        output,
        seed=seed,
        split_seed=split_seed,
        evaluation_id=evaluation_id,
        protocol_checksum=protocol_checksum,
        historical_exclusion_fingerprint=historical_exclusion_fingerprint,
    )
    if chronology is not None and not reproduction_mode:
        chronology.append(
            ChronologyState.PRE_TEST_FROZEN,
            artifact_digests={"pre_test_manifest": _sha256(pre_test_path)},
            configuration_digest=protocol_checksum or "",
        )
        chronology.append(
            ChronologyState.TEST_ACCESSED,
            artifact_digests={"pre_test_manifest": _sha256(pre_test_path)},
            configuration_digest=protocol_checksum or "",
        )
    splits = _formal_splits(dataset_path, split_seed)
    if splits.integrity["TEST"]["rows"] == 0:
        raise ValueError("M9 requires a non-empty TEST partition")

    frozen_models: dict[str, FrozenModel] = {}
    for baseline in tuple(BASELINE_IDS)[1:]:
        experiment_id = BASELINE_IDS[baseline]
        metadata = pre_test["comparison_baselines"][baseline]
        frozen_models[baseline] = _load_model(
            m8_path,
            experiment_id,
            metadata["binary_checksum"],
            metadata["metadata_checksum"],
        )

    validation_scores: dict[str, np.ndarray] = {
        "B0_HEURISTIC": _heuristic_scores(splits.validation)
    }
    test_scores: dict[str, np.ndarray] = {"B0_HEURISTIC": _heuristic_scores(splits.test)}
    for baseline, frozen in frozen_models.items():
        validation_scores[baseline] = _scores(frozen, splits.validation)
        test_scores[baseline] = _scores(frozen, splits.test)

    primary_validation = validation_scores["B1_LOGISTIC_A"]
    calibrator = LogisticRegression(C=1.0, max_iter=1000, solver="lbfgs", random_state=seed)
    calibrator.fit(primary_validation.reshape(-1, 1), labels(list(splits.validation)))
    calibrated_validation = np.asarray(
        calibrator.predict_proba(primary_validation.reshape(-1, 1))[:, 1], dtype=float
    )
    calibrated_test = np.asarray(
        calibrator.predict_proba(test_scores["B1_LOGISTIC_A"].reshape(-1, 1))[:, 1], dtype=float
    )
    if not np.all(np.isfinite(calibrated_test)) or np.any(
        (calibrated_test < 0) | (calibrated_test > 1)
    ):
        raise ValueError("Platt calibrator emitted an invalid probability")

    calibration_dir = output / "calibration"
    calibrator_bytes = pickle.dumps(calibrator, protocol=5)
    calibrator_path = calibration_dir / "platt-v1.pkl"
    _write_immutable(calibrator_path, calibrator_bytes)
    primary_frozen = frozen_models["B1_LOGISTIC_A"]
    calibration_metadata = {
        "schema_version": M9_CALIBRATION_SCHEMA_VERSION,
        "calibrator_type": "platt_sigmoid",
        "base_model_experiment_id": PRIMARY_MODEL_ID,
        "base_model_artifact_checksum": primary_frozen.binary_checksum,
        "calibration_partition": "VALIDATION",
        "calibration_row_ids": [row.id for row in splits.validation],
        "calibration_group_ids": sorted({row.migration_id for row in splits.validation}),
        "feature_schema": primary_frozen.encoder.metadata(),
        "dataset_version": pre_test["dataset_version"],
        "dataset_checksum": pre_test["dataset_checksum"],
        "parameters": {"C": 1.0, "max_iter": 1000, "solver": "lbfgs", "seed": seed},
        "coef": [float(value) for value in calibrator.coef_[0]],
        "intercept": [float(value) for value in calibrator.intercept_],
        "artifact_checksum": _sha256(calibrator_path),
        "test_used_for_fit": False,
        "limitation": (
            "VALIDATION was reused after M8 model selection; TEST remained evaluation-only."
        ),
    }
    calibration_metadata_path = calibration_dir / "platt-v1.json"
    _write_immutable(calibration_metadata_path, calibration_metadata)

    test_metrics: dict[str, Any] = {}
    validation_metrics: dict[str, Any] = {}
    per_group: dict[str, Any] = {}
    bootstrap: dict[str, Any] = {}
    slice_diagnostics: dict[str, Any] = {}
    for baseline, scores in test_scores.items():
        test_metrics[baseline] = {
            "experiment_id": BASELINE_IDS[baseline],
            "ranking": _ranking(splits.test, scores),
            "secondary": classification_metrics(splits.test, scores),
        }
        validation_metrics[baseline] = {
            "experiment_id": BASELINE_IDS[baseline],
            "ranking": _ranking(splits.validation, validation_scores[baseline]),
            "secondary": classification_metrics(splits.validation, validation_scores[baseline]),
        }
        per_group[baseline] = _per_group(splits.test, scores)
        bootstrap[baseline] = group_bootstrap_intervals(
            splits.test, scores, replicates=bootstrap_replicates, seed=BOOTSTRAP_SEED
        )
        slice_diagnostics[baseline] = {
            "mutation_family": _slice_summary(splits.test, scores, "mutation_family"),
            "api_family": _slice_summary(splits.test, scores, "api_family_id"),
            "repository_family": _slice_summary(splits.test, scores, "repository_family_id"),
            "direct_indirect_hard_cases": _truth_rank_diagnostics(splits.test, scores),
            "graph_distance": _distance_diagnostics(splits.test, scores),
        }

    raw_calibration = probabilistic_metrics(
        splits.test, test_scores["B1_LOGISTIC_A"], bin_count=ECE_BIN_COUNT
    )
    calibrated_metrics = probabilistic_metrics(
        splits.test, calibrated_test, bin_count=ECE_BIN_COUNT
    )
    acceptance = bool(
        calibrated_metrics["brier"] <= raw_calibration["brier"]
        and calibrated_metrics["ece"] <= raw_calibration["ece"]
        and calibrated_metrics["log_loss"] <= raw_calibration["log_loss"]
        and calibrated_metrics["ece"] <= 0.10
    )
    raw_ranked = _ranked_rows(splits.test, test_scores["B1_LOGISTIC_A"])
    calibrated_ranked = _ranked_rows(splits.test, calibrated_test)
    raw_order = [row.id for key in sorted(raw_ranked) for row, _, _ in raw_ranked[key]]
    calibrated_order = [
        row.id for key in sorted(calibrated_ranked) for row, _, _ in calibrated_ranked[key]
    ]
    raw_values = test_scores["B1_LOGISTIC_A"]
    ranking_inversions = 0
    for first in range(len(raw_values)):
        for second in range(first + 1, len(raw_values)):
            if splits.test[first].migration_id != splits.test[second].migration_id:
                continue
            raw_delta = raw_values[first] - raw_values[second]
            calibrated_delta = calibrated_test[first] - calibrated_test[second]
            if raw_delta > 1e-12 and calibrated_delta < -1e-12:
                ranking_inversions += 1
    calibration = {
        "primary_method": "platt_sigmoid",
        "fit_partition": "VALIDATION",
        "test_partition": "TEST",
        "test_used_for_fit": False,
        "raw_uncalibrated": raw_calibration,
        "calibrated": calibrated_metrics,
        "validation_fit_metrics": probabilistic_metrics(
            splits.validation, calibrated_validation, bin_count=ECE_BIN_COUNT
        ),
        "reliability_table": {
            "raw": [
                item.as_dict()
                for item in reliability_bins(
                    labels(list(splits.test)), test_scores["B1_LOGISTIC_A"]
                )
            ],
            "calibrated": [
                item.as_dict()
                for item in reliability_bins(labels(list(splits.test)), calibrated_test)
            ],
        },
        "raw_ranking": _ranking(splits.test, raw_values),
        "calibrated_ranking": _ranking(splits.test, calibrated_test),
        "ranking_preserved": ranking_inversions == 0,
        "ranking_order_exact_match": raw_order == calibrated_order,
        "ranking_inversions_above_tolerance": ranking_inversions,
        "ranking_note": (
            "Platt is monotonic; any exact-order difference is a deterministic tie change from "
            "floating-point compression of nearly equal raw scores."
        ),
        "decision": (
            "CALIBRATION SUFFICIENT FOR LIMITED ESTIMATED-PROBABILITY USE"
            if acceptance
            else "CALIBRATION NOT SUFFICIENT — RETAIN RANKING SCORE ONLY"
        ),
        "policy": pre_test["ece_policy"],
    }

    predictions_path = output / "predictions" / "test.jsonl"
    prediction_lines: list[str] = []
    for baseline, scores in test_scores.items():
        ranked = _ranked_rows(splits.test, scores)
        for migration_id in sorted(ranked):
            for row, score, rank in ranked[migration_id]:
                record = {
                    "model_experiment_id": BASELINE_IDS[baseline],
                    "baseline": baseline,
                    "row_id": row.id,
                    "ranking_group_id": migration_id,
                    "ground_truth_label": row.ground_truth_label.value,
                    "raw_model_score": score,
                    "calibrated_probability": (
                        float(
                            calibrated_test[
                                next(
                                    index
                                    for index, item in enumerate(splits.test)
                                    if item.id == row.id
                                )
                            ]
                        )
                        if baseline == "B1_LOGISTIC_A" and acceptance
                        else None
                    ),
                    "rank": rank,
                }
                prediction_lines.append(json.dumps(record, sort_keys=True, separators=(",", ":")))
    _write_immutable(predictions_path, ("\n".join(prediction_lines) + "\n").encode("utf-8"))

    metric_payload = {
        "schema_version": M9_EVALUATION_SCHEMA_VERSION,
        "evaluation_id": evaluation_id,
        "dataset_version": pre_test["dataset_version"],
        "dataset_checksum": pre_test["dataset_checksum"],
        "split_integrity": splits.integrity,
        "test_distribution": _test_distribution(splits.test),
        "primary_model": {"baseline": "B1_LOGISTIC_A", "experiment_id": PRIMARY_MODEL_ID},
        "frozen_baselines": BASELINE_IDS,
        "test_ranking_metrics": test_metrics,
        "test_secondary_metrics": {key: value["secondary"] for key, value in test_metrics.items()},
        "per_group_results": per_group,
        "bootstrap_uncertainty": bootstrap,
        "validation_metrics": validation_metrics,
        "validation_test_gap": {
            baseline: {
                metric: {
                    "validation": validation_metrics[baseline]["ranking"][metric],
                    "test": test_metrics[baseline]["ranking"][metric],
                    "difference_test_minus_validation": test_metrics[baseline]["ranking"][metric]
                    - validation_metrics[baseline]["ranking"][metric],
                }
                for metric in (
                    "precision_at_5",
                    "recall_at_5",
                    "precision_at_10",
                    "recall_at_10",
                    "mrr",
                    "ndcg_at_5",
                    "ndcg_at_10",
                )
            }
            for baseline in BASELINE_IDS
        },
        "calibration": calibration,
        "diagnostics": {
            "heuristic_ablation": {
                "logistic_a": test_metrics["B1_LOGISTIC_A"]["ranking"],
                "logistic_b": test_metrics["B2_LOGISTIC_B"]["ranking"],
            },
            "simple_vs_complex": {
                key: test_metrics[key]["ranking"]
                for key in ("B1_LOGISTIC_A", "B3_RANDOM_FOREST", "B4_XGBOOST")
            },
            "slices": slice_diagnostics,
            "unseen_test_families": {
                "api_families_not_in_train": sorted(
                    {row.api_family_id for row in splits.test}
                    - {row.api_family_id for row in splits.train}
                ),
                "repository_families_not_in_train": sorted(
                    {row.repository_family_id for row in splits.test}
                    - {row.repository_family_id for row in splits.train}
                ),
            },
            "primary_logistic_coefficients": _coefficient_diagnostics(primary_frozen),
            "label_shuffle_sanity_carried_from_m8": json.loads(
                (m8_path / "metrics" / "validation.json").read_text(encoding="utf-8")
            )["label_shuffle_sanity"],
        },
        "probability_terminology_audit": {
            "heuristic_scores_are_probabilities": False,
            "raw_model_scores_are_probabilities": False,
            "accepted_calibrated_output": acceptance,
        },
        "limitations": [
            "Synthetic/curated dataset, not real-world accuracy evidence.",
            (
                f"Only {len({row.migration_id for row in splits.test})} held-out migration groups; "
                "intervals are group-bootstrap uncertainty, not precise population guarantees."
            ),
            "Mutation families and API families are imbalanced.",
            (
                "VALIDATION was reused for M8 model selection and M9 calibration; TEST remained "
                "independently held out."
            ),
        ],
        "artifacts": {
            "pre_test_manifest": "manifests/pre_test.json",
            "predictions": "predictions/test.jsonl",
            "calibration_metadata": "calibration/platt-v1.json",
        },
    }
    metrics_path = output / "metrics" / "test.json"
    _write_immutable(metrics_path, metric_payload)

    formal_manifest = {
        "schema_version": M9_EVALUATION_SCHEMA_VERSION,
        "evaluation_id": evaluation_id,
        "dataset_version": pre_test["dataset_version"],
        "dataset_checksum": pre_test["dataset_checksum"],
        "test_row_fingerprint": hashlib.sha256(
            "\n".join(row.id for row in splits.test).encode("utf-8")
        ).hexdigest(),
        "evaluation_configuration": pre_test,
        "model_checksums": {
            baseline: frozen.binary_checksum for baseline, frozen in frozen_models.items()
        },
        "calibrator_checksum": _sha256(calibrator_path),
        "metric_artifact_checksum": _sha256(metrics_path),
        "prediction_artifact_checksum": _sha256(predictions_path),
        "timestamp": datetime.now(UTC).isoformat(),
        "git_commit": _load_git_commit(),
        "seed": seed,
        "test_accessed": True,
    }
    _write_immutable(formal_manifest_path, formal_manifest)
    if chronology is not None and not reproduction_mode:
        chronology.append(
            ChronologyState.FORMAL_EVALUATION_COMPLETE,
            artifact_digests={
                "metrics": _sha256(metrics_path),
                "predictions": _sha256(predictions_path),
                "calibration": _sha256(calibration_metadata_path),
            },
            configuration_digest=protocol_checksum or "",
        )
    return M9RunResult(
        evaluation_id=evaluation_id,
        dataset_version=pre_test["dataset_version"],
        dataset_checksum=pre_test["dataset_checksum"],
        primary_model=PRIMARY_MODEL_ID,
        pre_test_manifest=str(pre_test_path),
        test_metrics=str(metrics_path),
        predictions=str(predictions_path),
        calibration=str(calibration_metadata_path),
        formal_manifest=str(formal_manifest_path),
        output_directory=str(output),
    )
