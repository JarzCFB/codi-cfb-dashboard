"""V4 research-only, season-held-out ridge adjustments against locked V3.

This is NOT an official betting model. Only independently authenticated, point-in-time
feature rows should be supplied. Never reconstruct features using postgame reports.
"""
from math import isfinite, sqrt
from random import Random
from v4_evidence_audit import FEATURES, _time

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
    # fit() is also callable directly, so reject malformed inputs here
    # rather than relying exclusively on evaluate()'s validation.
    for row in train:
        try:
            values = [float(row[f]) for f in FEATURES] + [
                float(row["actual_home_margin"]), float(row["v3_home_margin"])]
            if not all(isfinite(value) for value in values):
                raise ValueError("missing or nonfinite training value")
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError("missing or nonfinite training value") from exc
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
    weights = _solve(gram, rhs)
    return {"intercept": weights[0], "coefficients": dict(zip(FEATURES, weights[1:])),
            "means": means, "scales": scales, "weights": weights}

def predict(model, row):
    x = [1.0] + [(float(row[f]) - model["means"][j]) / model["scales"][j]
                 for j, f in enumerate(FEATURES)]
    return float(row["v3_home_margin"]) + sum(a*b for a, b in zip(model["weights"], x))

def _mae(rows, model=None):
    errors = [(predict(model, r) if model else float(r["v3_home_margin"]))
              - float(r["actual_home_margin"]) for r in rows]
    return sum(abs(e) for e in errors) / len(errors)

def _paired_mae_interval(v3_errors, v4_errors, draws=2000):
    """Deterministic paired game-level bootstrap; descriptive, not a release test."""
    if len(v3_errors) != len(v4_errors):
        raise ValueError("paired error arrays must have equal lengths")
    if not v3_errors:
        raise ValueError("empty holdout")
    if not isinstance(draws, int) or draws < 40:
        raise ValueError("bootstrap requires at least 40 integer draws")
    improvements = [abs(a) - abs(b) for a, b in zip(v3_errors, v4_errors)]
    if not all(isfinite(value) for value in improvements):
        raise ValueError("nonfinite paired holdout error")
    rng = Random(20261021)
    n = len(improvements)
    estimates = sorted(sum(improvements[rng.randrange(n)] for _ in range(n)) / n
                       for _ in range(draws))
    return [round(estimates[int(0.025 * draws)], 4),
            round(estimates[min(draws - 1, int(0.975 * draws))], 4)]


def evaluate(complete_rows, source_authenticity_verified=False):
    """Strict chronological season holdout. Never auto-promote V4."""
    output = {"status": "RESEARCH_ONLY", "release_ready": False,
              "source_authenticity_verified": bool(source_authenticity_verified),
              "complete_games": len(complete_rows), "evaluations": [],
              "warning": "No official V4 promotion; independent authentication and forward validation required."}
    if not source_authenticity_verified:
        output["reason"] = "Feature source authenticity not independently verified"
        return output
    seen = set()
    for row in complete_rows:
        gid = str(row.get("game_id") or "").strip()
        if not gid:
            raise ValueError("missing game ID in V4 evaluation")
        try:
            season = int(str(row.get("season", "")).strip())
        except (ValueError, TypeError):
            raise ValueError("invalid season in V4 evaluation") from None
        if season < 2000 or season > 2100:
            raise ValueError("invalid season in V4 evaluation")
        # An authenticated feature set is still unusable if the underlying
        # prediction snapshot was recorded at or after kickoff.
        try:
            captured = _time(row["captured_at_utc"])
            kickoff = _time(row["kickoff_utc"])
        except (KeyError, ValueError, TypeError) as exc:
            raise ValueError("missing or invalid pregame timestamps in V4 evaluation") from exc
        if captured >= kickoff:
            raise ValueError("V4 evaluation capture must precede kickoff")
        # Game identifiers are globally unique; reuse in another season can
        # place the same game in both training and holdout partitions.
        if gid in seen:
            raise ValueError("duplicate season/game ID in V4 evaluation")
        seen.add(gid)
        values = [row.get(f) for f in FEATURES] + [
            row.get("v3_home_margin"), row.get("actual_home_margin")]
        try:
            valid = all(isfinite(float(v)) for v in values)
        except (ValueError, TypeError):
            valid = False
        if not valid:
            raise ValueError("missing or nonfinite research value")
    seasons = sorted({int(r["season"]) for r in complete_rows})
    for season in seasons[1:]:
        train = [r for r in complete_rows if int(r["season"]) < season]
        test = [r for r in complete_rows if int(r["season"]) == season]
        if len(train) < MIN_TRAIN or len(test) < MIN_HOLDOUT:
            continue
        model = fit(train)
        baseline, candidate = _mae(test), _mae(test, model)
        v3_errors = [float(r["v3_home_margin"]) - float(r["actual_home_margin"]) for r in test]
        v4_errors = [predict(model, r) - float(r["actual_home_margin"]) for r in test]
        v3_rmse = sqrt(sum(e*e for e in v3_errors) / len(test))
        v4_rmse = sqrt(sum(e*e for e in v4_errors) / len(test))
        # Diagnostics only: a candidate must not be described as improved
        # when one error metric improves but the other deteriorates.
        both_errors_improved = candidate < baseline and v4_rmse < v3_rmse
        mae_interval = _paired_mae_interval(v3_errors, v4_errors)
        output["evaluations"].append({"holdout_season": season, "training_games": len(train),
            "holdout_games": len(test), "v3_mae": round(baseline, 4),
            "v4_mae": round(candidate, 4), "v4_mae_improvement": round(baseline-candidate, 4),
            "v3_rmse": round(v3_rmse, 4), "v4_rmse": round(v4_rmse, 4),
            "both_error_metrics_improved": both_errors_improved,
            "paired_mae_improvement_bootstrap_95pct": mae_interval,
            "bootstrap_draws": 2000,
            "holdout_improvement_claim_allowed": False,
            "improved_game_count": sum(abs(b) > abs(a) for b, a in zip(v3_errors, v4_errors)),
            "standardized_coefficients": model["coefficients"],
            "note": "Exploratory paired error diagnostics only; no authenticated historical V3-versus-V4 betting edge or ROI."})
    output["reason"] = ("No season holdout meets minimum sample requirements"
                        if not output["evaluations"] else
                        "Research holdout metrics only; independent forward betting ROI and governance approval still required")
    return output
