# ADR-005: Provider-Independent AI

## Status
Accepted.
## Context
Vendor lock-in and availability must not define product logic.
## Decision
Use a provider-neutral AI abstraction and preserve an AI-disabled path.
## Alternatives Considered
Single-vendor API embedded in core domain logic.
## Consequences
Adapter work and normalized usage/cost uncertainty.
## Revisit Conditions
Only to revise the contract through an ADR, not remove optionality.
