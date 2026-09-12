"""opentrace migrate — generate migration plan using RouteForge + AI pipeline."""

from __future__ import annotations

import sys
from pathlib import Path

from opentrace.ai_migration import DeterministicFakeProvider, GenerationConfiguration, GenerationStatus
from opentrace.cli.output import (
    bold, cyan, dim, green, print_banner, print_error,
    print_info, print_ok, print_section, print_warn, red, yellow,
)
from opentrace.cli.workspace import (
    analysis_exists, analysis_path, migration_plan_exists,
    migration_plan_path, read_json, write_json,
)
from opentrace.migration_context.vertical import analyze_migration_context_vertical_slice
from opentrace.routeforge.models import RouteChoice, RouteForgeStrategy
from opentrace.routeforge.router import (
    ROUTEFORGE_DECISION_POLICY_VERSION,
    ROUTEFORGE_ROUTER_VERSION,
    RoutingDecision,
    RoutingExplanation,
    StrategyScore,
)


_POLICY_STRATEGY_MAP = {
    "economy": RouteChoice.SMALL,
    "balanced": RouteChoice.SMALL,
    "critical": RouteChoice.STRONG,
}


def run_migrate(workspace: Path, policy: str, ai_enabled: bool) -> None:
    """Run migration pipeline to produce a migration plan."""

    if not analysis_exists(workspace):
        print_error("No analysis found. Run  opentrace analyze  first.")
        sys.exit(1)

    analysis = read_json(analysis_path(workspace))
    if not analysis:
        print_error("Could not read analysis.json.")
        sys.exit(1)

    repo = Path(analysis["repo"])
    old_spec = Path(analysis["old_spec"])
    new_spec = Path(analysis["new_spec"])
    changes_count = analysis.get("changes_count", 0)

    print_banner("OpenTrace  Migrate")
    print_info(f"Policy    : {policy}")
    print_info(f"AI-enabled: {ai_enabled}")
    print_info(f"Changes   : {changes_count}")
    print()

    if changes_count == 0:
        print_ok("No changes to migrate.")
        return

    # --- Build a governed routing decision for CLI use ---
    strategy = _POLICY_STRATEGY_MAP.get(policy, RouteChoice.SMALL)
    routing_decision = _build_cli_routing_decision(strategy, policy)

    # --- Generate migration plan ---
    print(f"  Running migration pipeline...")
    try:
        # Always use the DeterministicFakeProvider for local demo mode.
        # A real AI provider can be plugged in by implementing GenerationProvider.
        provider = DeterministicFakeProvider()
        configuration = GenerationConfiguration(
            ai_enabled=True,  # fake provider counts as "enabled" for demo
            provider_id="deterministic-fake-v1",
            model_by_strategy={
                RouteChoice.SMALL: "small-model",
                RouteChoice.MEDIUM: "medium-model",
                RouteChoice.STRONG: "strong-model",
            },
        )

        context_selection = analyze_migration_context_vertical_slice(
            old_spec, new_spec, repo, routing_decision
        )
        context = context_selection.context

        from opentrace.ai_migration.generator import MigrationGenerator
        gen_result = MigrationGenerator().generate(
            context, routing_decision, configuration, provider
        )
    except Exception as exc:
        print_error(f"Migration pipeline failed: {exc}")
        sys.exit(1)

    # --- Format output ---
    print_section("Migration Plan")

    patch = gen_result.patch
    if gen_result.status is GenerationStatus.GENERATED and patch:
        print(f"  {green('✓')} Patch generated  ({len(patch.edits)} edit(s))\n")
        for i, edit in enumerate(patch.edits, 1):
            strategy_label = _strategy_label(patch.selected_strategy, ai_enabled)
            risk = _risk_label(patch.selected_strategy)
            print(f"  {bold(str(i))}. {cyan(edit.file)}")
            print(f"     Strategy : {strategy_label}")
            print(f"     Risk     : {risk}")
            if edit.symbol:
                print(f"     Symbol   : {dim(edit.symbol)}")
            print(f"     Reason   : {edit.reason}")
            print()

    elif gen_result.status.value == "NOT_REQUIRED":
        print_warn("Strategy is NO_AI — deterministic patch only.")
        print_info("No AI generation needed for this migration.")
    elif gen_result.status.value == "AI_DISABLED":
        print_warn("AI is disabled. Set --ai-enabled to enable AI-assisted repair.")
    else:
        print_warn(f"Generation status: {gen_result.status.value}")
        if gen_result.failure:
            print_error(f"Reason: {gen_result.failure.message}")

    # --- Save migration plan ---
    plan = {
        "schema_version": "migration-plan-v1",
        "policy": policy,
        "ai_enabled": ai_enabled,
        "generation_status": gen_result.status.value,
        "routing_decision_id": routing_decision.decision_id,
        "selected_strategy": strategy.value,
        "repo": str(repo),
        "old_spec": str(old_spec),
        "new_spec": str(new_spec),
        "patch": _patch_to_dict(patch) if patch else None,
        "failure": _failure_to_dict(gen_result.failure) if gen_result.failure else None,
        "warnings": list(gen_result.warnings),
    }
    out = migration_plan_path(workspace)
    write_json(out, plan)

    print_section("Next Step")
    print_ok(f"Migration plan written → {out}")
    if patch:
        print_info("Run  opentrace validate  to test the patch in an isolated sandbox.")
    else:
        print_warn("No patch was generated. Review the status above.")
    print()


