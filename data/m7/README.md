# ChangeMesh M7 dataset foundation

This directory is the canonical, deterministic M7 artifact set:

- `canonical.jsonl` — one candidate row for each `APIChange × CodeSymbol` pair observed by the real M1–M6
  vertical slice.
- `scenarios.jsonl` — synthetic, curated adversarial, and manually constructed realistic scenario definitions,
  fixture provenance, and independently authored ground-truth paths.
- `manifest.json` — dataset/schema/generator versions, seed and configuration, counts, mutation families,
  evidence-resolution counts, duplicate checks, and the SHA-256 checksum of canonical JSONL.

## Labels and features

Ground-truth labels are authored during scenario construction from the intended dependency path. They are never
copied from M4 `impact_score`, M6 heuristic risk, direct-match results, or blast-radius propagation. The feature
object contains only observations produced by the actual M1–M6 analyzers, including explicit exact, partial, and
unresolved states. Heuristic scores are retained as named observations and are not labels or probabilities.

The row unit is `APIChange × candidate CodeSymbol`. Every row carries scenario, repository-family, API-family,
migration, mutation-family, actual API-change, symbol, provenance, and split-group metadata. Candidate symbols are
all analyzed `CodeSymbol` nodes, including unaffected and deliberately difficult negatives.

The `REALISTIC` family means manually constructed multi-file workflows for representative payment and inventory
domains; it is not a scrape of a real-world repository. No fixture is imported or executed, and generation has no
network, database, Redis, credential, or future-service dependency.

## Reproduce

From the repository root, with the package installed in the project environment:

```powershell
@'
from pathlib import Path
from changemesh.datasets import GeneratorConfig, generate_dataset, write_artifacts

dataset = generate_dataset(GeneratorConfig(seed=42, synthetic_scenarios=10))
write_artifacts(dataset, Path("data/m7"))
'@ | python -
```

The same seed and configuration produce the same scenario IDs, row IDs, canonical JSONL, and manifest checksum.
Changing the seed changes scenario fingerprints and generated fixture variation. M7 intentionally does not train
or evaluate an ML model and does not commit model metrics, probabilities, or a preselected train/validation/test
prediction set.
