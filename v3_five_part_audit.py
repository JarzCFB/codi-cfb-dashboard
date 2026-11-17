"""Read-only V3 five-part research audit. Never alters official V3 picks or ratings."""
import csv
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "reports" / "v3_five_part_audit.json"

def rows(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))

def number(value):
    try:
        v = float(value)
        return v if math.isfinite(v) else None
    except (ValueError, TypeError):
        return None

def stamp(value):
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None

def summary(items):
    settled = [r for r in items if r.get("grading_status") == "settled"
               and r.get("selection_result") in ("win", "loss", "push")]
    w = sum(r["selection_result"] == "win" for r in settled)
    l = sum(r["selection_result"] == "loss" for r in settled)
    profit = sum(number(r.get("one_unit_profit")) or 0 for r in settled)
    return dict(selections=len(items), settled=len(settled), wins=w, losses=l,
                pushes=len(settled)-w-l, net_units=round(profit, 4),
                roi=round(profit/len(settled), 4) if settled else None)

def side_spread(row):
    s = number(row.get("spread"))
    if s is None:
        return None
    if row.get("selection") == row.get("home_team"):
        return s
    if row.get("selection") == row.get("away_team"):
        return -s
    return None

def quote_key(r):
    return (r.get("season"), r.get("game_id"), r.get("sportsbook_key"))

def validate_quotes(picks, snapshots):
    by_key = defaultdict(list)
    for q in snapshots:
        if q.get("capture_status") != "timestamped_live_quote":
            continue
        t, kick = stamp(q.get("captured_at_utc")), stamp(q.get("kickoff_utc"))
        if not t or not kick or t >= kick:
            continue
        if any(v and stamp(v) and stamp(v) > t for v in
               (q.get("market_last_update_utc"), q.get("bookmaker_last_update_utc"))):
            continue
        if side_spread(q) is None:
            continue
        by_key[quote_key(q)].append(q)
    result = []
    for p in picks:
        base = dict(game_id=p.get("game_id"), kickoff_utc=p.get("kickoff_utc"),
                    matchup=p.get("away_team", "")+" @ "+p.get("home_team", ""),
                    selection=p.get("selection"), sportsbook_key=p.get("sportsbook_key"))
        kick = stamp(p.get("kickoff_utc"))
        capture = stamp(p.get("captured_at_utc"))
        frozen = number(p.get("spread"))
        if not kick or not capture or capture >= kick or frozen is None:
            result.append(dict(base, status="INVALID_FROZEN_PICK")); continue
        valid = [q for q in by_key[quote_key(p)] if q.get("home_team") == p.get("home_team")
                 and q.get("away_team") == p.get("away_team")
                 and stamp(q.get("captured_at_utc")) <= kick]
        valid.sort(key=lambda q: stamp(q["captured_at_utc"]))
        if not valid:
            result.append(dict(base, status="UNVERIFIED_NO_MATCHING_LIVE_SNAPSHOT")); continue
        latest = valid[-1]
        home = side_spread(latest)
        selected = home if p["selection"] == p["home_team"] else -home
        movement = selected-frozen
        age_hours = (kick-stamp(latest["captured_at_utc"])).total_seconds()/3600
        price = number(latest.get("american_odds"))
        status = ("REVIEW_EXTREME_MOVE" if abs(movement) >= 7 else
                  "REVIEW_LARGE_MOVE" if abs(movement) >= 3 else
                  "STALE_QUOTE" if age_hours > 6 else
                  "REVIEW_PRICE" if price is None or not -200 <= price <= 200 else "VERIFIED")
        result.append(dict(base, status=status, frozen_spread=frozen,
                           latest_spread=selected, movement_points=round(movement, 3),
                           quote_age_hours=round(age_hours, 2),
                           latest_quote_utc=latest["captured_at_utc"], latest_odds=price))
    return result, by_key

