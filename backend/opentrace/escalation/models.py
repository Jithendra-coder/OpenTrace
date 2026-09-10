"""M17 + M18 models: escalation decisions and feedback records."""

from __future__ import annotations

import json
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from opentrace.validation.models import ValidationStatus

ESCALATION_SCHEMA_VERSION = "escalation-v1"
ESCALATION_POLICY_VERSION = "escalation-policy-v1"
FEEDBACK_SCHEMA_VERSION = "feedback-record-v1"


class CanonicalModel(BaseModel):
    """Frozen, inspectable escalation and feedback artifacts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    def canonical_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json", exclude_none=True),
            sort_keys=True,
            separators=(",", ":"),
        )


# ---------------------------------------------------------------------------
# M17 — Escalation
# ---------------------------------------------------------------------------


class EscalationAction(StrEnum):
    """What the escalation engine decided to do next."""

    # Try again with a larger context budget.
    RETRY_WITH_MORE_CONTEXT = "RETRY_WITH_MORE_CONTEXT"
    # Bump to the next stronger AI strategy tier.
    ESCALATE_TO_STRONGER_STRATEGY = "ESCALATE_TO_STRONGER_STRATEGY"
    # All retries exhausted — human must review.
    AI_REQUIRED = "AI_REQUIRED"
    # AI strategies are not available; fall back to deterministic patch.
    DETERMINISTIC_FALLBACK = "DETERMINISTIC_FALLBACK"
    # Validation passed — no escalation needed.
    NO_ESCALATION_NEEDED = "NO_ESCALATION_NEEDED"
    # Strategy is not an AI strategy; escalation does not apply.
    NOT_APPLICABLE = "NOT_APPLICABLE"


class EscalationPolicy(CanonicalModel):
    """Configurable, finite escalation limits."""

    version: str = ESCALATION_POLICY_VERSION
    # Maximum total retry attempts across all escalation tiers.
    max_retries: int = Field(default=2, ge=0, le=10)
    # Whether to try expanding the context budget before changing strategy.
    allow_context_expansion: bool = True
    # Multiplier applied to context budget on each context-expansion retry.
    context_expansion_factor: float = Field(default=2.0, ge=1.1, le=8.0)
    # Whether to escalate to a stronger strategy tier when context expansion
    # does not resolve the failure.
    allow_strategy_escalation: bool = True


class EscalationAttempt(CanonicalModel):
    """Record of one escalation retry attempt."""

    attempt_number: int = Field(ge=1)
    action_taken: EscalationAction
    validation_status_before: ValidationStatus
    failure_summary_before: str | None = None
    # Evidence incorporated into the retry request.
    evidence_incorporated: tuple[str, ...] = ()
    context_budget_characters: int | None = None
    strategy_used: str | None = None


class EscalationResult(CanonicalModel):
    """Final result of the escalation engine after all retries."""

    schema_version: str = ESCALATION_SCHEMA_VERSION
    policy_version: str = ESCALATION_POLICY_VERSION
    patch_id: str
    final_action: EscalationAction
    total_attempts: int = Field(ge=0)
    attempts: tuple[EscalationAttempt, ...] = ()
    # The failure summary from the last validation attempt.
    terminal_failure_summary: str | None = None
    # Human-readable explanation of why escalation stopped.
    reason: str = ""

    @model_validator(mode="after")
    def attempts_match_total(self) -> EscalationResult:
        if len(self.attempts) != self.total_attempts:
            raise ValueError(
                f"total_attempts={self.total_attempts} but "
                f"len(attempts)={len(self.attempts)}"
            )
        return self


# ---------------------------------------------------------------------------
# M18 — Feedback records
# ---------------------------------------------------------------------------


class UserAction(StrEnum):
    """What the human decided to do with the migration result."""

    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SKIPPED = "SKIPPED"
    # Human reviewed but deferred the decision.
    DEFERRED = "DEFERRED"


class FeedbackRecord(CanonicalModel):
    """Immutable, versioned feedback record written after human review.

    Preserves task/context/route/provider/patch/result provenance.
    Never used for automatic online self-training.
    """

    schema_version: str = FEEDBACK_SCHEMA_VERSION
    record_id: str
    timestamp_utc: str  # ISO 8601

    # Provenance chain
    patch_id: str
    migration_context_id: str | None = None
    routing_decision_id: str | None = None
    selected_strategy: str | None = None
    provider_adapter_id: str | None = None
    model_id: str | None = None

    # Validation outcome
    validation_status: ValidationStatus | None = None
    validation_failure_summary: str | None = None
    escalation_attempts: int = Field(default=0, ge=0)
    final_escalation_action: EscalationAction | None = None

    # Human decision
    user_action: UserAction
    rejection_reason: str | None = None

    # Anti-self-training note — always recorded
    training_note: str = (
        "This record is for audit and offline analysis only. "
        "It must not be used for automatic online model updates."
    )
