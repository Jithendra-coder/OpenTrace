"""opentrace evaluate — summarize the current migration run's evaluation evidence."""

from __future__ import annotations

import sys
from pathlib import Path

from opentrace.cli.output import print_banner, print_error, print_info, print_ok, print_section
from opentrace.cli.workspace import (
    generation_evaluation_path,
    migration_plan_exists,
    migration_plan_path,
    read_json,
    validation_result_path,
    write_json,
)
from opentrace.evaluation.generation import build_generation_evaluation


def run_evaluate(workspace: Path) -> None:
    if not migration_plan_exists(workspace):
        print_error("No migration plan found. Run  opentrace migrate  first.")
        sys.exit(1)

    plan = read_json(migration_plan_path(workspace))
    if not isinstance(plan, dict):
        print_error("Could not read migration-plan.json.")
        sys.exit(1)
    validation_value = read_json(validation_result_path(workspace))
    validation = validation_value if isinstance(validation_value, dict) else None
    report = build_generation_evaluation(plan, validation)
    output = generation_evaluation_path(workspace)
    write_json(output, report)

    print_banner("OpenTrace  Evaluate")
    print_section("Generation Evaluation")
    print_info(f"Outcome          : {report['outcome']}")
    retrieval = report["retrieval"]
    print_info(f"Retrieval status : {retrieval['selection_status']} ({retrieval['completeness']})")
    print_info(
        f"Context items    : {retrieval['selected_item_count']} selected, "
        f"{retrieval['omitted_items']} omitted"
    )
    print_info(f"Generation       : {report['generation']['status']}")
    print_info(f"Validation       : {report['validation']['status']}")
    print_info(f"Semantic quality : {report['semantic_correctness']}")
    print_ok(f"Evaluation report written → {output}")
