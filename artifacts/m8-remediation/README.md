# M8 remediation artifacts

These artifacts are the frozen M8 validation run for the Gate B clone-isolation
remediation dataset `impact-dataset-v2` (`bfe2696c05e76b479c87210301638bab8323c8405aa1755aba8d73e2e99cf231`).

- Dataset: `data/m7-remediation`
- Generator: `synthetic-impact-generator-v2`
- Split: `clone-safe-component-round-robin-v2`, seed `20270813`
- Training seed: `42`
- Test access: none; M8 is development/validation only.
- Configurations and baseline families are unchanged from M8 v1; no metric-driven retuning was performed.

The original `artifacts/m8` directory is preserved as historical evidence.
