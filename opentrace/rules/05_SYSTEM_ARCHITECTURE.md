# System Architecture

## Early architecture

`CLI → Contract parser → Breaking-change engine → Python AST scanner → Direct matcher → Report`

## Mature architecture

`CLI / Frontend → FastAPI → Job orchestration → Analysis workers → (Contract Intelligence + Static Analysis + Call Graph) → Blast Radius → Impact ML → Migration Engine → RouteForge → AI Provider → Patch → Validation → Feedback → GitHub PR`

## Boundaries and direction

Contract Intelligence owns normalized specs and changes. Static Analysis owns source evidence. Call Graph consumes symbols/calls and produces graph evidence. Blast Radius consumes graph and direct candidates. Risk/Impact ML consume evidence and publish predictions, never source parsing. Migration Engine consumes approved tasks; RouteForge chooses strategy but does not create patches; AI Provider creates provider-neutral candidate responses; Validation consumes copies and patches; Feedback consumes immutable observed results; GitHub is the final authorized integration.

Dependencies flow left-to-right through typed contracts; no subsystem may import a later subsystem or create a circular dependency. CLI/frontend/API adapt contracts and do not contain domain logic. Early milestones use local synchronous components; FastAPI/workers are M19+ only.
