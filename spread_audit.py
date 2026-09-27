"""Fixed-rule audit of archived 2026 V1 pregame spreads; optional historical V1/V2 odds join.
No sportsbook lines are inferred from final scores or model predictions.
"""
import csv, json, math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

CUTOFF_HOURS = 6
MIN_EDGE_POINTS = 3.0

def when(value):
    return datetime.fromisoformat(str(value).replace('Z', '+00:00')).astimezone(timezone.utc)

def num(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError):
        return None

def profit(result, odds):
    if result == 'push': return 0.0
    if result == 'loss': return -1.0
    if result != 'win' or odds is None or odds == 0: return None
    return 100 / abs(odds) if odds < 0 else odds / 100

def side_result(actual_home, spread, is_home):
    cover = (actual_home if is_home else -actual_home) + spread
    return 'win' if cover > 0.000001 else 'loss' if cover < -0.000001 else 'push'

def select_archived(quotes, min_edge=MIN_EDGE_POINTS):
    """Latest available snapshot at least 6h before kickoff; max projected edge; one bet/game.
    No final-score field is accessed until after the selection has been frozen.
    """
    games = defaultdict(list)
    for r in quotes:
        try:
            if when(r['captured_at_utc']) > when(r['kickoff_utc']) - timedelta(hours=CUTOFF_HOURS): continue
            if r.get('market_last_update_utc') and when(r['market_last_update_utc']) > when(r['captured_at_utc']): continue
            p, s, o = num(r.get('projected_home_margin')), num(r.get('spread')), num(r.get('american_odds'))
            if p is None or s is None or o is None or o == 0: continue
            if o < -200 or o > 200: continue  # fixed price window, not chosen by results
            is_home = r['selection'] == r['home_team']
            if not is_home and r['selection'] != r['away_team']: continue
            edge = (p if is_home else -p) + s
            if edge < min_edge: continue
            games[(r['season'],r['game_id'])].append((r,edge))
        except (ValueError, KeyError): continue
    selections=[]
    for key, choices in sorted(games.items()):
        # Most recent eligible snapshot; then highest edge; deterministic tiebreak by price/book.
        last = max(when(r['captured_at_utc']) for r,_ in choices)
        latest = [(r,e) for r,e in choices if when(r['captured_at_utc']) == last]
        r,edge = sorted(latest,key=lambda x:(-x[1],-num(x[0]['american_odds']),x[0]['sportsbook_key'],x[0]['selection']))[0]
        actual = num(r.get('actual_home_margin'))
        result = side_result(actual,num(r['spread']),r['selection']==r['home_team']) if actual is not None else 'pending'
        selections.append(dict(season=r['season'],game_id=r['game_id'],kickoff_utc=r['kickoff_utc'],home_team=r['home_team'],away_team=r['away_team'],selection=r['selection'],sportsbook_key=r['sportsbook_key'],spread=r['spread'],american_odds=r['american_odds'],captured_at_utc=r['captured_at_utc'],projected_home_margin=r['projected_home_margin'],edge_points=round(edge,3),actual_home_margin=r.get('actual_home_margin',''),result=result,one_unit_profit=profit(result,num(r['american_odds']))))
    return selections

def summarize(rows):
    settled=[r for r in rows if r['result'] in ('win','loss','push')]
    staked=[r for r in settled if r['result'] != 'push']
    return {'rule':'One selection/game: latest snapshot >=6h before kickoff, maximum model edge >=3 pts, odds -200..+200; one unit per bet', 'selected_games':len(rows),'settled':len(settled),'wins':sum(r['result']=='win' for r in settled),'losses':sum(r['result']=='loss' for r in settled),'pushes':sum(r['result']=='push' for r in settled),'units_profit':round(sum(r['one_unit_profit'] for r in settled),3),'roi_per_settled_bet':round(sum(r['one_unit_profit'] for r in settled)/len(settled),4) if settled else None,'warning':'Retrospective rule; not a prespecified prospective betting strategy. V1 only; no 2024-25 historical odds provided.'}

def read(path):
    with open(path,newline='',encoding='utf-8-sig') as f:return list(csv.DictReader(f))

def write(path,rows):
    if not rows:return
    with open(path,'w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

def historical_join(games,lines):
    """Only real archived 2024/25 lines with timestamp <= kickoff-6h and matching CFBD game ID.
    Prices and sides must be present; never create synthetic odds. One market snapshot/game.
    """
    byid={str(r['game_id']):r for r in games}
    candidates=defaultdict(list)
    for l in lines:
        g=byid.get(str(l.get('game_id','')))
        if not g:continue
        try:
            if when(l['captured_at_utc']) > when(g['kickoff_utc'])-timedelta(hours=CUTOFF_HOURS):continue
            if num(l['home_spread']) is None or num(l['home_american_odds']) is None or num(l['away_american_odds']) is None:continue
            candidates[l['game_id']].append((l,g))
        except (ValueError,KeyError):continue
    output=[]
    for gid,pairs in sorted(candidates.items()):
        l,g=max(pairs,key=lambda p:when(p[0]['captured_at_utc']))
        home_spread=num(l['home_spread']);actual=num(g['actual_home_margin'])
        for version in ('v1','v2'):
            pred=num(g[version+'_home_margin'])
            if pred is None:continue
            home_edge=pred+home_spread;away_edge=-home_edge
            side='home' if home_edge>=away_edge else 'away'
            edge=max(home_edge,away_edge)
            if edge<MIN_EDGE_POINTS:continue
            odds=num(l[side+'_american_odds'])
            if odds is None or odds==0 or odds < -200 or odds > 200:continue
            result=side_result(actual,home_spread if side=='home' else -home_spread,side=='home')
            output.append(dict(season=g['season'],game_id=gid,version=version,selection=side,home_team=g['home_team'],away_team=g['away_team'],home_spread=home_spread,american_odds=odds,edge_points=round(edge,3),captured_at_utc=l['captured_at_utc'],result=result,one_unit_profit=profit(result,odds)))
    return output

def main():
    out=Path('backtests');out.mkdir(exist_ok=True)
    q=Path('reports/graded_quotes.csv')
    if q.exists():
        picks=select_archived(read(q));write(out/'v1_archived_spread_selections.csv',picks)
        summary=summarize(picks)
        (out/'v1_archived_spread_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
        print(json.dumps({'archived_2026_v1':summary},indent=2))
    games=out/'v1_v2_game_results.csv';lines=Path('data/historical_pregame_spreads.csv')
    if games.exists() and lines.exists():
        results=historical_join(read(games),read(lines));write(out/'historical_spread_selections.csv',results)
        print(json.dumps({'historical_lines_matched_selections':len(results),'note':'V1/V2 historical spread results; inspect provenance of lines before interpreting'},indent=2))
    else:print('2024-25 historical spread comparison SKIPPED: supply real timestamped data/historical_pregame_spreads.csv and backtests/v1_v2_game_results.csv; no lines fabricated.')
if __name__=='__main__':main()
