# Product Requirements

## Users

Backend Engineers repair consumers; Platform Engineers operate integrations; API Owners assess compatibility; Tech Leads prioritize migration; Developer Productivity Engineers improve workflows; Engineering Managers assess risk and progress.

## Core workflows

| Workflow | Goal, inputs, processing, output | Failure / uncertainty | Acceptance criteria |
|---|---|---|---|
| A Compare API v1/v2 | Specs → normalize/diff → structured changes | Invalid/unresolved refs; directional compatibility/certainty | Each reported change has location, old/new evidence, classification and certainty |
| B Scan Python repo | Repo/config → AST extraction → symbols/call sites | Parse/import/dynamic-resolution warnings | Findings identify source location and resolution state |
| C Find direct impact | Changes + calls → evidence matcher → candidates | No match or partial identity/path evidence | Score and feature contributions are shown, without probability claims before M9 |
| D Blast radius | Candidates + graph → transitive propagation → indirect exposure | Unresolved edges/cycles | Paths, distance, scores and uncertainty distinguish indirect from direct |
| E Rank impact | Evidence/features → ordered candidates | Ties/missing features | Explainable deterministic rank; calibrated probability only after M9 |
| F Assess risk | Change/impact/graph signals → risk assessment | Missing coverage or incomplete graph | Risk band, factors and limitations are explicit |
| G Select strategy | Migration task/features/policy → route | Insufficient feature history/unsupported task | Strategy, rationale, predicted evidence and policy constraints recorded |
| H Generate repair | Task/context/strategy → candidate patch | Unsupported transform/provider failure | Patch, assumptions, uncertainty; source repo unchanged |
| I Validate repair | Patch + isolated repo → checks/tests → result | Setup failure, timeout, unsafe execution | Structured result includes apply/syntax/test/exit evidence |
| J Escalate failure | Prior patch + validation evidence → reroute/regenerate | Retry budget exhausted | New request incorporates failure evidence; no blind duplicate retry |
| K Create PR | Approved patch + GitHub authorization → PR | Auth/rate/API error | Draft/human-reviewable PR only, auditable action |
| L Multi-repo impact | Change + authorized repositories → analyses → aggregate | Access/analysis gaps | Per-repo evidence and uncertainty retained; no cross-repo certainty inflation |

All workflows are introduced only at their corresponding roadmap milestones. “No result” and “unsupported” are valid outputs.
