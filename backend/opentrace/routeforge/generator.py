"""Small deterministic RouteForge scenario and outcome-table generator."""

from __future__ import annotations

import hashlib
from collections import Counter, deque
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from opentrace.blast_radius.models import BlastRadius
from opentrace.blast_radius.vertical import analyze_vertical_slice as analyze_blast_slice
from opentrace.code_analysis.call_models import StaticCallGraph
from opentrace.code_analysis.models import APICallSite, ResolutionState
from opentrace.contracts.models import APIChange, ChangeCategory
from opentrace.impact.models import DirectImpact
from opentrace.migration import (
    analyze_migration_vertical_slice,
)
from opentrace.migration.models import MigrationResult
from opentrace.routeforge.models import (
    DatasetFamily,
    DuplicateAudit,
    FeatureOrigin,
    M10ObservedEvidence,
    OutcomeProvenance,
    RouteForgeConfig,
    RouteForgeDataset,
    RouteForgeDatasetRow,
    RouteForgeFeatures,
    RouteForgeManifest,
    RouteForgeScenario,
    RouteForgeStrategy,
    RoutingDecisionContext,
    RoutingObjective,
    SplitPartition,
    StrategyOutcome,
    StrategyOutcomeStatus,
    derive_preferred_strategy,
    stable_id,
)
from opentrace.routeforge.serialization import content_checksum, validate_dataset


@dataclass(frozen=True)
class _OutcomeSpec:
    status: StrategyOutcomeStatus
    provenance: OutcomeProvenance
    producer: str
    cost: float | None
    latency: float | None
    quality: float | None
    candidate_generated: bool = False
    no_repair_required: bool = False
    notes: str = "Offline scenario outcome; not a validated provider result."


@dataclass(frozen=True)
class _ScenarioPlan:
    scenario_id: str
    family: DatasetFamily
    repository_family_id: str
    api_family_id: str
    migration_id: str
    mutation_family: str
    template_family_id: str
    feature_origin: FeatureOrigin
    features: RouteForgeFeatures
    m10_evidence: M10ObservedEvidence
    no_repair_required: bool
    outcomes: tuple[_OutcomeSpec, ...]
    provenance: str
    tags: tuple[str, ...] = ()


