# Canonical Terminology

Use these terms exactly. This document resolves terminology disputes; subsystem documents define their detailed fields.

| Term | Meaning and restrictions |
|---|---|
| `APIChange` / Breaking Change | A structured old-to-new contract difference. `breaking_classification` is `CLIENT_BREAKING`, `SERVER_BREAKING`, `POTENTIALLY_BREAKING`, or `COMPATIBLE`; it includes compatibility direction, certainty, assumptions and reason. “Breaking Change” is not every syntax diff. |
| Compatibility Direction | Which party/request-response direction may be incompatible, including client-to-server or server-to-client. Runtime-dependent interpretation is conditional, never silently certain. |
| `APICallSite` / `CodeSymbol` / `DependencyEdge` | Respectively an extracted HTTP use, a named source entity, and an evidence-backed static graph relationship. Resolution is `EXACT`, `PARTIAL`, or `UNRESOLVED`. |
| Direct Impact | Evidence-backed association from an `APIChange` to a concrete API call/site/symbol. It is not graph reachability. |
| Indirect Exposure / Blast Radius | A potentially exposed symbol reachable from direct impact through evidenced graph edges. Blast radius is the aggregate of such results; neither proves runtime failure. |
| `ImpactEvidence` | Atomic, provenance-bearing observed fact used to justify a candidate: type, source location/artifact, observed value, weight/contribution, resolution state, and uncertainty. |
| Impact Score | Pre-M9 explainable heuristic/evidence ranking score. It must never be called probability, confidence probability, likelihood percentage, calibrated output, or ML prediction. |
| Impact Probability | Only an M9+ statistically evaluated and calibrated `estimated_impact_probability`, carrying model, dataset/split, calibration and uncertainty metadata. |
| Risk Score / Risk Level | An M6 heuristic prioritization score and its `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL` level. Not a failure probability or trained ML result until separately governed. |
| `MigrationTask` / `MigrationContext` | A bounded requested repair and its minimal evidence-selected context. Context is never a whole repository by default. |
| `RoutingCandidate` / `RoutingDecision` | A strategy estimate and selected policy-constrained strategy. `NO_AI` means no generated repair is required; `DETERMINISTIC` means programmatic candidate repair is produced. |
| `GeneratedPatch` | A candidate diff with origin, assumptions and uncertainty; it has not changed a production repository and is not accepted until validation/human review. |
| `ValidationAttempt` / `ValidationResult` | One controlled attempt and its structured isolated outcome. Validation evidence outranks generation confidence. |

Status vocabulary: `SUPPORTED`, `PARTIALLY_SUPPORTED`, and `UNSUPPORTED` describe feature support; `EXACT`, `PARTIAL`, and `UNRESOLVED` describe analysis resolution. Never substitute one set for the other.
