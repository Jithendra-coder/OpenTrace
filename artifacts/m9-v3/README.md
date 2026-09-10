# SpecImpact M9 v3 formal evaluation

This is the canonical `impact-eval-m9-v3` evaluation from the frozen v3
protocol and chronology. The five held-out migration groups contain 71 TEST
rows (23 positive, 48 negative), with no hard-positive rows; this small
synthetic/curated sample is not real-world accuracy evidence.

The formal TEST partition was accessed only after `PRE_TEST_FROZEN` in
`artifacts/gate-b-v3/chronology.jsonl`. Calibration was fit on VALIDATION only;
because ECE remained above the frozen threshold, the authoritative decision is
`CALIBRATION FAILURE CONFIRMED — RANKING SCORE ONLY`.
