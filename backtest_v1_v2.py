"""Historical walk-forward margin comparison; never reads 2026 or live games.

Usage: CFBD_API_KEY=... python backtest_v1_v2.py
Output: backtests/v1_v2_game_results.csv and backtests/v1_v2_summary.json
"""
import csv
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import requests
import numpy as np
from cfb_team_matching import canonical_school
from cfb_v2_experimental import build_v2, projected_margin

YEARS = (2024, 2025)  # 2023 supplies the first preseason prior; 2026 never fetched
HOME_ADV = 2.5
SHRINK = 4.0


def dt(game):
    raw = game.get('startDate')
    if not raw: return None
    try: value = datetime.fromisoformat(raw.replace('Z', '+00:00'))
    except (ValueError, TypeError): return None
    return value.astimezone(timezone.utc) if value.tzinfo else None


def valid(game):
    """Use CFBD's historical per-game classifications, not today's FBS roster."""
    return (game.get('completed') is True and
            str(game.get('seasonType', '')).lower() == 'regular' and
            str(game.get('homeClassification', '')).lower() == 'fbs' and
            str(game.get('awayClassification', '')).lower() == 'fbs' and
            game.get('homePoints') is not None and game.get('awayPoints') is not None and
            dt(game) is not None and
            not (game['homePoints'] == 0 and game['awayPoints'] == 0))


def v1_fit(games):
    """Reproduce the V1 current-season ridge formula on historical FBS games."""
    rows = [(canonical_school(g['homeTeam']), canonical_school(g['awayTeam']),
             float(g['homePoints']) - float(g['awayPoints'])) for g in games]
    teams = sorted({t for h, a, _ in rows for t in (h, a)})
    if not teams: return {}
    ix = {t: i for i, t in enumerate(teams)}
    x = np.zeros((len(rows)+1, len(teams)))
    y = np.zeros(len(rows)+1)
    for i, (h, a, margin) in enumerate(rows):
        x[i, ix[h]] = 1
        x[i, ix[a]] = -1
        y[i] = margin - HOME_ADV
    x[-1, :] = 1 / len(teams)
    ratings = np.linalg.solve(x.T @ x + np.eye(len(teams))*SHRINK, x.T @ y)
    return dict(zip(teams, map(float, ratings)))


def fetch_year(year, session):
    key = os.getenv('CFBD_API_KEY')
    if not key: raise RuntimeError('Set CFBD_API_KEY in GitHub Actions secrets.')
    response = session.get('https://api.collegefootballdata.com/games',
                           params={'year': year, 'seasonType': 'regular'},
                           headers={'Authorization': f'Bearer {key}'}, timeout=45)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, list): raise ValueError('Unexpected CFBD response')
    return [g for g in data if valid(g)]


def run(seasons, out_dir):
    """Weekly frozen predictions; the same games and cutoffs for both versions."""
    rows = []
    for year in YEARS:
        prev, current = seasons[year-1], seasons[year]
        weeks = sorted({int(g['week']) for g in current if g.get('week') is not None})
        for week in weeks:
            targets = sorted((g for g in current if int(g['week']) == week), key=dt)
            if not targets: continue
            # Freeze both models before the FIRST kickoff of the week.
            asof = dt(targets[0])
            eligible = [g for g in current if dt(g) <= asof-timedelta(hours=6)]
            r1 = v1_fit(eligible)
            # V2 uses the prior year's completed games plus current games at the same cutoff.
            # build_v2 itself enforces the six-hour embargo.
            r2, _ = build_v2(prev, current, asof, HOME_ADV, SHRINK, .5)
            for g in targets:
                h, a = canonical_school(g['homeTeam']), canonical_school(g['awayTeam'])
                if h not in r1 or a not in r1: continue  # paired sample only
                p1 = r1[h]-r1[a]+HOME_ADV
                p2 = projected_margin(h, a, r2, HOME_ADV)
                if p2 is None or not math.isfinite(p2): continue
                actual = float(g['homePoints'])-float(g['awayPoints'])
                rows.append({'season':year, 'week':week, 'game_id':g['id'],
                             'kickoff_utc':dt(g).isoformat(), 'home_team':g['homeTeam'],
                             'away_team':g['awayTeam'], 'actual_home_margin':round(actual,3),
                             'v1_home_margin':round(p1,3), 'v2_home_margin':round(p2,3),
                             'v1_abs_error':round(abs(p1-actual),3),
                             'v2_abs_error':round(abs(p2-actual),3)})
    if not rows: raise RuntimeError('No paired predictions; check historical FBS classification and input seasons.')
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with (out/'v1_v2_game_results.csv').open('w', newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    def summarize(group):
        return {'paired_games':len(group),
                'v1_mae':round(sum(r['v1_abs_error'] for r in group)/len(group),3),
                'v2_mae':round(sum(r['v2_abs_error'] for r in group)/len(group),3),
                'v1_lower_error_games':sum(r['v1_abs_error'] < r['v2_abs_error'] for r in group),
                'v2_lower_error_games':sum(r['v2_abs_error'] < r['v1_abs_error'] for r in group)}
    summary={'method':'weekly walk-forward, first kickoff minus 6 hours; paired FBS-only games; margins only; no betting ROI',
             'caveat':'V2 parameters were developed before this audit, but historical tuning provenance is not verified; do not treat this as untouched prospective validation.',
             'overall':summarize(rows),
             'by_season':{str(y):summarize([r for r in rows if r['season']==y]) for y in YEARS}}
    (out/'v1_v2_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    return summary


if __name__ == '__main__':
    with requests.Session() as session:
        seasons={y:fetch_year(y,session) for y in (2023,2024,2025)}
    print(json.dumps(run(seasons,'backtests'),indent=2))
