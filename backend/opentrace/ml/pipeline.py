"""Canonical M8 training and validation experiment path."""

from __future__ import annotations

import hashlib
import json
import pickle
import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.ensemble import RandomForestClassifier  # type: ignore[import-untyped]
from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]
from xgboost import XGBClassifier

from opentrace.datasets import assign_group_partitions, parse_rows, validate_dataset
from opentrace.datasets.models import (
    DATASET_REMEDIATION_VERSION,
    DATASET_SCHEMA_VERSION,
    DATASET_V3_VERSION,
    DATASET_VERSION,
    DatasetManifest,
    GroundTruthLabel,
    ImpactDataset,
    ImpactDatasetRow,
    ScenarioDefinition,
)
from opentrace.ml.features import FeatureEncoder, _is_structural, labels
from opentrace.ml.metrics import classification_metrics, compute_ranking_metrics, predictions
from opentrace.ml.models import (
    ExperimentRecord,
    FeatureSet,
    M8Model,
    M8ModelName,
    M8RunResult,
    SplitCounts,
    SplitIntegrity,
)


@dataclass(frozen=True)
class DevelopmentSplits:
    train: tuple[ImpactDatasetRow, ...]
    validation: tuple[ImpactDatasetRow, ...]
    integrity: SplitIntegrity

    @property
    def test_rows(self) -> tuple[ImpactDatasetRow, ...]:
        raise RuntimeError("TEST partition is sealed for M9")


