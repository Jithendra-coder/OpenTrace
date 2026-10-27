# M14 migration context selection

This is OpenTrace's graph-grounded RAG retriever: it builds bounded, provenance-aware context for repair generation. It consumes typed
M1–M10 evidence and an already-made M13 routing decision, selects only whole relevant source spans, and records
budget accounting, omissions, uncertainty, content hashes, and a deterministic manifest checksum.

The retrieval signal is the API contract diff plus static code-analysis evidence: exact API call sites, affected target
symbols, and callers reachable through the call graph. Required direct evidence is prioritized, with optional callers
ranked by graph distance and bounded by a file and character budget. This is intentionally graph-first rather than
embedding-first: a migration needs dependency evidence tied to exact files and symbols, while semantic similarity alone
cannot prove that a function calls the changed API. No embedding model or vector store is used in this path.

The selector reads only evidence-addressed Python files beneath the supplied repository root. It excludes VCS,
credential, key, binary, absolute, traversal, and escaping-symlink paths. It never imports or executes analyzed
source, contacts a provider, generates a repair, or validates a patch.

Character accounting is provider-independent. The default limit is 8,000 content characters across at most eight
source files. Required API/direct-target evidence must fit as whole items; otherwise selection returns
`INSUFFICIENT_CONTEXT_BUDGET` rather than a misleading partial context. Optional caller spans are considered only
after required evidence and receive explicit omissions when a bound prevents their inclusion. Generation plans retain
the context identity, checksum, selected item hashes, provenance IDs, graph distances, and omission reasons without
copying source text into the audit trace. Run `opentrace evaluate` after validation to write the per-run retrieval,
generation, and sandbox evidence summary.
