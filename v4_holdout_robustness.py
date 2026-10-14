"""Research-only paired V3/V4 holdout diagnostics, without model fitting."""
from collections import Counter
from math import isfinite, sqrt
from statistics import mean

from v4_walkforward import evaluate_walkforward


def paired_holdout_report(rows, min_holdout_games=100):
    """Assess V4 vs locked V3 on the latest season, with no release authorization.

    The confidence interval is a descriptive normal approximation for paired
    absolute-error improvements; it is not valid under strong game dependence.
    """
    records = list(rows)
    baseline = evaluate_walkforward(records, min_holdout_games=min_holdout_games)
    season = baseline["holdout_season"]
    holdout = [r for r in records if int(r["season"]) == season]
    improvements = []
    for row in holdout:
        actual = float(row["actual_home_margin"])
        v3 = float(row["v3_home_margin"])
        v4 = float(row["v4_home_margin"])
        delta = abs(actual - v3) - abs(actual - v4)
        if not isfinite(delta):
            raise ValueError("nonfinite paired improvement")
        improvements.append(delta)
    n = len(improvements)
    wins = sum(d > 0 for d in improvements)
    losses = sum(d < 0 for d in improvements)
    ties = n - wins - losses
    avg = mean(improvements)
    variance = sum((d - avg) ** 2 for d in improvements) / (n - 1) if n > 1 else 0.0
    se = sqrt(variance / n)
    return {
        **baseline,
        "paired_games": n,
        "v4_better_games": wins,
        "v3_better_games": losses,
        "equal_error_games": ties,
        "paired_mean_improvement": avg,
        "paired_standard_error": se,
        "approx_95pct_lower": avg - 1.96 * se,
        "approx_95pct_upper": avg + 1.96 * se,
        "v4_positive_lower_bound": avg - 1.96 * se > 0,
        "release_ready": False,
        "limitations": "Normal-approximation uncertainty ignores cross-game correlation, selection bias and multiple testing; requires representative, independently verified point-in-time data. Research only.",
    }
