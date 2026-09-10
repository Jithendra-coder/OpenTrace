# Call Graph and Blast Radius Specification

Graph nodes are `FUNCTION`, `METHOD`, `CLASS`, and `API_CALL`; edges are `CALLS`, `CONTAINS`, and `USES_API`. Use NetworkX initially. An API change is a contract fact; a direct candidate is a separately evidenced API-use match; indirect exposure is a separately graph-reachable result. Graph connectivity never upgrades either exposure to guaranteed runtime failure.

For each indirect result record source direct impact id, source symbol, graph distance, propagation path, propagation score, uncertainty, edge evidence, traversal configuration, and cycle/truncation warnings. Traversal must be bounded and deterministic; unresolved imports/calls lower confidence rather than inventing edges. M6 release blocking requires demonstrated transitive paths from graph edges, not hardcoded relationships.
