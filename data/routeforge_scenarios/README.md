# RouteForge M11 artifact

This is the checked-in `routeforge-dataset-v1` offline foundation. It contains nine migration decision groups and
45 rows, with one row per strategy (`NO_AI`, `DETERMINISTIC`, `SMALL`, `MEDIUM`, `STRONG`) per group.

The canonical `scenario-001` group is built from the real M1–M10 payment migration. Its observed deterministic
outcome records candidate generation only; it does not claim validation. All other strategy outcomes are explicitly
`SYNTHETIC_ORACLE` or `CURATED_ORACLE` and use relative synthetic cost/latency units, never provider dollars or
measured latency.

Files:

- `scenarios.jsonl`: typed contexts, M10 evidence, outcome tables, preferred strategy, and fingerprints.
- `canonical.jsonl`: one typed strategy row per decision group and strategy.
- `manifest.json`: versions, objective, distributions, duplicate audit, split metadata, and checksum.

Reproduce with:

```powershell
python -m changemesh.routeforge --output data/routeforge-m11
```
