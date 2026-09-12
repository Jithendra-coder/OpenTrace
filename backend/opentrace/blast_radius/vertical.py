"""The end-to-end blast radius analysis path."""

from pathlib import Path

from opentrace.blast_radius.models import BlastRadius
from opentrace.blast_radius.propagation import analyze_blast_radius
from opentrace.code_analysis import analyze_repository, build_call_graph
from opentrace.impact.vertical import analyze_vertical_slice as analyze_direct_slice


def analyze_vertical_slice(
    old_spec_path: Path | str,
    new_spec_path: Path | str,
    repository_path: Path | str,
) -> BlastRadius:
    direct = analyze_direct_slice(old_spec_path, new_spec_path, repository_path)
    repository = analyze_repository(repository_path)
    graph = build_call_graph(repository_path, analysis=repository)
    return analyze_blast_radius(
        direct.direct_impacts,
        graph,
        changes=direct.changes,
        call_sites=direct.call_sites,
        files=direct.files,
        unmatched_change_ids=tuple(item.change_id for item in direct.unmatched),
    )
