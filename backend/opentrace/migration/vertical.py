"""Real M1→M6 evidence feeding the deterministic M10 engine."""

from __future__ import annotations

from pathlib import Path

from opentrace.blast_radius.vertical import analyze_vertical_slice as analyze_blast_slice
from opentrace.migration.engine import DeterministicMigrationEngine
from opentrace.migration.models import (
    MigrationBatchResult,
    MigrationResult,
    MigrationSummary,
)


def analyze_vertical_slice(
    old_spec_path: Path | str,
    new_spec_path: Path | str,
    repository_path: Path | str,
) -> MigrationBatchResult:
    """Analyze real M1–M6 evidence and produce M10 candidate results.

    The migration engine receives only changes, call sites, and direct impacts
    emitted by the canonical blast-radius pipeline.  It never executes source
    code and it never consults the M7–M9 ML artifacts.
    """

    repository_root = Path(repository_path)
    blast = analyze_blast_slice(old_spec_path, new_spec_path, repository_root)
    calls = {call.id: call for call in blast.call_sites}
    sources: dict[str, str] = {}
    for call in blast.call_sites:
        path = Path(call.file)
        source_path = path if path.is_absolute() else repository_root / path
        if source_path.exists() and call.file not in sources:
            sources[call.file] = source_path.read_text(encoding="utf-8")

    engine = DeterministicMigrationEngine()
    results: list[MigrationResult] = []
    for change in sorted(blast.changes, key=lambda item: item.id):
        impacts = [item for item in blast.direct_impacts if item.change_id == change.id]
        if not impacts:
            continue
        batch = engine.plan_many(
            change,
            impacts,
            calls.values(),
            sources,
        )
        results.extend(batch.results)

    ordered = tuple(
        sorted(
            results,
            key=lambda item: (
                item.plan.target_file,
                item.plan.target_line,
                item.plan.target_column,
                item.plan.id,
            ),
        )
    )
    warnings = tuple(
        sorted(
            set(blast.warnings)
            | {warning for result in ordered for warning in result.summary.warnings}
        )
    )
    summary = MigrationSummary(
        changes_analyzed=len(blast.changes),
        deterministically_repairable=sum(
            result.outcome.value == "DETERMINISTIC_CANDIDATE" for result in ordered
        ),
        unsupported=sum(result.outcome.value == "UNSUPPORTED" for result in ordered),
        partial_or_ambiguous=sum(
            result.outcome.value == "AI_REQUIRED" for result in ordered
        ),
        edits_generated=sum(len(result.plan.edits) for result in ordered),
        files_targeted=len({edit.file for result in ordered for edit in result.plan.edits}),
        conflicts=sum(len(result.conflicts) for result in ordered),
        warnings=warnings,
    )
    return MigrationBatchResult(
        id=f"migration-vertical-{blast.id}",
        results=ordered,
        summary=summary,
    )


analyze_migration_vertical_slice = analyze_vertical_slice


__all__ = ["analyze_migration_vertical_slice", "analyze_vertical_slice"]
