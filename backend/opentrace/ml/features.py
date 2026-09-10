"""Explicit, train-fitted M8 feature schemas and preprocessing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from sklearn.preprocessing import OneHotEncoder, StandardScaler  # type: ignore[import-untyped]

from opentrace.datasets.models import ImpactDatasetRow
from opentrace.ml.models import M8_FEATURE_SCHEMA_VERSION, FeatureSet

STRUCTURAL_NUMERIC_FEATURES = (
    "request_field_overlap_count",
    "response_field_overlap_count",
    "parameter_overlap_count",
    "evidence_exact_count",
    "evidence_partial_count",
    "evidence_unresolved_count",
    "graph_distance",
    "direct_caller_count",
    "upstream_caller_count",
    "coverage_unresolved_calls",
    "coverage_failed_files",
)
STRUCTURAL_CATEGORICAL_FEATURES = (
    "change_category",
    "change_severity",
    "change_certainty",
    "breaking_classification",
    "compatibility_direction",
    "endpoint_path_match",
    "host_match",
    "method_match",
    "direct_reference",
    "url_resolution_state",
    "request_resolution_state",
    "response_resolution_state",
)
HEURISTIC_NUMERIC_FEATURES = ("m4_impact_score", "m6_risk_score")
HEURISTIC_CATEGORICAL_FEATURES = ("m6_risk_level",)


def _is_structural(feature_set: object) -> bool:
    return feature_set == FeatureSet.STRUCTURAL or getattr(feature_set, "value", feature_set) in (
        FeatureSet.STRUCTURAL,
        FeatureSet.STRUCTURAL.value,
        "A_STRUCTURAL",
    )


def _is_structural_heuristics(feature_set: object) -> bool:
    return feature_set == FeatureSet.STRUCTURAL_HEURISTICS or getattr(feature_set, "value", feature_set) in (
        FeatureSet.STRUCTURAL_HEURISTICS,
        FeatureSet.STRUCTURAL_HEURISTICS.value,
        "B_STRUCTURAL_HEURISTICS",
    )


def feature_names(feature_set: FeatureSet) -> tuple[str, ...]:
    structural = STRUCTURAL_NUMERIC_FEATURES + STRUCTURAL_CATEGORICAL_FEATURES
    if _is_structural(feature_set):
        return structural
    return structural + HEURISTIC_NUMERIC_FEATURES + HEURISTIC_CATEGORICAL_FEATURES


def _numeric_feature_names(feature_set: FeatureSet) -> tuple[str, ...]:
    if _is_structural(feature_set):
        return STRUCTURAL_NUMERIC_FEATURES
    return STRUCTURAL_NUMERIC_FEATURES + HEURISTIC_NUMERIC_FEATURES


def _enum_value(value: object | None) -> str:
    if value is None:
        return "MISSING"
    return str(getattr(value, "value", value))


def _numeric(value: int | float | None) -> float | None:
    return float(value) if value is not None else None


def row_feature_values(row: ImpactDatasetRow, feature_set: FeatureSet) -> dict[str, Any]:
    features = row.features
    values: dict[str, Any] = {
        "request_field_overlap_count": len(features.request_field_overlap),
        "response_field_overlap_count": len(features.response_field_overlap),
        "parameter_overlap_count": len(features.parameter_overlap),
        "evidence_exact_count": sum(
            item.resolution_state.value == "EXACT" for item in features.evidence
        ),
        "evidence_partial_count": sum(
            item.resolution_state.value == "PARTIAL" for item in features.evidence
        ),
        "evidence_unresolved_count": sum(
            item.resolution_state.value in {"UNRESOLVED", "UNSUPPORTED"}
            for item in features.evidence
        ),
        "graph_distance": _numeric(features.graph_distance),
        "direct_caller_count": _numeric(features.direct_caller_count),
        "upstream_caller_count": _numeric(features.upstream_caller_count),
        "coverage_unresolved_calls": features.coverage_unresolved_calls,
        "coverage_failed_files": features.coverage_failed_files,
        "change_category": features.change_category,
        "change_severity": features.change_severity,
        "change_certainty": features.change_certainty,
        "breaking_classification": features.breaking_classification,
        "compatibility_direction": features.compatibility_direction,
        "endpoint_path_match": _enum_value(features.endpoint_path_match),
        "host_match": _enum_value(features.host_match),
        "method_match": _enum_value(features.method_match),
        "direct_reference": _enum_value(features.direct_reference),
        "url_resolution_state": _enum_value(features.url_resolution_state),
        "request_resolution_state": _enum_value(features.request_resolution_state),
        "response_resolution_state": _enum_value(features.response_resolution_state),
    }
    if _is_structural_heuristics(feature_set):
        values.update(
            {
                "m4_impact_score": _numeric(features.m4_impact_score),
                "m6_risk_score": _numeric(features.m6_risk_score),
                "m6_risk_level": _enum_value(features.m6_risk_level),
            }
        )
    return values


@dataclass
class FeatureEncoder:
    """Train-fitted encoder with explicit missing numeric indicators."""

    feature_set: FeatureSet
    scale_numeric: bool = True
    _categorical: OneHotEncoder | None = None
    _scaler: StandardScaler | None = None
    _numeric_means: np.ndarray | None = None
    _feature_names: tuple[str, ...] = ()

    def fit(self, rows: tuple[ImpactDatasetRow, ...] | list[ImpactDatasetRow]) -> FeatureEncoder:
        if not rows:
            raise ValueError("cannot fit M8 features on an empty TRAIN partition")
        expected = set(feature_names(self.feature_set))
        matrices = [row_feature_values(row, self.feature_set) for row in rows]
        if any(set(values) != expected for values in matrices):
            raise ValueError("row feature values do not match the explicit M8 allowlist")
        numeric_names = _numeric_feature_names(self.feature_set)
        numeric = np.array(
            [
                [
                    float(values[name]) if values[name] is not None else np.nan
                    for name in numeric_names
                ]
                for values in matrices
            ],
            dtype=float,
        )
        means = np.array(
            [
                float(np.mean(column[np.isfinite(column)]))
                if np.isfinite(column).any()
                else 0.0
                for column in numeric.T
            ],
            dtype=float,
        )
        filled = np.where(np.isnan(numeric), means, numeric)
        self._numeric_means = means
        self._scaler = StandardScaler().fit(filled) if self.scale_numeric else None
        categorical_names = STRUCTURAL_CATEGORICAL_FEATURES + (
            HEURISTIC_CATEGORICAL_FEATURES
            if _is_structural_heuristics(self.feature_set)
            else ()
        )
        categorical = np.array(
            [[str(values[name]) for name in categorical_names] for values in matrices]
        )
        self._categorical = OneHotEncoder(
            handle_unknown="ignore", sparse_output=False, dtype=float
        ).fit(categorical)
        self._feature_names = tuple(numeric_names) + tuple(
            f"{name}_missing" for name in numeric_names
        ) + tuple(self._categorical.get_feature_names_out(categorical_names))
        return self

    def transform(self, rows: tuple[ImpactDatasetRow, ...] | list[ImpactDatasetRow]) -> np.ndarray:
        if self._categorical is None or self._numeric_means is None:
            raise ValueError("M8 feature encoder must be fitted on TRAIN before transform")
        matrices = [row_feature_values(row, self.feature_set) for row in rows]
        expected = set(feature_names(self.feature_set))
        if any(set(values) != expected for values in matrices):
            raise ValueError("row feature values do not match the explicit M8 allowlist")
        numeric_names = _numeric_feature_names(self.feature_set)
        numeric = np.array(
            [
                [
                    float(values[name]) if values[name] is not None else np.nan
                    for name in numeric_names
                ]
                for values in matrices
            ],
            dtype=float,
        )
        missing = np.isnan(numeric).astype(float)
        filled = np.where(np.isnan(numeric), self._numeric_means, numeric)
        if self._scaler is not None:
            filled = self._scaler.transform(filled)
        categorical_names = STRUCTURAL_CATEGORICAL_FEATURES + (
            HEURISTIC_CATEGORICAL_FEATURES
            if _is_structural_heuristics(self.feature_set)
            else ()
        )
        categorical = np.array(
            [[str(values[name]) for name in categorical_names] for values in matrices]
        )
        return np.column_stack((filled, missing, self._categorical.transform(categorical)))

    @property
    def output_feature_names(self) -> tuple[str, ...]:
        if not self._feature_names:
            raise ValueError("M8 feature encoder must be fitted before reading feature names")
        return self._feature_names

    def metadata(self) -> dict[str, object]:
        return {
            "schema_version": M8_FEATURE_SCHEMA_VERSION,
            "feature_set": self.feature_set.value,
            "allowlist": list(feature_names(self.feature_set)),
            "expanded_feature_names": list(self.output_feature_names),
            "scale_numeric": self.scale_numeric,
            "fit_partition": "TRAIN",
        }


def labels(rows: tuple[ImpactDatasetRow, ...] | list[ImpactDatasetRow]) -> np.ndarray:
    return np.array([row.ground_truth_label.value == "AFFECTED" for row in rows], dtype=int)
