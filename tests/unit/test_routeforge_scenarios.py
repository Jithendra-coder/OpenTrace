"""M11 RouteForge schema, objective, leakage, and reproducibility tests."""

from pathlib import Path

from opentrace.routeforge import (
    OutcomeProvenance,
    RouteChoice,
    RouteForgeDatasetGenerator,
    RouteForgeStrategy,
    RoutingObjective,
    StrategyOutcome,
    StrategyOutcomeStatus,
    content_checksum,
    derive_preferred_strategy,
    read_artifacts,
    validate_dataset,
    write_artifacts,
)


def _outcome(
    strategy: RouteForgeStrategy,
    status: StrategyOutcomeStatus,
    cost: float,
    latency: float,
    quality: float,
) -> StrategyOutcome:
    return StrategyOutcome(
        id=f"outcome-{strategy.value}",
        decision_group_id="group",
        strategy=strategy,
        outcome=status,
        provenance=OutcomeProvenance.SYNTHETIC_ORACLE,
        producer="test-oracle",
        synthetic_cost_units=cost,
        synthetic_latency_units=latency,
        quality_units=quality,
        notes="test oracle",
    )


def test_strategy_taxonomy_and_canonical_artifact() -> None:
    dataset = RouteForgeDatasetGenerator().generate()
    assert set(RouteForgeStrategy) == {
        RouteForgeStrategy.NO_AI,
        RouteForgeStrategy.DETERMINISTIC,
        RouteForgeStrategy.SMALL,
        RouteForgeStrategy.MEDIUM,
        RouteForgeStrategy.STRONG,
    }
    assert len(dataset.scenarios) == 9
    assert len(dataset.rows) == 45
    assert dataset.manifest.preferred_strategy_counts[RouteChoice.NO_FEASIBLE_STRATEGY.value] == 1
    assert dataset.manifest.provenance_counts[OutcomeProvenance.OBSERVED_DETERMINISTIC.value] == 1
    assert dataset.manifest.strategy_counts == {
        strategy.value: 9 for strategy in RouteForgeStrategy
    }


def test_objective_derivation_and_no_feasible_state() -> None:
    objective = RoutingObjective()
    outcomes = tuple(
        _outcome(strategy, StrategyOutcomeStatus.FAILURE, index, index, 90)
        for index, strategy in enumerate(RouteForgeStrategy)
    )
    selected, feasible = derive_preferred_strategy(
        outcomes, objective, no_repair_required=False
    )
    assert selected is RouteChoice.NO_FEASIBLE_STRATEGY
    assert feasible == ()

    outcomes = (
        _outcome(RouteForgeStrategy.NO_AI, StrategyOutcomeStatus.NOT_APPLICABLE, 0, 0, 0),
        _outcome(RouteForgeStrategy.DETERMINISTIC, StrategyOutcomeStatus.SUCCESS, 0, 0, 100),
        _outcome(RouteForgeStrategy.SMALL, StrategyOutcomeStatus.SUCCESS, 1, 1, 80),
        _outcome(RouteForgeStrategy.MEDIUM, StrategyOutcomeStatus.SUCCESS, 2, 2, 90),
        _outcome(RouteForgeStrategy.STRONG, StrategyOutcomeStatus.SUCCESS, 4, 4, 100),
    )
    selected, feasible = derive_preferred_strategy(
        outcomes, objective, no_repair_required=False
    )
    assert selected is RouteChoice.DETERMINISTIC
    assert feasible == (
        RouteForgeStrategy.DETERMINISTIC,
        RouteForgeStrategy.SMALL,
        RouteForgeStrategy.MEDIUM,
        RouteForgeStrategy.STRONG,
    )

    for expected, successful in (
        (RouteChoice.SMALL, {RouteForgeStrategy.SMALL, RouteForgeStrategy.MEDIUM}),
        (RouteChoice.MEDIUM, {RouteForgeStrategy.MEDIUM, RouteForgeStrategy.STRONG}),
        (RouteChoice.STRONG, {RouteForgeStrategy.STRONG}),
    ):
        table = tuple(
            _outcome(
                strategy,
                StrategyOutcomeStatus.SUCCESS
                if strategy in successful
                else StrategyOutcomeStatus.FAILURE,
                index,
                index,
                80,
            )
            for index, strategy in enumerate(RouteForgeStrategy)
        )
        selected, _ = derive_preferred_strategy(
            table, objective, no_repair_required=False
        )
        assert selected is expected

    tie_table = tuple(
        _outcome(
            strategy,
            StrategyOutcomeStatus.SUCCESS
            if strategy in {RouteForgeStrategy.SMALL, RouteForgeStrategy.MEDIUM}
            else StrategyOutcomeStatus.FAILURE,
            1 if strategy in {RouteForgeStrategy.SMALL, RouteForgeStrategy.MEDIUM} else 4,
            1,
            80,
        )
        for strategy in RouteForgeStrategy
    )
    selected, _ = derive_preferred_strategy(
        tie_table, objective, no_repair_required=False
    )
    assert selected is RouteChoice.SMALL

    no_repair = derive_preferred_strategy(
        outcomes, objective, no_repair_required=True
    )
    assert no_repair == (RouteChoice.NO_AI, (RouteForgeStrategy.NO_AI,))


