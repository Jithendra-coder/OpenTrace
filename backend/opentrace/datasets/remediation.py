"""Deterministic clone-safe dataset revision used for Gate B remediation."""

from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from opentrace.datasets.generator import DatasetGenerator
from opentrace.datasets.models import (
    DATASET_REMEDIATION_VERSION,
    DATASET_V3_VERSION,
    GENERATOR_V3_VERSION,
    GeneratorConfig,
    ImpactDataset,
    ScenarioDefinition,
    SplitPartition,
)
from opentrace.datasets.scenarios import build_scenarios
from opentrace.ml.features import row_feature_values
from opentrace.ml.models import FeatureSet


@dataclass(frozen=True)
class RemediationConfig:
    """Predeclared inputs for the fresh Gate B dataset."""

    seed: int = 20270813
    synthetic_scenarios: int = 30
    include_curated: bool = True
    include_realistic: bool = True
    split_seed: int = 20270813
    revision: str = "gate-b-remediation-v1"


V3_SEED = 727088594
V3_SPLIT_SEED = 746580208
V3_REVISION = "gate-b-remediation-v3"


def _digest(*parts: object) -> str:
    payload = "\x1f".join(
        part if isinstance(part, str) else json.dumps(part, sort_keys=True, separators=(",", ":"))
        for part in parts
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _canonical_sources(scenario: ScenarioDefinition) -> list[dict[str, str]]:
    return [source.model_dump(mode="json") for source in scenario.sources]


def _freshen_scenario(scenario: ScenarioDefinition, revision: str) -> ScenarioDefinition:
    """Make a new governed fixture without changing its independent truth."""

    marker = _digest(revision, scenario.scenario_id)
    old_spec = re.sub(r"([a-z]+)\.example\.com", r"\1.gateb.example.com", scenario.old_spec)
    new_spec = re.sub(r"([a-z]+)\.example\.com", r"\1.gateb.example.com", scenario.new_spec)
    sources = tuple(
        source.model_copy(
            update={
                "content": re.sub(
                    r"([a-z]+)\.example\.com", r"\1.gateb.example.com", source.content
                )
            }
        )
        for source in scenario.sources
    )
    marker_path = f"__gate_b_marker_{marker}.py"
    sources = tuple(
        sorted(
            sources
            + (
                type(scenario.sources[0])(
                    path=marker_path,
                    content=(
                        f"def marker_{marker}(value: object) -> object:\n"
                        "    return value\n"
                    ),
                ),
            ),
            key=lambda source: source.path,
        )
    )
    scenario_id = _digest(
        "scenario-remediation-v2",
        revision,
        scenario.scenario_id,
        old_spec,
        new_spec,
        _canonical_sources(scenario.model_copy(update={"sources": sources})),
        [target.model_dump(mode="json") for target in scenario.ground_truth],
    )
    return scenario.model_copy(
        update={
            "scenario_id": scenario_id,
            "scenario_fingerprint": _digest(
                "scenario-fingerprint-v2", scenario_id, old_spec, new_spec
            ),
            "repository_id": _digest("repository-v2", scenario.repository_id, revision),
            "repository_family_id": _digest(
                "repository-family-v2", scenario.repository_family_id, revision
            ),
            "api_family_id": _digest("api-family-v2", scenario.api_family_id, revision),
            "migration_id": _digest("migration-v2", scenario.migration_id, scenario_id),
            "old_spec": old_spec,
            "new_spec": new_spec,
            "sources": sources,
            "tags": tuple(sorted((*scenario.tags, "gate-b-remediation"))),
        }
    )


def _source_fingerprint(scenario: ScenarioDefinition) -> str:
    return _digest("source-v2", _canonical_sources(scenario))


def _drop_empty_call_arguments(shape: str) -> str:
    """Normalize the empty ``Call.args`` presentation across Python AST versions."""

    starts: list[int] = []
    cursor = 0
    while (start := shape.find("Call(", cursor)) >= 0:
        starts.append(start)
        cursor = start + len("Call(")
    for start in reversed(starts):
        depth = 0
        for index in range(start + len("Call("), len(shape)):
            if shape[index] == "(":
                depth += 1
            elif shape[index] == ")":
                if depth == 0:
                    if shape[index - 4 : index] == ", []":
                        shape = shape[: index - 4] + shape[index:]
                    break
                depth -= 1
    return shape


def _source_shape(scenario: ScenarioDefinition) -> tuple[tuple[str, str], ...]:
    shapes: list[tuple[str, str]] = []
    for source in scenario.sources:
        try:
            tree = ast.parse(source.content, filename=source.path)
            shape = ast.dump(tree, annotate_fields=False, include_attributes=False)
        except SyntaxError:
            shape = "SYNTAX_ERROR"
        # ast.dump() changed how it prints empty fields between supported Python
        # versions.  Template identities are a frozen cross-version clone guard,
        # so erase those presentation-only empty lists before hashing.
        shape = re.sub(r", [a-z_]+=\[\]", "", shape)
        shape = re.sub(r", \[\](?=\))", "", shape)
        shape = _drop_empty_call_arguments(shape)
        shape = shape.replace("Module([])", "Module()")
        shape = re.sub(r"'[^']*'", "<literal>", shape)
        shape = re.sub(r"marker_[0-9a-f]{24}", "marker", shape)
        path = re.sub(r"__gate_b_marker_[0-9a-f]{24}\.py", "__gate_b_marker.py", source.path)
        shapes.append((path, shape))
    return tuple(sorted(shapes))


def _template_family(scenario: ScenarioDefinition) -> str:
    return _digest(
        "template-family-v2",
        scenario.family.value,
        scenario.mutation_family,
        _source_shape(scenario),
    )


def annotate_leakage_fingerprints(dataset: ImpactDataset) -> ImpactDataset:
    by_scenario: dict[str, tuple[str, str, str, str]] = {}
    for scenario in dataset.scenarios:
        rows = [row for row in dataset.rows if row.scenario_id == scenario.scenario_id]
        candidates = sorted((row.candidate_symbol, row.candidate_file) for row in rows)
        candidate_fp = _digest("candidate-v2", candidates)
        structural_values = [
            (row.candidate_symbol, row_feature_values(row, FeatureSet.STRUCTURAL))
            for row in rows
        ]
        heuristic_values = [
            (row.candidate_symbol, row_feature_values(row, FeatureSet.STRUCTURAL_HEURISTICS))
            for row in rows
        ]
        structural_fp = _digest(
            "feature-a-v2",
            sorted(
                structural_values,
                key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")),
            ),
        )
        heuristic_fp = _digest(
            "feature-b-v2",
            sorted(
                heuristic_values,
                key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")),
            ),
        )
        by_scenario[scenario.scenario_id] = (
            _source_fingerprint(scenario),
            candidate_fp,
            structural_fp,
            heuristic_fp,
        )
    scenarios: list[ScenarioDefinition] = []
    for scenario in dataset.scenarios:
        source_fp, candidate_fp, structural_fp, heuristic_fp = by_scenario[scenario.scenario_id]
        scenarios.append(
            scenario.model_copy(
                update={
                    "source_fingerprint": source_fp,
                    "candidate_fingerprint": candidate_fp,
                    "structural_input_fingerprint": structural_fp,
                    "heuristic_input_fingerprint": heuristic_fp,
                    "template_family_id": _template_family(scenario),
                }
            )
        )
    scenario_map = {scenario.scenario_id: scenario for scenario in scenarios}
    annotated_rows = tuple(
        row.model_copy(
            update={
                "source_fingerprint": scenario_map[row.scenario_id].source_fingerprint,
                "candidate_fingerprint": scenario_map[row.scenario_id].candidate_fingerprint,
                "structural_input_fingerprint": scenario_map[
                    row.scenario_id
                ].structural_input_fingerprint,
                "heuristic_input_fingerprint": scenario_map[
                    row.scenario_id
                ].heuristic_input_fingerprint,
                "template_family_id": scenario_map[row.scenario_id].template_family_id,
            }
        )
        for row in dataset.rows
    )
    return dataset.model_copy(update={"scenarios": tuple(scenarios), "rows": annotated_rows})


def _component_groups(dataset: ImpactDataset) -> tuple[tuple[str, tuple[str, ...]], ...]:
    parent = {scenario.scenario_id: scenario.scenario_id for scenario in dataset.scenarios}

    def find(value: str) -> str:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    fields = (
        "source_fingerprint",
        "candidate_fingerprint",
        "structural_input_fingerprint",
        "heuristic_input_fingerprint",
        "template_family_id",
    )
    seen: dict[tuple[str, str], str] = {}
    for scenario in dataset.scenarios:
        for field in fields:
            value = getattr(scenario, field)
            if value is None:
                continue
            key = (field, value)
            if key in seen:
                union(scenario.scenario_id, seen[key])
            else:
                seen[key] = scenario.scenario_id
    groups: dict[str, list[str]] = {}
    for scenario in dataset.scenarios:
        groups.setdefault(find(scenario.scenario_id), []).append(scenario.scenario_id)
    return tuple(
        sorted((root, tuple(sorted(values))) for root, values in groups.items())
    )


def assign_remediation_partitions(
    dataset: ImpactDataset, *, split_seed: int
) -> ImpactDataset:
    """Assign balanced partitions while keeping every clone component together."""

    return _assign_partitions(dataset, split_seed=split_seed, forbidden_test_templates=frozenset())


def assign_v3_partitions(
    dataset: ImpactDataset,
    *,
    split_seed: int,
    forbidden_test_templates: frozenset[str],
) -> ImpactDataset:
    """Seal v3 partitions while excluding historical template families from TEST."""

    return _assign_partitions(
        dataset,
        split_seed=split_seed,
        forbidden_test_templates=forbidden_test_templates,
    )


def _assign_partitions(
    dataset: ImpactDataset,
    *,
    split_seed: int,
    forbidden_test_templates: frozenset[str],
) -> ImpactDataset:
    groups = _component_groups(dataset)
    ordered = sorted(groups, key=lambda item: _digest("split-v2", split_seed, item[1]))
    partitions = (SplitPartition.TRAIN, SplitPartition.VALIDATION, SplitPartition.TEST)
    scenario_index = {scenario.scenario_id: scenario for scenario in dataset.scenarios}
    assignment: dict[str, SplitPartition] = {}
    eligible_index = 0
    for _, scenario_ids in ordered:
        templates = {
            scenario_index[scenario_id].template_family_id for scenario_id in scenario_ids
        }
        allowed = (
            (SplitPartition.TRAIN, SplitPartition.VALIDATION)
            if templates & forbidden_test_templates
            else partitions
        )
        partition = allowed[eligible_index % len(allowed)]
        eligible_index += 1
        assignment.update({scenario_id: partition for scenario_id in scenario_ids})
    rows = tuple(
        row.model_copy(update={"split_partition": assignment[row.scenario_id]})
        for row in dataset.rows
    )
    split_fingerprint = _digest(
        "split-fingerprint-v2",
        sorted((scenario_id, partition.value) for scenario_id, partition in assignment.items()),
    )
    content = "".join(
        f"{row.canonical_json()}\n" for row in sorted(rows, key=lambda item: item.id)
    ).encode("utf-8")
    manifest = dataset.manifest.model_copy(
        update={
            "content_sha256": hashlib.sha256(content).hexdigest(),
            "split_strategy": "clone-safe-component-round-robin-v2",
            "split_fingerprint": split_fingerprint,
        }
    )
    result = dataset.model_copy(update={"manifest": manifest, "rows": rows})
    validate_remediation_partitions(result)
    return result


def validate_remediation_partitions(dataset: ImpactDataset) -> None:
    """Reject forbidden cross-partition exact clones and template reuse."""

    partitions: dict[SplitPartition, list[ScenarioDefinition]] = {
        partition: [] for partition in SplitPartition
    }
    scenario_map = {scenario.scenario_id: scenario for scenario in dataset.scenarios}
    for row in dataset.rows:
        if row.split_partition is not None:
            partitions[row.split_partition].append(scenario_map[row.scenario_id])
    fields = (
        "migration_id",
        "source_fingerprint",
        "candidate_fingerprint",
        "structural_input_fingerprint",
        "heuristic_input_fingerprint",
        "template_family_id",
    )
    for field in fields:
        owners: dict[str, SplitPartition] = {}
        for partition, scenarios in partitions.items():
            for scenario in scenarios:
                value = getattr(scenario, field)
                if value is None:
                    continue
                previous = owners.setdefault(value, partition)
                if previous is not partition:
                    raise ValueError(f"{field} crosses partitions: {value}")
    if any(row.split_partition is None for row in dataset.rows):
        raise ValueError("remediation dataset requires sealed split assignments")


def generate_remediation_dataset(config: RemediationConfig | None = None) -> ImpactDataset:
    settings = config or RemediationConfig()
    generator_config = GeneratorConfig(
        seed=settings.seed,
        synthetic_scenarios=settings.synthetic_scenarios,
        include_curated=settings.include_curated,
        include_realistic=settings.include_realistic,
    )
    scenarios = tuple(
        _freshen_scenario(scenario, settings.revision)
        for scenario in build_scenarios(
            settings.seed,
            settings.synthetic_scenarios,
            settings.include_curated,
            settings.include_realistic,
        )
    )
    dataset = DatasetGenerator(generator_config).generate_scenarios(scenarios)
    dataset = annotate_leakage_fingerprints(dataset)
    content = "".join(
        f"{row.canonical_json()}\n"
        for row in sorted(dataset.rows, key=lambda item: item.id)
    ).encode("utf-8")
    manifest = dataset.manifest.model_copy(
        update={
            "dataset_version": DATASET_REMEDIATION_VERSION,
            "generator_version": "synthetic-impact-generator-v2",
            "revision_reason": (
                "Gate B remediation: isolate model-input clones and evaluate fresh scenarios; "
                "impact-eval-m9-v1 remains historical and compromised."
            ),
            "content_sha256": hashlib.sha256(content).hexdigest(),
        }
    )
    dataset = dataset.model_copy(update={"manifest": manifest})
    return assign_remediation_partitions(dataset, split_seed=settings.split_seed)


def generate_v3_dataset(
    *, forbidden_test_templates: frozenset[str] = frozenset()
) -> ImpactDataset:
    """Generate the single predeclared v3 dataset revision."""

    config = RemediationConfig(
        seed=V3_SEED,
        split_seed=V3_SPLIT_SEED,
        revision=V3_REVISION,
    )
    dataset = generate_remediation_dataset(config)
    pairs = tuple(
        (
            scenario,
            scenario.model_copy(
                update={
                    "scenario_id": _digest("scenario-v3", scenario.scenario_id),
                    "migration_id": _digest("migration-v3", scenario.migration_id),
                }
            ),
        )
        for scenario in dataset.scenarios
    )
    scenarios = tuple(sorted((new for _, new in pairs), key=lambda scenario: scenario.scenario_id))
    scenario_map = {old.scenario_id: new for old, new in pairs}
    rows = tuple(
        row.model_copy(
            update={
                "dataset_version": DATASET_V3_VERSION,
                "scenario_id": scenario_map[row.scenario_id].scenario_id,
                "migration_id": scenario_map[row.scenario_id].migration_id,
                "split_group_id": scenario_map[row.scenario_id].migration_id,
            }
        )
        for row in dataset.rows
    )
    updated = dataset.model_copy(
        update={
            "manifest": dataset.manifest.model_copy(
                update={
                    "dataset_version": DATASET_V3_VERSION,
                    "generator_version": GENERATOR_V3_VERSION,
                    "seed": config.seed,
                    "config": GeneratorConfig(
                        seed=config.seed,
                        synthetic_scenarios=config.synthetic_scenarios,
                        include_curated=config.include_curated,
                        include_realistic=config.include_realistic,
                    ),
                    "revision_reason": (
                        "Gate B final remediation: fresh v3 data with pre-generation protocol, "
                        "historical exclusion, canonical ordering, and sealed chronology."
                    ),
                }
            ),
            "scenarios": scenarios,
            "rows": rows,
        }
    )
    updated = annotate_leakage_fingerprints(updated)
    return assign_v3_partitions(
        updated,
        split_seed=config.split_seed,
        forbidden_test_templates=forbidden_test_templates,
    )


def remediation_data_manifest(config: RemediationConfig, dataset: ImpactDataset) -> dict[str, Any]:
    return {
        "manifest_version": "gate-b-remediation-data-v1",
        "revision": config.revision,
        "generator_version": dataset.manifest.generator_version,
        "dataset_version": dataset.manifest.dataset_version,
        "scenario_count": len(dataset.scenarios),
        "synthetic_scenarios": config.synthetic_scenarios,
        "include_curated": config.include_curated,
        "include_realistic": config.include_realistic,
        "seed": config.seed,
        "split_seed": config.split_seed,
        "split_strategy": dataset.manifest.split_strategy,
        "split_fingerprint": dataset.manifest.split_fingerprint,
        "api_family_plan": "payments, identity, inventory plus fresh namespace",
        "mutation_family_plan": "governed generator families; no metric-driven filtering",
        "candidate_generation_policy": "all analyzed CodeSymbol nodes",
        "hard_positive_policy": "scenario hard_positive and affected ground truth",
        "hard_negative_policy": "scenario hard_negative or governed high-risk negative",
        "clone_checks": [
            "source_fingerprint",
            "candidate_fingerprint",
            "structural_input_fingerprint",
            "heuristic_input_fingerprint",
            "template_family_id",
        ],
        "dataset_checksum": dataset.manifest.content_sha256,
    }
