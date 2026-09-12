# RouteForge dataset v2

This is the independent `routeforge-dataset-v2` revision generated from the
frozen Gate C protocol. It contains 64 decision groups and 320 strategy rows
with group-safe TRAIN/VALIDATION/TEST partitions, provenance-only offline
outcomes, and zero cross-partition clone overlap. The historical M11 dataset
is preserved and is not used as the formal TEST set.

Formal TEST access is governed by `data/routeforge-gate-c/pre-test-manifest.json`
and the exactly-once seal in `formal-test-access.json`.
