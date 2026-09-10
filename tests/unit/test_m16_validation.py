"""M16 unit tests: sandbox, runner, validator contracts and adversarial cases."""

from __future__ import annotations

import hashlib
import textwrap
from pathlib import Path

import pytest

from opentrace.ai_migration.models import (
    ProposedFileEdit,
    ProposedMigrationPatch,
)
from opentrace.routeforge.models import RouteChoice
from opentrace.validation import (
    SandboxConfig,
    ValidationEvidence,
    ValidationStatus,
    validate_patch,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ROOT = Path(__file__).parents[2]
DEMO = ROOT / "demo" / "ecommerce"
PAYMENT_FILE = "payment_service.py"

# The exact text the fake provider removes (see providers.py _target).
ORIGINAL_TEXT = '"amount": price, '
REPLACEMENT_TEXT = ""


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _make_edit(
    file: str = PAYMENT_FILE,
    original_text: str = ORIGINAL_TEXT,
    replacement_text: str = REPLACEMENT_TEXT,
    *,
    bad_hash: bool = False,
) -> ProposedFileEdit:
    source = (DEMO / file).read_text(encoding="utf-8")
    source_hash = _sha256(source)
    original_hash = _sha256(original_text) if not bad_hash else "not-a-hash"
    return ProposedFileEdit(
        id=f"edit-{file}-test",
        file=file,
        context_item_id="ctx-item-test",
        symbol="create_payment",
        start_line=7,
        end_line=10,
        source_item_hash=source_hash,
        original_text_hash=original_hash,
        expected_original_text=original_text,
        replacement_text=replacement_text,
        reason="Remove obsolete amount field",
        response_item_indexes=(0,),
    )


def _make_patch(
    edits: tuple[ProposedFileEdit, ...] | None = None,
) -> ProposedMigrationPatch:
    if edits is None:
        edits = (_make_edit(),)
    return ProposedMigrationPatch(
        id="patch-m16-test",
        migration_context_id="ctx-m16-test",
        migration_context_checksum="fixture-checksum",
        routing_decision_id="decision-m16-test",
        selected_strategy=RouteChoice.SMALL,
        provider_adapter_id="deterministic-fake-v1",
        model_id="small-configured-model",
        generation_policy_version="migration-generation-policy-v1",
        generation_fingerprint="fixture-fingerprint",
        provider_response_hash="fixture-response-hash",
        edits=edits,
        explanation="Fixture patch for M16 unit tests.",
    )


# ---------------------------------------------------------------------------
# Workspace and patch application tests
# ---------------------------------------------------------------------------


def test_valid_patch_is_applied_and_workspace_is_cleaned() -> None:
    patch = _make_patch()
    config = SandboxConfig(timeout_seconds=60)

    evidence = validate_patch(patch, DEMO, config)

    assert evidence.patch_id == "patch-m16-test"
    assert evidence.patch_applied is True
    assert evidence.workspace_created is True
    assert evidence.workspace_cleaned is True
    assert evidence.workspace_path_hint is not None
    assert len(evidence.workspace_path_hint) == 8
    assert evidence.duration_ms is not None and evidence.duration_ms >= 0


def test_source_repository_is_not_mutated_after_validation() -> None:
    before = {p.name: p.read_text(encoding="utf-8") for p in DEMO.glob("*.py")}
    patch = _make_patch()
    validate_patch(patch, DEMO)
    after = {p.name: p.read_text(encoding="utf-8") for p in DEMO.glob("*.py")}

    assert before == after


def test_missing_original_text_returns_patch_failed() -> None:
    edit = _make_edit(original_text="this text does not exist in the file")
    patch = _make_patch(edits=(edit,))

    evidence = validate_patch(patch, DEMO)

    assert evidence.status is ValidationStatus.PATCH_FAILED
    assert evidence.patch_applied is False
    assert evidence.patch_failure_reason is not None
    assert evidence.workspace_cleaned is True


def test_path_traversal_in_edit_returns_patch_failed() -> None:
    edit = ProposedFileEdit(
        id="traversal-edit",
        file="../../outside.py",
        context_item_id="ctx-test",
        symbol=None,
        start_line=1,
        end_line=1,
        source_item_hash="x" * 64,
        original_text_hash="x" * 64,
        expected_original_text="anything",
        replacement_text="anything",
        reason="adversarial traversal",
        response_item_indexes=(0,),
    )
    patch = _make_patch(edits=(edit,))

    evidence = validate_patch(patch, DEMO)

    assert evidence.status is ValidationStatus.PATCH_FAILED
    assert evidence.patch_applied is False
    assert evidence.workspace_cleaned is True


def test_nonexistent_file_returns_patch_failed() -> None:
    edit = ProposedFileEdit(
        id="missing-edit",
        file="does_not_exist.py",
        context_item_id="ctx-test",
        symbol=None,
        start_line=1,
        end_line=1,
        source_item_hash="x" * 64,
        original_text_hash="x" * 64,
        expected_original_text="anything",
        replacement_text="anything",
        reason="missing file test",
        response_item_indexes=(0,),
    )
    patch = _make_patch(edits=(edit,))

    evidence = validate_patch(patch, DEMO)

    assert evidence.status is ValidationStatus.PATCH_FAILED
    assert evidence.patch_applied is False
    assert evidence.workspace_cleaned is True


# ---------------------------------------------------------------------------
# Syntax check tests
# ---------------------------------------------------------------------------


def test_syntax_error_patch_returns_syntax_error_status(tmp_path: Path) -> None:
    """Create a repo with a .py file and apply a patch that breaks syntax."""
    # Build a minimal temp repo.
    (tmp_path / "broken_module.py").write_text(
        "def hello():\n    return 'ok'\n", encoding="utf-8"
    )

    original = "return 'ok'"
    replacement = "return 'ok'\n    def bad syntax here!!!"

    edit = ProposedFileEdit(
        id="syntax-edit",
        file="broken_module.py",
        context_item_id="ctx-test",
        symbol="hello",
        start_line=2,
        end_line=2,
        source_item_hash=_sha256("def hello():\n    return 'ok'\n"),
        original_text_hash=_sha256(original),
        expected_original_text=original,
        replacement_text=replacement,
        reason="intentional syntax error for testing",
        response_item_indexes=(0,),
    )
    patch = ProposedMigrationPatch(
        id="patch-syntax-test",
        migration_context_id="ctx-syntax",
        migration_context_checksum="checksum",
        routing_decision_id="decision-syntax",
        selected_strategy=RouteChoice.SMALL,
        provider_adapter_id="fake",
        model_id="fake-model",
        generation_policy_version="migration-generation-policy-v1",
        generation_fingerprint="fp",
        provider_response_hash="rh",
        edits=(edit,),
        explanation="Syntax error test.",
    )

    evidence = validate_patch(patch, tmp_path)

    assert evidence.status is ValidationStatus.SYNTAX_ERROR
    assert evidence.patch_applied is True
    assert evidence.syntax_ok is False
    assert evidence.syntax_failure_file == "broken_module.py"
    assert evidence.workspace_cleaned is True


# ---------------------------------------------------------------------------
# Validation evidence model contracts
# ---------------------------------------------------------------------------


def test_validation_evidence_has_correct_schema_version() -> None:
    patch = _make_patch()
    evidence = validate_patch(patch, DEMO)

    assert evidence.schema_version == "validation-evidence-v1"


def test_validation_evidence_limitations_are_documented() -> None:
    patch = _make_patch()
    evidence = validate_patch(patch, DEMO)

    assert len(evidence.limitations) >= 1
    assert any("subprocess" in lim.lower() for lim in evidence.limitations)
    assert any("docker" in lim.lower() for lim in evidence.limitations)


def test_valid_patch_reports_workspace_audit_fields() -> None:
    patch = _make_patch()
    evidence = validate_patch(patch, DEMO)

    assert evidence.workspace_created is True
    assert evidence.workspace_cleaned is True
    assert evidence.duration_ms is not None


def test_canonical_json_is_deterministic() -> None:
    patch = _make_patch()
    first = validate_patch(patch, DEMO)
    second = validate_patch(patch, DEMO)

    # Status and structural fields are deterministic (timing will differ).
    assert first.status == second.status
    assert first.patch_applied == second.patch_applied
    assert first.syntax_ok == second.syntax_ok
    assert first.patch_id == second.patch_id
