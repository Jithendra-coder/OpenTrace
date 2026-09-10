# Context Selection Specification

Starting M14, build a bounded `MigrationContext`; never send an entire repository to a model by default. Candidates may include the breaking change, old/new schemas, affected symbol, key callers, relevant types/models/tests, prior patch, and sanitized validation evidence.

Selection records inclusion/exclusion rationale, provenance, size/token estimate, confidentiality classification, and uncertainty. Enforce configurable file/token bounds and minimize disclosure. Evaluate OpenTrace-selected bounded context against large/raw context using real token count, cost, latency and repair success before claiming quality or cost improvement.
