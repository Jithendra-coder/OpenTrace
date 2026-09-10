# ADR-002: Python AST First

## Status
Accepted.
## Context
Initial scope needs explainable Python source analysis.
## Decision
Use Python AST as the primary initial mechanism for `requests` and `httpx` extraction.
## Alternatives Considered
Regex, runtime instrumentation, multi-language parsers first.
## Consequences
Static partial/unresolved states are explicit; dynamic behavior is limited.
## Revisit Conditions
After AST evidence demonstrates a need for richer resolution.
