# Coding Agent Rules

1. Never hardcode demo outputs or fabricate metrics/cost savings.
2. Never call heuristic scores calibrated probabilities; do not hide unresolved analysis or guess dynamic endpoints.
3. Implement no future milestone early; declare completion only after tests and real CLI/API execution.
4. Add practical regression tests for defects; prefer deterministic analysis and deterministic migration when sufficient.
5. Keep RouteForge provider-independent and AI optional; never send whole repositories to AI by default.
6. Never automatically merge generated changes or execute arbitrary repository code on host.
7. Benchmark before performance claims; compare ML to simple baselines and preserve train/test isolation.
8. Keep focused modules; avoid `utils.py` dumping grounds, global mutable state, unnecessary inheritance and premature microservices.
9. Architecture changes require ADRs. Unsupported means unsupported; partial means partial.
10. Keep each milestone small, reviewable, documented and within its allowed boundary.
