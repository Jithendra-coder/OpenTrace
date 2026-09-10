"""M7 deterministic scenario generation and real M1-M6 feature extraction."""

from __future__ import annotations

import hashlib
import tempfile
from collections import Counter, deque
from pathlib import Path

from opentrace.blast_radius import analyze_vertical_slice
from opentrace.blast_radius.models import BlastRadius, ImpactedSymbol
from opentrace.code_analysis.call_models import StaticCallGraph
from opentrace.code_analysis.models import APICallSite, CodeSymbol, ResolutionState
from opentrace.contracts.models import APIChange
from opentrace.datasets.models import (
    DATASET_VERSION,
    AnalyzerObservation,
    DatasetFeatures,
    DatasetManifest,
    FeatureEvidence,
    GeneratorConfig,
    GroundTruthImpactType,
    GroundTruthLabel,
    GroundTruthTarget,
    ImpactDataset,
    ImpactDatasetRow,
    ScenarioDefinition,
    SplitPartition,
)
from opentrace.datasets.scenarios import build_scenarios
from opentrace.impact.models import DirectImpact


class DatasetGenerator:
    """Construct independent-truth scenarios, then observe the real core."""

    def __init__(self, config: GeneratorConfig | None = None) -> None:
        self.config = config or GeneratorConfig()

    def generate(self) -> ImpactDataset:
        scenarios = build_scenarios(
            self.config.seed,
            self.config.synthetic_scenarios,
            self.config.include_curated,
            self.config.include_realistic,
        )
        return self.generate_scenarios(scenarios)

    def generate_scenarios(
        self, scenarios: tuple[ScenarioDefinition, ...]
    ) -> ImpactDataset:
        """Generate rows for an already materialized, governed scenario set."""
        canonical_scenarios = tuple(sorted(scenarios, key=lambda scenario: scenario.scenario_id))
        rows: list[ImpactDatasetRow] = []
        for scenario in canonical_scenarios:
            rows.extend(self._run_scenario(scenario))
        rows = sorted(rows, key=lambda row: row.id)
        manifest = _manifest(self.config, canonical_scenarios, rows)
        return ImpactDataset(manifest=manifest, scenarios=canonical_scenarios, rows=tuple(rows))

    def _run_scenario(self, scenario: ScenarioDefinition) -> list[ImpactDatasetRow]:
        with tempfile.TemporaryDirectory(prefix="opentrace-m7-") as directory:
            root = Path(directory)
            old_spec = root / "old.json"
            new_spec = root / "new.json"
            old_spec.write_text(scenario.old_spec, encoding="utf-8")
            new_spec.write_text(scenario.new_spec, encoding="utf-8")
            for source in scenario.sources:
                path = root / source.path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(source.content, encoding="utf-8")
            result = analyze_vertical_slice(old_spec, new_spec, root)
        truth = {target.symbol: target for target in scenario.ground_truth}
        rows: list[ImpactDatasetRow] = []
        for change in result.changes:
            for symbol in result.graph.nodes if result.graph is not None else ():
                rows.append(self._row(scenario, result, change, symbol, truth))
        return rows

    def _row(
        self,
        scenario: ScenarioDefinition,
        result: BlastRadius,
        change: APIChange,
        symbol: CodeSymbol,
        truth: dict[str, GroundTruthTarget],
    ) -> ImpactDatasetRow:
        # The result/change types are concrete M1-M6 objects; keeping this helper
        # local avoids duplicating their domain models in the dataset package.
        if result.graph is None:
            raise ValueError("M6 result must include its static call graph")
        direct: DirectImpact | None = (
            next(
                impact
                for impact in result.direct_impacts
                if impact.change_id == change.id and impact.symbol == symbol.qualified_name
            )
            if any(
                impact.change_id == change.id and impact.symbol == symbol.qualified_name
                for impact in result.direct_impacts
            )
            else None
        )
        impacted: ImpactedSymbol | None = (
            next(
                item
                for item in result.impacted_symbols
                if item.symbol == symbol.qualified_name and change.id in item.source_change_ids
            )
            if any(
                item.symbol == symbol.qualified_name and change.id in item.source_change_ids
                for item in result.impacted_symbols
            )
            else None
        )
        target = truth.get(symbol.qualified_name)
        label = GroundTruthLabel.AFFECTED if target is not None else GroundTruthLabel.UNAFFECTED
        target_type = target.impact_type if target is not None else GroundTruthImpactType.UNAFFECTED
        target_distance = target.distance if target is not None else None
        target_path = target.path if target is not None else ()
        call_site = _candidate_call(result.call_sites, symbol.id, direct)
        features = _features(result, change, direct, impacted, call_site, symbol.id)
        coverage_state = _coverage_state(result.graph)
        observation = AnalyzerObservation(
            direct_match=direct is not None,
            indirect_match=impacted is not None and impacted.impact_type.value == "INDIRECT",
            impact_type=impacted.impact_type.value if impacted is not None else None,
            certainty=impacted.certainty
            if impacted is not None
            else (
                direct.certainty
                if direct is not None
                else (
                    call_site.url_resolution_state
                    if call_site is not None
                    else ResolutionState.UNRESOLVED
                )
            ),
            distance=impacted.distance if impacted is not None else None,
            propagation_path=(
                impacted.propagation[0].path
                if impacted is not None and impacted.propagation
                else ()
            ),
            unmatched_change=change.id in result.unmatched_change_ids,
            coverage_state=coverage_state,
            warnings=tuple(result.warnings),
        )
        error_flags: list[str] = []
        if label is GroundTruthLabel.AFFECTED and direct is None:
            error_flags.append("GROUND_TRUTH_POSITIVE_NO_DIRECT_MATCH")
        if target_type is GroundTruthImpactType.INDIRECT and impacted is None:
            error_flags.append("GROUND_TRUTH_INDIRECT_NO_GRAPH_PATH")
        if (
            label is GroundTruthLabel.UNAFFECTED
            and call_site is not None
            and result.risk_assessment is not None
            and result.risk_assessment.risk_score >= 50
        ):
            error_flags.append("HARD_NEGATIVE_HEURISTIC_SCORE")
        if call_site is not None and call_site.url_resolution_state is not ResolutionState.EXACT:
            error_flags.append("PARTIAL_OR_UNRESOLVED_URL")
        if result.graph is not None and result.graph.coverage.files_failed:
            error_flags.append("FAILED_FILE_COVERAGE")
        if result.graph is not None and result.graph.coverage.calls_unresolved:
            error_flags.append("UNRESOLVED_CALL_COVERAGE")
        row_id = _digest(DATASET_VERSION, scenario.scenario_id, change.id, symbol.id)
        return ImpactDatasetRow(
            id=f"row-{row_id}",
            scenario_id=scenario.scenario_id,
            scenario_fingerprint=scenario.scenario_fingerprint,
            repository_id=scenario.repository_id,
            repository_family_id=scenario.repository_family_id,
            api_family_id=scenario.api_family_id,
            migration_id=scenario.migration_id,
            mutation_family=change.category.value,
            api_change_id=change.id,
            candidate_symbol_id=symbol.id,
            candidate_symbol=symbol.qualified_name,
            candidate_file=symbol.file,
            ground_truth_label=label,
            ground_truth_impact_type=target_type,
            ground_truth_distance=target_distance,
            ground_truth_path=target_path,
            ground_truth_rationale=(
                target.rationale
                if target is not None
                else (
                    "Scenario construction marked this candidate outside the changed "
                    "dependency set."
                )
            ),
            features=features,
            observation=observation,
            family=scenario.family,
            provenance=scenario.provenance,
            hard_negative=scenario.hard_negative or "HARD_NEGATIVE_HEURISTIC_SCORE" in error_flags,
            hard_positive=scenario.hard_positive and label is GroundTruthLabel.AFFECTED,
            error_flags=tuple(sorted(error_flags)),
            split_group_id=scenario.migration_id,
        )


