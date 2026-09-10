# SpecImpact M9 formal evaluation

This directory is the canonical `impact-eval-m9-v1` held-out evaluation artifact for the checked-in M7
synthetic/curated dataset. The pre-test manifest freezes Logistic Regression Feature Set A as primary, the
heuristic, Logistic B, Random Forest, and XGBoost comparisons, the TRAIN-fitted M8 preprocessing, Platt
calibration on VALIDATION, ten equal-width ECE bins, and migration-group bootstrap settings before TEST labels
are consumed.

- `manifests/pre_test.json` - immutable pre-TEST configuration (`test_accessed: false`).
- `manifests/formal.json` - final provenance, fingerprints, checksums, timestamp, and commit when available.
- `metrics/test.json` - held-out ranking/secondary metrics, per-group results, slice diagnostics, calibration,
  reliability tables, validation-TEST gaps, and group-bootstrap intervals.
- `predictions/test.jsonl` - TEST-only row predictions with raw scores and deterministic ranks; calibrated values
  are present only if the frozen acceptance policy permits probability terminology.
- `calibration/` - trusted-local Platt artifact and complete provenance metadata.

The current calibration decision is `CALIBRATION NOT SUFFICIENT — RETAIN RANKING SCORE ONLY`. The dataset is small,
synthetic/curated, mutation-imbalanced, and VALIDATION is reused for calibration after M8 model selection. These
results are not real-world accuracy claims and do not change M4/M6 heuristic semantics.

## Reproduce

Use a new output directory to preserve the immutable canonical run:

```powershell
python -c "from specimpact.evaluation import run_m9_evaluation; run_m9_evaluation(output_directory='artifacts/m9-reproduction')"
```
# Historical Gate B status

STATUS: COMPROMISED BY CLONE LEAKAGE

HISTORICAL ONLY

NOT RESUME-ELIGIBLE

`impact-eval-m9-v1` is immutable historical evidence. It is invalid for a
clean Gate B held-out claim because Gate B found a VALIDATION/TEST model-input
clone (the unsupported-webhook difference was not a meaningful isolation
boundary). The remediation is `impact-eval-m9-v2` under
`data/m7-remediation`, `artifacts/m8-remediation`, and
`artifacts/m9-remediation`. No v1 metric artifact was overwritten and model
configurations were not retuned.
