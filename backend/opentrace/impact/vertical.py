"""The first real M1 → M2 → M3 → M4 in-memory analysis path."""

from pathlib import Path
from urllib.parse import urlsplit

from opentrace.code_analysis import analyze_repository
from opentrace.contracts.changes import compare_specifications
from opentrace.contracts.parser import OpenAPIParser
from opentrace.impact.matcher import DirectImpactMatcher
from opentrace.impact.models import ImpactAnalysis


def analyze_vertical_slice(
    old_spec_path: Path | str,
    new_spec_path: Path | str,
    repository_path: Path | str,
) -> ImpactAnalysis:
    """Normalize two specs, extract repository calls, and match direct evidence."""
    parser = OpenAPIParser()
    old_specification = parser.parse_file(Path(old_spec_path))
    new_specification = parser.parse_file(Path(new_spec_path))
    changes = compare_specifications(old_specification, new_specification)
    repository = analyze_repository(repository_path)
    hosts = tuple(
        host
        for host in (urlsplit(server).hostname for server in old_specification.servers)
        if host is not None
    )
    result = DirectImpactMatcher(api_hosts=hosts).match(changes, repository.call_sites)
    warnings = list(result.warnings)
    warnings.extend(
        f"{file.path}: {file.reason or file.error_category or 'file not fully analyzed'}"
        for file in repository.files
        if file.state.value != "PARSED"
    )
    return result.model_copy(
        update={
            "changes": changes,
            "call_sites": repository.call_sites,
            "files": repository.files,
            "warnings": tuple(sorted(set(warnings))),
        }
    )
