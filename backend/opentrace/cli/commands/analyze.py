"""opentrace analyze — detect API changes and find affected code."""

from __future__ import annotations

import sys
from pathlib import Path

from opentrace.blast_radius.vertical import analyze_vertical_slice
from opentrace.cli.output import (
    bold, cyan, dim, green, print_banner, print_error,
    print_info, print_item, print_ok, print_section, print_warn, red, rule, yellow,
)
from opentrace.cli.workspace import (
    analysis_path, ensure_workspace, write_json,
)


def run_analyze(
    old_spec: Path,
    new_spec: Path,
    repo: Path,
    output_dir: Path,
) -> None:
    """Run analysis pipeline and write results to .opentrace/analysis.json."""

    # --- Auto-resolve paths: check current dir, then fallback to repository root ---
    repo_root = Path(__file__).resolve().parents[4]
    if not old_spec.exists() and (repo_root / old_spec).exists():
        old_spec = repo_root / old_spec
    if not new_spec.exists() and (repo_root / new_spec).exists():
        new_spec = repo_root / new_spec
    if not repo.exists() and (repo_root / repo).exists():
        repo = repo_root / repo

    # --- Validate inputs ---
    for p, label in [(old_spec, "--old-spec"), (new_spec, "--new-spec"), (repo, "--repo")]:
        if not p.exists():
            print_error(f"{label} path does not exist: {p}")
            sys.exit(1)

    print_banner("OpenTrace  Analyze")
    print_info(f"Old spec : {old_spec}")
    print_info(f"New spec : {new_spec}")
    print_info(f"Repo     : {repo}")
    print()

    # --- Run pipeline ---
    print(f"  Running analysis pipeline...")
    try:
        blast = analyze_vertical_slice(old_spec, new_spec, repo)
    except Exception as exc:
        print_error(f"Analysis failed: {exc}")
        sys.exit(1)

    # --- Summarise changes ---
    changes = list(blast.changes) if blast.changes else []
    direct = list(blast.direct_impacts) if blast.direct_impacts else []
    direct_symbols = {getattr(d, "symbol", getattr(d, "function_name", "")) for d in direct}
    indirect_symbols = [
        s for s in (blast.impacted_symbols or ())
        if getattr(s, "distance", 0) > 0 or getattr(s, "symbol", "") not in direct_symbols
    ]

    print_section("API Changes Detected")
    if not changes:
        print(f"  {dim('No breaking changes detected.')}")
        print()
        print_ok("Nothing to migrate.")
        return

    print(f"  {bold(str(len(changes)))} breaking change(s) found.\n")

    for i, change in enumerate(changes, 1):
        method = getattr(change, "method", "")
        path = getattr(change, "path", "")
        category = getattr(change, "category", None)
        kind = category.value if hasattr(category, "value") else str(getattr(change, "change_type", "BREAKING"))
        field = getattr(change, "location", getattr(change, "field_path", ""))

        print(f"  {bold(str(i))}. {cyan(method.upper())} {path}")
        if field:
            print(f"     {yellow('Location:')} {field}")
        print(f"     {dim(str(kind))}")
        print()

    # --- Affected code ---
    print_section("Affected Code")
    if not direct and not indirect_symbols:
        print(f"  {dim('No affected code found in repository.')}")
    else:
        direct_count = len(direct)
        indirect_count = len(indirect_symbols)
        print(f"  Direct impacts  : {bold(str(direct_count))}")
        print(f"  Indirect impacts: {bold(str(indirect_count))}")
        print()

        shown = 0
        for imp in direct:
            file = getattr(imp, "file", getattr(imp, "source_file", "?"))
            line = getattr(imp, "line", getattr(imp, "start_line", None))
            symbol = getattr(imp, "symbol", getattr(imp, "function_name", None))
            loc = f"{file}:{line}" if line else file
            sym_str = f"  {dim(symbol)}" if symbol else ""
            print(f"    {cyan('[DIRECT]')}   {loc}{sym_str}")
            shown += 1
            if shown >= 8:
                break

        for sym in indirect_symbols:
            file = getattr(sym, "file", "?")
            symbol = getattr(sym, "symbol", "")
            dist = getattr(sym, "distance", 1)
            print(f"    {yellow('[INDIRECT]')} {file}  {dim(symbol)} (distance: {dist})")
            shown += 1
            if shown >= 12:
                remaining = indirect_count - (shown - direct_count)
                if remaining > 0:
                    print(f"    {dim(f'... and {remaining} more indirect impact(s)')}")
                break

    # --- Save workspace ---
    ensure_workspace(output_dir)
    artifact = {
        "schema_version": "analysis-v1",
        "old_spec": str(old_spec.resolve()),
        "new_spec": str(new_spec.resolve()),
        "repo": str(repo.resolve()),
        "changes_count": len(changes),
        "direct_count": len(direct),
        "indirect_count": len(indirect_symbols),
        "changes": [_change_to_dict(c) for c in changes],
        "direct_impacts": [_impact_to_dict(d) for d in direct],
    }
    out = analysis_path(output_dir)
    write_json(out, artifact)

    print()
    print_section("Next Step")
    print_ok(f"Analysis written → {out}")
    print_info("Run  opentrace migrate  to generate a migration plan.")
    print()


def _change_to_dict(change: object) -> dict:
    category = getattr(change, "category", None)
    cat_val = category.value if hasattr(category, "value") else str(getattr(change, "change_type", ""))
    return {
        "method": str(getattr(change, "method", "")),
        "path": str(getattr(change, "path", "")),
        "change_type": cat_val,
        "field": str(getattr(change, "location", getattr(change, "field_path", ""))),
        "change_id": str(getattr(change, "id", getattr(change, "change_id", ""))),
    }


def _impact_to_dict(impact: object) -> dict:
    return {
        "file": str(getattr(impact, "file", getattr(impact, "source_file", ""))),
        "line": getattr(impact, "line", getattr(impact, "start_line", None)),
        "symbol": str(getattr(impact, "symbol", getattr(impact, "function_name", ""))),
        "change_id": str(getattr(impact, "change_id", getattr(impact, "id", ""))),
    }
