# Risk Model Specification

M6 introduces an explainable heuristic risk assessment, not trained ML or a failure probability. Inputs may include change severity, direct-impact count/score, indirect-exposure count, graph depth/breadth, affected files, critical-symbol indicators, test coverage when actually available, resolution quality, and missing-data signals. Output is numeric risk score, `LOW`/`MEDIUM`/`HIGH`/`CRITICAL` level, contributing factors, assumptions and uncertainty.

Risk bands require configurable documented thresholds and tests at boundaries; thresholds are policy defaults, not scientifically optimal claims without empirical evidence. A high score means prioritization evidence, not proof of failure. Learned risk/impact outputs require versioned data and M8/M9 evaluation governance.
