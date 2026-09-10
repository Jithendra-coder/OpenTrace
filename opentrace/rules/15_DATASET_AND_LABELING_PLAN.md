# Dataset and Labeling Plan

M7 datasets comprise: synthetic known-ground-truth mutations; curated adversarial cases that challenge the analyzer; and realistic/real-world open-source or manually constructed migration scenarios. Synthetic data is useful but cannot be the sole basis of final quality claims. Each record has dataset/version id, generator version and random seed where generated, creation date, source/provenance/license, repository/API/scenario/mutation family, label definition/distribution, annotator or generator, evidence, limitations, and split assignment.

Prohibit naive random row-level splitting whenever candidate rows from a repository or migration can cross train/test. Isolate by repository, API family, migration scenario, and mutation family where feasible; final evaluation includes genuinely unseen structures. Freeze splits before model selection; keep held-out evaluation untouched. Label uncertainty and disagreements instead of forcing false labels.