def test_unknown_is_not_failure_and_ai_required_is_not_route_label() -> None:
    dataset = RouteForgeDatasetGenerator().generate()
    scenarios = {scenario.scenario_id: scenario for scenario in dataset.scenarios}
    unknown = scenarios["scenario-008"]
    assert unknown.context.features.m10_outcome == "AI_REQUIRED"
    assert unknown.preferred_strategy is RouteChoice.MEDIUM
    statuses = {outcome.strategy: outcome.outcome for outcome in unknown.outcomes}
    assert statuses[RouteForgeStrategy.SMALL] is StrategyOutcomeStatus.UNKNOWN
    assert statuses[RouteForgeStrategy.MEDIUM] is StrategyOutcomeStatus.SUCCESS

    independent = {
        scenario.scenario_id: scenario
        for scenario in dataset.scenarios
        if scenario.scenario_id in {"scenario-003", "scenario-004"}
    }
    assert {
        scenario.context.features.m10_outcome for scenario in independent.values()
    } == {"AI_REQUIRED"}
    assert independent["scenario-003"].preferred_strategy is RouteChoice.SMALL
    assert independent["scenario-004"].preferred_strategy is RouteChoice.MEDIUM
    no_repair = scenarios["scenario-006"]
    assert no_repair.preferred_strategy is RouteChoice.NO_AI
    assert {
        outcome.outcome for outcome in no_repair.outcomes
    } == {StrategyOutcomeStatus.NOT_APPLICABLE}


def test_features_are_allowlisted_and_strategy_rows_stay_together() -> None:
    dataset = RouteForgeDatasetGenerator().generate()
    forbidden = {
        "strategy",
        "outcome",
        "preferred_strategy",
        "oracle_strategy",
        "synthetic_cost_units",
        "synthetic_latency_units",
    }
    for scenario in dataset.scenarios:
        assert set(scenario.context.features.model_dump()) == set(
            scenario.context.features.ALLOWLIST
        )
        assert not forbidden.intersection(scenario.context.features.model_dump())
        rows = [row for row in dataset.rows if row.scenario_id == scenario.scenario_id]
        assert len({row.split_partition for row in rows}) == 1
        assert {row.split_group_id for row in rows} == {scenario.decision_group_id}


def test_canonical_m10_evidence_is_observed_and_not_validated() -> None:
    dataset = RouteForgeDatasetGenerator().generate()
    scenario = next(item for item in dataset.scenarios if item.scenario_id == "scenario-001")
    assert scenario.context.feature_origin.value == "OBSERVED_M1_M10"
    assert scenario.context.m10_evidence.rule_id == "remove-request-property-v1"
    deterministic = next(
        outcome
        for outcome in scenario.outcomes
        if outcome.strategy is RouteForgeStrategy.DETERMINISTIC
    )
    assert deterministic.provenance is OutcomeProvenance.OBSERVED_DETERMINISTIC
    assert deterministic.candidate_generated is True
    assert deterministic.outcome is StrategyOutcomeStatus.UNKNOWN
    assert "no validation" in deterministic.notes


def test_roundtrip_checksum_and_seed_reproducibility(tmp_path: Path) -> None:
    first = RouteForgeDatasetGenerator().generate()
    second = RouteForgeDatasetGenerator().generate()
    assert first.canonical_json() == second.canonical_json()
    assert content_checksum(first) == first.manifest.content_sha256

    write_artifacts(first, tmp_path)
    loaded = read_artifacts(tmp_path)
    validate_dataset(loaded)
    assert loaded.canonical_json() == first.canonical_json()
