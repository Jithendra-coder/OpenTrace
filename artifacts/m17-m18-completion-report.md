```
MILESTONE
M17 — Adaptive Repair Escalation
M18 — Feedback Record Persistence
(Implemented together in one session as planned)

STATUS
COMPLETE

IMPLEMENTED — M17

- EscalationPolicy (pydantic, frozen): configurable max_retries (0–10,
  default 2), allow_context_expansion, context_expansion_factor (1.1–8.0),
  allow_strategy_escalation. Policy version: escalation-policy-v1.
- EscalationAction enum: RETRY_WITH_MORE_CONTEXT, ESCALATE_TO_STRONGER_STRATEGY,
  AI_REQUIRED, DETERMINISTIC_FALLBACK, NO_ESCALATION_NEEDED, NOT_APPLICABLE.
- EscalationAttempt (pydantic, frozen): per-retry audit record with
  action_taken, validation_status_before, failure_summary_before,
  evidence_incorporated (non-empty — blind regeneration is prohibited),
  context_budget_characters, strategy_used.
- EscalationResult (pydantic, frozen, canonical_json): schema_version,
  policy_version, patch_id, final_action, total_attempts, attempts tuple,
  terminal_failure_summary, reason. Model validator enforces
  len(attempts) == total_attempts.
- RepairEscalationEngine.run(): full bounded retry loop
    • Non-AI routes (NO_AI, DETERMINISTIC, NO_FEASIBLE_STRATEGY) →
      NOT_APPLICABLE immediately; no retry.
    • Generation failure → NOT_APPLICABLE.
    • TESTS_PASSED on first validation → NO_ESCALATION_NEEDED; no retry.
    • Retryable statuses: TESTS_FAILED, SYNTAX_ERROR, RUNNER_ERROR,
      NO_TESTS_COLLECTED.
    • Non-retryable: TIMEOUT, PATCH_FAILED, SANDBOX_ERROR — breaks loop.
    • Retry 1: RETRY_WITH_MORE_CONTEXT (expand context budget by factor).
    • Retry 2+: ESCALATE_TO_STRONGER_STRATEGY (SMALL → MEDIUM → STRONG).
    • On exhaustion: AI_REQUIRED (human must review).
    • Each retry: EscalationAttempt.evidence_incorporated is always non-empty
      (validation_status, failure_excerpt, syntax_failure_file, counts).
    • Strategy escalation calls _with_strategy() (model_copy) on the routing
      decision — original decision is never mutated.
- _next_strategy(): SMALL → MEDIUM → STRONG → None (None means already
  at strongest; escalation stops).

NOT IMPLEMENTED — M17
- Real AI provider adapters to re-invoke on escalation — the fake provider
  re-generates the same patch (deterministic). Escalation with a real provider
  would incorporate the failure evidence into a new prompt; deferred to
  real-provider integration.
- Token budget awareness on context expansion — budget number is computed
  but not enforced against a real token counter (deferred to real provider).

IMPLEMENTED — M18

- FeedbackRecord (pydantic, frozen, canonical_json): full provenance chain —
  schema_version, record_id, timestamp_utc, patch_id, migration_context_id,
  routing_decision_id, selected_strategy, provider_adapter_id, model_id,
  validation_status, validation_failure_summary, escalation_attempts,
  final_escalation_action, user_action, rejection_reason.
  Anti-self-training note always recorded in training_note field.
- UserAction enum: ACCEPTED, REJECTED, SKIPPED, DEFERRED.
- write_feedback_record(): writes immutable JSONL line to
  <output_dir>/.specimpact/feedback/<timestamp_with_microseconds>-<id>.jsonl.
  Microsecond timestamp prevents filename collisions for rapid successive writes.
- load_feedback_records(): loads all *.jsonl records from the feedback dir;
  skips malformed lines; returns list in filesystem order.
- training_note is always written; content: "This record is for audit and
  offline analysis only. It must not be used for automatic online model updates."

NOT IMPLEMENTED — M18
- Online learning pipeline — explicitly prohibited by spec; feedback records
  are for offline analysis only.
- Feedback record expiry or rotation — deferred.

RUNTIME FIX
- runner.py: removed --timeout=30 flag (requires pytest-timeout which is not
  installed on this host). Wall-clock timeout is enforced by subprocess.run()
  timeout_seconds parameter. Per-test timeout deferred to pytest-timeout
  installation in production environments.
- feedback.py: timestamp format changed from %H%M%SZ to %H%M%S%fZ
  (microseconds) to prevent filename collisions.

FILES CHANGED (new)
backend/specimpact/escalation/__init__.py
backend/specimpact/escalation/models.py
backend/specimpact/escalation/engine.py
backend/specimpact/escalation/feedback.py
tests/unit/test_m17_m18_escalation.py

FILES CHANGED (modified)
backend/specimpact/validation/runner.py  (removed --timeout=30 flag)

INPUTS TESTED
- RouteChoice.SMALL with DeterministicFakeProvider → escalation runs
- RouteChoice.NO_AI → NOT_APPLICABLE immediately
- RouteChoice.DETERMINISTIC → NOT_APPLICABLE immediately
- max_retries=0 with pre-injected TESTS_FAILED evidence → AI_REQUIRED, 0 attempts
- Pre-injected TESTS_FAILED evidence, max_retries=1 → evidence_incorporated non-empty
- Feedback: ACCEPTED, REJECTED, SKIPPED written to tmp_path
- Feedback: two records written in rapid succession → both recoverable
- Feedback: load from missing directory → empty list
- Strategy escalation: SMALL → MEDIUM → STRONG → None verified

OUTPUTS VERIFIED
- EscalationAction.NOT_APPLICABLE for non-AI routes
- EscalationAction.AI_REQUIRED after max_retries=0 with failed pre-injected evidence
- EscalationAction in {NO_ESCALATION_NEEDED, NOT_APPLICABLE, AI_REQUIRED}
  for real sandbox run (demo repo has no installed test suite)
- SMALL → MEDIUM → STRONG → None escalation order correct
- All retry attempts have non-empty evidence_incorporated
- EscalationResult canonical_json is valid JSON string
- FeedbackRecord written as JSONL, readable back with load_feedback_records
- FeedbackRecord fields: schema_version, user_action, rejection_reason, patch_id
- training_note contains "not" and "automatic"
- Two rapid-succession records produce 2 distinct files and 2 loadable records
- Empty feedback dir returns []

TESTS RUN
tests/unit/test_m17_m18_escalation.py   14 passed
Full suite (tests/)                     193 passed, 1 skipped

REAL COMMANDS EXECUTED
python -m pytest tests/unit/test_m17_m18_escalation.py -v --tb=short
  → 14 passed in 6.35s

python -m pytest tests/ -q --tb=short
  → 193 passed, 1 skipped in 30.73s

Platform: win32, Python 3.13.5, pytest-8.4.2

KNOWN LIMITATIONS
- DeterministicFakeProvider produces the same patch on each retry regardless
  of the failure evidence. With a real provider, the retry prompt would include
  the failure evidence. This is the correct V1 boundary.
- --timeout=30 (per-test) not enforced in sandbox; only wall-clock subprocess
  timeout is enforced. Requires pytest-timeout to be installed in production.
- Feedback records are not rotated, expired, or size-limited. Production
  deployment should add retention policy.

NEXT ALLOWED MILESTONE
M19 — CLI UX (specimpact analyze / migrate / validate / apply)
```
