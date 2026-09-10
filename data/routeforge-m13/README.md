# RouteForge M13 learned-router artifact

This checked-in artifact records the real M13 offline run over the frozen
`routeforge-dataset-v1` and M12 Logistic experiment.

- The primary scorer is a checksummed JSON Logistic artifact trained on 19 eligible TRAIN rows.
- Three VALIDATION decision groups are routed; all strategy rows remain grouped.
- TEST remains sealed: `TEST METRICS NOT COMPUTED — DATASET INADEQUATE FOR GATE C EVIDENCE`.
- Decisions use pre-decision features and strategy identity only.
- Outcome lookup appears only in the separate post-selection offline evaluation artifact.
- Scores are uncalibrated offline oracle-success scores; costs and latency are synthetic relative units.
- `AI_REQUIRED`/unsupported M10 evidence excludes only `DETERMINISTIC`; SMALL/MEDIUM/STRONG remain abstract
  applicable strategies.
- Routing is a score-only prototype: no governed pre-decision strategy cost/latency attributes exist, so
  cost-aware `routeforge-objective-v1` selection remains a Gate C evidence/design gap.

Reproduce with:

```powershell
python -m changemesh.routeforge.router --output data/routeforge-m13
```

M13 does not call providers, generate patches, validate repairs, measure real cost or latency, or claim production
routing performance. Gate C requires additional independent RouteForge evidence before M14.
