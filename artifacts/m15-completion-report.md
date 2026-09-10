```
MILESTONE
M15 — Provider-Independent AI Migration

STATUS
COMPLETE

IMPLEMENTED
- GenerationProvider Protocol (vendor-neutral; no SDK or vendor response object
  crosses the boundary)
- MigrationGenerator orchestrator with full safety guard pipeline:
    • Path traversal detection (.. sequences, absolute paths)
    • Sensitive file detection (.env, .pem, .key, .aws/*, .ssh/*, credentials/*)
    • Oversized response rejection (> maximum_response_characters)
    • Malformed / non-JSON response rejection
    • Refusal normalization
    • Provider timeout and unavailability normalization
    • Duplicate edit deduplication with merged response_item_indexes provenance
    • Overlapping edit detection and rejection
    • Precondition hash verification (original_text_hash must match actual content)
    • Prompt injection labeling (CONTEXT_ITEMS explicitly marked as untrusted data
      in system instructions)
- Non-AI route short-circuit: NO_AI, DETERMINISTIC, NO_FEASIBLE_STRATEGY all
  return GenerationStatus.NOT_REQUIRED without calling any provider
- AI_ENABLED=false path returns GenerationStatus.AI_DISABLED cleanly — the
  product remains functional without any provider configured
- GenerationConfiguration: runtime-only strategy→model mapping; never freezes
  vendor-specific fields into domain logic
- GenerationPolicy: configurable timeout, max edits, max files, max response
  characters, max replacement characters, max explanation characters
- GenerationRequest / GenerationResponse: full audit-trail contracts with
  fingerprint, checksums, context_item_ids, warnings
- ProposedMigrationPatch / ProposedFileEdit: structured unvalidated candidate
  with source_item_hash, original_text_hash, response_item_indexes provenance
- MigrationGenerationResult: single unified result with status/patch/failure;
  model validator enforces GENERATED↔patch and non-GENERATED↔no-patch
- DeterministicFakeProvider with 12 adversarial modes: VALID, MALFORMED,
  REFUSAL, TIMEOUT, UNAVAILABLE, UNSAFE_PATH, SENSITIVE_FILE,
  UNAUTHORIZED_FILE, OVERSIZED, EXTRA_PROSE, DUPLICATE, OVERLAPPING, MULTI_FILE
- generation_configuration_from_settings(): wires Settings → GenerationConfiguration
- generation_policy_from_settings(): wires Settings → GenerationPolicy
- analyze_migration_generation_vertical_slice(): real M1→M15 path
- Settings extended with ai_enabled, ai_provider_id, ai_provider_endpoint,
  ai_model_small, ai_model_medium, ai_model_strong, generation_timeout_seconds

NOT IMPLEMENTED
- Real production AI provider adapters (Anthropic, OpenAI, Vertex, etc.) —
  by design. Any provider implementing the GenerationProvider protocol works.
- Cost/latency tracking from live providers — deferred to real provider adapters
- Async provider invocation — deferred to M19

FILES CHANGED
backend/specimpact/ai_migration/__init__.py
backend/specimpact/ai_migration/models.py
backend/specimpact/ai_migration/generator.py
backend/specimpact/ai_migration/providers.py
backend/specimpact/ai_migration/vertical.py
backend/specimpact/ai_migration/README.md
backend/specimpact/config/settings.py   (ai_* fields)
tests/unit/test_m15_ai_migration.py
tests/integration/test_m15_ai_generation_vertical.py

INPUTS TESTED
- demo/payment_api_v1.yaml → demo/payment_api_v2.yaml (removal of request.amount)
- demo/ecommerce/ Python repository (payment_service.py, checkout.py)
- RouteChoice: SMALL, MEDIUM, STRONG, NO_AI, DETERMINISTIC, NO_FEASIBLE_STRATEGY
- GenerationConfiguration: ai_enabled=True and ai_enabled=False
- MigrationContext: None (missing context path)
- FakeProviderMode: all 12 adversarial modes
- Injected context item with "Ignore prior instructions" content

OUTPUTS VERIFIED
- GenerationStatus.GENERATED with ProposedMigrationPatch for AI routes
- GenerationStatus.NOT_REQUIRED for non-AI routes (no provider call made)
- GenerationStatus.AI_DISABLED when ai_enabled=False (no provider call made)
- GenerationStatus.INSUFFICIENT_CONTEXT when context=None
- GenerationStatus.MALFORMED_RESPONSE for malformed/oversized/extra-prose
- GenerationStatus.REFUSED for provider refusal
- GenerationStatus.PROVIDER_TIMEOUT for timeout error
- GenerationStatus.PROVIDER_UNAVAILABLE for unavailable error
- GenerationStatus.UNSAFE_OUTPUT for path traversal, sensitive file,
  unauthorized file, overlapping edits, precondition hash mismatch
- Duplicate edits correctly deduplicated to 1 edit with merged indexes (0,1)
- Multi-file patches: both files authorized, edits deterministically ordered
- Precondition hash mismatch returns UNSAFE_OUTPUT with code PRECONDITION_HASH_MISMATCH
- Prompt injection: system_instructions contain "untrusted data" warning;
  injected content preserved in context_items but not promoted to instructions
- Fingerprint stability: two identical runs produce identical canonical_json()
- Repository mutation test: before/after file contents identical — no files
  modified by analyze_migration_generation_vertical_slice()
- patch.edits[0].file == "payment_service.py" (real M1→M15 real evidence)
- patch.edits[0].replacement_text == "" (correct deterministic removal)
- patch.warnings contains "Candidate is unvalidated and was not applied to any repository."
- request.model_dump() does not contain "repository_root"

TESTS RUN
tests/unit/test_m15_ai_migration.py                  23 passed
tests/integration/test_m15_ai_generation_vertical.py  1 passed
Full suite (tests/)                                  167 passed, 1 skipped

REAL COMMANDS EXECUTED
python -m pytest tests/unit/test_m15_ai_migration.py -v
  → 23 passed in 5.55s

python -m pytest tests/integration/test_m15_ai_generation_vertical.py -v
  → 1 passed in 2.53s

python -m pytest tests/ -v --tb=short
  → 167 passed, 1 skipped in 42.80s

Platform: win32, Python 3.13.5, pytest-8.4.2

KNOWN LIMITATIONS
- No real AI provider adapter exists. The product requires a real provider
  implementing GenerationProvider to produce live AI-generated patches.
- DeterministicFakeProvider is the only included adapter — suitable for tests
  and local demonstrations only.
- Provider cost, usage tokens, and latency fields are not populated by the fake
  provider; real providers must not invent unavailable fields.
- Async invocation is not implemented — synchronous blocking call only.
- The 1 skipped test (test_binary_and_escaping_symlink_are_rejected) requires
  symlink creation, which is unavailable on Windows. This is a platform
  limitation, not a logic gap.

UNCERTAINTIES
- Real provider response latency and cost fields will vary by vendor and model
  and must be normalized without invention.
- Production security posture of the provider boundary (credentials, retries,
  rate limiting) remains to be hardened when a real adapter is introduced.

REGRESSION TESTS ADDED
- test_untrusted_provider_outcomes_are_normalized — parametrized over all 10
  adversarial failure modes
- test_prompt_and_openapi_injection_remain_context_data — validates injection
  labeling without suppressing the injected content
- test_repeatable_fake_generation_has_stable_fingerprint — determinism guarantee
- test_real_m1_to_m15_generates_unvalidated_candidate_without_repository_mutation

ARCHITECTURAL CHANGES
None. M15 extends the existing M14 MigrationContext and M13 RoutingDecision
contracts without modifying them. All new code is additive.

NEXT ALLOWED MILESTONE
M16 — Isolated Patch Validation
```
