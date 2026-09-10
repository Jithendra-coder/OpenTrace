# Canonical Milestone Roadmap

Only this numbering is canonical. A milestone becomes complete only under `37_DEFINITION_OF_DONE.md`; all begin as planned.

Planning foundation status: **pre-M0**. M0 has not begun. Once implementation is explicitly authorized, the current milestone is the first incomplete canonical milestone following the latest accepted completion report and all required preceding gates.

| Milestone | Scope |
|---|---|
| M0 | Engineering Foundation |
| M1 | OpenAPI Parsing + Normalization |
| M2 | Breaking-Change Engine |
| M3 | Python AST + HTTP Usage Extraction |
| M4 | Direct Impact Matcher |
| M5 | Static Call Graph |
| M6 | Blast-Radius Propagation + Heuristic Risk |
| M7 | Synthetic + Curated Dataset |
| M8 | Impact ML Baselines |
| M9 | Impact Evaluation + Probability Calibration |
| M10 | Deterministic Migration Engine |
| M11 | RouteForge Offline Dataset |
| M12 | RouteForge Baselines |
| M13 | Learned RouteForge Router |
| M14 | Migration Context Selection |
| M15 | Provider-Independent AI Migration |
| M16 | Isolated Patch Validation |
| M17 | Adaptive Repair Escalation |
| M18 | Routing Feedback / Learning Dataset |
| M19 | Async Jobs and Workers |
| M20 | Incremental Repository Analysis |
| M21 | GitHub Pull Request Integration |
| M22 | Frontend Dashboard |
| M23 | Multi-Repository Blast Radius |
| M24 | Final Benchmarks, Ablations, Documentation and Portfolio Release |

## Mandatory architecture gates

| Gate | Timing | Mandatory review |
|---|---|---|
| A | After M6 | Direct-impact correctness, graph correctness, blast-radius behavior, false positives, false negatives, architecture quality |
| B | After M9 | Dataset quality, leakage, ML baselines, ranking metrics, calibration, generalization |
| C | After M13 | RouteForge baseline comparisons, routing calibration, cost/quality tradeoffs, whether ML is useful |
| D | After M17 | Generation, validation, escalation, retry evidence, safety |
| E | After M21 | Async architecture, repository security, GitHub operations, end-to-end reproducibility |

A failed gate blocks later work absent an ADR and remediation plan.
