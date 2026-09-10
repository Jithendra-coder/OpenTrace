# Experiment Governance

Every experiment receives an immutable record before results are communicated:

```text
Experiment ID
Date
Hypothesis
Dataset Version
Split Strategy
Features
Baseline
Treatment
Model
Hyperparameters
Primary Metric
Secondary Metrics
Result
Interpretation
Limitations
Artifacts
Reproduction Command
```

Metrics are always tied to a dataset version and experiment record. Preserve seeds, code revision, environment, exclusions and failed runs. Post-hoc exploration must be labelled exploratory, not confirmatory; changes to split/labels/features after results require a new record.
