"""Pre-generation protocol and historical exclusion helpers for Gate B v3."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from opentrace.datasets.models import ImpactDataset
from opentrace.datasets.remediation import (
    V3_REVISION,
    V3_SEED,
    V3_SPLIT_SEED,
)

PROTOCOL_ID = "gate-b-v3-protocol-v3"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def protocol_payload(root: Path) -> dict[str, Any]:
    code_files = (
        root / "backend/opentrace/datasets/remediation.py",
        root / "backend/opentrace/datasets/generator.py",
        root / "backend/opentrace/datasets/scenarios.py",
        root / "backend/opentrace/ml/features.py",
        root / "backend/opentrace/ml/pipeline.py",
        root / "backend/opentrace/evaluation/pipeline.py",
    )
    return {
        "protocol_id": PROTOCOL_ID,
        "protocol_version": "gate-b-v3-protocol-v3",
        "dataset_schema_version": "impact-dataset-v1",
        "dataset_version": "impact-dataset-v3",
        "generator_version": "synthetic-impact-generator-v3",
        "generator_code_digest": hashlib.sha256(
            "".join(_sha256(path) for path in code_files).encode("utf-8")
        ).hexdigest(),
        "generator_configuration": {
            "seed": V3_SEED,
            "split_seed": V3_SPLIT_SEED,
            "revision": V3_REVISION,
            "synthetic_scenarios": 30,
            "include_curated": True,
            "include_realistic": True,
        },
        "seed_derivation": {
            "rule": "int.from_bytes(sha256(label)[:4], big-endian)",
            "label": "opentrace-gate-b-v3-fresh-evaluation",
            "seed": V3_SEED,
            "split_label": "opentrace-gate-b-v3-fresh-evaluation:split",
            "split_seed": V3_SPLIT_SEED,
        },
        "scenario_policy": {
            "families": ["SYNTHETIC", "CURATED", "REALISTIC"],
            "counts": {"synthetic": 30, "curated": "all governed", "realistic": "all governed"},
            "historical_exclusion": "all v1 and v2 scenario/model-input/template identities",
            "formal_test_template_exclusion": (
                "historical v1/v2 template families are ineligible for TEST"
            ),
        },
        "api_family_policy": "governed payments, identity, inventory namespaces",
        "mutation_family_policy": "all governed generator families; no metric filtering",
        "repository_family_policy": "governed deterministic repository families",
        "template_family_policy": "exact template families are indivisible split components",
        "hard_positive_policy": "scenario hard_positive and affected independent truth",
        "hard_negative_policy": "scenario hard_negative or governed high-risk negative",
        "candidate_generation_policy": "all analyzed CodeSymbol nodes",
        "clone_rules": [
            "migration_id",
            "source_fingerprint",
            "candidate_fingerprint",
            "structural_input_fingerprint",
            "heuristic_input_fingerprint",
            "template_family_id",
        ],
        "split_policy": {
            "algorithm": "clone-safe-component-round-robin-v2",
            "canonical_order": "scenario_id",
            "partition_targets": ["TRAIN", "VALIDATION", "TEST"],
        },
        "feature_policy": {
            "feature_a": "impact-ml-features-v1:A_STRUCTURAL",
            "feature_b": "impact-ml-features-v1:B_STRUCTURAL_PLUS_HEURISTICS",
        },
        "model_policy": {
            "primary": "E2-logistic-structural-v1",
            "feature_set": "A_STRUCTURAL",
            "hyperparameters": {"C": 1.0, "class_weight": "balanced", "max_iter": 500},
            "comparisons": [
                "E1-heuristic-v1",
                "E3-logistic-heuristics-v1",
                "E4-random-forest-v1",
                "E5-xgboost-v1",
            ],
        },
        "evaluation_policy": {
            "formal_evaluation_id": "impact-eval-m9-v3",
            "calibration": "platt_sigmoid:VALIDATION_ONLY",
            "ece": "10 equal-width bins; calibrated metrics no worse than raw and ECE <= 0.10",
            "bootstrap": "migration_group_percentile_95:1000:seed42",
            "metrics": ["P@5", "R@5", "P@10", "R@10", "MRR", "NDCG@5", "NDCG@10"],
        },
    }


def write_protocol(root: Path, output: Path) -> tuple[Path, str]:
    path = output / "protocol" / "pre_generation.json"
    payload = protocol_payload(root)
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    sealed = dict(payload)
    sealed["protocol_checksum"] = digest
    content = json.dumps(sealed, sort_keys=True, separators=(",", ":")) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != content:
            raise FileExistsError("v3 protocol already exists with different content")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
    return path, hashlib.sha256(content.encode("utf-8")).hexdigest()


def historical_exclusion(
    dataset: ImpactDataset, historical: tuple[ImpactDataset, ...]
) -> dict[str, Any]:
    fields = (
        "scenario_id",
        "source_fingerprint",
        "candidate_fingerprint",
        "structural_input_fingerprint",
        "heuristic_input_fingerprint",
        "template_family_id",
    )
    result: dict[str, Any] = {}
    for field in fields:
        fresh = {getattr(scenario, field) for scenario in dataset.scenarios}
        old = {
            getattr(scenario, field)
            for item in historical
            for scenario in item.scenarios
            if getattr(scenario, field) is not None
        }
        result[field] = {
            "overlap": len(fresh & old),
            "fresh_count": len(fresh),
            "historical_count": len(old),
        }
    canonical = json.dumps(result, sort_keys=True, separators=(",", ":")).encode("utf-8")
    result["exclusion_fingerprint"] = hashlib.sha256(canonical).hexdigest()
    return result
