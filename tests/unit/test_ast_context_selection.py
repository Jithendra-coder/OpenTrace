"""Bounded MigrationContext policy and adversarial tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from opentrace.blast_radius.vertical import analyze_vertical_slice as analyze_blast_slice
from opentrace.code_analysis.models import (
    FileAnalysisState,
    RepositoryFile,
    ResolutionState,
)
from opentrace.migration import analyze_migration_vertical_slice
from opentrace.migration_context import (
    ContextItemRole,
    ContextOmissionReason,
    ContextSelectionStatus,
    MigrationContextSelector,
)
from opentrace.routeforge.models import RouteChoice, RouteForgeStrategy
from opentrace.routeforge.router import (
    ROUTEFORGE_DECISION_POLICY_VERSION,
    ROUTEFORGE_ROUTER_VERSION,
    RoutingAbstention,
    RoutingDecision,
    RoutingExplanation,
    StrategyScore,
)

ROOT = Path(__file__).parents[2]
OLD_SPEC = ROOT / "demo" / "payment_api_v1.yaml"
NEW_SPEC = ROOT / "demo" / "payment_api_v2.yaml"
DEMO = ROOT / "demo" / "ecommerce"


def _decision(strategy: RouteChoice = RouteChoice.SMALL) -> RoutingDecision:
    """Governed routing fixture containing only pre-decision, non-oracle route evidence."""

    abstention = (
        RoutingAbstention(code="LEARNED_ABSTENTION", reason="fixture abstention")
        if strategy is RouteChoice.NO_FEASIBLE_STRATEGY
        else None
    )
    return RoutingDecision(
        decision_id=f"m13-governed-fixture-{strategy.value}",
        context_id="m13-context-fixture",
        scenario_id="m13-scenario-fixture",
        decision_group_id="m13-group-fixture",
        migration_id="m10-payment-fixture",
        selected_strategy=strategy,
        strategy_scores=(
            StrategyScore(
                strategy=RouteForgeStrategy.SMALL,
                score=0.5,
                applicable=True,
                reason="fixture pre-decision applicability",
            ),
        ),
        feature_schema_version="routeforge-features-v1",
        strategy_taxonomy_version="routeforge-strategies-v1",
        objective_version="routeforge-objective-v1",
        model_id="RF-M13-LOGISTIC-V1",
        scorer_version="routeforge-logistic-scorer-v1",
        router_version=ROUTEFORGE_ROUTER_VERSION,
        decision_policy_version=ROUTEFORGE_DECISION_POLICY_VERSION,
        model_artifact_checksum="fixture-model-checksum",
        context_fingerprint="fixture-context-fingerprint",
        explanation=RoutingExplanation(
            summary="Governed routing fixture.",
            applicability=("SMALL applicable",),
            selection_basis="Pre-decision fixture evidence only.",
            evidence_features=("m10_outcome=DETERMINISTIC_CANDIDATE",),
        ),
        warnings=("Routing fixture is governed test evidence only.",),
        abstention=abstention,
    )


@pytest.fixture(scope="module")
def canonical_evidence():
    blast = analyze_blast_slice(OLD_SPEC, NEW_SPEC, DEMO)
    migrations = analyze_migration_vertical_slice(OLD_SPEC, NEW_SPEC, DEMO)
    return blast, migrations.results


def test_ample_context_is_bounded_relevant_and_repeatable(canonical_evidence) -> None:
    blast, migrations = canonical_evidence
    selector = MigrationContextSelector()
    first = selector.select(DEMO, blast, migrations, _decision(), budget_characters=12_000)
    second = selector.select(DEMO, blast, migrations, _decision(), budget_characters=12_000)

    assert first.status is ContextSelectionStatus.CONTEXT_READY
    assert first.context is not None
    assert first.canonical_json() == second.canonical_json()
    assert first.context.manifest.checksum == second.context.manifest.checksum
    roles = {item.role for item in first.context.items}
    assert {
        ContextItemRole.API_CHANGE,
        ContextItemRole.DIRECT_API_CALL,
        ContextItemRole.TARGET_SYMBOL,
        ContextItemRole.REQUEST_EVIDENCE,
        ContextItemRole.MIGRATION_EVIDENCE,
        ContextItemRole.ROUTING_EVIDENCE,
        ContextItemRole.CALLER_SYMBOL,
    } <= roles
    payload = "\n".join(item.content for item in first.context.items)
    assert '"path":"/payments"' in payload
    assert "requests.post" in payload
    assert "amount" in payload
    assert "remove-request-property-v1" in payload
    assert "refunds" not in payload
    assert "users" not in payload
    assert first.context.summary.graph_distances_represented == (1, 2)
    assert first.context.budget.used_characters < first.context.budget.limit_characters


def test_budget_preserves_direct_evidence_without_silent_truncation(canonical_evidence) -> None:
    blast, migrations = canonical_evidence
    selector = MigrationContextSelector()
    ample = selector.select(DEMO, blast, migrations, _decision(), budget_characters=12_000)
    assert ample.context is not None
    required_roles = {
        ContextItemRole.API_CHANGE,
        ContextItemRole.DIRECT_API_CALL,
        ContextItemRole.TARGET_SYMBOL,
        ContextItemRole.REQUEST_EVIDENCE,
        ContextItemRole.MIGRATION_EVIDENCE,
        ContextItemRole.ROUTING_EVIDENCE,
    }
    exact_required_budget = sum(
        len(item.content) for item in ample.context.items if item.role in required_roles
    )
    reduced = selector.select(
        DEMO, blast, migrations, _decision(), budget_characters=exact_required_budget
    )
    assert reduced.status is ContextSelectionStatus.CONTEXT_READY
    assert reduced.context is not None
    assert all(item.role is not ContextItemRole.CALLER_SYMBOL for item in reduced.context.items)
    assert any(item.reason is ContextOmissionReason.BUDGET_EXCEEDED for item in reduced.omissions)
    assert reduced.budget.used_characters == exact_required_budget
    assert reduced.budget.remaining_characters == 0
    assert reduced.budget.truncated is True

    too_small = selector.select(
        DEMO, blast, migrations, _decision(), budget_characters=exact_required_budget - 1
    )
    assert too_small.status is ContextSelectionStatus.INSUFFICIENT_CONTEXT_BUDGET
    assert too_small.context is None
    assert too_small.budget.used_characters == 0


def test_no_ai_and_no_feasible_do_not_build_fake_context(canonical_evidence) -> None:
    blast, migrations = canonical_evidence
    selector = MigrationContextSelector()
    deterministic = selector.select(DEMO, blast, migrations, _decision(RouteChoice.DETERMINISTIC))
    no_ai = selector.select(DEMO, blast, migrations, _decision(RouteChoice.NO_AI))
    no_feasible = selector.select(
        DEMO, blast, migrations, _decision(RouteChoice.NO_FEASIBLE_STRATEGY)
    )

    assert deterministic.status is ContextSelectionStatus.CONTEXT_READY
    assert deterministic.context is not None
    assert any("provenance only" in warning for warning in deterministic.warnings)
    assert no_ai.status is ContextSelectionStatus.NOT_REQUIRED
    assert no_ai.context is None
    assert no_feasible.status is ContextSelectionStatus.NO_FEASIBLE_STRATEGY
    assert no_feasible.context is None


def test_partial_dynamic_payload_is_preserved_as_uncertainty(canonical_evidence) -> None:
    blast, migrations = canonical_evidence
    original = next(item for item in blast.call_sites if item.id == migrations[0].plan.call_site_id)
    dynamic = original.model_copy(
        update={
            "url_resolution_state": ResolutionState.PARTIAL,
            "request_field_resolution_state": ResolutionState.UNRESOLVED,
            "warnings": ("payload construction is dynamic",),
        }
    )
    altered = blast.model_copy(
        update={
            "call_sites": tuple(
                dynamic if item.id == dynamic.id else item for item in blast.call_sites
            )
        }
    )
    result = MigrationContextSelector().select(DEMO, altered, migrations, _decision())

    assert result.context is not None
    request = next(
        item for item in result.context.items if item.role is ContextItemRole.REQUEST_EVIDENCE
    )
    assert '"url_resolution_state":"PARTIAL"' in request.content
    assert '"request_field_resolution_state":"UNRESOLVED"' in request.content
    assert any("dynamic" in warning for warning in result.warnings)


def test_duplicate_spans_merge_provenance_and_large_irrelevant_evidence_stays_out(
    canonical_evidence,
) -> None:
    blast, migrations = canonical_evidence
    duplicate = migrations[0].model_copy(
        update={
            "id": "migration-result-duplicate",
            "plan": migrations[0].plan.model_copy(update={"id": "migration-plan-duplicate"}),
        }
    )
    irrelevant = tuple(
        RepositoryFile(
            id=f"irrelevant-{index}",
            path=f"large/irrelevant_{index}.py",
            state=FileAnalysisState.PARSED,
            source_hash=f"hash-{index}",
        )
        for index in range(100)
    )
    same_name = RepositoryFile(
        id="same-name",
        path="large/payment_service.py",
        state=FileAnalysisState.PARSED,
        source_hash="different-payment-service",
    )
    altered = blast.model_copy(update={"files": (*blast.files, *irrelevant, same_name)})
    result = MigrationContextSelector().select(DEMO, altered, (*migrations, duplicate), _decision())

    assert result.context is not None
    targets = [item for item in result.context.items if item.role is ContextItemRole.TARGET_SYMBOL]
    assert len(targets) == 1
    assert "migration-plan-duplicate" in targets[0].provenance_ids
    assert any(item.reason is ContextOmissionReason.DUPLICATE for item in result.omissions)
    assert all("large/" not in (item.file or "") for item in result.context.items)


def test_multiple_direct_targets_in_multiple_files_remain_bounded(tmp_path: Path) -> None:
    for name, function in (("payment_service.py", "create_payment"), ("retry.py", "retry_payment")):
        (tmp_path / name).write_text(
            "import requests\n\n"
            "BASE_URL = 'https://payments.example.com'\n\n\n"
            f"def {function}(amount: float, currency: str) -> object:\n"
            "    return requests.post(\n"
            "        BASE_URL + '/payments',\n"
            "        json={'amount': amount, 'currency': currency},\n"
            "    )\n",
            encoding="utf-8",
        )
    blast = analyze_blast_slice(OLD_SPEC, NEW_SPEC, tmp_path)
    migrations = analyze_migration_vertical_slice(OLD_SPEC, NEW_SPEC, tmp_path)
    result = MigrationContextSelector().select(tmp_path, blast, migrations.results, _decision())

    assert result.context is not None
    targets = [item for item in result.context.items if item.role is ContextItemRole.TARGET_SYMBOL]
    direct_calls = [
        item for item in result.context.items if item.role is ContextItemRole.DIRECT_API_CALL
    ]
    assert {item.file for item in targets} == {"payment_service.py", "retry.py"}
    assert len(direct_calls) == 2
    assert result.context.budget.files_used == 2


def test_multiple_changes_share_one_target_span_without_duplicate_source(
    canonical_evidence,
) -> None:
    blast, migrations = canonical_evidence
    original_change = next(
        item for item in blast.changes if item.id == migrations[0].plan.change_id
    )
    original_impact = next(
        item for item in blast.direct_impacts if item.id == migrations[0].plan.direct_impact_id
    )
    second_change = original_change.model_copy(update={"id": "api-change-second"})
    second_impact = original_impact.model_copy(
        update={"id": "impact-second", "change_id": second_change.id}
    )
    second_plan = migrations[0].plan.model_copy(
        update={
            "id": "migration-plan-second",
            "change_id": second_change.id,
            "direct_impact_id": second_impact.id,
        }
    )
    second_result = migrations[0].model_copy(
        update={"id": "migration-result-second", "plan": second_plan}
    )
    altered = blast.model_copy(
        update={
            "changes": (*blast.changes, second_change),
            "direct_impacts": (*blast.direct_impacts, second_impact),
        }
    )
    result = MigrationContextSelector().select(
        DEMO, altered, (*migrations, second_result), _decision()
    )

    assert result.context is not None
    assert set(result.context.api_change_ids) == {original_change.id, second_change.id}
    assert len(
        [item for item in result.context.items if item.role is ContextItemRole.API_CHANGE]
    ) == 2
    assert len(
        [item for item in result.context.items if item.role is ContextItemRole.TARGET_SYMBOL]
    ) == 1


def test_oversized_symbol_and_unresolved_caller_are_explicit(
    tmp_path: Path, canonical_evidence
) -> None:
    oversized = "x" * 9000
    (tmp_path / "payment_service.py").write_text(
        "import requests\n\n"
        "BASE_URL = 'https://payments.example.com'\n\n\n"
        "def create_payment(amount: float, currency: str) -> object:\n"
        f"    note = '{oversized}'\n"
        "    return requests.post(\n"
        "        BASE_URL + '/payments',\n"
        "        json={'amount': amount, 'currency': currency},\n"
        "    )\n",
        encoding="utf-8",
    )
    oversized_blast = analyze_blast_slice(OLD_SPEC, NEW_SPEC, tmp_path)
    oversized_migrations = analyze_migration_vertical_slice(OLD_SPEC, NEW_SPEC, tmp_path)
    oversized_result = MigrationContextSelector().select(
        tmp_path, oversized_blast, oversized_migrations.results, _decision()
    )
    assert oversized_result.status is ContextSelectionStatus.INSUFFICIENT_CONTEXT_BUDGET
    assert oversized_result.context is None

    blast, migrations = canonical_evidence
    caller = next(item for item in blast.impacted_symbols if item.distance == 1)
    unresolved = caller.model_copy(
        update={
            "id": "unresolved-caller",
            "symbol_id": "missing-symbol",
            "file": "missing.py",
            "symbol": "missing.py::caller",
        }
    )
    result = MigrationContextSelector().select(
        DEMO,
        blast.model_copy(update={"impacted_symbols": (*blast.impacted_symbols, unresolved)}),
        migrations,
        _decision(),
    )
    assert result.context is not None
    assert any(
        item.role is ContextItemRole.CALLER_SYMBOL
        and item.reason is ContextOmissionReason.MISSING_EVIDENCE
        for item in result.omissions
    )


@pytest.mark.parametrize("unsafe_file", ("../outside.py", ".env", "private.pem"))
def test_path_and_sensitive_file_evidence_is_never_read(
    canonical_evidence, unsafe_file: str
) -> None:
    blast, migrations = canonical_evidence
    original = next(item for item in blast.call_sites if item.id == migrations[0].plan.call_site_id)
    unsafe_call = original.model_copy(update={"file": unsafe_file})
    unsafe_plan = migrations[0].plan.model_copy(update={"target_file": unsafe_file})
    unsafe_result = migrations[0].model_copy(update={"plan": unsafe_plan})
    altered = blast.model_copy(
        update={
            "call_sites": tuple(
                unsafe_call if item.id == unsafe_call.id else item for item in blast.call_sites
            )
        }
    )
    result = MigrationContextSelector().select(DEMO, altered, (unsafe_result,), _decision())

    assert result.status is ContextSelectionStatus.INCOMPLETE_EVIDENCE
    assert result.context is None
    assert any(item.file == unsafe_file for item in result.omissions)
    assert all(
        unsafe_file not in item.content for item in (result.context.items if result.context else ())
    )


def test_binary_and_escaping_symlink_are_rejected(canonical_evidence, tmp_path: Path) -> None:
    blast, migrations = canonical_evidence
    (tmp_path / "payment_service.py").write_text(
        (DEMO / "payment_service.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "binary.py").write_bytes(b"\x00not python")
    original = next(item for item in blast.call_sites if item.id == migrations[0].plan.call_site_id)
    binary_call = original.model_copy(update={"file": "binary.py"})
    binary_plan = migrations[0].plan.model_copy(update={"target_file": "binary.py"})
    binary = MigrationContextSelector().select(
        tmp_path,
        blast.model_copy(
            update={
                "call_sites": tuple(
                    binary_call if item.id == binary_call.id else item for item in blast.call_sites
                )
            }
        ),
        (migrations[0].model_copy(update={"plan": binary_plan}),),
        _decision(),
    )
    assert binary.status is ContextSelectionStatus.INCOMPLETE_EVIDENCE
    assert any(item.reason is ContextOmissionReason.UNSAFE_FILE for item in binary.omissions)

    outside = tmp_path.parent / "m14-outside.py"
    outside.write_text("raise RuntimeError('must not execute')\n", encoding="utf-8")
    escape = tmp_path / "escape.py"
    try:
        escape.symlink_to(outside)
        target_file = "escape.py"
    except OSError:
        target_file = "../m14-outside.py"

    escaped_call = original.model_copy(update={"file": target_file})
    escaped_plan = migrations[0].plan.model_copy(update={"target_file": target_file})
    escaped = MigrationContextSelector().select(
        tmp_path,
        blast.model_copy(
            update={
                "call_sites": tuple(
                    escaped_call if item.id == escaped_call.id else item
                    for item in blast.call_sites
                )
            }
        ),
        (migrations[0].model_copy(update={"plan": escaped_plan}),),
        _decision(),
    )
    assert escaped.status is ContextSelectionStatus.INCOMPLETE_EVIDENCE
    assert any(
        item.reason in (ContextOmissionReason.OUTSIDE_REPOSITORY, ContextOmissionReason.UNRESOLVED_SOURCE, ContextOmissionReason.UNSAFE_FILE)
        for item in escaped.omissions
    )
