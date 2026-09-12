"""Regression tests for Gate C v3 abstention and bootstrap semantics."""

from pathlib import Path

from opentrace.routeforge.gate_c_evidence import _bootstrap_intervals, _decision_metrics
from opentrace.routeforge.models import RouteChoice, RouteForgeStrategy
from opentrace.routeforge.router import select_classified_strategy
from opentrace.routeforge.serialization import read_artifacts


def _context(name: str):
    dataset = read_artifacts(Path("data/routeforge_scenarios"))
    return next(item.context for item in dataset.scenarios if item.scenario_id == name)


def test_v3_classified_selection_represents_learned_abstention_and_all_routes() -> None:
    deterministic_context = _context("scenario-001")
    ai_required = _context("scenario-007")
    score_floor = {
        RouteForgeStrategy.DETERMINISTIC: -1.0,
        RouteForgeStrategy.SMALL: -1.0,
        RouteForgeStrategy.MEDIUM: -1.0,
        RouteForgeStrategy.STRONG: -1.0,
    }
    choice, reason = select_classified_strategy(
        ai_required, score_floor, read_artifacts(Path("data/routeforge_scenarios")).manifest.objective
    )
    assert choice is RouteChoice.NO_FEASIBLE_STRATEGY
    assert reason == "LEARNED_ABSTENTION"

    for strategy, expected in (
        (RouteForgeStrategy.DETERMINISTIC, RouteChoice.DETERMINISTIC),
        (RouteForgeStrategy.SMALL, RouteChoice.SMALL),
        (RouteForgeStrategy.MEDIUM, RouteChoice.MEDIUM),
        (RouteForgeStrategy.STRONG, RouteChoice.STRONG),
    ):
        scores = dict(score_floor)
        scores[strategy] = 0.0
        choice, reason = select_classified_strategy(
            deterministic_context,
            scores,
            read_artifacts(Path("data/routeforge_scenarios")).manifest.objective,
        )
        assert choice is expected
        assert reason is None

    no_repair = _context("scenario-006")
    choice, reason = select_classified_strategy(
        no_repair,
        score_floor,
        read_artifacts(Path("data/routeforge_scenarios")).manifest.objective,
    )
    assert choice is RouteChoice.NO_AI
    assert reason is None


def test_bootstrap_point_is_the_canonical_metric_not_a_random_replicate() -> None:
    records = [
        {
            "selected_strategy": "SMALL",
            "oracle_preferred_strategy": "SMALL",
            "objective_satisfied": True,
            "selected_cost_units": 1.0,
            "selected_latency_units": 1.0,
            "objective_regret_units": 0.0,
        },
        {
            "selected_strategy": "STRONG",
            "oracle_preferred_strategy": "STRONG",
            "objective_satisfied": True,
            "selected_cost_units": 4.0,
            "selected_latency_units": 4.0,
            "objective_regret_units": 0.0,
        },
    ]
    result = _bootstrap_intervals({"Random": records}, seed=7, replicates=20)["Random"]
    assert result["intervals"]["cost"]["point"] == _decision_metrics(records)[
        "synthetic_average_cost_units"
    ]
    assert result["point_estimate_semantics"].startswith("canonical held-out")