class RouteForgeDatasetGenerator:
    """Generate only offline contexts and independent strategy outcomes."""

    def __init__(self, config: RouteForgeConfig | None = None) -> None:
        self.config = config or RouteForgeConfig()
        self.objective = RoutingObjective()

    def generate(self) -> RouteForgeDataset:
        plans: list[_ScenarioPlan] = []
        if self.config.include_canonical_m10:
            plans.append(self._canonical_plan())
        plans.extend(self._authored_plans())
        scenarios: list[RouteForgeScenario] = []
        rows: list[RouteForgeDatasetRow] = []
        for plan in sorted(plans, key=lambda item: item.scenario_id):
            scenario = self._materialize(plan)
            scenarios.append(scenario)
            rows.extend(self._rows(scenario))
        dataset = RouteForgeDataset(
            manifest=self._manifest(tuple(scenarios), tuple(rows)),
            scenarios=tuple(scenarios),
            rows=tuple(sorted(rows, key=lambda item: item.id)),
        )
        validate_dataset(dataset)
        return dataset

    def _canonical_plan(self) -> _ScenarioPlan:
        root = Path(__file__).parents[3]
        old_spec = root / "demo" / "payment_api_v1.yaml"
        new_spec = root / "demo" / "payment_api_v2.yaml"
        repository = root / "demo" / "ecommerce"
        blast = analyze_blast_slice(old_spec, new_spec, repository)
        migration = analyze_migration_vertical_slice(old_spec, new_spec, repository)
        change = next(
            item
            for item in blast.changes
            if item.category is ChangeCategory.REQUEST_PROPERTY_REMOVED
        )
        impacts = tuple(item for item in blast.direct_impacts if item.change_id == change.id)
        direct = impacts[0] if impacts else None
        call = (
            next((item for item in blast.call_sites if item.id == direct.call_site_id), None)
            if direct is not None
            else None
        )
        migration_result = next(
            (item for item in migration.results if item.plan.change_id == change.id), None
        )
        features = self._observed_features(blast, change, impacts, call, migration_result)
        evidence = self._observed_m10(migration_result)
        curated = OutcomeProvenance.CURATED_ORACLE
        return _ScenarioPlan(
            scenario_id="scenario-001",
            family=DatasetFamily.REALISTIC,
            repository_family_id="repository-ecommerce",
            api_family_id="api-payments",
            migration_id="migration-payments-amount",
            mutation_family=change.category.value,
            template_family_id="template-01",
            feature_origin=FeatureOrigin.OBSERVED_M1_M10,
            features=features,
            m10_evidence=evidence,
            no_repair_required=False,
            outcomes=(
                _oracle(
                    RouteForgeStrategy.NO_AI,
                    StrategyOutcomeStatus.NOT_APPLICABLE,
                    curated,
                    0.0,
                    0.0,
                    None,
                    notes="Repair is required; NO_AI is analysis-only for this scenario.",
                ),
                _observed_deterministic(evidence),
                _oracle(RouteForgeStrategy.SMALL, StrategyOutcomeStatus.SUCCESS, curated, 1, 1, 80),
                _oracle(
                    RouteForgeStrategy.MEDIUM,
                    StrategyOutcomeStatus.SUCCESS,
                    curated,
                    2,
                    2,
                    90,
                ),
                _oracle(
                    RouteForgeStrategy.STRONG,
                    StrategyOutcomeStatus.FAILURE,
                    curated,
                    4,
                    4,
                    100,
                ),
            ),
            provenance="Canonical M1-M10 payment migration with curated offline counterfactuals.",
            tags=("canonical-m10", "real-pipeline"),
        )

    def _authored_plans(self) -> tuple[_ScenarioPlan, ...]:
        base = self._authored_features()
        return (
            self._plan(
                "scenario-002",
                DatasetFamily.CURATED_ADVERSARIAL,
                base,
                self._m10(
                    "DETERMINISTIC_CANDIDATE",
                    "SUPPORTED",
                    "remove-request-property-v1",
                    True,
                    1,
                    1,
                ),
                deterministic_success=True,
                tags=("same-status-different-outcome",),
            ),
            self._plan(
                "scenario-003",
                DatasetFamily.SYNTHETIC,
                base.model_copy(
                    update={
                        "m10_outcome": "AI_REQUIRED",
                        "m10_repairability": "PARTIALLY_SUPPORTED",
                        "deterministic_rule_available": True,
                        "expected_edit_count": 0,
                        "dynamic_payload": True,
                        "source_shape": "dynamic_payload",
                    }
                ),
                self._m10(
                    "AI_REQUIRED",
                    "PARTIALLY_SUPPORTED",
                    "remove-request-property-v1",
                    False,
                    0,
                    0,
                ),
                small_success=True,
                tags=("dynamic-source", "label-independence-a"),
            ),
            self._plan(
                "scenario-004",
                DatasetFamily.SYNTHETIC,
                base.model_copy(
                    update={
                        "m10_outcome": "AI_REQUIRED",
                        "m10_repairability": "PARTIALLY_SUPPORTED",
                        "indirect_exposure_count": 1,
                        "maximum_graph_distance": 1,
                        "shared_payload_ambiguity": True,
                        "source_shape": "shared_payload",
                    }
                ),
                self._m10(
                    "AI_REQUIRED",
                    "PARTIALLY_SUPPORTED",
                    "remove-request-property-v1",
                    False,
                    0,
                    0,
                ),
                medium_success=True,
                tags=("shared-source", "label-independence-b"),
            ),
            self._plan(
                "scenario-005",
                DatasetFamily.CURATED_ADVERSARIAL,
                base.model_copy(
                    update={
                        "m10_outcome": "AI_REQUIRED",
                        "m10_repairability": "PARTIALLY_SUPPORTED",
                        "repair_conflict_count": 1,
                        "maximum_graph_distance": 3,
                        "ambiguity_flag_count": 2,
                        "source_shape": "conflicting_edits",
                    }
                ),
                self._m10(
                    "AI_REQUIRED",
                    "PARTIALLY_SUPPORTED",
                    "remove-request-property-v1",
                    False,
                    0,
                    1,
                ),
                strong_success=True,
                tags=("conflict-case", "escalation"),
            ),
            self._plan(
                "scenario-006",
                DatasetFamily.CURATED_ADVERSARIAL,
                base.model_copy(
                    update={
                        "m10_outcome": "NO_CHANGE",
                        "m10_repairability": "SUPPORTED",
                        "deterministic_rule_available": True,
                        "source_shape": "already-compliant",
                    }
                ),
                self._m10("NO_CHANGE", "SUPPORTED", "remove-request-property-v1", False, 0, 0),
                no_repair=True,
                tags=("abstention",),
            ),
            self._plan(
                "scenario-007",
                DatasetFamily.CURATED_ADVERSARIAL,
                base.model_copy(
                    update={
                        "change_category": "required_parameter_added",
                        "change_severity": "HIGH",
                        "m10_outcome": "UNSUPPORTED",
                        "m10_repairability": "UNSUPPORTED",
                        "deterministic_rule_available": False,
                        "expected_edit_count": 0,
                        "source_shape": "missing-authoritative-value",
                    }
                ),
                self._m10("UNSUPPORTED", "UNSUPPORTED", None, False, 0, 0),
                all_fail=True,
                tags=("no-feasible",),
            ),
            self._plan(
                "scenario-008",
                DatasetFamily.SYNTHETIC,
                base.model_copy(
                    update={
                        "m10_outcome": "AI_REQUIRED",
                        "m10_repairability": "PARTIALLY_SUPPORTED",
                        "coverage_unresolved_calls": 2,
                        "ambiguity_flag_count": 1,
                        "source_shape": "partial-static-evidence",
                    }
                ),
                self._m10(
                    "AI_REQUIRED",
                    "PARTIALLY_SUPPORTED",
                    "remove-request-property-v1",
                    False,
                    0,
                    1,
                ),
                medium_success=True,
                unknown_small=True,
                tags=("unknown-outcome",),
            ),
            self._plan(
                "scenario-009",
                DatasetFamily.SYNTHETIC,
                base.model_copy(
                    update={
                        "change_severity": "CRITICAL",
                        "maximum_graph_distance": 4,
                        "indirect_exposure_count": 4,
                        "source_shape": "large-blast-radius",
                    }
                ),
                self._m10(
                    "AI_REQUIRED",
                    "PARTIALLY_SUPPORTED",
                    "remove-request-property-v1",
                    False,
                    0,
                    0,
                ),
                small_success=True,
                tags=("hard-cheap-case",),
            ),
        )

    def _plan(
        self,
        scenario_id: str,
        family: DatasetFamily,
        features: RouteForgeFeatures,
        evidence: M10ObservedEvidence,
        *,
        deterministic_success: bool = False,
        small_success: bool = False,
        medium_success: bool = False,
        strong_success: bool = False,
        no_repair: bool = False,
        all_fail: bool = False,
        unknown_small: bool = False,
        tags: tuple[str, ...] = (),
    ) -> _ScenarioPlan:
        provenance = (
            OutcomeProvenance.SYNTHETIC_ORACLE
            if family is DatasetFamily.SYNTHETIC
            else OutcomeProvenance.CURATED_ORACLE
        )
        statuses = {
            RouteForgeStrategy.DETERMINISTIC: deterministic_success,
            RouteForgeStrategy.SMALL: small_success,
            RouteForgeStrategy.MEDIUM: medium_success,
            RouteForgeStrategy.STRONG: strong_success,
        }
        outcomes: list[_OutcomeSpec] = [
            _oracle(
                RouteForgeStrategy.NO_AI,
                StrategyOutcomeStatus.NOT_APPLICABLE,
                provenance,
                0,
                0,
                None,
                no_repair_required=no_repair,
                notes=(
                    "No repair is required; NO_AI is the explicit abstention/no-op strategy."
                    if no_repair
                    else "Repair is required; NO_AI does not generate a candidate."
                ),
            )
        ]
        for strategy, cost, latency, quality in (
            (RouteForgeStrategy.DETERMINISTIC, 0, 0, 100),
            (RouteForgeStrategy.SMALL, 1, 1, 75),
            (RouteForgeStrategy.MEDIUM, 2, 2, 88),
            (RouteForgeStrategy.STRONG, 4, 4, 98),
        ):
            success = statuses[strategy] and not all_fail
            outcome = (
                StrategyOutcomeStatus.NOT_APPLICABLE
                if no_repair
                else StrategyOutcomeStatus.UNKNOWN
                if strategy is RouteForgeStrategy.SMALL and unknown_small
                else StrategyOutcomeStatus.SUCCESS
                if success
                else StrategyOutcomeStatus.FAILURE
            )
            outcomes.append(
                _oracle(
                    strategy,
                    outcome,
                    provenance,
                    cost,
                    latency,
                    quality,
                    candidate_generated=(
                        strategy is RouteForgeStrategy.DETERMINISTIC
                        and evidence.candidate_generated
                    ),
                    no_repair_required=no_repair,
                )
            )
        return _ScenarioPlan(
            scenario_id=scenario_id,
            family=family,
            repository_family_id="repository-authored",
            api_family_id="api-authored",
            migration_id=f"migration-{scenario_id}",
            mutation_family=features.change_category,
            template_family_id=f"template-{int(scenario_id[-3:]) % 3 + 1:02d}",
            feature_origin=FeatureOrigin.SCENARIO_AUTHORED,
            features=features,
            m10_evidence=evidence,
            no_repair_required=no_repair,
            outcomes=tuple(outcomes),
            provenance="Seeded offline scenario policy; no provider execution.",
            tags=tags,
        )

    def _materialize(self, plan: _ScenarioPlan) -> RouteForgeScenario:
        decision_group_id = stable_id(
            "routeforge-group", self.config.dataset_version, self.config.seed, plan.scenario_id
        )
        context_id = stable_id(
            "routeforge-context", decision_group_id, plan.features.canonical_json()
        )
        context = RoutingDecisionContext(
            id=context_id,
            scenario_id=plan.scenario_id,
            decision_group_id=decision_group_id,
            migration_id=plan.migration_id,
            repository_family_id=plan.repository_family_id,
            api_family_id=plan.api_family_id,
            mutation_family=plan.mutation_family,
            template_family_id=plan.template_family_id,
            feature_origin=plan.feature_origin,
            features=plan.features,
            m10_evidence=plan.m10_evidence,
            no_repair_required=plan.no_repair_required,
        )
        outcomes = tuple(
            StrategyOutcome(
                id=stable_id("routeforge-outcome", decision_group_id, strategy.value),
                decision_group_id=decision_group_id,
                strategy=strategy,
                outcome=spec.status,
                provenance=spec.provenance,
                producer=spec.producer,
                candidate_generated=spec.candidate_generated,
                synthetic_cost_units=spec.cost,
                synthetic_latency_units=spec.latency,
                quality_units=spec.quality,
                no_repair_required=spec.no_repair_required,
                notes=spec.notes,
            )
            for strategy, spec in zip(RouteForgeStrategy, plan.outcomes, strict=True)
        )
        preferred, feasible = derive_preferred_strategy(
            outcomes, self.objective, no_repair_required=plan.no_repair_required
        )
        outcome_fingerprint = stable_id(
            "routeforge-outcome-table", *(outcome.canonical_json() for outcome in outcomes)
        )
        features_fingerprint = stable_id("routeforge-features", plan.features.canonical_json())
        source_fingerprint = stable_id(
            "routeforge-source", plan.family.value, plan.features.source_shape, plan.mutation_family
        )
        template_fingerprint = stable_id("routeforge-template", plan.template_family_id)
        scenario_fingerprint = stable_id(
            "routeforge-scenario",
            self.config.seed,
            plan.scenario_id,
            context.canonical_json(),
            source_fingerprint,
        )
        return RouteForgeScenario(
            scenario_id=plan.scenario_id,
            scenario_fingerprint=scenario_fingerprint,
            source_fingerprint=source_fingerprint,
            routing_feature_fingerprint=features_fingerprint,
            template_fingerprint=template_fingerprint,
            family=plan.family,
            repository_family_id=plan.repository_family_id,
            api_family_id=plan.api_family_id,
            migration_id=plan.migration_id,
            mutation_family=plan.mutation_family,
            template_family_id=plan.template_family_id,
            decision_group_id=decision_group_id,
            context=context,
            outcomes=outcomes,
            feasible_strategies=feasible,
            preferred_strategy=preferred,
            outcome_table_fingerprint=outcome_fingerprint,
            provenance=plan.provenance,
            tags=plan.tags,
        )

    def _rows(self, scenario: RouteForgeScenario) -> tuple[RouteForgeDatasetRow, ...]:
        partition = _partition(scenario.decision_group_id, self.config.seed)
        outcome_by_strategy = {outcome.strategy: outcome for outcome in scenario.outcomes}
        return tuple(
            RouteForgeDatasetRow(
                id=stable_id("routeforge-row", scenario.decision_group_id, strategy.value),
                scenario_id=scenario.scenario_id,
                scenario_fingerprint=scenario.scenario_fingerprint,
                decision_group_id=scenario.decision_group_id,
                split_group_id=scenario.decision_group_id,
                split_partition=partition,
                context_id=scenario.context.id,
                strategy=strategy,
                outcome=outcome_by_strategy[strategy].outcome,
                outcome_provenance=outcome_by_strategy[strategy].provenance,
                producer=outcome_by_strategy[strategy].producer,
                candidate_generated=outcome_by_strategy[strategy].candidate_generated,
                synthetic_cost_units=outcome_by_strategy[strategy].synthetic_cost_units,
                synthetic_latency_units=outcome_by_strategy[strategy].synthetic_latency_units,
                quality_units=outcome_by_strategy[strategy].quality_units,
                features=scenario.context.features,
                preferred_strategy=scenario.preferred_strategy,
                feasible_strategies=scenario.feasible_strategies,
            )
            for strategy in RouteForgeStrategy
        )

    def _manifest(
        self, scenarios: tuple[RouteForgeScenario, ...], rows: tuple[RouteForgeDatasetRow, ...]
    ) -> RouteForgeManifest:
        strategy_counts = Counter(row.strategy.value for row in rows)
        preferred_counts = Counter(scenario.preferred_strategy.value for scenario in scenarios)
        outcome_counts: dict[str, dict[str, int]] = {}
        for row in rows:
            bucket = outcome_counts.setdefault(row.strategy.value, {})
            bucket[row.outcome.value] = bucket.get(row.outcome.value, 0) + 1
        provenance_counts = Counter(row.outcome_provenance.value for row in rows)
        resolution_counts = Counter(
            state.value
            for scenario in scenarios
            for state in (
                scenario.context.features.url_resolution_state,
                scenario.context.features.request_resolution_state,
                scenario.context.features.response_resolution_state,
            )
        )
        duplicate_audit = DuplicateAudit(
            scenario_fingerprint_duplicates=_duplicates(
                scenario.scenario_fingerprint for scenario in scenarios
            ),
            source_fingerprint_duplicates=_duplicates(
                scenario.source_fingerprint for scenario in scenarios
            ),
            routing_feature_clone_groups=sum(
                count > 1
                for count in Counter(s.routing_feature_fingerprint for s in scenarios).values()
            ),
            outcome_table_duplicates=_duplicates(
                scenario.outcome_table_fingerprint for scenario in scenarios
            ),
            template_clone_groups=sum(
                count > 1
                for count in Counter(s.template_fingerprint for s in scenarios).values()
            ),
        )
        return RouteForgeManifest(
            objective=self.objective,
            seed=self.config.seed,
            config=self.config,
            scenario_count=len(scenarios),
            decision_group_count=len({scenario.decision_group_id for scenario in scenarios}),
            strategy_outcome_row_count=len(rows),
            strategy_counts=dict(sorted(strategy_counts.items())),
            preferred_strategy_counts=dict(sorted(preferred_counts.items())),
            strategy_outcome_counts={
                key: dict(sorted(value.items())) for key, value in sorted(outcome_counts.items())
            },
            provenance_counts=dict(sorted(provenance_counts.items())),
            repairability_counts=dict(
                sorted(
                    Counter(s.context.features.m10_repairability for s in scenarios).items()
                )
            ),
            change_category_counts=dict(
                sorted(Counter(s.mutation_family for s in scenarios).items())
            ),
            api_family_counts=dict(sorted(Counter(s.api_family_id for s in scenarios).items())),
            repository_family_counts=dict(
                sorted(Counter(s.repository_family_id for s in scenarios).items())
            ),
            template_family_counts=dict(
                sorted(Counter(s.template_family_id for s in scenarios).items())
            ),
            resolution_state_counts=dict(sorted(resolution_counts.items())),
            duplicate_audit=duplicate_audit,
            content_sha256=content_checksum(
                RouteForgeDataset(
                    manifest=RouteForgeManifest.model_construct(
                        objective=self.objective,
                        seed=self.config.seed,
                        config=self.config,
                        scenario_count=len(scenarios),
                        decision_group_count=len(scenarios),
                        strategy_outcome_row_count=len(rows),
                        duplicate_audit=duplicate_audit,
                        content_sha256="",
                    ),
                    scenarios=scenarios,
                    rows=rows,
                )
            ),
        )

    def _observed_features(
        self,
        blast: BlastRadius,
        change: APIChange,
        impacts: tuple[DirectImpact, ...],
        call: APICallSite | None,
        migration_result: MigrationResult | None,
    ) -> RouteForgeFeatures:
        direct = impacts[0] if impacts else None
        impacted = tuple(
            item
            for item in blast.impacted_symbols
            if change.id in item.source_change_ids
        )
        graph = blast.graph
        direct_symbol_id = (
            next(
                (
                    node.id
                    for node in graph.nodes
                    if direct is not None and node.qualified_name == direct.symbol
                ),
                None,
            )
            if graph is not None
            else None
        )
        direct_callers, upstream_callers = _graph_counts(graph, direct_symbol_id)
        plan = migration_result.plan if migration_result is not None else None
        outcome = migration_result.outcome.value if migration_result is not None else "UNSUPPORTED"
        repairability = plan.repairability.value if plan is not None else "UNSUPPORTED"
        return RouteForgeFeatures(
            change_category=change.category.value,
            change_severity=change.severity.value,
            change_certainty=change.certainty.value,
            breaking_classification=change.breaking_classification.value,
            compatibility_direction=change.compatibility_direction.value,
            url_resolution_state=(
                call.url_resolution_state if call is not None else ResolutionState.UNRESOLVED
            ),
            request_resolution_state=(
                call.request_field_resolution_state
                if call is not None
                else ResolutionState.UNRESOLVED
            ),
            response_resolution_state=(
                call.response_field_resolution_state
                if call is not None
                else ResolutionState.UNRESOLVED
            ),
            direct_impact_count=len(impacts),
            direct_reference=direct is not None,
            indirect_exposure_count=sum(item.impact_type.value == "INDIRECT" for item in impacted),
            maximum_graph_distance=max((item.distance for item in impacted), default=0),
            direct_caller_count=direct_callers,
            upstream_caller_count=upstream_callers,
            coverage_unresolved_calls=graph.coverage.calls_unresolved if graph is not None else 0,
            coverage_failed_files=graph.coverage.files_failed if graph is not None else 0,
            m10_outcome=outcome,
            m10_repairability=repairability,
            deterministic_rule_available=plan is not None and plan.rule_id is not None,
            supported_rule_count=int(plan is not None and plan.rule_id is not None),
            expected_edit_count=len(plan.edits) if plan is not None else 0,
            target_file_count=len({edit.file for edit in plan.edits}) if plan is not None else 0,
            repair_conflict_count=len(plan.conflicts) if plan is not None else 0,
            shared_payload_ambiguity=False,
            dynamic_payload=False,
            nested_literal=False,
            ambiguity_flag_count=len(plan.warnings) if plan is not None else 1,
            source_shape="literal_inline",
        )

    def _observed_m10(self, result: MigrationResult | None) -> M10ObservedEvidence:
        if result is None:
            return self._m10("UNSUPPORTED", "UNSUPPORTED", None, False, 0, 0)
        plan = result.plan
        return M10ObservedEvidence(
            outcome=result.outcome.value,
            repairability=plan.repairability.value,
            rule_id=plan.rule_id,
            candidate_generated=result.candidate is not None,
            edit_count=len(plan.edits),
            target_file_count=len({edit.file for edit in plan.edits}),
            conflict_count=len(plan.conflicts),
            warnings=plan.warnings,
        )

    def _authored_features(self) -> RouteForgeFeatures:
        return RouteForgeFeatures(
            change_category="request_property_removed",
            change_severity="MEDIUM",
            change_certainty="CONDITIONAL",
            breaking_classification="CLIENT_BREAKING",
            compatibility_direction="CLIENT_TO_SERVER",
            url_resolution_state=ResolutionState.EXACT,
            request_resolution_state=ResolutionState.EXACT,
            response_resolution_state=ResolutionState.UNRESOLVED,
            direct_impact_count=1,
            direct_reference=True,
            indirect_exposure_count=0,
            maximum_graph_distance=0,
            direct_caller_count=0,
            upstream_caller_count=0,
            coverage_unresolved_calls=0,
            coverage_failed_files=0,
            m10_outcome="DETERMINISTIC_CANDIDATE",
            m10_repairability="SUPPORTED",
            deterministic_rule_available=True,
            supported_rule_count=1,
            expected_edit_count=1,
            target_file_count=1,
            repair_conflict_count=0,
            shared_payload_ambiguity=False,
            dynamic_payload=False,
            nested_literal=False,
            ambiguity_flag_count=0,
            source_shape="literal_inline",
        )

    def _m10(
        self,
        outcome: str,
        repairability: str,
        rule_id: str | None,
        candidate: bool,
        edits: int,
        conflicts: int,
    ) -> M10ObservedEvidence:
        return M10ObservedEvidence(
            outcome=outcome,
            repairability=repairability,
            rule_id=rule_id,
            candidate_generated=candidate,
            edit_count=edits,
            target_file_count=int(edits > 0),
            conflict_count=conflicts,
            warnings=(),
        )


