"""Real M1→M10 evidence path consumed by the M14 context selector."""

from __future__ import annotations

from pathlib import Path

from opentrace.blast_radius.vertical import analyze_vertical_slice as analyze_blast_slice
from opentrace.migration.vertical import analyze_vertical_slice as analyze_migration_slice
from opentrace.migration_context.models import ContextSelection
from opentrace.migration_context.selector import MigrationContextSelector
from opentrace.routeforge.router import RoutingDecision


def analyze_migration_context_vertical_slice(
    old_spec_path: Path | str,
    new_spec_path: Path | str,
    repository_path: Path | str,
    routing_decision: RoutingDecision,
    *,
    budget_characters: int | None = None,
) -> ContextSelection:
    """Select M14 context from real M1–M10 artifacts and an already-made M13 decision.

    The caller supplies M13's typed decision.  This path intentionally does
    not route, read RouteForge datasets, or inspect any oracle outcome table.
    """

    repository_root = Path(repository_path)
    blast = analyze_blast_slice(old_spec_path, new_spec_path, repository_root)
    migrations = analyze_migration_slice(old_spec_path, new_spec_path, repository_root)
    return MigrationContextSelector().select(
        repository_root,
        blast,
        migrations.results,
        routing_decision,
        budget_characters=budget_characters,
    )
