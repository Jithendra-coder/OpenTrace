"""RouteForge real artifact and upstream-integrity integration checks."""

import json
from pathlib import Path

from opentrace.routeforge.serialization import read_artifacts


def test_checked_in_m12_run_is_real_grouped_validation_artifact() -> None:
    root = Path("data/routeforge_baselines")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    dataset = read_artifacts(Path("data/routeforge_scenarios"))

    assert manifest["schema_version"] == "routeforge-baselines-v1"
    assert manifest["dataset_checksum"] == dataset.manifest.content_sha256
    assert manifest["split_counts"] == {
        "TRAIN": {"decision_groups": 5, "strategy_rows": 25},
        "VALIDATION": {"decision_groups": 3, "strategy_rows": 15},
        "TEST": {"decision_groups": 1, "strategy_rows": 5},
    }
    assert manifest["test_used_for_model_selection"] is False
    assert manifest["test_evaluated"] is False
    assert manifest["upstream_integrity"]["m7_v3_unchanged"] is True
    assert manifest["upstream_integrity"]["m9_v3_unchanged"] is True
    assert manifest["upstream_integrity"]["m10_observed_not_validated"] is True
    assert len(manifest["experiment_ids"]) == 6
    for experiment_id in manifest["experiment_ids"]:
        assert (root / "experiments" / f"{experiment_id}.json").exists()
        assert (root / "decisions" / f"{experiment_id}.jsonl").exists()
        experiment = json.loads(
            (root / "experiments" / f"{experiment_id}.json").read_text(encoding="utf-8")
        )
        assert experiment["artifact_paths"] == {
            "experiment": f"experiments/{experiment_id}.json",
            "predictions": f"predictions/{experiment_id}.jsonl",
            "decisions": f"decisions/{experiment_id}.jsonl",
            "model_provenance": f"models/{experiment_id}.json",
        }
    assert (root / "label_shuffle_sanity.json").exists()
