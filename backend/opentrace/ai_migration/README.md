# M15 provider-independent AI migration

OpenTrace can request a structured, unvalidated migration candidate from a provider-neutral adapter after M14 has
selected bounded context and M13 has chosen an abstract `SMALL`, `MEDIUM`, or `STRONG` route. The core accepts only
typed request and response contracts; it has no vendor SDK or network adapter.

`AI_ENABLED` defaults to false. `NO_AI`, `DETERMINISTIC`, and `NO_FEASIBLE_STRATEGY` never call a provider. A
deterministic fake adapter provides valid, malformed, refusal, timeout, unavailable, unsafe-path, unauthorized-file,
oversized, duplicate, and overlapping-output cases for local tests.

Candidates are in-memory structured edits only. They are never applied, executed, validated, described as safe, or
treated as a repair success. M16 owns isolated application and validation.