def clv(picks, by_key):
    output = []
    for p in picks:
        kick = stamp(p.get("kickoff_utc"))
        if not kick:
            continue
        options = [q for q in by_key[quote_key(p)] if
                   q.get("home_team") == p.get("home_team") and
                   q.get("away_team") == p.get("away_team") and
                   stamp(q["captured_at_utc"]) < kick]
        if not options:
            continue
        latest = max(options, key=lambda q: stamp(q["captured_at_utc"]))
        minutes = (kick-stamp(latest["captured_at_utc"])).total_seconds()/60
        if minutes > 60:
            continue
        home = side_spread(latest)
        close = home if p["selection"] == p["home_team"] else -home
        frozen = number(p.get("spread"))
        if frozen is None:
            continue
        output.append(dict(game_id=p["game_id"], selection=p["selection"],
                           book=p.get("sportsbook_key"), close_proxy_spread=close,
                           frozen_spread=frozen, clv_points=round(frozen-close, 3),
                           quote_minutes_before_kickoff=round(minutes, 1),
                           warning="Last observed same-book pregame quote, NOT verified true closing line"))
    return output

def walk_forward(picks):
    """Evaluate fixed 3 vs 5 threshold in chronological calendar weeks; no re-fitting."""
    groups = defaultdict(list)
    for p in picks:
        dt = stamp(p.get("kickoff_utc"))
        if dt and number(p.get("edge_points")) is not None:
            year, week, _ = dt.isocalendar()
            groups[f"{year}-W{week:02d}"].append(p)
    return [dict(week=week, threshold_3=summary(group),
                 threshold_5=summary([r for r in group if number(r.get("edge_points")) >= 5]))
            for week, group in sorted(groups.items())]

def run(picks, snapshots):
    v3 = [r for r in picks if r.get("model_version") == "v3"]
    quote_audit, by_key = validate_quotes(v3, snapshots)
    spread_buckets = {}
    for name, low, high in [("0_to_under_3", 0, 3), ("3_to_under_7", 3, 7),
                            ("7_to_under_14", 7, 14), ("14_plus", 14, float("inf"))]:
        spread_buckets[name] = summary([r for r in v3 if number(r.get("spread")) is not None
                                        and low <= abs(float(r["spread"])) < high])
    clv_rows = clv(v3, by_key)
    return {
        "research_only": True,
        "official_v3_unchanged": True,
        "data_limitations": [
            "Historical outcomes used for descriptive analysis only; threshold choice is not an out-of-sample discovery.",
            "A valid true closing line is unavailable without a verified closing-feed quote.",
            "Recent-game weighting cannot be honestly evaluated from selected-bet ledger alone: requires timestamped pregame ratings for all games and chronological retraining.",
            "A frozen pick is not a live executable wager; same-book prices and kickoff must be rechecked."
        ],
        "part_1_thresholds": {str(t): summary([r for r in v3 if
                              number(r.get("edge_points")) is not None and
                              number(r["edge_points"]) >= t]) for t in (3, 5, 7)},
        "part_1_week_by_week_fixed_thresholds": walk_forward(v3),
        "part_2_line_validation": {
            "status_counts": {s: sum(r["status"] == s for r in quote_audit)
                              for s in sorted({r["status"] for r in quote_audit})},
            "details": quote_audit},
        "part_3_spread_buckets": spread_buckets,
        "part_4_recent_weighting": {
            "status": "NOT_RUN_MISSING_FULL_POINT_IN_TIME_RATINGS",
            "required": "Historical all-game pre-kickoff team ratings, dates, opponent strengths and final margins; rolling-origin backtest with no future games"},
        "part_5_closing_line_proxy": {
            "definition": "Frozen selected spread minus last same-book observed selected spread within 60 minutes before kickoff; positive is favorable",
            "sample_size": len(clv_rows),
            "average_clv_points": round(sum(r["clv_points"] for r in clv_rows)/len(clv_rows), 3) if clv_rows else None,
            "details": clv_rows}
    }

def main():
    graded = rows(ROOT / "prospective" / "graded_selections.csv")
    snapshots = []
    folder = ROOT / "snapshots"
    if folder.exists():
        for path in sorted(folder.glob("**/*.csv")):
            snapshots.extend(rows(path))
    report = run(graded, snapshots)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    print("V3 five-part research audit:", report["part_2_line_validation"]["status_counts"],
          "CLV proxy sample:", report["part_5_closing_line_proxy"]["sample_size"])

if __name__ == "__main__":
    main()
