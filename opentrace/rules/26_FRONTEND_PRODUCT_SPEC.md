# Frontend Product Specification

Frontend is deliberately late: do not implement before M22. Final navigation: Overview, Projects, Analyses, Migrations, Experiments, Integrations, Settings. Analysis detail tabs: Overview, Changes, Impact, Dependency Graph, Risk, Migration, Validation.

Every displayed item must map to real backend artifact data with provenance, timestamps, uncertainty and empty/error states. Its purpose is explanatory: Changes answers “What changed?”; Impact, “What code is exposed?”; Dependency Graph, “How does impact propagate?”; Risk, “How serious is this migration?”; Migration, “What repair strategy was selected?”; Validation, “Did the repair work?”. Never create fake dashboard statistics, fabricated graphs or static successful-migration displays. UI is an adapter to versioned API contracts and must preserve direct versus indirect distinction; it is not a separate product.
