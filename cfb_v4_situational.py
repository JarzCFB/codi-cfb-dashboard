"""V4 research-only player and situational review; does not modify V3 or frozen picks.

No unsupported point adjustments: missing data is displayed as unknown, not zero impact.
The CSV is a curated, timestamped evidence ledger, not a live injury feed.
"""
import csv
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import pandas as pd
from cfb_team_matching import canonical_school, normalize, ALIASES
import requests

FACTORS = ("quarterback", "star_player", "injury", "stadium", "travel", "rest", "weather", "rivalry", "big_game")
FIELDS = ("game_id", "team", "player", "position", "factor", "status", "source", "observed_at_utc", "notes", "impact_points")

def parse_evidence_csv(handle):
    """Parse a CSV upload and fail closed on missing required columns.

    Parsing does not certify truth of any report; review_games enforces game,
    team, source URL and time constraints before displaying it.
    """
    rows = list(csv.DictReader(handle))
    if not rows and not getattr(handle, "seekable", lambda: False)():
        return []
    if getattr(handle, "seekable", lambda: False)():
        handle.seek(0)
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or ())
        if not set(FIELDS).issubset(columns):
            raise ValueError("Evidence CSV missing columns: " + ", ".join(sorted(set(FIELDS) - columns)))
        rows = list(reader)
    return [r for r in rows if r.get("factor") in FACTORS]


def load_evidence(path="v4/evidence.csv"):
    path = Path(path)
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return parse_evidence_csv(handle)

def review_games(projections, evidence, asof=None):
    """Add V4 review columns without touching original V3 projections."""
    asof = asof or datetime.now(timezone.utc)
    if asof.tzinfo is None:
        raise ValueError("asof must be timezone-aware")
    result = projections.copy()
    if result.empty:
        return result
    statuses, players, alerts, sources = [], [], [], []
    for _, game in result.iterrows():
        game_id = str(game.get("Game ID") if pd.notna(game.get("Game ID")) else "")
        matchup = str(game.get("Matchup", ""))
        teams = matchup.split(" @ ")
        allowed_teams = {canonical_school(ALIASES.get(normalize(t), t)) for t in teams} if len(teams) == 2 else set()
        matched = []
        for item in evidence:
            # Never let a team-only observation leak into unrelated games.
            if not isinstance(item, dict) or not item.get("game_id") or str(item["game_id"]) != game_id:
                continue
            team = str(item.get("team") or "").strip()
            if not team or canonical_school(ALIASES.get(normalize(team), team)) not in allowed_teams:
                continue
            try:
                observed = datetime.fromisoformat(str(item["observed_at_utc"]).replace("Z", "+00:00"))
                kickoff = game.get("Kickoff UTC")
                kick = pd.to_datetime(kickoff, utc=True, errors="coerce")
                if observed.tzinfo is None or observed.astimezone(timezone.utc) > asof or pd.isna(kick) or observed >= kick.to_pydatetime():
                    continue
            except (ValueError, KeyError, AttributeError):
                continue
            source = urlparse(str(item.get("source") or "").strip())
            if source.scheme != "https" or not source.hostname or source.username or source.password or source.hostname in ("localhost", "127.0.0.1"):
                continue
            if item.get("factor") not in FACTORS:
                continue
            matched.append(item)
        statuses.append("Source-linked report — independently verify" if matched else "Not verified — do not assume healthy")
        players.append("; ".join(dict.fromkeys(
            (f'{r.get("player", "")} ({r.get("position", "")}: {r.get("status", "")})')
            for r in matched if str(r.get("player") or "").strip()
        )) or "No source-linked standout-player report")
        alerts.append("; ".join(
            f'{r["factor"]}: {r.get("status", "unknown")} — {r.get("notes", "")}'.strip()
            for r in matched
        ) or "Injuries, key players, venue, travel, rest, weather and stakes unverified")
        sources.append("; ".join(dict.fromkeys(str(r["source"]) for r in matched)))
    result["V4 verification"] = statuses
    result["V4 key players"] = players
    result["V4 situational notes"] = alerts
    result["V4 evidence sources"] = sources
    result["V4 adjusted margin"] = float("nan")
    result["V4 action"] = "Research only — no calibrated adjustment"
    return result

def fetch_player_stats(api_key, year, team, timeout=12):
    """CFBD player-season production, not injury or availability data.

    Returns (players, error). All players are ranked by available cumulative
    statistical production within their *own category*; cross-position value
    and point spreads cannot be inferred from these numbers.
    """
    if not api_key:
        return [], "CFBD API key unavailable"
    try:
        response = requests.get(
            "https://api.collegefootballdata.com/stats/player/season",
            params={"year": int(year), "team": team},
            headers={"Authorization": "Bearer " + api_key},
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            return [], "Unexpected CFBD player-stat response"
        output = []
        for record in payload:
            if not isinstance(record, dict):
                continue
            name = record.get("player")
            category = record.get("category")
            stat_type = record.get("statType")
            try:
                value = float(str(record.get("stat", "")).replace(",", ""))
            except (ValueError, TypeError):
                continue
            if not name or not category or not stat_type or not pd.notna(value) or value == float("inf") or value == float("-inf"):
                continue
            output.append({"player": str(name), "category": str(category),
                           "stat_type": str(stat_type), "value": value})
        return output, None
    except (requests.RequestException, ValueError, TypeError) as exc:
        return [], f"CFBD player statistics unavailable: {type(exc).__name__}"

def standout_players(stats, limit=6):
    """Select production leaders with an explicit metric; not a talent ranking."""
    preferred = (("passing", "YDS"), ("rushing", "YDS"),
                 ("receiving", "YDS"), ("defensive", "TOT"),
                 ("defensive", "SACKS"), ("kicking", "PTS"))
    selected = []
    seen = set()
    for category, metric in preferred:
        candidates = [r for r in stats if r.get("category", "").lower() == category
                      and r.get("stat_type", "").upper() == metric
                      and isinstance(r.get("value"), (int, float))]
        candidates.sort(key=lambda r: r["value"], reverse=True)
        for item in candidates[:2]:
            if item["player"] not in seen:
                selected.append(item)
                seen.add(item["player"])
                break
        if len(selected) >= limit:
            break
    return selected[:limit]


def evidence_coverage(review):
    """Return counts for the V4 source-review queue; never a health estimate."""
    if review.empty or "V4 verification" not in review:
        return {"games": 0, "source_linked": 0, "unverified": 0}
    total = len(review)
    linked = int(review["V4 verification"].str.startswith("Source-linked report").sum())
    return {"games": total, "source_linked": linked, "unverified": total - linked}

