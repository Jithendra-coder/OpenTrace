# Async Job Specification

M19 introduces jobs/workers only for long-running analysis and validation. `AnalysisJob` has immutable input artifact references, configuration/version, owner/authorization context, state, stage progress, timestamps, output artifact references, retry count, errors and cancellation reason. Mature states are `QUEUED`, `PARSING_SPEC`, `SCANNING_REPOSITORY`, `BUILDING_GRAPH`, `RANKING_IMPACT`, `PREPARING_MIGRATION`, `GENERATING_MIGRATION`, `VALIDATING`, `COMPLETED`, `FAILED`, and `CANCELLED`; do not collapse all work into generic `PROCESSING`.

Jobs must be idempotent by input/config identity, observable, bounded by quotas/timeouts, safe to retry, and never expose source/secret contents in status. Synchronous behavior remains the simpler pre-M19 architecture; no worker or Redis implementation belongs earlier.
