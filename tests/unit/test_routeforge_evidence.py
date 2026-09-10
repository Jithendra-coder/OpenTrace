import json
from pathlib import Path

import pytest
from opentrace.routeforge.gate_c_evidence import (
    _partition_fingerprints,
    _score_policy_v2,
    run_formal_gate_c_test,
)
from opentrace.routeforge.models import RouteChoice, RouteForgeStrategy
from opentrace.routeforge.serialization import read_artifacts

ROOT = Path(__file__).parents[2]


def test_gate_c_v2_manifest_is_group_safe_and_independent() -> None:
    dataset = read_artifacts(ROOT / "data" / "routeforge-v2")
    audit = _partition_fingerprints(dataset)
    assert dataset.manifest.dataset_version == "routeforge-dataset-v2"
    assert dataset.manifest.decision_group_count == 64
    assert dataset.manifest.strategy_outcome_row_count == 320
    assert audit["all_zero"] is True
    protocol = json.loads(
        (ROOT / "data" / "routeforge-gate-c" / "protocol.json").read_text(
            encoding="utf-8"
        )
    )
    assert protocol["created_before_generation"] is True
    assert protocol["dataset_checksum"] == "PENDING_GENERATION"


def test_gate_c_pretest_manifest_remains_closed() -> None:
    manifest = json.loads(
        (ROOT / "data" / "routeforge-gate-c" / "pre-test-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["test_accessed"] is False
    assert manifest["test_group_count"] == 12


def test_gate_c_formal_test_seal_rejects_rerun() -> None:
    with pytest.raises(ValueError, match="already completed"):
        run_formal_gate_c_test(
            ROOT / "data" / "routeforge-v2", ROOT / "data" / "routeforge-gate-c"
        )


def test_gate_c_score_policy_uses_explicit_applicability() -> None:
    dataset = read_artifacts(ROOT / "data" / "routeforge-v2")
    scenario = next(
        item
        for item in dataset.scenarios
        if item.preferred_strategy is not RouteChoice.NO_AI
    )
    scores = {strategy: float(index) for index, strategy in enumerate(RouteForgeStrategy)}
    chosen, explanation = _score_policy_v2(scenario, scores)
    assert chosen in {
        RouteChoice.DETERMINISTIC,
        RouteChoice.SMALL,
        RouteChoice.MEDIUM,
        RouteChoice.STRONG,
    }
    assert "uncalibrated score" in explanation
