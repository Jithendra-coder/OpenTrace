# ML Evaluation Plan

ML evaluation uses frozen versioned datasets/splits from `15_DATASET_AND_LABELING_PLAN.md`, simple baselines, held-out repositories/scenarios, and experiment records. Report ranking metrics (P@K/R@K, MRR, NDCG), classification metrics, Brier score/ECE, calibration plots/tables, confidence intervals where feasible, per-slice results, error analysis, and compute/cost.

Select models without touching held-out test data; evaluate calibration only after training selection. Compare learned systems against heuristic and policy baselines. Claims must cite experiment id, data version, split and reproduction command; no fabricated or unqualified generalization claims.
