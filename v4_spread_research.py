"""V4 research-only, season-held-out ridge adjustments against locked V3.

This is NOT an official betting model. Only independently authenticated, point-in-time
feature rows should be supplied. Never reconstruct features using postgame reports.
"""
from collections import defaultdict
from math import isfinite, sqrt
from v4_evidence_audit import FEATURES

MIN_TRAIN = 200
MIN_HOLDOUT = 100
RIDGE = 100.0

def _solve(matrix, target):
    """Small dense linear system with partial pivoting; no external dependency."""
    n = len(target)
    a = [list(matrix[i]) + [target[i]] for i in range(n)]
    for k in range(n):
        pivot = max(range(k, n), key=lambda i: abs(a[i][k]))
        if abs(a[pivot][k]) < 1e-10:
            raise ValueError("singular research fit")
        a[k], a[pivot] = a[pivot], a[k]
        div = a[k][k]
        for j in range(k, n + 1):
            a[k][j] /= div
        for i in range(n):
            if i == k:
                continue
            factor = a[i][k]
            for j in range(k, n + 1):
                a[i][j] -= factor * a[k][j]
    return [a[i][-1] for i in range(n)]

def fit(train):
    if len(train) < MIN_TRAIN:
        raise ValueError("insufficient independently verified training games")
    means = [sum(float(r[f]) for r in train) / len(train) for f in FEATURES]
    scales = [max(sqrt(sum((float(r[f]) - means[j]) ** 2 for r in train) / len(train)), 1.0)
              for j, f in enumerate(FEATURES)]
    xs = [[1.0] + [(float(r[f]) - means[j]) / scales[j] for j, f in enumerate(FEATURES)]
          for r in train]
    ys = [float(r["actual_home_margin"]) - float(r["v3_home_margin"]) for r in train]
    n = len(FEATURES) + 1
    gram = [[sum(x[i] * x[j] for x in xs) + (RIDGE if i == j and i else 0.0)
             for j in range(n)] for i in range(n)]
    rhs = [sum(x[i] * y for x, y in zip(xs, ys)) for i in range(n)]
    return {"intercept": _solve(gram, rhs)[0], "coefficients": None, "means": means,
            "scales": scales, "weights": _solve(gram, rhs)}

def predict(model, row):
    x = [1.0] + [(float(row[f]) - model["means"][j]) / model["scales"][j]
                 for j, f in enumerate(FEATURES)]
    return float(row["v3_home_margin"]) + sum(a*b for a, b in zip(model["weights"], x))

def _mae(rows, model=None):
    errors = [(predict(model, r) if model else float(r["v3_home_margin"]))
              - float(r["actual_home_margin"]) for r in rows]
    return sum(abs(e) for e in errors) / len(errors)

def evaluate(complete_rows, source_authenticity_verified=False):
    """Strict chronological season holdout. Never auto-promote V4."""
    output = {"status": "RESEARCH_ONLY", "release_ready": False,
              "source_authenticity_verified": bool(source_authenticity_verified),
              "complete_games": len(complete_rows), "evaluations": [],
              "warning": "No official V4 promotion; independent authentication and forward validation required."}
    if not source_authenticity_verified:
        output["reason"] = "Feature source authenticity not independently verified"
        return output
    seasons = sorted({int(r["season"]) for r in complete_rows})
    for season in seasons[1:]:
        train = [r for r in complete_rows if int(r["season"]) < season]
        test = [r for r in complete_rows if int(r["season"]) == season]
        if len(train) < MIN_TRAIN or len(test) < MIN_HOLDOUT:
            continue
        for row in train + test:
            values = [row.get(f) for f in FEATURES] + [row.get("v3_home_margin"), row.get("actual_home_margin")]
            if not all(isfinite(float(v)) for v in values):
                raise ValueError("nonfinite research value")
        model = fit(train)
        baseline, candidate = _mae(test), _mae(test, model)
        output["evaluations"].append({"holdout_season": season, "training_games": len(train),
            "holdout_games": len(test), "v3_mae": round(baseline, 4),
            "v4_mae": round(candidate, 4), "v4_mae_improvement": round(baseline-candidate, 4)})
    output["reason"] = ("No season holdout meets minimum sample requirements"
                        if not output["evaluations"] else
                        "Research holdout metrics only; independent forward betting ROI and governance approval still required")
    return output
