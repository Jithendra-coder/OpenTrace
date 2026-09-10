# Test Strategy

Four layers: unit tests for deterministic units; integration tests for contract boundaries and parser/analyzer composition; adversarial tests from `30_ADVERSARIAL_TEST_PLAN.md`; and end-to-end tests of allowed vertical slices. Test fixtures are small, provenance-safe, deterministic and do not hardcode expected product display behavior beyond asserted analysis facts.

Release-blocking E2E eventually covers OpenAPI v1 + v2 + Python demo repository → breaking change → genuinely affected Python function, while proving unrelated code remains unaffected. Every discovered practical defect gets a regression test. ML tests include split/leakage and reproducibility checks; validation tests must never execute untrusted code on host.

Milestone release blockers: M2 proves compatible optional additions are not breaking; M3 proves comments/docstrings/unrelated strings create no HTTP call sites; M4 identifies an actually affected function and excludes an unrelated file; M6 derives transitive paths from the graph; M9 evaluates held-out scenarios; M13 compares learned routing against required baselines; M16 runs validation in the documented isolated environment; M17 escalates with failure evidence; and M21 requires human review for generated PRs. Mocks may isolate dependencies but cannot substitute for the milestone’s required real CLI/API vertical slice.
