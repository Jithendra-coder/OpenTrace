# Security Rules

Protect source confidentiality through repository isolation, access control, minimal data retention, and no source code in logs by default. Minimize credentials/scopes; use secret stores/environment injection rather than commits; redact logs/errors/telemetry. AI is opt-in/disableable, sends only minimized bounded context, and records provider disclosure metadata.

Validation is ephemeral, resource-limited and network-restricted; never execute arbitrary submitted repository code directly on the host. Treat Docker as defense-in-depth, not perfect isolation. Require human approval before PR/merge actions, auditable operations, deletion/retention procedures, dependency/supply-chain review and incident-safe error handling. Security design changes require ADR review.
