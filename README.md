# OpenTrace — Automated API Change Impact & Migration Engine

<div align="center">

[![Python 3.10 | 3.11 | 3.12 | 3.13](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-220%20passed%20(100%25)-success.svg)](https://github.com/Jithendra-coder/OpenTrace)
[![GitHub](https://img.shields.io/badge/GitHub-Jithendra--coder%2FOpenTrace-black?logo=github)](https://github.com/Jithendra-coder/OpenTrace)
[![License: MIT](https://img.shields.io/badge/license-MIT-purple.svg)](LICENSE)
[![UI: Dashboard](https://img.shields.io/badge/UI-Single--Page%20Dashboard-black.svg)](#interactive-dashboard)

**Know precisely what an API breaking change breaks — and get a validated migration patch before you ship.**

[Quickstart](#quick-demo) • [Architecture](#architecture) • [CLI Reference](#cli-reference) • [RouteForge Engine](#routeforge-engine) • [Sandbox Validation](#sandbox-validation) • [GitHub Action](#github-actions-cicd) • [Web Dashboard](#dashboard)

</div>

---

## Overview

**OpenTrace** is a high-performance developer platform engineered by **Jithendra** ([@Jithendra-coder](https://github.com/Jithendra-coder)) for automated API change impact analysis and adaptive code migration. When upstream OpenAPI contracts evolve, downstream services and repositories break silently. OpenTrace eliminates this problem by analyzing contract diffs and propagating them directly into application source code:

1. **Detects** 100% of breaking changes between OpenAPI specifications (schema removals, route mutations, parameter churn).
2. **Traces** affected files, functions, and call sites across codebases using Python AST parsing and modern TypeScript/JavaScript scanners.
3. **Synthesizes** targeted migration patches using the **RouteForge** adaptive strategy selection engine (Economy, Balanced, Critical).
4. **Validates** patches inside an isolated ephemeral sandbox (copies repo → applies patch → executes regression tests → verifies syntax → cleans up).
5. **Opens an audited draft GitHub PR** with complete validation evidence, never auto-merging without developer review.
6. **Visualizes the full impact surface** in an interactive single-page web dashboard with dynamic call graph telemetry.

---

## Quick Demo

### 1. Installation (Requires Python ≥ 3.10)

```powershell
# Clone the repository
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

OpenTrace includes self-contained sample projects to test end-to-end immediately from any environment:

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
$env:OPENTRACE_WORKSPACE = "."
uvicorn opentrace.main:app --port 8000
```

### 4. Running OpenTrace on Your Own Repository

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
  1. POST /payments  BREAKING (field removed)
  2. POST /payments  BREAKING (type mutation)

  Affected Code
  Direct impacts  : 1
    [DIRECT]  payment_service.py:7  create_payment

  ✓ Analysis written → .opentrace/analysis.json
```

---

## Architecture

```
OpenAPI Spec (old) ──┐
OpenAPI Spec (new) ──┤  Contract Comparison ──────► Breaking Changes Detection
                     │
Source Repository ───┤  AST Static Analysis ──────► Direct + Transitive Impacts
                     │                              (Call Graph, Blast Radius)
                     │
                     ├── Risk & Impact Baselines ─► Probabilistic Impact Scoring
                     │
                     ├── AST Migration Engine ────► Deterministic Patch Synthesis
                     │
                     ├── RouteForge Strategy ─────► Adaptive Policy Decision
                     │                              (Economy, Balanced, Critical)
                     │
                     ├── Patch Synthesis ─────────► Bounded Code Transformations
                     │
                     ├── Ephemeral Sandbox ───────► Test Suite Verification & Proof
                     │
                     ├── Escalation System ───────► Adaptive Feedback Persistence
                     │
                     ├── High-Speed CLI ──────────► opentrace CLI Core Commands
                     │
                     ├── GitHub Automation ───────► Audited Draft Pull Request
                     │
                     └── Web Dashboard ───────────► Real-Time System Telemetry
```

---

## CLI Reference & Commands

OpenTrace can be invoked via the `opentrace` binary or directly via Python with `python -m opentrace.cli.main` (aliases: `specimpact`, `changemesh`).

### 1. Command Syntax & Options

| Command | Key Arguments | Purpose |
|---|---|---|
| `analyze` | `--old <file> --new <file> --repo <dir> [--output-dir <dir>]` | Compares OpenAPI specs and recursively scans all repository folders for affected code. |
| `migrate` | `[--policy economy\|balanced\|critical] [--workspace <dir>] [--ai-enabled]` | Synthesizes an AST migration patch using the RouteForge decision engine. |
| `validate` | `[--workspace <dir>] [--timeout <seconds>]` | Applies patch inside an isolated sandbox and runs test verification. |
| `apply` | `[--workspace <dir>] [--yes]` | Applies validated patches directly to source files on disk. |
| `status` | `[--workspace <dir>]` | Shows current workspace state, analysis results, and migration status. |
| `pr` | `[--workspace <dir>] [--dry-run] [--base-branch <branch>]` | Creates a verified draft GitHub Pull Request with audit evidence. |

---

### 2. Copy-Pasteable Commands by Environment

#### Windows Command Prompt (`cmd.exe`)
```cmd
:: 1. Analyze (recursively scans all subfolders in the repo)
python -m opentrace.cli.main analyze --old path\to\old_api.json --new path\to\new_api.json --repo path\to\repo

:: 2. Generate migration plan
python -m opentrace.cli.main migrate --policy balanced

:: 3. Test patch in isolated sandbox
python -m opentrace.cli.main validate

:: 4. View workspace status
python -m opentrace.cli.main status

:: 5. Apply verified patch to codebase
python -m opentrace.cli.main apply --yes
```

#### Windows PowerShell
```powershell
# 1. Analyze
opentrace analyze --old "path/to/old_api.json" --new "path/to/new_api.json" --repo "path/to/repo"

# 2. Migrate
opentrace migrate --policy balanced

# 3. Validate in sandbox
opentrace validate

# 4. Status
opentrace status

# 5. Apply patch
opentrace apply --yes
```

#### Linux / macOS (Bash / Zsh)
```bash
# 1. Analyze
opentrace analyze --old path/to/old_api.json --new path/to/new_api.json --repo path/to/repo

# 2. Migrate
opentrace migrate --policy balanced

# 3. Validate in sandbox
opentrace validate

# 4. Status
opentrace status

# 5. Apply patch
opentrace apply --yes
```

---

## Tracing Large Multi-Folder Codebases & Blast Radius

**OpenTrace is specifically engineered to analyze large, multi-folder projects, microservices, and monorepos.** It does not just check a single file; it traverses the entire directory tree:

```text
my_large_enterprise_repo/
├── services/
│   ├── payment/
│   │   └── client.py          ◄── [DIRECT IMPACT] (Makes HTTP call: POST /payments)
│   └── billing/
│       └── processor.py
├── controllers/
│   └── checkout.py            ◄── [INDIRECT IMPACT: Distance 1] (Imports & calls payment client)
├── routes/
│   └── orders.py              ◄── [INDIRECT IMPACT: Distance 2] (Calls checkout controller)
└── utils/
    └── http_helpers.py
```

### How It Works Across Multiple Folders:

1. **Recursive Folder Scanning**: When you pass `--repo ./my_large_enterprise_repo`, OpenTrace recursively inspects every `.py` file across all nested directories, packages, and subfolders.
2. **Cross-Module Call Graph Construction**: It parses Python ASTs across all files to build a global **Static Call Graph**, connecting imports (`from services.payment.client import create_payment`) to caller functions.
3. **Transitive Blast Radius Resolution**:
   - **Direct Impact (`distance: 0`)**: The exact file, function, line, and column making the HTTP call matching the changed route.
   - **Indirect Impact (`distance: 1, 2, ...`)**: Upstream functions in other folders that invoke the affected caller or consume its returned response objects.
4. **Risk Ranking**: Prioritizes affected areas across the whole project by certainty, call graph distance, and breaking severity so teams know exactly what to test first.

All state is recorded cleanly in the `.opentrace/` workspace folder:

| Artifact File | Generated By | Purpose |
|---|---|---|
| `.opentrace/analysis.json` | `analyze` | Contract changes, direct impact sites, and indirect dependency graph |
| `.opentrace/migration-plan.json` | `migrate` | Concrete AST edits, RouteForge strategy, and patch diff |
| `.opentrace/validation-result.json` | `validate` | Sandbox test results, execution durations, and syntax checks |
| `.opentrace/pr-audit.json` | `pr` | Branch reference, commit hash, PR link, and safety gate verification |
| `.opentrace/feedback/*.jsonl` | `apply` | Developer feedback history (ACCEPTED, REJECTED, DEFERRED) |

---

## Interactive Dashboard

OpenTrace includes a zero-build, responsive web dashboard built with Tailwind CSS and modern vanilla JavaScript:

```powershell
$env:OPENTRACE_WORKSPACE = "."
uvicorn opentrace.main:app --port 8000
```

Launch the dashboard locally via Uvicorn to access all interactive tools:

| Module | Features & Capabilities |
|---|---|
| **Overview** | High-level telemetry, breaking changes summary, files affected, and interactive SVG Call Graph |
| **Analyze** | Interactive OpenAPI comparison with file browser and 1-click demo loaders |
| **Migrate** | RouteForge policy selection (Economy, Balanced, Critical) and unified diff viewer |
| **Validate** | Real-time sandbox test verification with test counts and isolated runtime logs |
| **Pull Requests** | One-click draft PR creation with full audit trail and GitHub links |
| **Feedback** | History of accepted, rejected, or deferred patches |
| **Settings** | Workspace directory settings, version information, and configuration guides |

---

## RouteForge Engine

RouteForge is the deterministic decision engine inside OpenTrace that selects optimal migration strategies based on risk, scope, and test coverage:

- **Economy Policy**: Minimizes code modification scope, applying only bounded, zero-risk structural AST transformations.
- **Balanced Policy** *(Default)*: Balances thoroughness with verification, generating clean caller updates verified against unit test suites.
- **Critical Policy**: Maximizes defensive safety, generating comprehensive adapters with validation guards and fallback protections.

---

## Sandbox Validation

Before any patch touches the host repository, OpenTrace verifies it in an isolated ephemeral filesystem sandbox:
1. Creates a clean, temporary duplicate of the target repository.
2. Applies the synthesized unified diff in memory.
3. Compiles the abstract syntax tree to confirm zero syntax errors.
4. Executes the repository's test suite (e.g. `pytest`) inside the isolated sandbox.
5. Captures test pass/fail metrics and execution duration.
6. Cleans up all temporary workspaces, ensuring **zero mutations to the host filesystem**.

---

## Quality & Test Suite

The OpenTrace test suite contains 220 automated unit and integration tests covering the entire pipeline:

```powershell
# Run the complete test suite
pytest -v

# Run unit tests only (180 tests)
pytest tests/unit/ -q

# Run integration tests only (40 tests)
pytest tests/integration/ -q
```

---

## Repository Structure

```
OpenTrace/
├── backend/opentrace/       Core Python package
│   ├── blast_radius/        OpenAPI parser, diff engine, call graph, blast radius
│   ├── code_analysis/       Python AST parser, TypeScript/JS scanner, HTTP call sites
│   ├── contracts/           Canonical OpenAPI schema models and normalizer
│   ├── ml/                  Impact-ranking baselines and evaluation
│   ├── migration/           Deterministic AST patch engine
│   ├── routeforge/          Dataset generator, baselines, and learned router
│   ├── migration_context/   AST context selection
│   ├── ai_migration/        Patch synthesis protocols and provider adapters
│   ├── validation/          Ephemeral sandbox runner & Docker isolation
│   ├── escalation/          Adaptive repair escalation & feedback persistence
│   ├── cli/                 opentrace CLI (analyze/migrate/validate/apply/pr/status)
│   ├── github/              GitHub API integration, git commands, PR templates
│   └── api/                 FastAPI dashboard endpoints
├── frontend/                Noir single-page dashboard (HTML + Tailwind + Vanilla JS)
├── tests/                   Complete 220-test automated suite
│   ├── unit/                180 unit tests
│   └── integration/         40 integration tests
├── sample1/                 Payment Service sample API & caller service
├── sample2/                 Billing Platform sample API & caller service
├── demo/                    E-commerce demo microservices
├── demo.ps1                 One-command PowerShell demo script
├── Dockerfile               Production container definition
├── docker-compose.yml       Docker Compose service configuration
└── pyproject.toml           Package configuration and CLI entry points
```

---

## Author & Engineering

OpenTrace was conceptualized, designed, and developed by **Jithendra** ([@Jithendra-coder](https://github.com/Jithendra-coder)).

- **GitHub**: [https://github.com/Jithendra-coder/OpenTrace](https://github.com/Jithendra-coder/OpenTrace)
- **License**: MIT License — see [LICENSE](LICENSE) for details.
