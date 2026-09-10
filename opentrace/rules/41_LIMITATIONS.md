# Limitations

Initial analysis is limited to OpenAPI-described REST APIs and Python `requests`/`httpx` static evidence. Dynamic URL construction, reflection, runtime configuration, unresolved imports, re-exports/wrappers and external calls may produce partial or unsupported results. Comments, docstrings and endpoint-like text are not usage evidence. Static reachability does not prove runtime failure; heuristic impact/risk scores are not probabilities.

Specs can be ambiguous; compatibility classification records assumptions. AI output is optional, fallible and never sufficient without validation. Sandboxing reduces risk but does not promise perfect isolation. Multi-repository coverage, incremental correctness, production security posture, model generalization and performance claims remain unproven until their later milestones and evidence.
