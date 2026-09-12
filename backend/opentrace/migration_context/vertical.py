"""Evidence path consumed by the context selector."""

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
    """Select context from real artifacts and an already-made routing decision.

    The caller supplies the typed decision.  This path intentionally does
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
