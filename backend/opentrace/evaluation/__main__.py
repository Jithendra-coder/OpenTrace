"""Run the canonical formal evaluator."""

from opentrace.evaluation.pipeline import run_m9_evaluation

if __name__ == "__main__":
    result = run_m9_evaluation()
    print(result.formal_manifest)
