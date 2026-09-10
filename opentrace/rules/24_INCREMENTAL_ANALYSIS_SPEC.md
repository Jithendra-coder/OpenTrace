# Incremental Analysis Specification

M20 may reuse prior analysis only when repository/spec/config/tool versions and content hashes establish valid provenance. Each reusable record stores path, content hash, analysis/schema version, AST/symbol artifact version, analysis timestamp and configuration version. Inputs are prior artifact manifest plus changed files/specs; outputs are updated artifacts, reused/invalidated artifact ids, reasons, timing and equivalence status.

Conservative invalidation is required when dependencies/resolution are uncertain or analyzer/schema/config versions change. Compare incremental output with clean analysis on fixtures; do not claim speedup without benchmark evidence. Incorrect reuse is worse than a full scan.
