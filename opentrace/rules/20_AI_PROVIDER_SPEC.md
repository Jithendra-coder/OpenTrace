# AI Provider Specification

M15 exposes a provider-independent abstraction with the responsibility of a `MigrationProvider`; do not freeze unnecessary concrete method signatures before implementation evidence. Core domain logic must not depend on any vendor or model. With `AI_ENABLED=false`, the product remains functional and returns a controlled AI-unavailable/AI-required outcome rather than failing analysis.

Provider responses normalize patch, explanation, assumptions, uncertainties, usage, latency, and cost when available. Do not invent unavailable cost/usage fields. Provider credentials remain outside source, logs and patches; retries obey policy and carry validation evidence rather than repeating unchanged prompts.
