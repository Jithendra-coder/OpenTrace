# Changelog

All notable changes to OpenTrace are documented here.

---

## [1.0.0-dev] — 2026-08-27

### First complete V1 — all milestones M0–M22 shipped.

#### Added — CLI
- `opentrace analyze` — detect breaking API changes and find affected code (M1→M6)
- `opentrace migrate` — generate a migration patch (M10→M15, RouteForge routing)
- `opentrace validate` — test the patch in an isolated subprocess sandbox (M16)
- `opentrace apply` — apply the patch with explicit confirmation gate + feedback record
- `opentrace pr` — create a draft GitHub PR (`--dry-run` available, never auto-merges)
- `opentrace status` — show full `.opentrace/` workspace state with next-step hint
- All commands read/write `.opentrace/` JSON artifacts for stateless pipeline chaining
- UTF-8 stdout fix for Windows terminals

#### Added — GitHub Integration (M21)
- `opentrace.github.client` — GitHub REST API via Python stdlib `urllib` (no external deps)
- `opentrace.github.git` — `subprocess` git helpers (find root, create branch, commit, push, rollback)
- `opentrace.github.pr_template` — PR title/body builder with full audit sections
- PR always created as `draft=True` — no auto-merge possible, enforced in code and audit record
- Error rollback: `restore_files` + `delete_local_branch` on any failure
- `.opentrace/pr-audit.json` with `never_auto_merged: true`

#### Added — Sandbox Validation (M16)
- `opentrace.validation.sandbox` — ephemeral workspace context manager, path-traversal guard
- `opentrace.validation.runner` — subprocess pytest, `_parse_counts()`, sanitized failure summary
- `opentrace.validation.validator` — `validate_patch()` orchestrator
- `opentrace.validation.vertical` — M1→M16 vertical slice

#### Added — Adaptive Escalation + Feedback (M17, M18)
- `opentrace.escalation.engine` — bounded retry (finite), SMALL→MEDIUM→STRONG escalation
- `opentrace.escalation.feedback` — `write_feedback_record()`, microsecond-timestamp filenames
- Feedback records: audit-only, never used for automatic online model updates

#### Added — AI Migration (M15)
- `opentrace.ai_migration.generator` — `MigrationGenerator`, `DeterministicFakeProvider`
- `ProposedMigrationPatch` with `ProposedFileEdit`, `expected_original_text`, precondition hashes
- `GenerationProvider` protocol for plugging in real AI providers

#### Added — Migration Context (M14)
- `opentrace.migration_context` — bounded, provenance-aware context selection
- Character/file-budget accounting, omissions, content hashes, deterministic manifest
- Never reads whole repository, never calls a provider

#### Added — Frontend Dashboard (M22)
- Zero-dependency SPA: HTML + Tailwind CDN + vanilla JS (no npm, no build step)
- 7 pages: Overview, Analyze, Migrate, Validate, Pull Requests, Feedback, Settings
- Live at `http://localhost:8000` via FastAPI `StaticFiles` mount
- Component library: badges, stat cards, diff viewer, checklist rows, empty states, toasts
- `/api/*` routes: workspace, analyze, migrate, validate, pr, feedback

#### Added — RouteForge (M11, M12, M13)
- M11 offline dataset: 9 migration decision groups, 45 strategy rows
- M12 baselines: AlwaysSmall, AlwaysStrong, Random, RulePolicy, LogisticRegression, XGBoost
- M13 learned router: checksummed JSON Logistic scorer, applicability gates, structured decisions

#### Added — ML Foundation (M7, M8, M9)
- M7 deterministic dataset: synthetic + curated adversarial + manually constructed scenarios
- M8 baselines: Heuristic, LR, RF, XGBoost — fit on TRAIN, evaluated on VALIDATION
- M9 formal held-out TEST evaluation, group-bootstrap uncertainty, Platt calibration attempt

#### Added — Core Analysis (M0–M6)
- M0: FastAPI shell, typed config, centralized logging, `GET /health`, `GET /version`
- M1: OpenAPI 3.x parser, canonical typed contract models, safe YAML loading
- M2: Breaking change detector — 8 rule types with compatibility classification
- M3: Python AST repository analyzer, `requests`/`httpx` call-site extraction
- M4: Direct API-change-to-call-site matcher with explainable evidence scoring
- M5: Static Python `CALLS` graph (NetworkX)
- M6: Blast radius propagation, heuristic risk bands

#### Test coverage
- **210 tests passing, 2 platform skips** (Windows symlink + no-.git-dir, both documented)
- Full test suite runs in ~40–54 seconds

---

## Design principles upheld throughout

- **No auto-merge** — PRs always draft, human confirms every apply
- **No silent failures** — every unsupported case is explicit `AI_REQUIRED` or `UNSUPPORTED`
- **No external services in tests** — `DeterministicFakeProvider`, subprocess only
- **No whole-repo-as-context** — M14 enforces hard character/file budgets
- **No data leakage** — TEST split sealed until M9 formal evaluation
- **Audit everything** — completion reports, feedback records, PR audit, governance rules
