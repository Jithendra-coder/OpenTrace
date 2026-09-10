# Milestone Execution Rules

Implement exactly one approved milestone. Before coding inspect the repository, rules, implementation and tests; confirm the boundary and prohibited future work. Then write/modify tests, run unit and relevant integration tests, execute the real CLI/API path, inspect real generated output, adversarially review it, fix defects, add practical regression tests, update documentation, and produce the report below. Do not declare completion without this evidence.

## Boundary enforcement

The roadmap names scope; the current milestone's subsystem specification, `07_INPUT_OUTPUT_CONTRACTS.md`, and `37_DEFINITION_OF_DONE.md` define the allowed artifacts and release evidence. A milestone may modify only its implementation, tests, fixtures and documentation necessary to produce those artifacts. It may not create a consumer of a future-stage artifact, a placeholder implementation for future work, or a technology reserved for a later milestone. If an earlier contract needs a field solely for a later consumer, record the need and defer it unless an ADR explicitly changes the boundary.

For example, M3 may introduce static Python repository discovery, AST parsing, import evidence, `CodeSymbol`, `APICallSite`, and their M3 test/documentation support. It must not implement API-change matching (M4), call graph/blast radius/risk (M5–M6), datasets/ML (M7–M9), migration/routing/AI/validation (M10–M18), jobs/storage/API (M19+), frontend (M22), or multi-repository analysis (M23).

```text
MILESTONE
STATUS

IMPLEMENTED

NOT IMPLEMENTED

FILES CHANGED

INPUTS TESTED

OUTPUTS VERIFIED

TESTS RUN

REAL COMMANDS EXECUTED

KNOWN LIMITATIONS

UNCERTAINTIES

REGRESSION TESTS ADDED

ARCHITECTURAL CHANGES

NEXT ALLOWED MILESTONE
```
