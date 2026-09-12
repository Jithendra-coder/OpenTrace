# Changelog

All notable changes to OpenTrace are documented here.

---

## [1.0.0] — 2026-08-27

### Initial Release — Production Platform

#### Added — Command-Line Interface (CLI)
- `opentrace analyze` — detect breaking API changes and identify affected code locations.
- `opentrace migrate` — synthesize migration patches using RouteForge adaptive strategy routing.
- `opentrace validate` — verify patches in an isolated subprocess sandbox workspace.
- `opentrace apply` — apply validated patches with an explicit developer confirmation gate and audit logging.
- `opentrace pr` — generate audited draft GitHub pull requests (`--dry-run` available; never auto-merges).
- `opentrace status` — display full `.opentrace/` workspace state with actionable next steps.
- All commands read and write `.opentrace/` JSON artifacts for deterministic pipeline chaining.
- Native UTF-8 terminal configuration for Windows environments.

#### Added — GitHub Integration Subsystem
- `opentrace.github.client` — GitHub REST API client using Python standard library (`urllib`).
- `opentrace.github.git` — Safe git subprocess helpers (branching, commits, pushes, and automated rollback).
- `opentrace.github.pr_template` — Pull request builder with complete validation audit trails.
- Pull requests are strictly created as `draft=True` to prevent accidental auto-merging.
- Automated rollback: restores files and removes local branches on failure.
- Audit persistence: records PR metadata with `never_auto_merged: true`.

#### Added — Sandbox Validation Subsystem
- `opentrace.validation.sandbox` — Ephemeral workspace manager with path-traversal safeguards.
- `opentrace.validation.runner` — Subprocess test runner with execution timeouts and sanitized error summaries.
- `opentrace.validation.validator` — End-to-end patch validation orchestrator.
- Zero host mutation during validation cycles.

#### Added — Adaptive Escalation & Feedback
- `opentrace.escalation.engine` — Finite, bounded retry logic escalating strategies (Small → Medium → Strong → Human).
- `opentrace.escalation.feedback` — Immutable, timestamped feedback recording for continuous evaluation.
- Feedback records remain strictly offline and audited.

#### Added — AI Migration & Candidate Generation
- `opentrace.ai_migration.generator` — Migration patch synthesis engine with pluggable provider support.
- Precondition validation ensuring edits match exact source lines before application.
- Safe AST syntax verification on all proposed edits.

#### Added — Bounded Migration Context
- `opentrace.migration_context` — Bounded, provenance-aware context selection.
- Strict token and character budgets (default 12,000 characters) preventing prompt bloat.
- Targeted extraction of affected call sites, AST symbols, and contract diffs.

#### Added — Single-Page Web Dashboard
- Zero-dependency web dashboard: HTML, Tailwind CSS, and vanilla JavaScript.
- 7 comprehensive views: Overview, Analyze, Migrate, Validate, Pull Requests, Feedback, Settings.
- Interactive SVG dependency graphs, diff viewers, and real-time status telemetry.
- Seamless FastAPI static file serving and REST API endpoints.

#### Added — RouteForge Strategy Engine
- Offline decision scenarios covering multiple mutation and repository families.
- Baseline policies: AlwaysSmall, AlwaysStrong, Random, RulePolicy, LogisticRegression, XGBoost.
- Cost- and risk-aware adaptive routing policies.

#### Added — Machine Learning & Evaluation
- Benchmark datasets combining synthetic, curated, and real-world API scenarios.
- Baseline ranking models: Logistic Regression, Random Forest, XGBoost.
- Rigorous held-out test evaluation with group-bootstrap confidence intervals.

#### Added — Core Analysis Pipeline
- OpenAPI 3.x contract parser and semantic normalizer.
- Breaking change detector covering schema mutations, route churn, and parameter restrictions.
- AST call-site extractor identifying direct HTTP client invocations (`requests`, `httpx`).
- Direct impact matcher with explainable scoring heuristics.
- Transitive call graph builder and blast radius propagation engine.

#### Test Coverage
- **220 automated tests passing (100% pass rate)**.
- Fast execution (~40–50 seconds across all unit and integration tests).

---

## Design Principles Upheld Throughout

- **No Auto-Merge** — PRs always draft, human confirms every apply
- **No Silent Failures** — every unsupported case is explicit `AI_REQUIRED` or `UNSUPPORTED`
- **No External Services in Tests** — `DeterministicFakeProvider`, subprocess only
- **No Whole-Repo-As-Context** — enforces hard character/file budgets
- **No Data Leakage** — TEST split sealed until formal evaluation
- **Audit Everything** — completion reports, feedback records, PR audit, governance rules
