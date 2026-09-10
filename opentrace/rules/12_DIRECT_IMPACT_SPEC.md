# Direct Impact Specification

Direct impact is evidence-based association between an `APIChange` and an `APICallSite`. Evidence includes API identity, host, path, HTTP method, request-field usage, response-field usage, direct HTTP invocation, and resolution quality.

Early output is `impact_score`, with configurable weights, feature contributions, reasons, and uncertainty. It is **not a probability** before M9 and cannot be described as one. Exact matches may still include compatibility assumptions; no evidence produces an explicit unmatched result. Direct impact is distinct from indirect exposure.
