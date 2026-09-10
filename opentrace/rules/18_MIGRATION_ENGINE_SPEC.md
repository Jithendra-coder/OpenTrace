# Migration Engine Specification

From M10, attempt deterministic transformations before AI when a supported exact transformation is available. Outcomes are `NO_CHANGE`, `DETERMINISTIC_CANDIDATE`, `AI_REQUIRED`, or `UNSUPPORTED`, each with rationale, target evidence and uncertainty.

The engine creates candidate patches only; it never directly changes a production repository, merges code, or conceals unsupported transforms. Patch application and validation occur later in isolated copies. Every deterministic rule needs positive, negative, idempotence where applicable, and regression tests.