def _build_cli_routing_decision(strategy: RouteChoice, policy: str) -> RoutingDecision:
    return RoutingDecision(
        decision_id=f"cli-{policy}-decision",
        context_id="cli-context",
        scenario_id="cli-scenario",
        decision_group_id="cli-group",
        migration_id="cli-migration",
        selected_strategy=strategy,
        strategy_scores=(
            StrategyScore(
                strategy=RouteForgeStrategy.SMALL,
                score=0.5,
                applicable=True,
                reason=f"CLI {policy} policy",
            ),
        ),
        feature_schema_version="routeforge-features-v1",
        strategy_taxonomy_version="routeforge-strategies-v1",
        objective_version="routeforge-objective-v1",
        model_id="routeforge-logistic-v1",
        scorer_version="routeforge-logistic-scorer-v1",
        router_version=ROUTEFORGE_ROUTER_VERSION,
        decision_policy_version=ROUTEFORGE_DECISION_POLICY_VERSION,
        model_artifact_checksum="cli-fixture",
        context_fingerprint="cli-fingerprint",
        explanation=RoutingExplanation(
            summary=f"CLI policy: {policy} → {strategy.value}",
            applicability=(f"{strategy.value} applicable via CLI policy",),
            selection_basis=f"CLI policy={policy}",
            evidence_features=(),
        ),
        warnings=(),
    )


def _strategy_label(strategy: RouteChoice, ai_enabled: bool) -> str:
    if not ai_enabled:
        return f"{strategy.value} (DeterministicFakeProvider — demo mode)"
    return strategy.value


def _risk_label(strategy: RouteChoice) -> str:
    return {
        RouteChoice.SMALL: green("LOW"),
        RouteChoice.MEDIUM: yellow("MEDIUM"),
        RouteChoice.STRONG: red("HIGH"),
        RouteChoice.DETERMINISTIC: green("LOW"),
        RouteChoice.NO_AI: green("LOW"),
        RouteChoice.NO_FEASIBLE_STRATEGY: red("HIGH"),
    }.get(strategy, dim("UNKNOWN"))


def _patch_to_dict(patch: object) -> dict:
    from opentrace.ai_migration.models import ProposedMigrationPatch
    if not isinstance(patch, ProposedMigrationPatch):
        return {}
    return {
        "id": patch.id,
        "selected_strategy": patch.selected_strategy.value,
        "provider_adapter_id": patch.provider_adapter_id,
        "model_id": patch.model_id,
        "generation_fingerprint": patch.generation_fingerprint,
        "explanation": patch.explanation,
        "warnings": list(patch.warnings),
        "edits": [
            {
                "id": e.id,
                "file": e.file,
                "symbol": e.symbol,
                "start_line": e.start_line,
                "end_line": e.end_line,
                "original_text_hash": e.original_text_hash,
                "expected_original_text": e.expected_original_text,
                "replacement_text": e.replacement_text,
                "reason": e.reason,
            }
            for e in patch.edits
        ],
    }


def _failure_to_dict(failure: object) -> dict:
    return {
        "status": str(getattr(failure, "status", "")),
        "code": str(getattr(failure, "code", "")),
        "message": str(getattr(failure, "message", "")),
    }
