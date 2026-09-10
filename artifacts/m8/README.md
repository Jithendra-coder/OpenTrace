# SpecImpact M8 baseline experiments

This directory contains reproducible M8 development artifacts generated from the checked-in M7 dataset.

- `experiments/` — immutable JSON records for E1–E5, including hypothesis, dataset checksum, split strategy,
  feature set, parameters, seed, metrics, and artifact paths.
- `models/` — trusted local model binaries plus safe JSON provenance/feature-schema metadata. Do not load model
  binaries supplied by untrusted users.
- `predictions/` — validation-only ranking scores with experiment ID, row ID, migration ranking group, label,
  score, and deterministic rank.
- `metrics/validation.json` — validation/development ranking diagnostics and the label-shuffle sanity check.

The five required experiments are: deterministic M4 heuristic, Logistic Regression Feature Set A, Logistic
Regression Feature Set B, Random Forest, and XGBoost. Feature Set A is structural-only; Feature Set B adds the
explicit M4/M6 aggregate heuristic features. Preprocessing is fitted on TRAIN only and handles unknown
validation categories with `OneHotEncoder(handle_unknown="ignore")` plus explicit numeric missingness columns.

The TEST partition is sealed: no TEST rows, labels, predictions, or metrics are used by M8 model selection.
Formal held-out evaluation and probability calibration belong to M9. The scores in these artifacts are ranking
scores/development metrics, never calibrated probabilities.

## Reproduce

From the repository root:

```powershell
python -m specimpact.ml
```

This validates the M7 schema and byte checksum, reassigns the frozen migration-group split with seed `42`, fits
all preprocessing on TRAIN, evaluates only VALIDATION, and writes the artifacts under `artifacts/m8`.
