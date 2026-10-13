"""Fail-closed V4 historical evaluation; never writes official V3 selections.

Input records must be immutable pregame snapshots with independent outcomes.
A passing metric is not proof of deployability or injury-feed correctness.
"""
import math
from datetime import datetime, timezone
from statistics import mean

REQUIRED = ("game_id", "season", "kickoff_utc", "captured_at_utc",
            "actual_home_margin", "v3_home_margin", "v4_home_margin")

def _timestamp(value):
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return dt.astimezone(timezone.utc)

def evaluate_walkforward(rows, min_holdout_games=100):
    """Compare frozen pregame V3/V4 predictions on later, unseen seasons.

    Fails closed on duplicates, missing predictions, future-known snapshots,
    invalid values, or insufficient held-out games. No model is fitted here.
    """
    if not isinstance(min_holdout_games, int) or min_holdout_games < 1:
        raise ValueError("min_holdout_games must be a positive integer")
    records = list(rows)
    if not records:
        raise ValueError("no historical snapshots supplied")
    seen = set()
    parsed = []
    for row in records:
        if not all(k in row and str(row[k]).strip() for k in REQUIRED):
            raise ValueError("snapshot missing required fields")
        game_id = str(row["game_id"]).strip()
        if game_id in seen:
            raise ValueError("duplicate game_id")
        seen.add(game_id)
        season = int(row["season"])
        kickoff = _timestamp(row["kickoff_utc"])
        captured = _timestamp(row["captured_at_utc"])
        if captured >= kickoff:
            raise ValueError("snapshot was not captured before kickoff")
        numbers = [float(row[k]) for k in ("actual_home_margin", "v3_home_margin", "v4_home_margin")]
        if not all(math.isfinite(n) for n in numbers):
            raise ValueError("nonfinite game margin")
        parsed.append((season, *numbers))
    seasons = sorted({r[0] for r in parsed})
    if len(seasons) < 2:
        raise ValueError("need separate earlier and held-out seasons")
    holdout_season = seasons[-1]
    holdout = [r for r in parsed if r[0] == holdout_season]
    if len(holdout) < min_holdout_games:
        raise ValueError("insufficient games in latest held-out season")
    v3_errors = [abs(r[1] - r[2]) for r in holdout]
    v4_errors = [abs(r[1] - r[3]) for r in holdout]
    v3_mae, v4_mae = mean(v3_errors), mean(v4_errors)
    return {"holdout_season": holdout_season, "holdout_games": len(holdout),
            "v3_mae": v3_mae, "v4_mae": v4_mae,
            "v4_mae_improvement": v3_mae - v4_mae,
            "v4_beats_v3_on_mae": v4_mae < v3_mae,
            "release_ready": False,
            "note": "Research-only. Requires verified point-in-time inputs, independently calibrated V4, and additional release gates."}
