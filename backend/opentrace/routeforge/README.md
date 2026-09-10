# RouteForge M11–M13 offline foundation

M11 defines a provider-independent offline dataset for future RouteForge routing baselines. Each decision group
contains one pre-decision `RoutingDecisionContext` and exactly one `StrategyOutcome` row for `NO_AI`,
`DETERMINISTIC`, `SMALL`, `MEDIUM`, and `STRONG`.

The canonical payment scenario consumes real M1–M10 evidence. Its observed deterministic row records that M10
generated a candidate; its other strategy rows are explicitly curated oracle counterfactuals. Synthetic and curated
oracle outcomes are scenario truth, not validated repair success, provider benchmarks, measured cost, or measured
latency. Costs and latency are relative synthetic units only.

Features are an explicit pre-decision allowlist: contract change, static resolution, direct impact, blast-radius
structure, coverage, M10 repairability/edit complexity, ambiguity, and source shape. Strategy outcomes, preferred
strategy, oracle fields, post-repair evidence, provider metadata, and future validation fields are excluded.

The objective is `routeforge-objective-v1`: minimize synthetic relative cost subject to oracle outcome `SUCCESS`,
latency at most 4 units, and quality at least 70 units. Ties use the fixed strategy order. `NO_FEASIBLE_STRATEGY`
and `UNKNOWN` are represented explicitly; unknown is never treated as failure.

Generate the artifact with:

```powershell
python -m opentrace.routeforge --output data/routeforge-m11
```

All IDs, ordering, fingerprints, JSONL, and checksums are deterministic for the fixed configuration. Strategy rows
share a decision-group split assignment, so future M12/M13 partitions cannot separate counterfactual strategies.
M11 contains no router, provider API, AI call, validation execution, or routing performance claim.

M12 runs the required offline baselines with:

```powershell
python -m opentrace.routeforge.baselines --output data/routeforge-m12
```

The baseline runner uses the M11 allowlist plus explicit strategy identity. Logistic Regression and bounded
XGBoost fit only eligible `SUCCESS`/`FAILURE` rows from the five TRAIN decision groups. `UNKNOWN` and
`NOT_APPLICABLE` remain excluded from the ordinary supervised target. Always Small, Always Strong, seeded Random,
and the frozen `RF-B3-RULE-V1` policy are evaluated alongside the learned scores. All policy metrics are
VALIDATION-only synthetic/curated oracle diagnostics; TEST is sealed and no prediction HTTP endpoint exists.

M13 runs the frozen Logistic scorer as a provider-independent routing prototype:

```powershell
python -m opentrace.routeforge.router --output data/routeforge-m13
```

The router loads only a checksummed local JSON model artifact, validates feature/taxonomy/objective versions,
applies pre-decision applicability gates, and emits deterministic typed decisions with structured explanations.
It supports `NO_AI`, `DETERMINISTIC`, `SMALL`, `MEDIUM`, `STRONG`, and `NO_FEASIBLE_STRATEGY` without reading
strategy outcomes during inference. M10 `AI_REQUIRED`/`UNSUPPORTED` evidence excludes only `DETERMINISTIC`; the
abstract AI strategies remain independently applicable. The M13 decision policy is explicitly score-only: highest
finite uncalibrated score with deterministic objective-order ties and no validation-tuned threshold. Validation
outcome lookup is a separate offline evaluation step. The frozen artifacts do not provide governed pre-decision
strategy cost/latency attributes, so cost-aware objective selection is a Gate C evidence/design gap. TEST remains
sealed; scores are uncalibrated offline oracle-success scores and the nine-group dataset is inadequate for Gate C.
