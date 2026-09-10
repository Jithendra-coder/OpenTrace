"""Deterministic JSONL serialization and integrity checks for M11."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from opentrace.routeforge.models import (
    RouteForgeDataset,
    RouteForgeDatasetRow,
    RouteForgeScenario,
    RouteForgeStrategy,
    derive_preferred_strategy,
    stable_id,
)


def scenarios_jsonl(scenarios: tuple[RouteForgeScenario, ...]) -> str:
    return "".join(
        f"{scenario.canonical_json()}\n"
        for scenario in sorted(scenarios, key=lambda item: item.scenario_id)
    )


def rows_jsonl(rows: tuple[RouteForgeDatasetRow, ...]) -> str:
    return "".join(
        f"{row.canonical_json()}\n" for row in sorted(rows, key=lambda item: item.id)
    )


def content_bytes(dataset: RouteForgeDataset) -> bytes:
    return (scenarios_jsonl(dataset.scenarios) + rows_jsonl(dataset.rows)).encode("utf-8")


def content_checksum(dataset: RouteForgeDataset) -> str:
    return hashlib.sha256(content_bytes(dataset)).hexdigest()


def parse_scenarios(content: str) -> tuple[RouteForgeScenario, ...]:
    scenarios: list[RouteForgeScenario] = []
    for line_number, line in enumerate(content.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            scenarios.append(RouteForgeScenario.model_validate_json(line))
        except ValueError as error:
            raise ValueError(f"invalid RouteForge scenario at line {line_number}") from error
    return tuple(sorted(scenarios, key=lambda item: item.scenario_id))


def parse_rows(content: str) -> tuple[RouteForgeDatasetRow, ...]:
    rows: list[RouteForgeDatasetRow] = []
    for line_number, line in enumerate(content.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(RouteForgeDatasetRow.model_validate_json(line))
        except ValueError as error:
            raise ValueError(f"invalid RouteForge row at line {line_number}") from error
    return tuple(sorted(rows, key=lambda item: item.id))


def validate_dataset(dataset: RouteForgeDataset) -> None:
    if dataset.manifest.content_sha256 != content_checksum(dataset):
        raise ValueError("RouteForge manifest checksum does not match content")
    scenarios = {scenario.scenario_id: scenario for scenario in dataset.scenarios}
    if len(scenarios) != len(dataset.scenarios):
        raise ValueError("scenario IDs must be unique")
    if len({row.id for row in dataset.rows}) != len(dataset.rows):
        raise ValueError("row IDs must be unique")
    if dataset.manifest.scenario_count != len(dataset.scenarios):
        raise ValueError("manifest scenario count mismatch")
    if dataset.manifest.decision_group_count != len(
        {scenario.decision_group_id for scenario in dataset.scenarios}
    ):
        raise ValueError("manifest decision-group count mismatch")
    if dataset.manifest.strategy_outcome_row_count != len(dataset.rows):
        raise ValueError("manifest strategy-row count mismatch")
    for scenario in dataset.scenarios:
        rows = [row for row in dataset.rows if row.scenario_id == scenario.scenario_id]
        if len(rows) != 5:
            raise ValueError("every decision group must contain five strategy rows")
        if {row.strategy for row in rows} != set(RouteForgeStrategy):
            raise ValueError("every decision group must contain every strategy")
        if any(row.decision_group_id != scenario.decision_group_id for row in rows):
            raise ValueError("strategy rows crossed decision groups")
        if len({row.split_partition for row in rows}) != 1:
            raise ValueError("strategy rows crossed split partitions")
        if any(row.features != scenario.context.features for row in rows):
            raise ValueError("strategy rows do not preserve pre-decision features")
        if any(row.preferred_strategy is not scenario.preferred_strategy for row in rows):
            raise ValueError("strategy rows disagree on preferred strategy")
        outcome_map = {outcome.strategy: outcome for outcome in scenario.outcomes}
        if any(
            row.outcome != outcome_map[row.strategy].outcome
            or row.outcome_provenance != outcome_map[row.strategy].provenance
            for row in rows
        ):
            raise ValueError("strategy rows disagree with their outcome table")
        preferred, feasible = derive_preferred_strategy(
            scenario.outcomes,
            dataset.manifest.objective,
            no_repair_required=scenario.context.no_repair_required,
        )
        if preferred is not scenario.preferred_strategy or feasible != scenario.feasible_strategies:
            raise ValueError("preferred strategy does not match the frozen objective")
        expected_fingerprint = stable_id(
            "routeforge-outcome-table",
            *(outcome.canonical_json() for outcome in scenario.outcomes),
        )
        if expected_fingerprint != scenario.outcome_table_fingerprint:
            raise ValueError("outcome table fingerprint mismatch")
    strategy_groups = Counter(row.strategy for row in dataset.rows)
    if any(strategy_groups[strategy] != len(dataset.scenarios) for strategy in strategy_groups):
        raise ValueError("strategy rows are not complete across decision groups")


def write_artifacts(
    dataset: RouteForgeDataset, output_directory: Path | str
) -> tuple[Path, Path, Path]:
    validate_dataset(dataset)
    directory = Path(output_directory)
    directory.mkdir(parents=True, exist_ok=True)
    scenarios_path = directory / "scenarios.jsonl"
    rows_path = directory / "canonical.jsonl"
    manifest_path = directory / "manifest.json"
    scenarios_path.write_text(scenarios_jsonl(dataset.scenarios), encoding="utf-8")
    rows_path.write_text(rows_jsonl(dataset.rows), encoding="utf-8")
    manifest_path.write_text(dataset.manifest.canonical_json() + "\n", encoding="utf-8")
    return scenarios_path, rows_path, manifest_path


def read_artifacts(output_directory: Path | str) -> RouteForgeDataset:
    directory = Path(output_directory)
    manifest_data = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    dataset = RouteForgeDataset(
        manifest=manifest_data,
        scenarios=parse_scenarios((directory / "scenarios.jsonl").read_text(encoding="utf-8")),
        rows=parse_rows((directory / "canonical.jsonl").read_text(encoding="utf-8")),
    )
    validate_dataset(dataset)
    return dataset