def _read_dataset(dataset_directory: Path) -> ImpactDataset:
    manifest_path = dataset_directory / "manifest.json"
    rows_path = dataset_directory / "canonical.jsonl"
    scenarios_path = dataset_directory / "scenarios.jsonl"
    manifest = DatasetManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    rows = parse_rows(rows_path.read_text(encoding="utf-8"))
    scenarios = tuple(
        ScenarioDefinition.model_validate_json(line)
        for line in scenarios_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    dataset = ImpactDataset(manifest=manifest, scenarios=scenarios, rows=rows)
    validate_dataset(dataset)
    actual = hashlib.sha256(rows_path.read_bytes()).hexdigest()
    if actual != manifest.content_sha256:
        raise ValueError("M7 canonical artifact checksum does not match manifest")
    if manifest.schema_version != DATASET_SCHEMA_VERSION or manifest.dataset_version not in {
        DATASET_VERSION,
        DATASET_REMEDIATION_VERSION,
        DATASET_V3_VERSION,
    }:
        raise ValueError("unsupported M7 dataset version")
    return dataset


def _counts(partition: str, rows: list[ImpactDatasetRow], include_labels: bool) -> SplitCounts:
    return SplitCounts(
        partition=partition,
        rows=len(rows),
        migrations=len({row.migration_id for row in rows}),
        positives=(
            sum(row.ground_truth_label is GroundTruthLabel.AFFECTED for row in rows)
            if include_labels
            else None
        ),
        negatives=(
            sum(row.ground_truth_label is GroundTruthLabel.UNAFFECTED for row in rows)
            if include_labels
            else None
        ),
        api_families=len({row.api_family_id for row in rows}),
        mutation_families=len({row.mutation_family for row in rows}),
    )


def _overlap(rows_a: list[ImpactDatasetRow], rows_b: list[ImpactDatasetRow], field: str) -> int:
    return len({getattr(row, field) for row in rows_a} & {getattr(row, field) for row in rows_b})


def _slice_counts(rows: tuple[ImpactDatasetRow, ...], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(getattr(row, field))
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _partition_rows(
    rows: tuple[ImpactDatasetRow, ...], partition: str
) -> list[ImpactDatasetRow]:
    return [
        row
        for row in rows
        if row.split_partition is not None and row.split_partition.value == partition
    ]


def load_development_splits(
    dataset_directory: Path | str = Path("data/m7"), *, split_seed: int = 42
) -> DevelopmentSplits:
    loaded = _read_dataset(Path(dataset_directory))
    dataset = (
        loaded
        if loaded.manifest.split_strategy == "clone-safe-component-round-robin-v2"
        else assign_group_partitions(loaded, seed=split_seed)
    )
    train = _partition_rows(dataset.rows, "TRAIN")
    validation = _partition_rows(dataset.rows, "VALIDATION")
    test = _partition_rows(dataset.rows, "TEST")
    integrity = SplitIntegrity(
        split_version=(
            loaded.manifest.split_strategy
            if loaded.manifest.split_strategy is not None
            else "migration-id-hash-v1"
        ),
        split_seed=split_seed,
        train=_counts("TRAIN", train, True),
        validation=_counts("VALIDATION", validation, True),
        test=_counts("TEST", test, False),
        train_validation_migration_overlap=_overlap(train, validation, "migration_id"),
        train_test_migration_overlap=_overlap(train, test, "migration_id"),
        validation_test_migration_overlap=_overlap(validation, test, "migration_id"),
        train_validation_repository_overlap=_overlap(train, validation, "repository_family_id"),
        train_validation_api_overlap=_overlap(train, validation, "api_family_id"),
        train_validation_scenario_overlap=_overlap(train, validation, "family"),
    )
    if any(
        value
        for value in (
            integrity.train_validation_migration_overlap,
            integrity.train_test_migration_overlap,
            integrity.validation_test_migration_overlap,
        )
    ):
        raise ValueError("migration groups cross M8 partitions")
    return DevelopmentSplits(tuple(train), tuple(validation), integrity)


def _score(model: Any, matrix: np.ndarray) -> np.ndarray:
    if hasattr(model, "predict_proba"):
        return np.asarray(model.predict_proba(matrix)[:, 1], dtype=float)
    return np.asarray(model.decision_function(matrix), dtype=float)


def _write_predictions(path: Path, values: tuple[Any, ...]) -> None:
    path.write_bytes(
        "".join(
            json.dumps(value.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
            + "\n"
            for value in values
        ).encode("utf-8")
    )


def _write_json(path: Path, value: object) -> None:
    content = json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
    path.write_bytes(content.encode("utf-8"))


def _experiment(
    experiment_id: str,
    hypothesis: str,
    model_name: M8ModelName,
    feature_set: FeatureSet | None,
    parameters: dict[str, str | int | float | bool | None],
    seed: int,
    split_seed: int,
    dataset: ImpactDataset,
    split_integrity: SplitIntegrity,
    metrics: dict[str, float],
    locations: tuple[str, ...],
    interpretation: str,
) -> ExperimentRecord:
    return ExperimentRecord(
        experiment_id=experiment_id,
        date=date.today().isoformat(),
        hypothesis=hypothesis,
        dataset_version=dataset.manifest.dataset_version,
        dataset_checksum=dataset.manifest.content_sha256,
        split_strategy=f"{split_integrity.split_version}:{split_integrity.group_by}",
        feature_schema_version=(
            "impact-ml-features-v1" if feature_set is not None else "not-applicable"
        ),
        feature_set=feature_set,
        model=M8Model(name=model_name, feature_set=feature_set, parameters=parameters, seed=seed),
        hyperparameters=parameters,
        seed=seed,
        split_seed=split_seed,
        metrics=metrics,
        interpretation=interpretation,
        limitations=(
            "Validation/development metrics only; TEST is sealed for M9.",
            "Dataset is small and synthetic/curated.",
        ),
        artifact_locations=locations,
    )


def run_m8_experiments(
    dataset_directory: Path | str = Path("data/m7"),
    output_directory: Path | str = Path("artifacts/m8"),
    *,
    seed: int = 42,
    split_seed: int = 42,
) -> M8RunResult:
    splits = load_development_splits(dataset_directory, split_seed=split_seed)
    dataset = _read_dataset(Path(dataset_directory))
    output = Path(output_directory)
    if output.exists():
        for child in output.iterdir():
            if child.name == "README.md":
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    for name in ("experiments", "models", "metrics", "predictions"):
        (output / name).mkdir(parents=True, exist_ok=True)

    records: list[ExperimentRecord] = []
    prediction_files: list[str] = []
    model_files: list[str] = []
    comparison: dict[str, dict[str, float]] = {}
    diagnostics: dict[str, dict[str, float]] = {}

    heuristic_scores = np.array(
        [row.features.m4_impact_score or 0.0 for row in splits.validation], dtype=float
    )
    heuristic_metrics = {
        **compute_ranking_metrics(splits.validation, heuristic_scores).as_dict(),
        **classification_metrics(splits.validation, heuristic_scores),
    }
    heuristic_id = "E1-heuristic-v1"
    heuristic_prediction_path = output / "predictions" / f"{heuristic_id}.jsonl"
    _write_predictions(
        heuristic_prediction_path,
        predictions(heuristic_id, splits.validation, heuristic_scores),
    )
    heuristic_record = _experiment(
        heuristic_id,
        "The existing deterministic M4 impact score provides a simple ranking baseline.",
        M8ModelName.HEURISTIC,
        None,
        {"missing_m4_score": 0.0},
        seed,
        split_seed,
        dataset,
        splits.integrity,
        heuristic_metrics,
        (str(heuristic_prediction_path),),
        "No-training deterministic M4 impact-score ranking.",
    )
    records.append(heuristic_record)
    prediction_files.append(str(heuristic_prediction_path))
    comparison[heuristic_id] = heuristic_metrics

    configurations: tuple[
        tuple[str, str, M8ModelName, FeatureSet, dict[str, Any], Any], ...
    ] = (
        (
            "E2-logistic-structural-v1",
            "Structural evidence can rank affected symbols without aggregate heuristics.",
            M8ModelName.LOGISTIC_REGRESSION,
            FeatureSet.STRUCTURAL,
            {"C": 1.0, "class_weight": "balanced", "max_iter": 500},
            LogisticRegression(C=1.0, class_weight="balanced", max_iter=500, random_state=seed),
        ),
        (
            "E3-logistic-heuristics-v1",
            "Adding named M4/M6 aggregate features may improve ranking while imitating "
            "the heuristic.",
            M8ModelName.LOGISTIC_REGRESSION,
            FeatureSet.STRUCTURAL_HEURISTICS,
            {"C": 1.0, "class_weight": "balanced", "max_iter": 500},
            LogisticRegression(C=1.0, class_weight="balanced", max_iter=500, random_state=seed),
        ),
        (
            "E4-random-forest-v1",
            "A bounded nonlinear tree baseline may capture structural feature interactions.",
            M8ModelName.RANDOM_FOREST,
            FeatureSet.STRUCTURAL_HEURISTICS,
            {"n_estimators": 64, "max_depth": 4, "class_weight": "balanced"},
            RandomForestClassifier(
                n_estimators=64, max_depth=4, class_weight="balanced", random_state=seed, n_jobs=1
            ),
        ),
        (
            "E5-xgboost-v1",
            "A bounded gradient-boosted tree baseline may capture interactions but risks "
            "overfitting.",
            M8ModelName.XGBOOST,
            FeatureSet.STRUCTURAL_HEURISTICS,
            {
                "n_estimators": 32,
                "max_depth": 3,
                "learning_rate": 0.1,
                "subsample": 1.0,
                "colsample_bytree": 1.0,
            },
            XGBClassifier(
                n_estimators=32,
                max_depth=3,
                learning_rate=0.1,
                subsample=1.0,
                colsample_bytree=1.0,
                reg_lambda=1.0,
                random_state=seed,
                n_jobs=1,
                eval_metric="logloss",
                tree_method="hist",
            ),
        ),
    )
    for experiment_id, hypothesis, model_name, feature_set, parameters, model in configurations:
        encoder = FeatureEncoder(feature_set, scale_numeric=_is_structural(feature_set))
        encoder.fit(list(splits.train))
        train_matrix = encoder.transform(list(splits.train))
        validation_matrix = encoder.transform(list(splits.validation))
        model.fit(train_matrix, labels(list(splits.train)))
        scores = _score(model, validation_matrix)
        metrics = {
            **compute_ranking_metrics(splits.validation, scores).as_dict(),
            **classification_metrics(splits.validation, scores),
        }
        if hasattr(model, "coef_"):
            coefficients = np.asarray(model.coef_[0], dtype=float)
            order = np.argsort(np.abs(coefficients))[::-1][:10]
            diagnostics[experiment_id] = {
                encoder.output_feature_names[index]: float(coefficients[index])
                for index in order
            }
        elif hasattr(model, "feature_importances_"):
            importance = np.asarray(model.feature_importances_, dtype=float)
            order = np.argsort(importance)[::-1][:10]
            diagnostics[experiment_id] = {
                encoder.output_feature_names[index]: float(importance[index])
                for index in order
            }
        comparison[experiment_id] = metrics
        model_path = output / "models" / f"{experiment_id}.pkl"
        model_path.write_bytes(pickle.dumps({"model": model, "encoder": encoder}, protocol=5))
        model_files.append(str(model_path))
        metadata_path = output / "models" / f"{experiment_id}.json"
        _write_json(
            metadata_path,
            {
                "model_type": model_name.value,
                "dataset_version": dataset.manifest.dataset_version,
                "dataset_checksum": dataset.manifest.content_sha256,
                "training_partition": "TRAIN",
                "validation_partition": "VALIDATION",
                "test_used": False,
                "seed": seed,
                "split_seed": split_seed,
                "parameters": parameters,
                "feature_schema": encoder.metadata(),
                "trusted_local_artifact_only": True,
            },
        )
        model_files.append(str(metadata_path))
        prediction_path = output / "predictions" / f"{experiment_id}.jsonl"
        _write_predictions(prediction_path, predictions(experiment_id, splits.validation, scores))
        prediction_files.append(str(prediction_path))
        record = _experiment(
            experiment_id,
            hypothesis,
            model_name,
            feature_set,
            parameters,
            seed,
            split_seed,
            dataset,
            splits.integrity,
            metrics,
            (str(model_path), str(metadata_path), str(prediction_path)),
            "Validation ranking scores only; not calibrated probabilities.",
        )
        records.append(record)
        _write_json(
            output / "experiments" / f"{experiment_id}.json",
            record.model_dump(mode="json"),
        )

    shuffle_rng = np.random.default_rng(seed)
    shuffled_labels = shuffle_rng.permutation(labels(list(splits.train)))
    shuffle_encoder = FeatureEncoder(FeatureSet.STRUCTURAL)
    shuffle_encoder.fit(list(splits.train))
    shuffle_model = LogisticRegression(
        C=1.0, class_weight="balanced", max_iter=500, random_state=seed
    )
    shuffle_model.fit(shuffle_encoder.transform(list(splits.train)), shuffled_labels)
    shuffled_scores = _score(shuffle_model, shuffle_encoder.transform(list(splits.validation)))
    shuffle_metrics = {
        **compute_ranking_metrics(splits.validation, shuffled_scores).as_dict(),
        **classification_metrics(splits.validation, shuffled_scores),
    }
    comparison["E6-label-shuffle-sanity"] = shuffle_metrics

    for record in records:
        _write_json(
            output / "experiments" / f"{record.experiment_id}.json",
            record.model_dump(mode="json"),
        )
    metrics_path = output / "metrics" / "validation.json"
    _write_json(
        metrics_path,
        {
            "dataset_version": dataset.manifest.dataset_version,
            "dataset_checksum": dataset.manifest.content_sha256,
            "split_integrity": splits.integrity.model_dump(mode="json"),
            "validation_development_metrics": comparison,
            "validation_slice_counts": {
                "mutation_family": _slice_counts(splits.validation, "mutation_family"),
                "api_family_id": _slice_counts(splits.validation, "api_family_id"),
            },
            "model_diagnostics": diagnostics,
            "label_shuffle_sanity": shuffle_metrics,
            "test_metrics": "SEALED_FOR_M9_NOT_COMPUTED",
        },
    )
    return M8RunResult(
        dataset_version=dataset.manifest.dataset_version,
        dataset_checksum=dataset.manifest.content_sha256,
        split_integrity=splits.integrity,
        experiments=tuple(records),
        validation_prediction_files=tuple(prediction_files),
        model_files=tuple(model_files),
        metrics_file=str(metrics_path),
    )
