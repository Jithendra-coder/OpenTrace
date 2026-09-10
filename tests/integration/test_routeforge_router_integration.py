"""M13 real router artifact and validation-run checks."""

import json
from pathlib import Path

from opentrace.routeforge.router import (
    ROUTEFORGE_EXPERIMENT_ID,
    ROUTEFORGE_ROUTER_ARTIFACT_SCHEMA,
    load_model_artifact,
)
from opentrace.routeforge.serialization import read_artifacts


def test_checked_in_m13_run_is_real_and_test_sealed() -> None:
    root = Path("data/routeforge-m13")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    router_config = json.loads((root / "router-config.json").read_text(encoding="utf-8"))
    m11 = read_artifacts(Path("data/routeforge-m11"))
    m12 = json.loads(Path("data/routeforge-m12/manifest.json").read_text(encoding="utf-8"))

    assert manifest["schema_version"] == ROUTEFORGE_ROUTER_ARTIFACT_SCHEMA
    assert manifest["experiment_id"] == ROUTEFORGE_EXPERIMENT_ID
    assert manifest["dataset_checksum"] == m11.manifest.content_sha256
    assert manifest["dataset_checksum"] == m12["dataset_checksum"]
    assert manifest["split_counts"] == {
        "TRAIN": {"decision_groups": 5, "strategy_rows": 25},
        "VALIDATION": {"decision_groups": 3, "strategy_rows": 15},
        "TEST": {"decision_groups": 1, "strategy_rows": 5},
    }
    assert manifest["test_used_for_model_selection"] is False
    assert manifest["test_evaluated"] is False
    assert manifest["test_metrics"] == (
        "TEST METRICS NOT COMPUTED — DATASET INADEQUATE FOR GATE C EVIDENCE"
    )
    assert router_config["decision_policy_version"] == "routeforge-score-routing-v2"
    assert "score-only prototype" in router_config["score_policy"]
    assert "post-selection" in router_config["score_policy"]
    assert "no threshold" in router_config["score_policy"]
    assert any("COST-AWARE ROUTING POLICY" in item for item in manifest["gate_c_evidence_gap"])
    assert manifest["upstream_integrity"]["m7_v3_unchanged"] is True
    assert manifest["upstream_integrity"]["m9_v3_unchanged"] is True
    assert manifest["upstream_integrity"]["m10_observed_not_validated"] is True
    assert manifest["m13_data_adequacy"].startswith("INADEQUATE —")
    first_decision = (
        (root / "validation_decisions.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert len(json.loads(first_decision)) > 0
    assert len((root / "validation_decisions.jsonl").read_text(encoding="utf-8").splitlines()) == 3
    assert len((root / "validation_evaluation.jsonl").read_text(encoding="utf-8").splitlines()) == 3
    assert not list(root.glob("*test*"))
    artifact, checksum = load_model_artifact(root / "model.json")
    assert artifact.dataset_checksum == m11.manifest.content_sha256
    assert checksum == manifest["model_artifact_checksum"]
