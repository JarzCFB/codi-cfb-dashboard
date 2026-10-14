"""Research-only V4 residual model. Locked V3 is never modified."""
from datetime import datetime, timezone
from v4_evidence_audit import _valid_feature
import math
import numpy as np

FEATURES = ("qb_out_diff", "key_players_out_diff", "rest_days_diff", "travel_miles_diff", "wind_mph", "neutral_site")
REQUIRED = ("game_id", "season", "kickoff_utc", "captured_at_utc", "actual_home_margin", "v3_home_margin") + FEATURES

def _timestamp(value):
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamps must have timezone")
    return dt.astimezone(timezone.utc)

def evaluate_candidate(rows, min_train=200, min_holdout=100, ridge=100.0):
    """Train on past seasons and score latest season without fitting to holdout."""
    if (type(min_train) is not int or type(min_holdout) is not int or
            min_train < 1 or min_holdout < 1 or not math.isfinite(float(ridge)) or ridge <= 0):
        raise ValueError("invalid evaluation configuration")
    records, seen = [], set()
    for row in rows:
        if any(k not in row or str(row[k]).strip() == "" for k in REQUIRED):
            raise ValueError("missing feature: unknown must not be treated as zero")
        gid = str(row["game_id"])
        if gid in seen:
            raise ValueError("duplicate game_id")
        seen.add(gid)
        if _timestamp(row["captured_at_utc"]) >= _timestamp(row["kickoff_utc"]):
            raise ValueError("future-known or post-kickoff record")
        values = np.asarray([float(row[k]) for k in ("actual_home_margin", "v3_home_margin") + FEATURES])
        if not np.isfinite(values).all():
            raise ValueError("nonfinite data")
        for feature in FEATURES:
            _valid_feature(feature, row[feature])
        records.append((int(row["season"]), values))
    seasons = sorted({season for season, _ in records})
    if len(seasons) < 2:
        raise ValueError("need earlier and later seasons")
    holdout_year = seasons[-1]
    train = [v for season, v in records if season < holdout_year]
    test = [v for season, v in records if season == holdout_year]
    if len(train) < min_train or len(test) < min_holdout:
        raise ValueError("insufficient train or holdout games")
    train, test = np.asarray(train), np.asarray(test)
    center = train[:, 2:].mean(axis=0)
    scale = train[:, 2:].std(axis=0)
    scale[scale == 0] = 1
    x = np.column_stack((np.ones(len(train)), (train[:, 2:] - center) / scale))
    xt = np.column_stack((np.ones(len(test)), (test[:, 2:] - center) / scale))
    target = train[:, 0] - train[:, 1]
    regularizer = np.eye(x.shape[1]) * ridge
    regularizer[0, 0] = 0
    coefficients = np.linalg.solve(x.T @ x + regularizer, x.T @ target)
    predicted = test[:, 1] + xt @ coefficients
    v3_mae = float(np.mean(np.abs(test[:, 0] - test[:, 1])))
    v4_mae = float(np.mean(np.abs(test[:, 0] - predicted)))
    return {"holdout_season": holdout_year, "training_games": len(train), "holdout_games": len(test),
            "v3_mae": v3_mae, "v4_candidate_mae": v4_mae, "improvement": v3_mae - v4_mae,
            "candidate_beats_v3": bool(v4_mae < v3_mae), "release_ready": False,
            "note": "Research only. Source provenance, point-in-time validity and further validation required."}
