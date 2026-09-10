# ADR-006: No Whole-Repository AI Context

## Status
Accepted.
## Context
Full repository disclosure is costly, insecure and poorly targeted.
## Decision
Use bounded, evidence-selected `MigrationContext` by default.
## Alternatives Considered
Whole-repository prompting; unrestricted retrieval.
## Consequences
Context selection requires provenance, bounds and evaluation.
## Revisit Conditions
Measured controlled studies and security review justify a scoped exception.
