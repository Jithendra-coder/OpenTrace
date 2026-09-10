# ADR-003: NetworkX Before Graph Database

## Status
Accepted.
## Context
Early call-graph and blast-radius needs do not justify graph infrastructure.
## Decision
Use NetworkX initially.
## Alternatives Considered
Neo4j or another graph database.
## Consequences
Simpler local experimentation; scale constraints must be benchmarked.
## Revisit Conditions
Measured scale/query needs and an approved ADR justify migration.
