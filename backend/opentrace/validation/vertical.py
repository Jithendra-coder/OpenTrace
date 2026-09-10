"""M16 vertical slice: real M1→M15 evidence composed with M16 validation."""

from __future__ import annotations

from pathlib import Path

from opentrace.ai_migration.generator import GenerationProvider, MigrationGenerator
from opentrace.ai_migration.models import (
    GenerationConfiguration,
    GenerationPolicy,
    GenerationStatus,
    MigrationGenerationResult,
)
from opentrace.migration_context.vertical import analyze_migration_context_vertical_slice
from opentrace.routeforge.router import RoutingDecision
from opentrace.validation.models import SandboxConfig, ValidationEvidence
from opentrace.validation.validator import validate_patch


def analyze_and_validate_vertical_slice(
    old_spec_path: Path | str,
    new_spec_path: Path | str,
    repository_path: Path | str,
    routing_decision: RoutingDecision,
    configuration: GenerationConfiguration,
    provider: GenerationProvider | None = None,
    *,
    context_budget_characters: int | None = None,
    policy: GenerationPolicy | None = None,
    sandbox_config: SandboxConfig | None = None,
) -> tuple[MigrationGenerationResult, ValidationEvidence | None]:
    """Run the real M1→M16 path without mutating the source repository.

    Returns:
        generation_result: The M15 generation result.
        validation_evidence: ValidationEvidence if a patch was generated,
                             None if no patch was produced.

    The source repository is never modified. Validation runs in an
    ephemeral temp workspace that is cleaned up regardless of outcome.
    """
    from opentrace.ai_migration.vertical import analyze_migration_generation_vertical_slice

    generation_result = analyze_migration_generation_vertical_slice(
        old_spec_path,
        new_spec_path,
        repository_path,
        routing_decision,
        configuration,
        provider,
        context_budget_characters=context_budget_characters,
        policy=policy,
    )

    if generation_result.status is not GenerationStatus.GENERATED:
        return generation_result, None

    assert generation_result.patch is not None
    evidence = validate_patch(
        generation_result.patch,
        repository_path,
        sandbox_config,
    )
    return generation_result, evidence