def generate_routeforge_dataset(config: RouteForgeConfig | None = None) -> RouteForgeDataset:
    return RouteForgeDatasetGenerator(config).generate()


def _oracle(
    strategy: RouteForgeStrategy,
    status: StrategyOutcomeStatus,
    provenance: OutcomeProvenance,
    cost: float | None,
    latency: float | None,
    quality: float | None,
    *,
    candidate_generated: bool = False,
    no_repair_required: bool = False,
    notes: str = "Offline oracle outcome; not a validated provider result.",
) -> _OutcomeSpec:
    return _OutcomeSpec(
        status=status,
        provenance=provenance,
        producer="routeforge-offline-oracle-v1",
        cost=cost,
        latency=latency,
        quality=quality,
        candidate_generated=candidate_generated,
        no_repair_required=no_repair_required,
        notes=notes,
    )


def _observed_deterministic(evidence: M10ObservedEvidence) -> _OutcomeSpec:
    return _OutcomeSpec(
        status=StrategyOutcomeStatus.UNKNOWN,
        provenance=OutcomeProvenance.OBSERVED_DETERMINISTIC,
        producer="m10:deterministic-migration-v1",
        cost=None,
        latency=None,
        quality=None,
        candidate_generated=evidence.candidate_generated,
        notes="Observed M10 candidate generation; no validation execution exists at M11.",
    )


def _partition(decision_group_id: str, seed: int) -> SplitPartition:
    value = int(hashlib.sha256(f"{seed}:{decision_group_id}".encode()).hexdigest(), 16) % 3
    return (SplitPartition.TRAIN, SplitPartition.VALIDATION, SplitPartition.TEST)[value]


def _duplicates(values: Iterable[str]) -> int:
    counts = Counter(values)
    return sum(max(0, count - 1) for count in counts.values())


def _graph_counts(graph: StaticCallGraph | None, symbol_id: str | None) -> tuple[int, int]:
    if graph is None or symbol_id is None:
        return 0, 0
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
