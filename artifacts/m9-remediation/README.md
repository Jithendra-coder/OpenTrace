# M9 remediation artifacts

STATUS: CHRONOLOGICALLY COMPROMISED

HISTORICAL ONLY

NOT RESUME-ELIGIBLE

Reason: TEST was inspected before the final v2 dataset revision.

This directory contains formal evaluation `impact-eval-m9-v2` over the fresh,
clone-safe `impact-dataset-v2` revision. The pre-test freeze is recorded in
`manifests/pre_test.json`; data generation was predeclared in
`data/m7-remediation/data_generation_manifest.json` before M8/M9 performance
runs.

- Dataset checksum: `bfe2696c05e76b479c87210301638bab8323c8405aa1755aba8d73e2e99cf231`
- Split: `clone-safe-component-round-robin-v2`, seed `20270813`
- Training/evaluation seed: `42`
- Calibration: Platt fit on VALIDATION only; acceptance is evaluated without retuning.
- The original `impact-eval-m9-v1` remains immutable historical evidence and is
  invalid for a clean Gate B held-out claim because Gate B reproduced model-input
  clone leakage. No old metric artifact was overwritten.

Reproduce with:

```powershell
python -c "from pathlib import Path; from specimpact.evaluation.pipeline import run_m9_evaluation; run_m9_evaluation(dataset_directory=Path('data/m7-remediation'), m8_directory=Path('artifacts/m8-remediation'), output_directory=Path('artifacts/m9-remediation'), seed=42, split_seed=20270813, evaluation_id='impact-eval-m9-v2')"
```
