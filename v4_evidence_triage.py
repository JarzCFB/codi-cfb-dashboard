"""Read-only V4 evidence collection triage. Never infers injuries or validates URLs."""
from datetime import datetime, timezone
import csv
import io

FEATURES = ("qb_out_diff", "key_players_out_diff", "rest_days_diff",
            "travel_miles_diff", "wind_mph", "neutral_site")

def _utc(value):
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamps must include UTC offset")
    return result.astimezone(timezone.utc)

def triage_rows(baseline, evidence=()):
    """One row per game, with capture lead time and unknown features.

    Report publication schedules are not evidence of actual availability.
    Do not infer statuses from conference affiliation or blank reports.
    """
    known = set()
    games = {str(r["game_id"]): r for r in baseline}
    if len(games) != len(baseline):
        raise ValueError("duplicate baseline game")
    for item in evidence:
        gid, feature = str(item["game_id"]), str(item["feature"])
        if gid not in games or feature not in FEATURES:
            raise ValueError("unknown game or feature")
        if (gid, feature) in known:
            raise ValueError("duplicate evidence")
        known.add((gid, feature))
    result = []
    for gid, base in games.items():
        capture = _utc(base["captured_at_utc"])
        kickoff = _utc(base["kickoff_utc"])
        hours = (kickoff - capture).total_seconds() / 3600
        if hours <= 0:
            raise ValueError("capture must precede kickoff")
        missing = [f for f in FEATURES if (gid, f) not in known]
        result.append({
            "game_id": gid, "season": base["season"],
            "home_team": base.get("home_team", ""),
            "away_team": base.get("away_team", ""),
            "captured_at_utc": base["captured_at_utc"],
            "kickoff_utc": base["kickoff_utc"],
            "lead_hours": round(hours, 2),
            "capture_window": "more_than_72h" if hours > 72 else
                              "24_to_72h" if hours > 24 else
                              "within_24h",
            "source_grading_status": base["source_grading_status"],
            "missing_feature_count": len(missing),
            "missing_features": "|".join(missing),
            "priority": "settled" if base["source_grading_status"] == "settled" else "pending",
            "caution": "Verify publication <= original capture; never substitute later reports",
        })
    return sorted(result, key=lambda r: (r["priority"] != "settled", r["kickoff_utc"], r["game_id"]))

def triage_csv(rows):
    output = io.StringIO()
    fields = ("game_id", "season", "home_team", "away_team", "captured_at_utc",
              "kickoff_utc", "lead_hours", "capture_window", "source_grading_status",
              "missing_feature_count", "missing_features", "priority", "caution")
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()
