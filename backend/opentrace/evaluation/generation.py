"""Deterministic per-run evaluation of retrieval, generation, and sandbox evidence."""

from __future__ import annotations

from typing import Any

GENERATION_EVALUATION_SCHEMA_VERSION = "generation-evaluation-v1"


def build_generation_evaluation(
    plan: dict[str, object], validation: dict[str, object] | None
) -> dict[str, Any]:
    """Summarize measured pipeline gates; do not infer semantic correctness."""
    context = plan.get("context_trace")
    trace = context if isinstance(context, dict) else {}
    summary_value = trace.get("summary")
    summary = summary_value if isinstance(summary_value, dict) else {}
    selected_value = trace.get("selected_items")
    selected = selected_value if isinstance(selected_value, list) else []
    patch_value = plan.get("patch")
    patch = patch_value if isinstance(patch_value, dict) else None
    generation_status = str(plan.get("generation_status", "UNKNOWN"))
    patch_id = str(patch.get("id")) if patch and patch.get("id") else None

    validation_status = "NOT_RUN"
    validation_gates: dict[str, object] = {
        "patch_id_matches": None,
        "patch_applied": None,
        "syntax_ok": None,
        "tests_collected": None,
        "tests_passed": None,
        "tests_failed": None,
        "sandbox_cleaned": None,
    }
    if validation is not None:
        validation_status = str(validation.get("status", "UNKNOWN"))
        validation_gates = {
            "patch_id_matches": validation.get("patch_id") == patch_id,
            "patch_applied": validation.get("patch_applied"),
            "syntax_ok": validation.get("syntax_ok"),
            "tests_collected": validation.get("tests_collected"),
            "tests_passed": validation.get("tests_passed"),
            "tests_failed": validation.get("tests_failed"),
            "sandbox_cleaned": validation.get("workspace_cleaned"),
        }
        if validation_gates["patch_id_matches"] is not True:
            validation_status = "MISMATCHED_PATCH_EVIDENCE"

    if generation_status == "NOT_REQUIRED":
        outcome = "NOT_REQUIRED"
    elif generation_status == "AI_DISABLED":
        outcome = "GENERATION_SKIPPED"
    elif generation_status == "INSUFFICIENT_CONTEXT":
        outcome = "BLOCKED_INSUFFICIENT_CONTEXT"
    elif generation_status != "GENERATED":
        outcome = "GENERATION_FAILED"
    elif validation is None:
        outcome = "AWAITING_VALIDATION"
    elif validation_status == "MISMATCHED_PATCH_EVIDENCE":
        outcome = "INVALID_EVIDENCE"
    elif validation_status == "TESTS_PASSED" and (
        validation_gates["patch_applied"] is True
        and validation_gates["syntax_ok"] is True
        and validation_gates["sandbox_cleaned"] is True
        and isinstance(validation_gates["tests_collected"], int)
        and validation_gates["tests_collected"] > 0
    ):
        outcome = "VALIDATED"
    elif validation_status == "NO_TESTS_COLLECTED":
        outcome = "REVIEW_REQUIRED_NO_TESTS"
    else:
        outcome = "VALIDATION_FAILED_OR_INCOMPLETE"

    budget_value = summary.get("budget_used_characters")
    budget = budget_value if isinstance(budget_value, int) else None
    limit_value = trace.get("budget_limit_characters")
    limit = limit_value if isinstance(limit_value, int) else None

    return {
        "schema_version": GENERATION_EVALUATION_SCHEMA_VERSION,
        "outcome": outcome,
        "semantic_correctness": "NOT_ASSESSED",
        "retrieval": {
            "selection_status": trace.get("selection_status", "UNKNOWN"),
            "context_id": trace.get("context_id"),
            "selection_policy_version": trace.get("selection_policy_version"),
            "manifest_checksum": trace.get("checksum"),
            "completeness": summary.get("completeness", "UNKNOWN"),
            "required_items_selected": summary.get("required_items_selected", 0),
            "optional_items_selected": summary.get("optional_items_selected", 0),
            "selected_item_count": len(selected),
            "omitted_items": summary.get("omitted_items", 0),
            "files_represented": summary.get("files_represented", []),
            "graph_distances_represented": summary.get("graph_distances_represented", []),
            "budget_used_characters": budget,
            "budget_limit_characters": limit,
            "uncertainty_warnings": summary.get("uncertainty_warnings", []),
        },
        "generation": {
            "status": generation_status,
            "strict_contract_accepted": generation_status == "GENERATED",
            "provider_adapter_id": plan.get("provider_adapter_id"),
            "model_id": plan.get("model_id"),
            "patch_id": patch_id,
            "edit_count": len(patch.get("edits", [])) if patch else 0,
        },
        "validation": {
            "status": validation_status,
            **validation_gates,
        },
        "limitations": [
            "This report measures retrieval and deterministic pipeline gates, not semantic repair correctness.",
            "Semantic quality needs a curated, repository-held-out benchmark with human-reviewed expected outcomes.",
        ],
    }
