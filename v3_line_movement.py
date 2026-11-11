"""Track V3 sportsbook spread movements from archived pregame snapshots.

Compare the same sportsbook's home-team spread across captures, never mix books.
Earliest observed quote is not necessarily the true opening line.
No changes to locked picks, V3 model, or historical snapshot files.
"""
import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from cfb_team_matching import canonical_school
from snapshot_capture import utc

THRESHOLD = 3.0
KEY_NUMBERS = (3.0, 7.0)
COLUMNS = ["season", "home_team", "away_team", "kickoff_utc", "sportsbook_key",
           "sportsbook", "first_seen_utc", "latest_seen_utc", "first_home_spread",
           "latest_home_spread", "movement_points", "absolute_movement_points",
           "direction", "severity", "crossed_key_numbers", "observation_count",
           "source", "is_major"]


def home_spread(row):
    try:
        spread = float(row["spread"])
    except (KeyError, TypeError, ValueError):
        return None
    if row.get("selection") == row.get("home_team"):
        return spread
    if row.get("selection") == row.get("away_team"):
        return -spread
    return None


def severity(points):
    p = abs(points)
    if p >= 5: return "MAJOR_5_PLUS"
    if p >= 3: return "SIGNIFICANT_3_PLUS"
    if p >= 2: return "WATCH_2_PLUS"
    return "NORMAL"


def crossed_keys(a, b):
    # Crossing either side of a key margin matters; no claim that odds
    # changed at the exact key number between observed captures.
    return ",".join(str(n) for n in KEY_NUMBERS
                    if any(min(a, b) < k <= max(a, b) for k in (-n, n)))


def summarize(rows):
    observations = defaultdict(dict)
    for r in rows:
        spread = home_spread(r)
        captured = utc(r.get("captured_at_utc"))
        kickoff = utc(r.get("kickoff_utc"))
        if spread is None or captured is None or kickoff is None or captured >= kickoff:
            continue
        if r.get("capture_status") != "timestamped_live_quote":
            continue
        market = utc(r.get("market_last_update_utc"))
        book = utc(r.get("bookmaker_last_update_utc"))
        if (market and market > captured) or (book and book > captured):
            continue
        home = canonical_school(r.get("home_team") or "")
        away = canonical_school(r.get("away_team") or "")
        book_key = str(r.get("sportsbook_key") or "")
        if not home or not away or not book_key:
            continue
        key = (str(r.get("season")), home, away, kickoff.isoformat(), book_key)
        timestamp = captured.isoformat()
        # Prefer a home-side quote where both sides exist at one capture.
        old = observations[key].get(timestamp)
        if old is None or r.get("selection") == r.get("home_team"):
            observations[key][timestamp] = (spread, r)
    output = []
    for (season, home, away, kickoff, book_key), by_time in sorted(observations.items()):
        if len(by_time) < 2:
            continue
        ordered = sorted(by_time.items())
        first_time, (first_spread, first) = ordered[0]
        last_time, (last_spread, last) = ordered[-1]
        movement = round(last_spread - first_spread, 5)
        output.append(dict(
            season=season, home_team=first["home_team"], away_team=first["away_team"],
            kickoff_utc=kickoff.replace("+00:00", "Z"), sportsbook_key=book_key,
            sportsbook=last.get("sportsbook") or book_key,
            first_seen_utc=first_time.replace("+00:00", "Z"),
            latest_seen_utc=last_time.replace("+00:00", "Z"),
            first_home_spread=first_spread, latest_home_spread=last_spread,
            movement_points=movement, absolute_movement_points=abs(movement),
            direction=("TOWARD_HOME" if movement < 0 else
                       "TOWARD_AWAY" if movement > 0 else "UNCHANGED"),
            severity=severity(movement), crossed_key_numbers=crossed_keys(first_spread, last_spread),
            observation_count=len(by_time), source="earliest_observed_same_sportsbook",
            is_major=abs(movement) >= THRESHOLD))
    return output


def read_snapshots(folder):
    for path in sorted(Path(folder).glob("*.csv")):
        with path.open(newline="", encoding="utf-8") as handle:
            yield from csv.DictReader(handle)


def main():
    now = datetime.now(timezone.utc)
    year = now.year
    rows = summarize(read_snapshots(Path("snapshots") / str(year)))
    folder = Path("reports")
    folder.mkdir(exist_ok=True)
    report = dict(generated_at_utc=now.isoformat().replace("+00:00", "Z"),
                  definition="Same-sportsbook home-team spread, earliest observed versus latest observed",
                  opening_line_warning="First observed quote is not necessarily true sportsbook opening line",
                  threshold_points=THRESHOLD, movements=rows,
                  major_movements=[r for r in rows if r["is_major"]])
    (folder / "v3_line_movements.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    with (folder / "v3_line_movements.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    majors = report["major_movements"]
    print(f"Line movement: {len(rows)} book/game series, {len(majors)} >=3 point moves")
    summary = __import__("os").environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as out:
            out.write(f"\n## V3 line movement monitor\n\n"
                      f"- Same-book series: **{len(rows)}**\n"
                      f"- Moves >= 3 points: **{len(majors)}**\n"
                      f"- Moves >= 5 points: **{sum(r['absolute_movement_points'] >= 5 for r in majors)}**\n"
                      "- First observed is not necessarily the true opening line.\n")
            for r in sorted(majors, key=lambda x: -x["absolute_movement_points"])[:20]:
                out.write(f"- {r['away_team']} at {r['home_team']}, {r['sportsbook']}: "
                          f"{r['first_home_spread']:+g} to {r['latest_home_spread']:+g} "
                          f"({r['absolute_movement_points']:g} points, {r['direction']})\n")


if __name__ == "__main__":
    main()
