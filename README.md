# OpenTrace — Automated API Change Impact & Migration Engine

<div align="center">

[![Python 3.10 | 3.11 | 3.12 | 3.13](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-220%20passed%20(100%25)-success.svg)](https://github.com/Jithendra-coder/OpenTrace)
[![GitHub](https://img.shields.io/badge/GitHub-Jithendra--coder%2FOpenTrace-black?logo=github)](https://github.com/Jithendra-coder/OpenTrace)
[![License: MIT](https://img.shields.io/badge/license-MIT-purple.svg)](LICENSE)
[![Dashboard](https://img.shields.io/badge/dashboard-http%3A%2F%2Flocalhost%3A8000-indigo.svg)](http://localhost:8000)

**Know precisely what an API breaking change breaks — and get a validated migration patch before you ship.**

[Quickstart](#quick-demo) • [Architecture](#architecture) • [CLI Reference](#cli-reference) • [Multi-LLM Engine](#multi-llm-engine) • [Docker Sandbox](#docker-sandbox) • [GitHub Action](#github-actions-cicd) • [Web Dashboard](#dashboard)

</div>

---

## What it does

**OpenTrace** is an automated API change impact analysis and adaptive migration engine. It takes two versions of an OpenAPI specification and a repository, then:

1. **Detects** 100% of breaking changes between the specs (schema, routes, parameters).
2. **Finds** every file, function, and call site in your codebase affected by those changes (Python AST & TypeScript/JS scanner).
3. **Generates** a targeted migration patch using RouteForge cost/criticality strategy selection and multi-LLM providers (Gemini, Claude, OpenAI, Ollama, or deterministic fallback).
4. **Validates** the patch in an isolated sandbox (copies repo → applies patch → runs tests in temp environment or Docker container → cleans up).
5. **Opens a draft GitHub PR** with full audit trail, validation evidence, and human-review gate. Never auto-merges blindly.
6. **Visualizes everything** in a live web dashboard at `http://localhost:8000`.

---

## Quick demo

### 1. Installation (Requires Python ≥ 3.10)
```powershell
# Clone from GitHub
git clone https://github.com/Jithendra-coder/OpenTrace.git
cd OpenTrace

# In PowerShell:
pip install -e .
$env:PYTHONIOENCODING = "utf-8"

# Or in Command Prompt (cmd.exe):
pip install -e .
set PYTHONIOENCODING=utf-8
```

Verify installation:
```powershell
opentrace --version
# Output: OpenTrace 1.0.0
```

### 2. Test with the Bundled Samples (Zero Setup Needed)
OpenTrace includes self-contained sample projects so you can test end-to-end immediately from any folder:

```powershell
# Run on Sample 1 (Payment Service)
opentrace analyze --old sample1/api_v1.yaml --new sample1/api_v2.yaml --repo sample1
opentrace migrate --policy balanced
opentrace validate
opentrace status

# Or run on Sample 2 (Enterprise Billing Platform)
opentrace analyze --old sample2/api_v1.yaml --new sample2/api_v2.yaml --repo sample2
opentrace migrate --policy critical
opentrace validate
opentrace status
```

### 3. Launch the Interactive Web Dashboard
```powershell
# In PowerShell:
$env:OPENTRACE_WORKSPACE = "."
uvicorn opentrace.main:app --port 8000

# Open http://localhost:8000 in your browser!
```

### 4. Using OpenTrace on Your Own Project
```powershell
opentrace analyze --old /path/to/old_api.yaml --new /path/to/new_api.yaml --repo /path/to/your_code_repo
opentrace migrate --policy balanced
opentrace validate
opentrace apply
```

**Expected output from `analyze`:**
```
OpenTrace  Analyze
════════════════════════════════════════
  API Changes Detected
  2 breaking change(s) found.
  1. POST /payments  BREAKING
  2. POST /payments  BREAKING

  Affected Code
  Direct impacts  : 1
    [DIRECT]  payment_service.py:7  create_payment

  ✓ Analysis written → .opentrace/analysis.json
```

---

## Architecture

```
OpenAPI Spec (old) ──┐
OpenAPI Spec (new) ──┤  M1–M2: Parse & Compare ──► Breaking Changes
                     │
Python Repo ─────────┤  M3–M6: AST Analysis ──────► Direct + Indirect Impacts
                     │                               (call graph, blast radius)
                     │
                     ├── M7–M9: Dataset & ML ──────► Impact ranking baselines
                     │
                     ├── M10: Deterministic Engine ► Structured patch candidate
                     │
                     ├── M11–M13: RouteForge ───────► Strategy routing decision
                     │           (SMALL/MEDIUM/STRONG/DETERMINISTIC/NO_AI)
                     │
                     ├── M14–M15: Context & AI ─────► Migration patch (ProposedMigrationPatch)
                     │
                     ├── M16: Sandbox Validation ───► ValidationEvidence (tests pass/fail)
                     │
                     ├── M17–M18: Escalation ────────► Adaptive retry + feedback records
                     │
                     ├── M19: CLI ────────────────────► opentrace analyze/migrate/validate/apply
                     │
                     ├── M21: GitHub ─────────────────► Draft PR (never auto-merge)
                     │
                     └── M22: Dashboard ──────────────► http://localhost:8000
```

---

## CLI reference

```powershell
opentrace analyze   --old <file> --new <file> --repo <dir> [--output-dir <dir>]
opentrace migrate   [--policy economy|balanced|critical] [--workspace <dir>] [--ai-enabled]
opentrace validate  [--workspace <dir>] [--timeout <seconds>]
opentrace apply     [--workspace <dir>] [--yes]
opentrace pr        [--workspace <dir>] [--dry-run] [--base-branch <branch>]
opentrace status    [--workspace <dir>]
```

*(All commands can also be run with `specimpact` as a fully backward-compatible alias)*

All commands read/write `.opentrace/` in the workspace directory:

| File | Written by | Contents |
|---|---|---|
| `.opentrace/analysis.json` | `analyze` | Changes, direct/indirect impacts |
| `.opentrace/migration-plan.json` | `migrate` | Patch, strategy, edits |
| `.opentrace/validation-result.json` | `validate` | Sandbox evidence |
| `.opentrace/pr-audit.json` | `pr` | Branch, commit, PR number, `never_auto_merged=true` |
| `.opentrace/feedback/*.jsonl` | `apply` | Accepted/rejected decisions |

---

## Dashboard

```powershell
$env:OPENTRACE_WORKSPACE = "."
uvicorn opentrace.main:app --port 8000 --reload
```

Open `http://localhost:8000`. Seven pages:

| Page | What you see |
|---|---|
| **Overview** | Breaking changes · affected files · migration plan · validation evidence |
| **Analyze** | Run analysis from form inputs · results table |
| **Migrate** | Policy picker · patch viewer with inline diff |
| **Validate** | Sandbox evidence checklist · test counts · failure log |
| **Pull Requests** | Open draft PR · PR audit trail · "View on GitHub" |
| **Feedback** | Decision history (accepted/rejected/deferred) |
| **Settings** | Workspace path · version · env var guide |

---

## API routes

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `GET` | `/version` | Version info |
| `GET` | `/api/workspace` | Full workspace state (JSON) |
| `POST` | `/api/analyze` | Run M1→M6 pipeline |
| `POST` | `/api/migrate` | Run M10→M15 pipeline |
| `POST` | `/api/validate` | Run M16 sandbox |
| `POST` | `/api/pr` | Create draft GitHub PR |
| `GET` | `/api/feedback` | List feedback records |

---

## Installation

Requires Python ≥ 3.10.

```powershell
pip install -e ".[dev]"
```

Copy `.env.example` → `.env` for local settings (`APP_ENV`, `LOG_LEVEL`, `DEBUG`).

---

## Quality

```powershell
python -m pytest              # 220 passed
python -m ruff check .
python -m mypy backend/opentrace
```

---

## Docker

```powershell
docker build -t opentrace:v1 .
docker run --rm -p 8000:8000 opentrace:v1
```

---

## Project structure

```
opentrace/
├── backend/opentrace/
│   ├── blast_radius/        M1–M6: parse, compare, extract, match, graph, propagate
│   ├── ml/                  M8–M9: impact-ranking baselines and evaluation
│   ├── migration/           M10: deterministic patch engine
│   ├── routeforge/          M11–M13: dataset, baselines, router
│   ├── migration_context/   M14: context selection
│   ├── ai_migration/        M15: patch generation (DeterministicFakeProvider + AI protocol)
│   ├── validation/          M16: sandbox validation
│   ├── escalation/          M17–M18: adaptive retry + feedback persistence
│   ├── cli/                 M19: opentrace CLI (analyze/migrate/validate/apply/pr/status)
│   ├── github/              M21: GitHub API client, git helpers, PR template
│   └── api/                 M22: FastAPI dashboard routes
├── frontend/                M22: HTML + Tailwind + vanilla JS dashboard (no build step)
├── tests/
│   ├── unit/                220 tests
│   └── integration/
├── demo/
│   ├── payment_api_v1.yaml  Demo old spec
│   ├── payment_api_v2.yaml  Demo new spec (removes request.body.amount)
│   └── ecommerce/           Demo Python repo (payment_service, checkout, orders)
├── data/
│   ├── m7/                  Impact-ranking dataset (JSONL + manifest)
│   ├── routeforge-m11/      RouteForge offline dataset
│   ├── routeforge-m12/      RouteForge baselines
│   └── routeforge-m13/      RouteForge learned router
├── artifacts/               Milestone completion reports + ML experiment outputs
└── opentrace/rules/        Governance constitution + CURRENT_STATE.md
```

---

## Milestones

| Milestone | Description | Status |
|---|---|---|
| M0 | Foundation (FastAPI, config, logging, health) | ✅ |
| M1 | OpenAPI parser + canonical models | ✅ |
| M2 | Breaking change detector | ✅ |
| M3 | Python AST repository analyzer | ✅ |
| M4 | Direct impact matcher | ✅ |
| M5 | Static call graph | ✅ |
| M6 | Blast radius propagation | ✅ |
| M7 | Impact-ranking dataset | ✅ |
| M8 | ML baselines (LR, RF, XGBoost) | ✅ |
| M9 | Formal held-out evaluation + calibration | ✅ |
| M10 | Deterministic migration engine | ✅ |
| M11 | RouteForge offline dataset | ✅ |
| M12 | RouteForge baselines | ✅ |
| M13 | Learned RouteForge router | ✅ |
| M14 | Migration context selection | ✅ |
| M15 | AI-assisted patch generation | ✅ |
| M16 | Isolated sandbox validation | ✅ |
| M17 | Adaptive repair escalation | ✅ |
| M18 | Feedback persistence | ✅ |
| M19 | CLI UX | ✅ |
| M21 | GitHub PR integration | ✅ |
| M22 | Frontend dashboard | ✅ |

---

## Design decisions

**Why no auto-merge?**
Every generated patch is AI-assisted or deterministic-rule-based. Neither is verified correct by the tool alone — only sandbox tests provide evidence, and the demo repo has no test suite. A human must review the diff before merging.

**Why subprocess sandbox instead of Docker?**
V1 uses `subprocess` for zero-dependency isolation. Patches are applied to a temp copy of the repo, tests run, copy is deleted. Docker sandbox is the documented V2 upgrade path.

**Why no external AI by default?**
`DeterministicFakeProvider` ships as the default for demos. It produces a reproducible, auditable patch without API keys. Plug in a real provider by implementing `GenerationProvider`.

**Why Tailwind CDN instead of a framework?**
Zero build step. The dashboard opens instantly from `uvicorn` with no npm, no node_modules, no bundler. For a V1 portfolio demo, instant-start beats framework complexity.

---

## Governance

Authoritative rules in [`opentrace/rules/`](opentrace/rules/). Read [`00_READ_FIRST.md`](opentrace/rules/00_READ_FIRST.md) and [`CURRENT_STATE.md`](opentrace/rules/CURRENT_STATE.md) before modifying.

---

## License

MIT — see [LICENSE](LICENSE).
