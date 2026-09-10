```
MILESTONE
M16 — Isolated Patch Validation

STATUS
COMPLETE

IMPLEMENTED
- SandboxConfig (pydantic, frozen): configurable timeout_seconds (5–300),
  max_failure_summary_lines, max_failure_summary_line_chars
- ValidationStatus enum: TESTS_PASSED, TESTS_FAILED, NO_TESTS_COLLECTED,
  PATCH_FAILED, SYNTAX_ERROR, TIMEOUT, RUNNER_ERROR, SANDBOX_ERROR
- ValidationEvidence (pydantic, frozen, canonical_json): full spec output
  contract — patch_applied, syntax_ok, tests_collected, tests_passed,
  tests_failed, timeout, exit_code, failure_summary — plus audit fields:
  schema_version, patch_id, workspace_created, workspace_cleaned,
  workspace_path_hint (8-char suffix only), duration_ms, limitations
- SandboxWorkspace (context manager): ephemeral temp directory, full
  shutil.copytree of repository, guaranteed cleanup in __exit__ even on error,
  cleanup verification via filesystem check
- Patch application safety:
    • Path traversal rejection (.. sequences and absolute paths)
    • Sensitive file name rejection (.env, credentials, id_rsa, etc.)
    • Sensitive path component rejection (.aws, .git, .ssh, secrets, etc.)
    • Sensitive suffix rejection (.key, .pem, .p12, .pfx)
    • Sandbox escape check (resolved path must stay inside workspace/repo)
    • Missing file detection
    • Original text precondition check (expected_original_text must appear)
- Syntax validation: ast.parse on each edited .py file post-application;
  reports syntax_failure_file on first error
- subprocess pytest runner with configurable wall-clock timeout; captures
  stdout+stderr; parses pass/fail/error counts from pytest summary line;
  sanitizes failure_summary (redacts TOKEN/SECRET/PASSWORD/KEY lines);
  truncates to configured line/char limits
- validate_patch() orchestrator: single call from patch + repo path → evidence
- analyze_and_validate_vertical_slice(): real M1→M16 path; generation +
  sandbox validation; non-AI routes return (result, None)
- Documented limitation in every ValidationEvidence.limitations: subprocess
  isolation in temp directory — not Docker-isolated, not suitable for untrusted
  code without container boundary

NOT IMPLEMENTED
- Docker container isolation — documented as known V1 limitation.
  Subprocess + temp directory is the V1 boundary. Docker is deferred.
- CPU/memory/PID limits — OS-level limits deferred to Docker milestone.
- Network restriction — not enforced in subprocess mode.
- Dependency installation inside sandbox — deferred; sandbox uses
  the host environment's installed packages.

FILES CHANGED (new)
backend/specimpact/validation/__init__.py
backend/specimpact/validation/models.py
backend/specimpact/validation/sandbox.py
backend/specimpact/validation/runner.py
backend/specimpact/validation/validator.py
backend/specimpact/validation/vertical.py
tests/unit/test_m16_validation.py
tests/integration/test_m16_validation_vertical.py

INPUTS TESTED
- demo/ecommerce/payment_service.py with valid patch (remove "amount" field)
- Patch with missing original text → PATCH_FAILED
- Patch targeting path traversal path (../../outside.py) → PATCH_FAILED
- Patch targeting nonexistent file → PATCH_FAILED
- Patch that introduces a SyntaxError → SYNTAX_ERROR
- No-AI routing decision → generation NOT_REQUIRED → evidence None
- Real M1→M16 vertical slice via analyze_and_validate_vertical_slice()
- demo/ecommerce/ repository contents before/after validation

OUTPUTS VERIFIED
- ValidationStatus.PATCH_FAILED for missing text, traversal, nonexistent file
- ValidationStatus.SYNTAX_ERROR with syntax_failure_file populated
- patch_applied=True when patch applies correctly
- syntax_ok=True when all edited files parse cleanly
- workspace_created=True, workspace_cleaned=True for all runs
- workspace_path_hint is 8-char string (not full temp path)
- duration_ms is non-negative integer
- schema_version == "validation-evidence-v1"
- limitations tuple contains "subprocess" and "docker" references
- Source repository bytes identical before and after every validation run
- Non-AI route: generation_result.status==NOT_REQUIRED, evidence==None
- Real M1→M16 path: evidence.patch_applied==True, workspace_cleaned==True

TESTS RUN
tests/unit/test_m16_validation.py                 10 passed
tests/integration/test_m16_validation_vertical.py  2 passed
Full suite (tests/)                              179 passed, 1 skipped

REAL COMMANDS EXECUTED
python -m pytest tests/unit/test_m16_validation.py \
  tests/integration/test_m16_validation_vertical.py -v --tb=short
  → 12 passed in 8.52s

python -m pytest tests/ -v --tb=short -q
  → 179 passed, 1 skipped in 23.29s

Platform: win32, Python 3.13.5, pytest-8.4.2

KNOWN LIMITATIONS
- Subprocess + temp directory: not Docker-isolated. Arbitrary repository code
  runs in the host Python environment. Do not use with untrusted repositories
  without a container boundary. Documented in every ValidationEvidence.
- Sandbox uses host-installed packages. If the repository under test requires
  packages not installed in the host environment, tests will fail with import
  errors (RUNNER_ERROR).
- CPU, memory, PID limits not enforced. Only wall-clock timeout is bounded.
- Network not restricted inside subprocess.
- 1 skipped test: symlink test in test_m14_context_selection.py —
  Windows platform limitation, not M16.

UNCERTAINTIES
- Pytest output format changes across versions could break _parse_counts().
  Tested against pytest-8.4.2 only.
- Very large repositories may be slow to copy into temp workspace.

REGRESSION TESTS ADDED
- test_source_repository_is_not_mutated_after_validation — M16 isolation contract
- test_path_traversal_in_edit_returns_patch_failed — safety regression
- test_syntax_error_patch_returns_syntax_error_status — syntax guard regression
- test_real_m1_to_m16_generates_and_validates_without_source_mutation —
  end-to-end regression

ARCHITECTURAL CHANGES
None. validation/ is a new leaf module. It depends on ai_migration.models
(ProposedMigrationPatch) and is not depended on by any existing module.

NEXT ALLOWED MILESTONE
M17 — Adaptive Repair Escalation
```
