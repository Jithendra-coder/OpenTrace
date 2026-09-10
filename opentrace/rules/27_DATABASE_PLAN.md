# Database Plan

No database implementation is authorized before M19 needs durable job/artifact coordination. Persist immutable, versioned analysis artifacts and references: repositories, specs, changes, symbols/calls/edges, impacts, tasks/patches/validations, experiment/dataset versions, jobs and audit events. Large source/patch blobs require confidentiality controls and retention policy.

Use stable ids, explicit ownership/authorization scope, provenance hashes and migration-reviewed schemas. Do not introduce a graph database prematurely; NetworkX is the initial graph representation. Storage choice, schema migrations, retention and deletion procedures require an ADR when implementation begins.
