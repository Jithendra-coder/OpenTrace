"""Migration context evidence composed with guarded generation boundary."""

from __future__ import annotations

from pathlib import Path

from opentrace.ai_migration.generator import GenerationProvider, MigrationGenerator
from opentrace.ai_migration.models import (
    GenerationConfiguration,
    GenerationPolicy,
    MigrationGenerationResult,
)
from opentrace.migration_context.vertical import analyze_migration_context_vertical_slice
from opentrace.routeforge.router import RoutingDecision


def analyze_migration_generation_vertical_slice(
    old_spec_path: Path | str,
    new_spec_path: Path | str,
    repository_path: Path | str,
    routing_decision: RoutingDecision,
    configuration: GenerationConfiguration,
    provider: GenerationProvider | None = None,
    *,
    context_budget_characters: int | None = None,
    policy: GenerationPolicy | None = None,
) -> MigrationGenerationResult:
    """Run the guarded candidate generation path without rescanning beyond context selection."""

    selection = analyze_migration_context_vertical_slice(
        old_spec_path,
        new_spec_path,
        repository_path,
        routing_decision,
        budget_characters=context_budget_characters,
    )
    return MigrationGenerator(policy).generate(
        selection.context,
        routing_decision,
        configuration,
        provider,
    )
