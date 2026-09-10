# RouteForge M12 baseline artifact

This checked-in artifact records the real M12 offline baseline run over
`routeforge-dataset-v1`.

- Five decision groups / 25 strategy rows are used for TRAIN fitting.
- Three decision groups / 15 strategy rows are used for VALIDATION diagnostics.
- One decision group / 5 strategy rows remains sealed as TEST for M13.
- All five strategy rows for a migration remain in one partition.
- Outcomes are synthetic or curated oracle outcomes; the observed M10 row remains `UNKNOWN`.
- Cost and latency are synthetic relative units only.

Experiments:

- `RF-B0-ALWAYS-SMALL`
- `RF-B1-ALWAYS-STRONG`
- `RF-B2-RANDOM`
- `RF-B3-RULE-V1`
- `RF-B4-LOGISTIC`
- `RF-B5-XGBOOST`

Reproduce with:

```powershell
python -m changemesh.routeforge.baselines --output data/routeforge-m12
```

M12 is baseline development only. It does not provide a production router, call AI providers, validate patches,
claim calibrated probabilities, claim validated repair success, or claim real provider cost savings.
