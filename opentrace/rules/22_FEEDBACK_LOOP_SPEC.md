# Feedback Loop Specification

M17 adaptive flow: Route → Generate → Validate → on failure extract evidence → Route again → generate improved candidate → Validate. Retry input includes previous patch, test failures, traceback, changed files, remaining failures and syntax failures.

Retries are bounded, deduplicated, policy-controlled and auditable; the configurable maximum must be finite. A retry must materially incorporate observed evidence; blind regeneration of the same request is prohibited. On exhaustion, return a structured terminal result rather than looping. M18 persists versioned feedback records only after validation, preserving task/context/route/provider/patch/result provenance and avoiding unreviewed online self-training.
