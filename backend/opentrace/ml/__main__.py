from opentrace.ml.pipeline import run_m8_experiments

if __name__ == "__main__":
    result = run_m8_experiments()
    print(result.metrics_file)
