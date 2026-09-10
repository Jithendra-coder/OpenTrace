# API Surface Plan

No production API implementation before M19. Future API/CLI surfaces expose versioned typed artifacts rather than internal objects: submit/inspect analyses, retrieve changes/impacts/risk/graph, create migration tasks, retrieve patches/validation attempts, and authorized PR actions. Every endpoint/command defines auth scope, input validation, asynchronous/synchronous behavior, error code, uncertainty payload and idempotency semantics.

Early CLI is permitted only when its milestone explicitly requires a real execution path. Public contracts must be backward-compatible or versioned; do not expose provider credentials, raw source by default, or unsupported operations as success.
