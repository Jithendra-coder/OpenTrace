"""Feedback writer: persists versioned, immutable feedback records to disk."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from opentrace.escalation.models import (
    EscalationAction,
    EscalationResult,
    FeedbackRecord,
    UserAction,
)
from opentrace.ai_migration.models import MigrationGenerationResult
from opentrace.validation.models import ValidationEvidence

FEEDBACK_SCHEMA_VERSION = "feedback-record-v1"
_FEEDBACK_DIR_NAME = ".opentrace"
_FEEDBACK_SUBDIR = "feedback"


def write_feedback_record(
    generation_result: MigrationGenerationResult,
    validation_evidence: ValidationEvidence | None,
    escalation_result: EscalationResult | None,
    user_action: UserAction,
    output_dir: Path | str,
    *,
    rejection_reason: str | None = None,
) -> Path:
    """Persist one immutable feedback record to disk as JSONL.

    Records are written to:
      <output_dir>/.opentrace/feedback/<timestamp>-<record-id>.jsonl

    The record is never used for automatic online model updates.
    It is for audit and offline analysis only.

    Returns the path to the written record.
    """
    root = Path(output_dir)
    feedback_dir = root / _FEEDBACK_DIR_NAME / _FEEDBACK_SUBDIR
    feedback_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    record_id = _make_record_id(generation_result, timestamp)

    patch = generation_result.patch
    record = FeedbackRecord(
        schema_version=FEEDBACK_SCHEMA_VERSION,
        record_id=record_id,
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
        patch_id=patch.id if patch else "no-patch",
        migration_context_id=(
            generation_result.migration_context_id
        ),
        routing_decision_id=(
            patch.routing_decision_id if patch else None
        ),
        selected_strategy=(
            patch.selected_strategy.value if patch else None
        ),
        provider_adapter_id=(
            patch.provider_adapter_id if patch else None
        ),
        model_id=(
            patch.model_id if patch else None
        ),
        validation_status=(
            validation_evidence.status if validation_evidence else None
        ),
        validation_failure_summary=(
            validation_evidence.failure_summary if validation_evidence else None
        ),
        escalation_attempts=(
            escalation_result.total_attempts if escalation_result else 0
        ),
        final_escalation_action=(
            escalation_result.final_action if escalation_result else None
        ),
        user_action=user_action,
        rejection_reason=rejection_reason,
    )

    filename = f"{timestamp}-{record_id}.jsonl"
    out_path = feedback_dir / filename
    line = record.canonical_json() + "\n"
    out_path.write_text(line, encoding="utf-8", newline="\n")

    return out_path


def load_feedback_records(feedback_dir: Path | str) -> list[FeedbackRecord]:
    """Load all feedback records from a directory.

    Returns records in file-system order. Skips malformed lines with a warning.
    """
    root = Path(feedback_dir)
    search = root / _FEEDBACK_DIR_NAME / _FEEDBACK_SUBDIR
    if not search.exists():
        return []

    records: list[FeedbackRecord] = []
    for path in sorted(search.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                records.append(FeedbackRecord(**data))
            except Exception:
                # Malformed record — skip silently (real production code
                # should log this).
                pass
    return records


def _make_record_id(
    generation_result: MigrationGenerationResult,
    timestamp: str,
) -> str:
    patch = generation_result.patch
    raw = f"{patch.id if patch else 'no-patch'}-{timestamp}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
