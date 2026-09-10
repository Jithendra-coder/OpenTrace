"""opentrace status — show .opentrace/ workspace state at a glance."""

from __future__ import annotations

from pathlib import Path

from opentrace.cli.output import (
    bold, cyan, dim, green, print_banner, print_section,
    print_ok, print_warn, red, yellow,
)
from opentrace.cli.workspace import (
    analysis_exists, analysis_path,
    migration_plan_exists, migration_plan_path,
    read_json, validation_exists, validation_result_path,
    workspace_exists,
)


def run_status(workspace: Path) -> None:
    """Print the current state of the .opentrace/ workspace."""

    print_banner("OpenTrace  Status")

    if not workspace_exists(workspace):
        print_warn("No .opentrace/ workspace found.")
        print(f"  Run  {cyan('opentrace analyze --old-spec <file> --new-spec <file> --repo <dir>')}  to start.")
        print()
        return

    print(f"  Workspace: {workspace / '.opentrace'}\n")

    # --- Analysis ---
    if analysis_exists(workspace):
        data = read_json(analysis_path(workspace)) or {}
        changes = data.get("changes_count", "?")
        direct = data.get("direct_count", "?")
        indirect = data.get("indirect_count", "?")
        print_ok(f"Analysis found  ({changes} change(s), {direct} direct, {indirect} indirect)")
        print(f"    Old spec: {dim(data.get('old_spec', '?'))}")
        print(f"    New spec: {dim(data.get('new_spec', '?'))}")
        print(f"    Repo    : {dim(data.get('repo', '?'))}")
    else:
        print_warn("No analysis — run  opentrace analyze  first.")

    print()

    # --- Migration plan ---
    if migration_plan_exists(workspace):
        data = read_json(migration_plan_path(workspace)) or {}
        status = data.get("generation_status", "?")
        policy = data.get("policy", "?")
        ai = data.get("ai_enabled", False)
        edits = len((data.get("patch") or {}).get("edits", []))
        status_str = green(status) if status == "GENERATED" else yellow(status)
        print_ok(f"Migration plan  (status: {status_str}, policy: {policy}, ai: {ai}, edits: {edits})")
    else:
        print_warn("No migration plan — run  opentrace migrate  after analyze.")

    print()

    # --- Validation ---
    if validation_exists(workspace):
        data = read_json(validation_result_path(workspace)) or {}
        status = data.get("status", "?")
        passed = data.get("tests_passed")
        failed = data.get("tests_failed")
        ms = data.get("duration_ms")
        status_str = _val_status_str(status)
        test_str = ""
        if passed is not None:
            test_str = f"  passed={passed}" + (f" failed={failed}" if failed else "")
        duration_str = f"  {ms}ms" if ms is not None else ""
        print_ok(f"Validation result  ({status_str}{test_str}{duration_str})")
    else:
        print_warn("No validation result — run  opentrace validate  after migrate.")

    print()

    # --- Feedback ---
    feedback_dir = workspace / ".opentrace" / "feedback"
    if feedback_dir.exists():
        records = list(feedback_dir.glob("*.jsonl"))
        print_ok(f"Feedback records: {len(records)} record(s) in {feedback_dir}")
    else:
        print(f"  {dim('No feedback records yet.')}")

    print()
    _print_next_step(workspace)
    print()


def _val_status_str(status: str) -> str:
    mapping = {
        "TESTS_PASSED": green("TESTS_PASSED ✓"),
        "TESTS_FAILED": red("TESTS_FAILED ✗"),
        "NO_TESTS_COLLECTED": yellow("NO_TESTS_COLLECTED ⚠"),
        "PATCH_FAILED": red("PATCH_FAILED ✗"),
        "SYNTAX_ERROR": red("SYNTAX_ERROR ✗"),
        "TIMEOUT": red("TIMEOUT"),
        "RUNNER_ERROR": yellow("RUNNER_ERROR"),
    }
    return mapping.get(status, dim(status))


def _print_next_step(workspace: Path) -> None:
    if not analysis_exists(workspace):
        print(f"  {bold('Next:')} opentrace analyze --old-spec <old.yaml> --new-spec <new.yaml> --repo <dir>")
    elif not migration_plan_exists(workspace):
        print(f"  {bold('Next:')} opentrace migrate")
    elif not validation_exists(workspace):
        plan = read_json(migration_plan_path(workspace)) or {}
        if plan.get("patch"):
            print(f"  {bold('Next:')} opentrace validate")
        else:
            status = plan.get("generation_status", "NO_PATCH")
            print(f"  {bold('Next:')} Review migration status ({status}) or re-run migrate with a supported policy.")
    else:
        data = read_json(validation_result_path(workspace)) or {}
        if data.get("status") in ("TESTS_PASSED", "NO_TESTS_COLLECTED"):
            print(f"  {bold('Next:')} opentrace apply")
        else:
            print(f"  {bold('Next:')} Review validation failures, then opentrace apply --yes or re-run migrate.")
