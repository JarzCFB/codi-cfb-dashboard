"""Read-only inventory of archived odds/ratings snapshots; never labels them V3."""
import csv
import json
from math import isfinite
from collections import Counter
from pathlib import Path
from v4_evidence_audit import _time

REQUIRED = {"captured_at_utc", "game_id", "kickoff_utc", "sportsbook_key",
            "selection", "projected_home_margin", "capture_status"}

def inventory(root="snapshots/2026"):
    files = sorted(Path(root).glob("*.csv"))
    games = set()
    pregame = set()
    six_hour_pregame = set()
    future_market_updates = 0
    invalid_projection_rows = 0
    status = Counter()
    rows = 0
    invalid = 0
    for path in files:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if not REQUIRED.issubset(set(reader.fieldnames or ())):
                invalid += 1
                continue
            for row in reader:
                rows += 1
                gid = row["game_id"].strip()
                if not gid:
                    invalid += 1
                    continue
                games.add(gid)
                status[(row.get("capture_status") or "").strip()] += 1
                try:
                    projection = float(row["projected_home_margin"])
                    if not isfinite(projection):
                        raise ValueError("nonfinite ratings projection")
                except (ValueError, TypeError, KeyError):
                    invalid_projection_rows += 1
                    invalid += 1
                    continue
                try:
                    captured = _time(row["captured_at_utc"])
                    kickoff = _time(row["kickoff_utc"])
                    if captured >= kickoff:
                        invalid += 1
                        continue
                    market_update = (row.get("market_last_update_utc") or "").strip()
                    if market_update and _time(market_update) > captured:
                        future_market_updates += 1
                        invalid += 1
                        continue
                    pregame.add(gid)
                    if (kickoff - captured).total_seconds() >= 6 * 3600:
                        six_hour_pregame.add(gid)
                except (ValueError, TypeError, AttributeError):
                    invalid += 1
    return {
        "status": "RESEARCH_ONLY", "release_ready": False,
        "source_type": "archived_odds_and_ratings_not_official_v3",
        "snapshot_files": len(files), "snapshot_quote_rows": rows,
        "distinct_game_ids": len(games), "distinct_pregame_game_ids": len(pregame),
        "distinct_games_captured_at_least_6h_before_kickoff": len(six_hour_pregame),
        "market_update_after_capture_rows": future_market_updates,
        "invalid_ratings_projection_rows": invalid_projection_rows,
        "invalid_rows_or_files": invalid, "capture_status_counts": dict(sorted(status.items())),
        "official_v3_predictions_recovered": 0,
        "warning": "Ratings-derived projected_home_margin is NOT official calibrated V3. Odds game IDs may not match CFBD game IDs.",
    }

if __name__ == "__main__":
    target = Path("reports/v4_snapshot_inventory.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(inventory(), indent=2) + "\n", encoding="utf-8")
    print(target)