def generate_dataset(config: GeneratorConfig | None = None) -> ImpactDataset:
    return DatasetGenerator(config).generate()


def assign_group_partitions(
    dataset: ImpactDataset,
    *,
    seed: int = 42,
    group_by: str = "migration_id",
) -> ImpactDataset:
    """Assign optional train/validation/test partitions by whole groups."""

    if group_by not in {"migration_id", "repository_family_id", "api_family_id", "mutation_family"}:
        raise ValueError("group_by must be a governed grouping field")
    groups = sorted({str(getattr(row, group_by)) for row in dataset.rows})
    partitions = {
        group: (SplitPartition.TRAIN, SplitPartition.VALIDATION, SplitPartition.TEST)[
            int(_digest("split", seed, group), 16) % 3
        ]
        for group in groups
    }
    rows = tuple(
        row.model_copy(update={"split_partition": partitions[str(getattr(row, group_by))]})
        for row in dataset.rows
    )
    return dataset.model_copy(update={"rows": rows})


def _manifest(
    config: GeneratorConfig,
    scenarios: tuple[ScenarioDefinition, ...],
    rows: list[ImpactDatasetRow],
) -> DatasetManifest:
    content = "".join(f"{row.canonical_json()}\n" for row in rows).encode("utf-8")
    labels = Counter(row.ground_truth_label for row in rows)
    types = Counter(row.ground_truth_impact_type for row in rows)
    evidence = Counter(row.observation.certainty or row.observation.coverage_state for row in rows)
    scenario_counts = Counter(scenario.scenario_fingerprint for scenario in scenarios)
    row_counts = Counter(row.id for row in rows)
    return DatasetManifest(
        seed=config.seed,
        config=config,
        scenario_count=len(scenarios),
        migration_count=len({scenario.migration_id for scenario in scenarios}),
        row_count=len(rows),
        positive_count=labels[GroundTruthLabel.AFFECTED],
        negative_count=labels[GroundTruthLabel.UNAFFECTED],
        direct_count=types[GroundTruthImpactType.DIRECT],
        indirect_count=types[GroundTruthImpactType.INDIRECT],
        mutation_families=tuple(sorted({scenario.mutation_family for scenario in scenarios})),
        api_family_ids=tuple(sorted({scenario.api_family_id for scenario in scenarios})),
        repository_family_ids=tuple(
            sorted({scenario.repository_family_id for scenario in scenarios})
        ),
        evidence_exact=evidence[ResolutionState.EXACT],
        evidence_partial=evidence[ResolutionState.PARTIAL],
        evidence_unresolved=evidence[ResolutionState.UNRESOLVED],
        scenario_duplicates=sum(max(0, count - 1) for count in scenario_counts.values()),
        row_duplicates=sum(max(0, count - 1) for count in row_counts.values()),
        content_sha256=hashlib.sha256(content).hexdigest(),
    )


