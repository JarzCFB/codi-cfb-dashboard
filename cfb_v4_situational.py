"""V4 research-only player and situational review; does not modify V3 or frozen picks.

No unsupported point adjustments: missing data is displayed as unknown, not zero impact.
The CSV is a curated, timestamped evidence ledger, not a live injury feed.
"""
import csv
from datetime import datetime, timezone
from pathlib import Path
from cfb_team_matching import canonical_school

FACTORS = ("quarterback", "star_player", "injury", "stadium", "travel", "rest", "weather", "rivalry", "big_game")
FIELDS = ("game_id", "team", "player", "position", "factor", "status", "source", "observed_at_utc", "notes", "impact_points")

def load_evidence(path="v4/evidence.csv"):
    path = Path(path)
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return [r for r in rows if r.get("factor") in FACTORS]

def review_games(projections, evidence, asof=None):
    """Add V4 review columns without touching original V3 projections."""
    asof = asof or datetime.now(timezone.utc)
    result = projections.copy()
    if result.empty:
        return result
    statuses, players, alerts, sources = [], [], [], []
    for _, game in result.iterrows():
        game_id = str(game.get("Game ID") or "")
        matchup = str(game.get("Matchup", ""))
        matched = []
        for item in evidence:
            if item.get("game_id") and str(item["game_id"]) != game_id:
                continue
            team = item.get("team", "").strip()
            if team and canonical_school(team).lower() not in matchup.lower():
                continue
            try:
                observed = datetime.fromisoformat(item["observed_at_utc"].replace("Z", "+00:00"))
                if observed.tzinfo is None or observed.astimezone(timezone.utc) > asof:
                    continue
            except (ValueError, KeyError, AttributeError):
                continue
            if not item.get("source", "").strip():
                continue
            matched.append(item)
        statuses.append("Evidence available — review required" if matched else "Not verified — do not assume healthy")
        players.append("; ".join(dict.fromkeys(
            (f'{r.get("player", "")} ({r.get("position", "")}: {r.get("status", "")})')
            for r in matched if r.get("player", "").strip()
        )) or "No verified standout-player report")
        alerts.append("; ".join(
            f'{r["factor"]}: {r.get("status", "unknown")} — {r.get("notes", "")}'.strip()
            for r in matched
        ) or "Injuries, key players, venue, travel, rest, weather and stakes unverified")
        sources.append("; ".join(dict.fromkeys(r["source"] for r in matched)))
    result["V4 verification"] = statuses
    result["V4 key players"] = players
    result["V4 situational notes"] = alerts
    result["V4 evidence sources"] = sources
    result["V4 adjusted margin"] = float("nan")
    result["V4 action"] = "Research only — no calibrated adjustment"
    return result
