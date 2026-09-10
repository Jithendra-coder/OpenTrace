```
MILESTONE
M22 — Frontend Dashboard

STATUS
COMPLETE

IMPLEMENTED

Dashboard served at: http://localhost:8000
Stack: HTML + Tailwind CSS CDN + vanilla JS (no build step, no npm)
Backend: FastAPI /api/* routes (dashboard.py)

PAGES
  Overview     — 4 stat cards + API changes table + migration plan + validation
                 evidence panel + quick action buttons
  Analyze      — old/new spec + repo form, run pipeline, results table + file tree
  Migrate      — Economy/Balanced/Critical policy picker, patch table with diff viewer
  Validate     — sandbox evidence checklist, failure code block, status badge
  Pull Requests — token input (per-request only), dry-run toggle, draft PR, audit trail
  Feedback     — feedback records table with timestamp/strategy/decision
  Settings     — workspace path, version, env var guide

DESIGN SYSTEM
  Font        : Inter (Google Fonts) + JetBrains Mono for code
  Sidebar     : #0F172A slate-900 (dark navy)
  Backgrounds : #F8FAFC page, #FFFFFF cards
  Borders     : #E2E8F0 1px
  Shadows     : 0 1px 3px rgba(15,23,42,0.04) (barely visible)
  Accent      : #4F46E5 indigo-600
  Success     : #10B981 emerald-500
  Warning     : #F59E0B amber-500
  Danger      : #EF4444 red-500
  Typography  : ExtraBold headings, SemiBold labels, 400 body, 11px mono code

COMPONENT LIBRARY (components.js)
  C.badge()            — method/type/status pills with color variants
  C.methodBadge()      — GET/POST/PUT/PATCH/DELETE with semantic colors
  C.statusBadge()      — TESTS_PASSED, RUNNER_ERROR, GENERATED, etc.
  C.riskBadge()        — SMALL→LOW, MEDIUM→MED, STRONG→HIGH
  C.statCard()         — metric card with top color border accent
  C.emptyState()       — icon + title + message + CTA for empty pages
  C.sectionHead()      — section heading + optional subtitle
  C.checkRow()         — label / value / ok checkmark row
  C.diff()             — red/green inline diff viewer (JetBrains Mono)
  C.skeleton()         — shimmer loading placeholder rows
  C.banner()           — info/warn/error/success alert banners with icons
  C.code()             — dark code block (slate-900 bg, white text)

API ROUTES (dashboard.py)
  GET  /api/workspace  — returns analysis, plan, validation, feedback, version
  POST /api/analyze    — runs M1→M6 blast radius pipeline
  POST /api/migrate    — runs M10→M15 migration pipeline
  POST /api/validate   — runs M16 sandbox validation
  POST /api/pr         — runs specimpact pr (dry-run or real)
  GET  /api/feedback   — lists all feedback records from .specimpact/feedback/

main.py CHANGES
  - Imports dashboard_router + StaticFiles
  - Mounts /frontend/ as StaticFiles (html=True) — serves index.html for /
  - Registers dashboard_router on /api prefix

VERIFIED WORKING
  GET /api/workspace → 200, returns all workspace data populated from demo run
  Browser loads http://localhost:8000 → dashboard renders with real data
  Overview: 2 breaking changes, 1 file affected, RUNNER_ERROR, 0 PRs
  All 7 nav pages render without errors
  Tailwind + Inter load from CDN correctly
  Diff viewer, badges, checklist rows all rendering

SECURITY
  GITHUB_TOKEN: accepted per-request in UI, held in memory for request only,
                never written to localStorage, disk, or cookies
  PR always draft=True — no auto-merge possible
  Workspace path: server-side only, controlled via SPECIMPACT_WORKSPACE env var

TO START
  $env:SPECIMPACT_WORKSPACE = "."
  uvicorn specimpact.main:app --port 8000 --reload
  → open http://localhost:8000

TEST RESULTS
  210 passed, 2 skipped in 53.81s
  (same as M21 — no regressions from M22 backend changes)

NEXT ALLOWED MILESTONE
  M24 — Portfolio Release
```
