"""Publish immutable weekly V2 power rankings from completed CFBD games."""
import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import requests
from cfb_v2_experimental import build_v2
from power_rankings import build_power_rankings

ROOT = Path(__file__).resolve().parent
HISTORY = ROOT / "rankings_history"
CENTRAL = ZoneInfo("America/Chicago")

def fetch_games(year, token):
    response = requests.get(
        "https://api.collegefootballdata.com/games",
        params={"year": year, "seasonType": "regular"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=45,
    )
    response.raise_for_status()
    games = response.json()
    if not isinstance(games, list):
        raise RuntimeError("CFBD games response is not a list")
    return games

def main():
    now = datetime.now(timezone.utc)
    local = now.astimezone(CENTRAL)
    # A Sunday publication is allowed only at/after 1 PM local time.
    if local.weekday() != 6 or local.hour != 13:
        print(f"Not Sunday 1 PM America/Chicago ({local.isoformat()}); skipping.")
        return
    token = os.environ.get("CFBD_API_KEY", "")
    if not token:
        raise RuntimeError("Configure the repository Actions secret CFBD_API_KEY")
    season = local.year
    prior = fetch_games(season - 1, token)
    current = fetch_games(season, token)
    # Keep parameters aligned with the dashboard's default V2 settings.
    ratings, info = build_v2(prior, current, now, home_adv=2.5, shrink=4.0)
    if not ratings or info["current_games"] < 1:
        raise RuntimeError("No current-season completed games; refusing empty publication")
    rows = build_power_rankings(ratings)
    week = local.strftime("%Y-%m-%d")
    HISTORY.mkdir(parents=True, exist_ok=True)
    target = HISTORY / f"{week}.json"
    if target.exists():
        print(f"Snapshot already exists: {target}; refusing overwrite")
        return
    previous_files = sorted(HISTORY.glob("????-??-??.json"))
    previous = json.loads(previous_files[-1].read_text()) if previous_files else None
    old_ranks = {r["team"]: r["rank"] for r in previous["rankings"]} if previous else {}
    for row in rows:
        old = old_ranks.get(row["team"])
        new = row["rank"]
        row["last_week_rank"] = old
        row["movement"] = (old - new) if old is not None and new is not None else None
    payload = {
        "published_central": local.isoformat(),
        "season": season,
        "v2_parameters": {"home_adv": 2.5, "shrink": 4.0, "prior_weight": 0.5},
        "games_used": info,
        "rankings": rows,
    }
    target.write_text(json.dumps(payload, indent=2) + "\n")
    (HISTORY / "latest.json").write_text(json.dumps(payload, indent=2) + "\n")
    print(f"Published {target}: {len(rows)} teams")

if __name__ == "__main__":
    main()