def _features(
    result: BlastRadius,
    change: APIChange,
    direct: DirectImpact | None,
    impacted: ImpactedSymbol | None,
    call_site: APICallSite | None,
    symbol_id: str,
) -> DatasetFeatures:
    evidence = tuple(
        FeatureEvidence(
            name=item.feature,
            observed_value=str(item.observed_value),
            contribution=item.contribution,
            resolution_state=item.resolution_state,
            explanation=item.explanation,
        )
        for item in (direct.evidence if direct is not None else ())
    )
    names = {item.name for item in evidence}
    graph_distance = impacted.distance if impacted is not None else None
    graph = result.graph
    if graph is None:
        raise ValueError("M6 result must include its static call graph")
    direct_callers, upstream_callers = _caller_counts(graph, symbol_id)
    return DatasetFeatures(
        change_category=change.category.value,
        change_severity=change.severity.value,
        change_certainty=change.certainty.value,
        breaking_classification=change.breaking_classification.value,
        compatibility_direction=change.compatibility_direction.value,
        evidence=evidence,
        endpoint_path_match=True if "endpoint_path_match" in names else None,
        host_match=True if "api_identity" in names else None,
        method_match=True if "http_method_match" in names else None,
        request_field_overlap=direct.matched_request_fields if direct is not None else (),
        response_field_overlap=direct.matched_response_fields if direct is not None else (),
        parameter_overlap=direct.matched_parameter_locations if direct is not None else (),
        direct_reference=direct is not None,
        url_resolution_state=call_site.url_resolution_state if call_site is not None else None,
        request_resolution_state=(
            call_site.request_field_resolution_state if call_site is not None else None
        ),
        response_resolution_state=(
            call_site.response_field_resolution_state if call_site is not None else None
        ),
        graph_distance=graph_distance,
        direct_caller_count=direct_callers,
        upstream_caller_count=upstream_callers,
        coverage_unresolved_calls=graph.coverage.calls_unresolved,
        coverage_failed_files=graph.coverage.files_failed,
        m4_impact_score=direct.impact_score if direct is not None else None,
        m6_risk_score=result.risk_assessment.risk_score
        if result.risk_assessment is not None
        else None,
        m6_risk_level=(
            result.risk_assessment.risk_level.value if result.risk_assessment is not None else None
        ),
    )


def _candidate_call(
    calls: tuple[APICallSite, ...], symbol_id: str, direct: DirectImpact | None
) -> APICallSite | None:
    if direct is not None:
        return next((call for call in calls if call.id == direct.call_site_id), None)
    candidates = sorted(
        (call for call in calls if call.owning_symbol_id == symbol_id), key=lambda call: call.id
    )
    return candidates[0] if candidates else None


def _coverage_state(graph: StaticCallGraph) -> ResolutionState:
    if graph.coverage.files_failed or graph.coverage.calls_unresolved:
        return ResolutionState.PARTIAL
    return ResolutionState.EXACT


def _caller_counts(graph: StaticCallGraph, symbol_id: str) -> tuple[int, int]:
    incoming: dict[str, set[str]] = {}
    for edge in graph.edges:
        incoming.setdefault(edge.callee_symbol_id, set()).add(edge.caller_symbol_id)
    direct = len(incoming.get(symbol_id, set()))
    seen: set[str] = set()
    queue: deque[str] = deque(incoming.get(symbol_id, set()))
    while queue:
        current = queue.popleft()
        if current in seen:
            continue
        seen.add(current)
        queue.extend(sorted(incoming.get(current, set())))
    return direct, len(seen)


def _digest(*parts: object) -> str:
    payload = "\x1f".join(str(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
