# GitHub Integration Specification

M21 only. Inputs are explicit user authorization, repository/branch identity, validated and reviewed candidate patch, metadata and least-privilege credentials. Eventual mutation flow is isolated branch/worktree preparation → branch creation → commit creation → draft or human-reviewable PR. Outputs are a PR reference and immutable audit event; errors include authorization, rate limit, conflict and API failures.

`AUTOMATIC MERGE = DISABLED`. Human review is mandatory. Never mutate the production repository before a validated candidate exists, except in an explicitly designed isolated temporary branch/worktree used for controlled testing. Validate repository identity/branch protection, minimize tokens/scopes, redact secrets, make operations idempotent, and surface exact remote results. Integration tests must use mocks/sandboxes; a live operation requires explicit authorization.
