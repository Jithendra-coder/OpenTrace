# OpenTrace — Complete Architectural & Operational Guide
> **API Change Intelligence & Automated Migration Engine**  
> *Detect. Trace. Fix. Verify.*

---

## 1. Executive Summary & Core Purpose
**OpenTrace** is an enterprise-grade developer infrastructure platform engineered to eliminate API contract breakage across complex software ecosystems. Modern microservices and distributed applications break when upstream OpenAPI contracts change. OpenTrace detects semantic diffs in OpenAPI specifications, traces their direct and transitive ripple impacts through repository source code using static AST analysis and call-graph blast-radius algorithms, synthesizes precise remediation patches using RouteForge ML strategies, validates patches in isolated sandboxes, and automatically opens draft GitHub pull requests.

---

## 2. The Core Pipeline Workflow

`	ext
  ┌───────────────────────┐
  │  OpenAPI v1 vs v2    │
  └──────────┬────────────┘
             │
             ▼
   [M1→M3: Semantic Diff]  ─── Detects breaking property/endpoint removals
             │
             ▼
  [M4→M6: AST Call Graph]  ─── Traces direct HTTP calls & callers through repo
             │
             ▼
   [M10→M14: RouteForge]   ─── Evaluates risk policy (Economy, Balanced, Critical)
             │                 and routes to SMALL, MEDIUM, STRONG, or HUMAN strategy
             ▼
   [M15: Patch Synthesizer]─── Generates unified multi-file unified diff
             │
             ▼
   [M16: Sandbox Runner]   ─── Creates isolated environment, applies patch,
             │                 and runs test suite (zero host side-effects)
             ▼
   [M21: GitHub Automation]─── Creates branch opentrace/migration-{id}
                               and draft PR with full audit trail
`

---

## 3. Brand Identity & The Noir Design System

### The Official API Gear + Plug Logo
The OpenTrace emblem depicts an industrial **10-tooth precision gear** enclosing a **concentric circuit trace** with two **interlocking electrical/API plugs** connecting at the center through orbiting signal wires. It communicates:
- **API & Systems**: Mechanical reliability, contract standardization.
- **Trace & Connectivity**: Direct mapping between API endpoints and dependent application code.
- **Precision**: Clean monochrome outline aesthetics.

### The Noir Color System
The UI adheres to a strict, developer-first monochrome foundation:
- **Primary Black**: #000000 (Brand black, headers, primary buttons, active anchors).
- **Secondary Slate**: #71717A (Muted labels, secondary indicators).
- **Surfaces**:
  - Main Canvas: #FFFFFF
  - Elevated Cards & Sheets: #FAFAFA
  - Action / Selection Pills: #F4F4F5
  - Dividers & Borders: #E4E4E7
  - Terminal & Code Viewers: #0B0F14
- **Restrained Semantic Status Colors**:
  - Breaking Changes / Errors: #EF4444
  - Affected Files / Warnings: #F59E0B
  - Tests Passed / Success: #10B981
  - Information: #3B82F6

---

## 4. The 4 Overview Metric Cards
The OpenTrace Overview dashboard features four equal-height metric cards engineered with distinct top-accent indicators:

| Metric Card | Accent Color | Hex | Purpose |
| :--- | :--- | :--- | :--- |
| **Breaking Changes** | Red | #EF4444 | Total breaking API contract diffs detected |
| **Files Affected** | Amber / Orange | #F59E0B | Count of direct code call-sites and indirect dependencies |
| **Validation** | Slate / Noir | #18181B | Real-time sandbox test verification (TESTS_PASSED) |
| **Open PRs / Scope** | Dark Slate | #18181B | Active pull request status and migration branch tracking |

---

## 5. Command-Line Interface (CLI) Guide

OpenTrace provides a high-performance CLI with automatic fallback support for all previously configured environments.

### Installation
`ash
# In the repository root
pip install -e .
`

### Core Commands
`ash
# 1. Analyze an API change
opentrace analyze --old-spec api/v1.yaml --new-spec api/v2.yaml --repo ./src

# 2. Generate a migration plan
opentrace migrate --policy balanced

# 3. Validate the patch in an isolated sandbox
opentrace validate

# 4. Check workspace status
opentrace status

# 5. Apply the validated patch directly to the working tree
opentrace apply --yes

# 6. Open a GitHub Draft Pull Request
opentrace pr --workspace .opentrace
`

*(Note: changemesh and specimpact are registered as fully functional backward-compatible command aliases).*

---

## 6. Web Dashboard Features

OpenTrace serves an interactive single-page dashboard at http://127.0.0.1:8000:

1. **Dashboard Overview**:
   - 4 Metric cards with live telemetry.
   - Interactive SVG Call Graph showing root API endpoint, direct impact nodes, and indirect ripple nodes.
   - Breakdown tables for breaking changes and affected files.
2. **Analyze Screen**:
   - File and directory browser for Old Spec, New Spec, and Target Repository.
   - 1-click **Load Demo Specs** button for instant end-to-end evaluation.
3. **Migrate Screen**:
   - Interactive RouteForge policy selection (Economy, Balanced, Critical).
   - Strategy selection breakdown: SMALL, MEDIUM, STRONG, HUMAN.
   - Unified Git-style diff viewer with additions and deletions highlighted.
4. **Validate Screen**:
   - Isolated sandbox environment runner.
   - Test execution logs, duration benchmarking, and AST syntax verification.
5. **API Simulator**:
   - Pre-loaded microservices (Payments, Billing, Users, Checkout).
   - Zero-typing contract mutation toggle with instant visual ripple graph update.
6. **Multi-Environment CLI Auto-Installer**:
   - 1-Click direct configuration across all detected Python installations on the host system.
   - Fast 0.13s importlib spec probe ensuring 100% detection rate without timeouts.
   - Downloadable .bat and .ps1 standalone installers.