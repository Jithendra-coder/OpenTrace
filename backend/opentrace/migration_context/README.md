# M14 migration context selection

OpenTrace builds bounded, provenance-aware migration context for future repair generation. It consumes typed
M1–M10 evidence and an already-made M13 routing decision, selects only whole relevant source spans, and records
budget accounting, omissions, uncertainty, content hashes, and a deterministic manifest checksum.

The selector reads only evidence-addressed Python files beneath the supplied repository root. It excludes VCS,
credential, key, binary, absolute, traversal, and escaping-symlink paths. It never imports or executes analyzed
source, contacts a provider, generates a repair, or validates a patch.

Character accounting is provider-independent. The default limit is 8,000 content characters across at most eight
source files. Required API/direct-target evidence must fit as whole items; otherwise selection returns
`INSUFFICIENT_CONTEXT_BUDGET` rather than a misleading partial context. Optional caller spans are considered only
after required evidence and receive explicit omissions when a bound prevents their inclusion.
