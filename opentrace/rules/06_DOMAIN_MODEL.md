# Domain Model

All objects have stable `id`, `created_at`, `source_version`, `evidence`, and `uncertainty` where applicable. Cross-subsystem exchange uses these typed objects, not arbitrary dictionaries.

| Object | Responsibility; required fields | Optional / uncertainty / relationships |
|---|---|---|
| APISpecification | `id`, source URI/hash, OpenAPI version, operations, schemas | parse warnings; owns operations/schemas |
| APIOperation | `id`, path, method, parameters, request/response ids | security; belongs to spec |
| Parameter | `id`, name, location, required, schema id | default; belongs to operation |
| RequestBody / Response | `id`, content types, schema id | required/status/headers; belongs to operation |
| Schema / SchemaProperty | `id`, kind/properties/composition; property `name`, schema id, required | nullable/enum/ref; nested relationship |
| SecurityRequirement | `id`, schemes/scopes | operation/spec scope |
| APIChange | `id`, category, operation identity, location, old/new value, severity, breaking classification, compatibility direction, certainty, reason | assumptions; relates old/new entities |
| Repository / RepositoryFile | `id`, canonical path/hash; file path/language/content hash | access/parse warnings; owns symbols |
| CodeSymbol | `id`, qualified name, kind, file/location | resolution confidence; graph node |
| APICallSite | `id`, symbol/file/location, client, method/path/host/payload/response evidence, resolution state | exact/partial/unresolved; references operation when matched |
| DependencyEdge | `id`, source id, target id, type | confidence/evidence; graph edge |
| ImpactEvidence | `id`, evidence type, source artifact/location, observed value, resolution state, contribution | confidence/assumptions; belongs to impact candidate, call site, or edge and is immutable |
| ImpactCandidate | `id`, change/call/symbol ids, `impact_score`, ordered evidence ids, reasons | uncertainty and unmatched state; pre-M9 heuristic only |
| ImpactPrediction | `id`, candidate/target ids, `estimated_impact_probability`, model/version, dataset/split/calibration artifact ids | only M9+; calibration interval/status and out-of-distribution warning |
| RiskAssessment | `id`, target/change, numeric risk score, `LOW`/`MEDIUM`/`HIGH`/`CRITICAL` level, factors | thresholds, assumptions and missing-data limitations; M6 heuristic |
| MigrationTask / MigrationContext | task id/change/target/policy; bounded context id/task/evidence | unsupported reason/token budget; task lifecycle queued→routed→patched→validated |
| RoutingCandidate / RoutingDecision | strategy/cost/latency/success estimate; chosen strategy/policy/rationale | estimate uncertainty; only M11+ |
| GeneratedPatch | `id`, task, diff/files, generator, assumptions | provider usage/uncertainty; candidate only |
| ValidationResult / ValidationAttempt | result id/status/apply/syntax/collection/pass/fail/timeout/exit/failure summary; attempt id/task/patch/result | sanitized evidence; attempt sequence |
| AnalysisJob | `id`, inputs/config/state/stage/artifact refs | explicit state, progress/errors/cancellation; M19+ lifecycle |

Lifecycle data is immutable per run; corrections create a new artifact version linked to its predecessor.
