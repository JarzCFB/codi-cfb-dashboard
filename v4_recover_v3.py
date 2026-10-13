"""Read-only import of archived prospective V3 ATS audit for V4 research."""
import csv
from datetime import datetime
from math import isfinite

def _utc(value):
    d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if d.tzinfo is None:
        raise ValueError("timestamps require UTC offsets")
    return d

def recover_v3_audit(rows):
    """Never edit official picks; separate settled outcomes from pending games."""
    result, seen = [], set()
    required = ("game_id", "season", "kickoff_utc", "captured_at_utc",
                "projected_home_margin", "grading_status", "model_version")
    for row in rows:
        if any(str(row.get(k, "")).strip() == "" for k in required):
            raise ValueError("missing required prospective audit field")
        if str(row["model_version"]).lower() != "v3":
            raise ValueError("expected V3-only audit")
        game_id = str(row["game_id"])
        if game_id in seen:
            raise ValueError("duplicate game id")
        seen.add(game_id)
        if _utc(row["captured_at_utc"]) >= _utc(row["kickoff_utc"]):
            raise ValueError("post-kickoff prediction is not prospective")
        margin = float(row["projected_home_margin"])
        if not isfinite(margin):
            raise ValueError("invalid V3 margin")
        status = str(row["grading_status"]).lower()
        if status not in ("settled", "pending"):
            raise ValueError("unsupported grading status")
        actual = None
        if status == "settled":
            if str(row.get("actual_home_margin", "")).strip() == "":
                raise ValueError("settled game missing outcome")
            actual = float(row["actual_home_margin"])
            if not isfinite(actual):
                raise ValueError("invalid final margin")
        result.append({"game_id": game_id, "season": int(row["season"]),
                       "kickoff_utc": row["kickoff_utc"], "captured_at_utc": row["captured_at_utc"],
                       "home_team": row.get("home_team", ""), "away_team": row.get("away_team", ""),
                       "v3_home_margin": margin, "actual_home_margin": actual,
                       "source_grading_status": status,
                       "v4_feature_verification": "NOT_COLLECTED"})
    return result

def recovery_summary(rows):
    settled = [r for r in rows if r["source_grading_status"] == "settled"]
    return {"total_games": len(rows), "settled": len(settled),
            "pending": len(rows) - len(settled),
            "seasons": sorted({r["season"] for r in rows}),
            "settled_v3_mae": (sum(abs(r["actual_home_margin"] - r["v3_home_margin"]) for r in settled) / len(settled)) if settled else None,
            "v4_training_ready": False,
            "warning": "Selected prospective V3 plays only; no verified situational features or multi-season calibration."}
