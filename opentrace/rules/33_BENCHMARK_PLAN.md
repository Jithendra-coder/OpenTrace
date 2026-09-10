# Benchmark Plan

Benchmarks begin only with stable implementations and versioned fixtures/datasets. Use approximate Tiny (~100 files), Medium (~1,000 files), and Large (~10,000 files) repository tiers when suitable. Record hardware/environment, dataset/repository version, software version/commit, command, configuration, date, input corpus hashes/sizes, warm/cold conditions, repetitions, summary statistic, variance and failures. Benchmark OpenAPI parsing, AST scanning, call-graph construction, impact ranking, peak memory, total analysis, incremental analysis, migration/context/validation, and routing where applicable.

Compare against prior revision or stated baseline; separate latency, throughput, memory and cost. Do not advertise performance, speedup or cost saving without stored reproducible artifacts. Benchmark safety must not weaken validation isolation.
