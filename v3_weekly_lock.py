"""Immutable, as-of V3 Tuesday/Saturday 8 AM Central game locks.

Independent of the existing first-qualifying prospective selection ledger.
Every scheduled CFBD regular-season game in the window receives PLAY or PASS.
Missing odds, ratings, or an unsupported matchup are explicit PASS records.
"""
import csv
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from cfb_division_safety import model_allowed
from cfb_team_matching import canonical_school
from cfb_v2_experimental import build_v2, projected_margin
from prospective_capture import V3_INTERCEPT, V3_SLOPE, V3_V2_WEIGHT, number
from snapshot_capture import capture, fetch, ratings_from_prior_games, utc

CENTRAL = ZoneInfo("America/Chicago")
CFBD = "https://api.collegefootballdata.com/games"
FIELDS = ("lock_id season game_id kickoff_utc home_team away_team locked_at_utc "
          "decision selection sportsbook_key sportsbook spread american_odds "
          "v3_projected_home_margin edge_points reason quote_captured_at_utc "
          "market_last_update_utc v1_v2_inputs_sha256").split()
RULE = "v3_all_games_lock_v1_edge3"


def lock_window(now):
    local = now.astimezone(CENTRAL)
    if local.weekday() not in (1, 5) or local.hour != 8:
        raise ValueError("Locks may run only Tuesday or Saturday at 8 AM America/Chicago")
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=4 if local.weekday() == 1 else 1)
    return ("weekday" if local.weekday() == 1 else "saturday",
            start.astimezone(timezone.utc), end.astimezone(timezone.utc))


def asof_rows(now, games, odds_rows, v2_ratings):
    label, start, end = lock_window(now)
    result = []
    quotes = {}
    for row in odds_rows:
        key = (canonical_school(row["home_team"]), canonical_school(row["away_team"]))
        quotes.setdefault(key, []).append(row)
    for game in games:
        kick = utc(game.get("startDate") or game.get("start_date"))
        if not kick or not start <= kick < end or kick <= now:
            continue
        if str(game.get("seasonType", game.get("season_type", "regular"))).lower() != "regular":
            continue
        home = game.get("homeTeam") or game.get("home_team")
        away = game.get("awayTeam") or game.get("away_team")
        if not home or not away:
            continue
        h, a = canonical_school(home), canonical_school(away)
        candidates = quotes.get((h, a), [])
        base = dict(lock_id=label, season=now.astimezone(CENTRAL).year,
                    game_id=str(game.get("id") or f"{kick.isoformat()}:{h}:{a}"),
                    kickoff_utc=kick.isoformat().replace("+00:00", "Z"),
                    home_team=home, away_team=away,
                    locked_at_utc=now.isoformat(timespec="seconds").replace("+00:00", "Z"),
                    decision="PASS", selection="", sportsbook_key="", sportsbook="",
                    spread="", american_odds="", v3_projected_home_margin="",
                    edge_points="", reason="", quote_captured_at_utc="",
                    market_last_update_utc="", v1_v2_inputs_sha256="")
        if not model_allowed(home, away):
            base["reason"] = "unsupported_division"
        elif not candidates:
            base["reason"] = "no_live_spread_quote"
        else:
            valid = []
            for q in candidates:
                spread, price = number(q.get("spread")), number(q.get("american_odds"))
                market = utc(q.get("market_last_update_utc"))
                book = utc(q.get("bookmaker_last_update_utc"))
                if (spread is None or price is None or price == 0 or not -200 <= price <= 200
                        or q.get("selection") not in (q.get("home_team"), q.get("away_team"))
                        or (market and market > now) or (book and book > now)):
                    continue
                v1 = number(q.get("projected_home_margin"))
                v2 = projected_margin(q["home_team"], q["away_team"], v2_ratings)
                if v1 is None or v2 is None:
                    continue
                v3 = V3_INTERCEPT + V3_SLOPE * ((1 - V3_V2_WEIGHT) * v1 + V3_V2_WEIGHT * v2)
                edge = (v3 if q["selection"] == q["home_team"] else -v3) + spread
                valid.append((edge, price, str(q.get("sportsbook_key") or ""), q, v3))
            if not valid:
                base["reason"] = "missing_model_or_eligible_quote"
            else:
                edge, price, _, q, v3 = sorted(valid, key=lambda x: (-x[0], -x[1], x[2], x[3]["selection"]))[0]
                base.update(selection=home if q["selection"] == q["home_team"] else away,
                            sportsbook_key=q.get("sportsbook_key") or "",
                            sportsbook=q.get("sportsbook") or "",
                            spread=q["spread"], american_odds=q["american_odds"],
                            v3_projected_home_margin=round(v3, 5),
                            edge_points=round(edge, 5),
                            quote_captured_at_utc=q["captured_at_utc"],
                            market_last_update_utc=q.get("market_last_update_utc") or "",
                            v1_v2_inputs_sha256=q.get("ratings_input_sha256") or "",
                            decision="PLAY" if edge >= 3 else "PASS",
                            reason="edge_at_least_3" if edge >= 3 else "edge_below_3")
        result.append(base)
    result.sort(key=lambda r: (r["kickoff_utc"], r["home_team"], r["away_team"]))
    return result


def save_lock(now, rows, root=Path("locks")):
    label, _, _ = lock_window(now)
    local_date = now.astimezone(CENTRAL).date().isoformat()
    target = Path(root) / str(now.astimezone(CENTRAL).year) / (local_date + "_" + label + ".csv")
    if target.exists():
        raise FileExistsError(f"Refusing to overwrite existing lock: {target}")
    if not rows:
        raise RuntimeError("No scheduled games returned; refusing empty lock")
    keys = [(r["game_id"], r["kickoff_utc"]) for r in rows]
    if len(keys) != len(set(keys)):
        raise RuntimeError("Duplicate games in lock")
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".tmp")
    with temp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    temp.replace(target)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix(".sha256").write_text(digest + "  " + target.name + "\n")
    return target, digest


def main():
    now = datetime.now(timezone.utc)
    label, _, _ = lock_window(now)
    year = now.astimezone(CENTRAL).year
    path = Path("locks") / str(year) / (now.astimezone(CENTRAL).date().isoformat() + "_" + label + ".csv")
    if path.exists():
        print(f"Existing lock preserved: {path}")
        return
    key = os.environ["CFBD_API_KEY"]
    games, _ = fetch(CFBD, params={"year": year, "seasonType": "regular"},
                     headers={"Authorization": "Bearer " + key})
    previous, _ = fetch(CFBD, params={"year": year - 1, "seasonType": "regular"},
                        headers={"Authorization": "Bearer " + key})
    # Capture the current market and as-of V1 inputs, not an older snapshot.
    snapshot, _ = capture(now=now, games=games, season=year)
    v2, meta = build_v2(previous, games, now)
    rows = asof_rows(now, games, snapshot, v2)
    target, digest = save_lock(now, rows)
    print(json.dumps({"lock": str(target), "sha256": digest,
                      "games": len(rows),
                      "PLAY": sum(r["decision"] == "PLAY" for r in rows),
                      "PASS": sum(r["decision"] == "PASS" for r in rows),
                      "v2_training_games": meta.get("current_games")}, indent=2))


if __name__ == "__main__":
    main()
