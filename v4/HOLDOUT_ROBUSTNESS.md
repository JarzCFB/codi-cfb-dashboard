# Paired holdout robustness (research only)

Use `paired_holdout_report(rows, min_holdout_games=100)` with the existing
`v4_walkforward` snapshot contract. It first invokes the fail-closed
walk-forward validator and evaluates only the latest held-out season.

The report includes paired V3/V4 absolute-error wins, losses and ties, mean
MAE improvement, standard error and a descriptive normal-approximation 95%
interval. The interval assumes independent game errors and is **not** a
production-ready significance test. Games may be correlated, and repeated
feature tuning can inflate apparent significance.

This does not fit a model, validate the provenance of input data, change
official V3, or authorize V4 predictions. `release_ready` remains false.

Run: `python -m unittest test_v4_holdout_robustness test_v4_walkforward`.
