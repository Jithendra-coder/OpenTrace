# Release-Blocking Requirements Traceability

This lightweight map links critical product rules to their milestone and verification. It complements rather than duplicates the roadmap, contracts, and Definition of Done.

| Requirement | Milestone | Verification |
|---|---:|---|
| Optional compatible additions are not classified as breaking | M2 | Compatibility fixture and adversarial tests |
| Comments, docstrings and endpoint-like text are not API calls | M3 | Release-blocking adversarial negative tests |
| Direct impact is evidence-backed and excludes an unrelated file | M4 | Integration plus real vertical-slice test |
| Indirect exposure comes from graph paths, not hardcoded links | M6 | Graph integration/cycle tests; Gate A |
| ML metrics are held out and leakage-safe | M9 | Versioned experiment artifact; Gate B |
| RouteForge improves or is rejected against baselines | M13 | Offline comparison and calibration record; Gate C |
| AI remains optional | M15 | Deterministic real path with `AI_ENABLED=false` |
| Candidate validation is isolated and cleaned up | M16 | Sandbox integration test; Gate D at M17 |
| Escalation uses failure evidence and is bounded | M17 | Failed-validation escalation test |
| Incremental results equal clean analysis | M20 | Equivalence suite and benchmark artifact |
| Generated changes require human review; automatic merge disabled | M21 | GitHub integration test and audit review; Gate E |
| Frontend displays only real artifact state | M22 | Backend-contract UI test and empty/error-state review |
