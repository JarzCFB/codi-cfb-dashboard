"""V4 research-only player and situational review; does not modify V3 or frozen picks.

No unsupported point adjustments: missing data is displayed as unknown, not zero impact.
The CSV is a curated, timestamped evidence ledger, not a live injury feed.
"""
import csv
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import pandas as pd
from cfb_team_matching import canonical_school, match_rating, _NORMALIZED_ALIASES
import requests

FACTORS = ("quarterback", "star_player", "injury", "stadium", "travel", "rest", "weather", "rivalry", "big_game")
FIELDS = ("game_id", "team", "player", "position", "factor", "status", "source", "observed_at_utc", "notes", "impact_points")

def parse_evidence_csv(handle):
    """Parse evidence rows with a strict schema; parsing never verifies truth."""
    reader = csv.DictReader(handle)
    columns = set(reader.fieldnames or ())
    if not set(FIELDS).issubset(columns):
        raise ValueError("Evidence CSV missing columns: " + ", ".join(
            sorted(set(FIELDS) - columns)))
    rows = []
    for row in reader:
        if None in row:
            raise ValueError("Evidence CSV contains extra unheaded columns")
        if row.get("factor") not in FACTORS:
            raise ValueError("Unknown evidence factor: " + str(row.get("factor")))
        for required in ("game_id", "team", "status", "source", "observed_at_utc"):
            if not str(row.get(required) or "").strip():
                raise ValueError("Evidence CSV row missing " + required)
        source = urlparse(str(row["source"]).strip())
        if source.scheme != "https" or not source.hostname or source.username or source.password:
            raise ValueError("Evidence CSV requires an HTTPS source URL")
        try:
            observed = datetime.fromisoformat(str(row["observed_at_utc"]).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("Evidence CSV contains invalid observed_at_utc") from exc
        if observed.tzinfo is None:
            raise ValueError("Evidence CSV timestamps must include a timezone")
        if row["factor"] in ("quarterback", "star_player", "injury") and not str(row.get("player") or "").strip():
            raise ValueError("Player-specific evidence must name a player")
        rows.append(row)
    return rows


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
        for column in ("V4 verification", "V4 key players", "V4 situational notes", "V4 evidence sources", "V4 adjusted margin", "V4 action"):
            result[column] = pd.Series(dtype="float64" if column == "V4 adjusted margin" else "object")
        return result
    statuses, players, alerts, sources = [], [], [], []
    for _, game in result.iterrows():
        game_id = str(game.get("Game ID") if pd.notna(game.get("Game ID")) else "")
        matchup = str(game.get("Matchup", ""))
        teams = matchup.split(" @ ")
        allowed_teams = {canonical_school(_NORMALIZED_ALIASES.get(canonical_school(t), t)) for t in teams} if len(teams) == 2 else set()
        matched = []
        for item in evidence:
            # Never let a team-only observation leak into unrelated games.
            if not isinstance(item, dict) or not item.get("game_id") or str(item["game_id"]) != game_id:
                continue
            team = str(item.get("team") or "").strip()
            matched_team = match_rating(team, {name: True for name in allowed_teams})[1] if team else None
            if not matched_team:
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

def cfbd_team_name(team):
    """Convert known sportsbook school+nickname names to CFBD school names.

    Unknown labels pass through unchanged rather than guessing a different
    school (for example Texas Southern must not become Texas).
    """
    from cfb_team_matching import normalize
    normalized = normalize(team)
    canonical = _NORMALIZED_ALIASES.get(normalized)
    if canonical:
        return canonical
    return str(team).strip()


def fetch_player_stats(api_key, year, team, timeout=12):
    """CFBD player-season production, not injury or availability data.

    Returns (players, error). All players are ranked by available cumulative
    statistical production within their *own category*; cross-position value
    and point spreads cannot be inferred from these numbers.
    """
    if not api_key:
        return [], "CFBD API key unavailable"
    if not isinstance(team, str) or not team.strip():
        return [], "Team name unavailable"
    try:
        response = requests.get(
            "https://api.collegefootballdata.com/stats/player/season",
            params={"year": int(year), "team": cfbd_team_name(team)},
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
            if not name or not category or not stat_type or not pd.notna(value) or value == float("inf") or value == float("-inf") or value < 0:
                continue
            output.append({"player": str(name), "category": str(category),
                           "stat_type": str(stat_type), "value": value})
        return output, None
    except (requests.RequestException, ValueError, TypeError) as exc:
        return [], f"CFBD player statistics unavailable: {type(exc).__name__}"

def _valid_player_reports(player, team, evidence, game_id, kickoff_utc, asof):
    """Select only reports known at the analysis cutoff and before kickoff."""
    if asof.tzinfo is None:
        raise ValueError("asof must be timezone-aware")
    kick = pd.to_datetime(kickoff_utc, utc=True, errors="coerce")
    if pd.isna(kick):
        return []
    target = canonical_school(_NORMALIZED_ALIASES.get(canonical_school(team), team))
    relevant = []
    for row in evidence:
        if not isinstance(row, dict) or str(row.get("game_id") or "") != str(game_id):
            continue
        school = canonical_school(_NORMALIZED_ALIASES.get(canonical_school(row.get("team")), row.get("team")))
        if school != target or str(row.get("player") or "").strip().casefold() != str(player).strip().casefold():
            continue
        if row.get("factor") not in ("quarterback", "star_player", "injury"):
            continue
        source = urlparse(str(row.get("source") or "").strip())
        if source.scheme != "https" or not source.hostname or source.username or source.password:
            continue
        try:
            observed = datetime.fromisoformat(str(row["observed_at_utc"]).replace("Z", "+00:00"))
            if observed.tzinfo is None or observed > asof or observed >= kick.to_pydatetime():
                continue
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
        relevant.append((observed, row))
    return relevant

def player_availability(player, team, evidence, game_id, kickoff_utc=None, asof=None):
    """Game-specific, point-in-time report label; never infer from statistics.

    Fail closed when kickoff or timestamp is unavailable. Source links are
    metadata, not independent verification of a player's status.
    """
    asof = asof or datetime.now(timezone.utc)
    relevant = _valid_player_reports(player, team, evidence, game_id, kickoff_utc, asof)
    if not relevant:
        return "Unknown — no time-valid game-specific report"
    latest = max(observed for observed, _ in relevant)
    statuses = {str(row.get("status") or "").strip().lower() for observed, row in relevant if observed == latest}
    if len(statuses) != 1 or "" in statuses:
        return "Conflicting or incomplete reports — review"
    return "Reported: " + next(iter(statuses)) + " (not independently verified)"


def player_report_details(player, team, evidence, game_id, kickoff_utc=None, asof=None):
    """Provide auditable, point-in-time report metadata for the UI."""
    asof = asof or datetime.now(timezone.utc)
    relevant = _valid_player_reports(player, team, evidence, game_id, kickoff_utc, asof)
    if not relevant:
        return {"status": "Unknown", "observed_at_utc": "", "sources": ""}
    latest = max(observed for observed, _ in relevant)
    current = [row for observed, row in relevant if observed == latest]
    statuses = {str(row.get("status") or "").strip().lower() for row in current}
    status = next(iter(statuses)) if len(statuses) == 1 and "" not in statuses else "Conflicting — review"
    sources = "; ".join(dict.fromkeys(str(row["source"]) for row in current))
    return {"status": status + " (source-linked, not verified)",
            "observed_at_utc": latest.astimezone(timezone.utc).isoformat(),
            "sources": sources}

def report_freshness(observed_at_utc, asof=None, max_age_hours=72):
    """Classify report age; source age is not evidence of player health."""
    asof = asof or datetime.now(timezone.utc)
    if asof.tzinfo is None:
        raise ValueError("asof must be timezone-aware")
    if not observed_at_utc:
        return "No report"
    try:
        observed = datetime.fromisoformat(str(observed_at_utc).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return "Invalid timestamp"
    if observed.tzinfo is None or observed > asof:
        return "Invalid or future report"
    age_hours = (asof - observed).total_seconds() / 3600
    return "Older report — recheck" if age_hours > max_age_hours else "Recent report — still verify"

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

