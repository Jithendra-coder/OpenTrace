from opentrace.evaluation.generation import build_generation_evaluation


def test_generation_evaluation_requires_matching_patch_and_passing_tests() -> None:
    plan = {
        "generation_status": "GENERATED",
        "provider_adapter_id": "deterministic-fake-v1",
        "model_id": "small-model",
        "context_trace": {
            "selection_status": "CONTEXT_READY",
            "budget_limit_characters": 8000,
            "summary": {
                "completeness": "CONTEXT_READY",
                "required_items_selected": 1,
                "optional_items_selected": 1,
                "omitted_items": 0,
                "budget_used_characters": 120,
            },
            "selected_items": [{"id": "ctx-1"}],
        },
        "patch": {"id": "patch-1", "edits": [{}, {}]},
    }
    validation = {
        "patch_id": "patch-1",
        "status": "TESTS_PASSED",
        "patch_applied": True,
        "syntax_ok": True,
        "tests_collected": 4,
        "tests_passed": 4,
        "tests_failed": 0,
        "workspace_cleaned": True,
    }

    report = build_generation_evaluation(plan, validation)

    assert report["outcome"] == "VALIDATED"
    assert report["semantic_correctness"] == "NOT_ASSESSED"
    assert report["retrieval"]["budget_limit_characters"] == 8000
    assert report["generation"]["edit_count"] == 2


def test_generation_evaluation_rejects_stale_validation_evidence() -> None:
    plan = {"generation_status": "GENERATED", "patch": {"id": "current"}}
    validation = {"patch_id": "stale", "status": "TESTS_PASSED"}

    report = build_generation_evaluation(plan, validation)

    assert report["outcome"] == "INVALID_EVIDENCE"
    assert report["validation"]["patch_id_matches"] is False


def test_generation_evaluation_does_not_treat_zero_test_runs_as_validated() -> None:
    plan = {"generation_status": "GENERATED", "patch": {"id": "patch-1"}}
    validation = {
        "patch_id": "patch-1",
        "status": "TESTS_PASSED",
        "patch_applied": True,
        "syntax_ok": True,
        "tests_collected": 0,
        "workspace_cleaned": True,
    }

    report = build_generation_evaluation(plan, validation)

    assert report["outcome"] == "VALIDATION_FAILED_OR_INCOMPLETE"
