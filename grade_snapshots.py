"""Grade archived pregame NCAAF spreads against CFBD final scores.
Read-only on snapshots/. Writes reports/graded_quotes.csv and reports/summary.json.
Only quotes captured before kickoff and finalized, unambiguously matched games count.
"""
import csv
import json
import os
from collections import defaultdict
from datetime import timedelta
from pathlib import Path
import requests
from snapshot_capture import utc, iso, canonical_school, match_rating, TEAM_ALIASES, normalize_team
from cfb_division_safety import model_allowed

ROOT=Path('snapshots')
REPORTS=Path('reports')
FIELDS=['season','game_id','kickoff_utc','home_team','away_team','sportsbook_key','selection','spread','american_odds','captured_at_utc','market_last_update_utc','projected_home_margin','actual_home_margin','selection_result','one_unit_profit','cfbd_game_id']

def fetch_results(season):
    key=os.environ['CFBD_API_KEY']
    response=requests.get('https://api.collegefootballdata.com/games',params={'year':season,'seasonType':'regular'},headers={'Authorization':'Bearer '+key},timeout=45)
    response.raise_for_status()
    return response.json()

def school(name):
    n=normalize_team(name)
    return canonical_school(TEAM_ALIASES.get(n,n))

def finished(g):
    hp=g.get('homePoints',g.get('home_points'))
    ap=g.get('awayPoints',g.get('away_points'))
    return bool(g.get('completed')) and hp is not None and ap is not None

def index_results(games):
    idx=defaultdict(list)
    for g in games:
        if not finished(g):continue
        kick=utc(g.get('startDate') or g.get('start_date'))
        if not kick:continue
        h=school(g.get('homeTeam') or g.get('home_team'))
        a=school(g.get('awayTeam') or g.get('away_team'))
        idx[(h,a)].append((kick,g))
    return idx

def grade(rows,results):
    idx=index_results(results)
    graded=[];stats=defaultdict(int)
    # The last available quote for each game, sportsbook and selection; do not
    # pretend that multiple 4-hour captures are independent wagers.
    latest={}
    for r in rows:
        stats['input_rows']+=1
        if not model_allowed(r.get('home_team'),r.get('away_team')):
            stats['excluded_unverified_division']+=1
            continue
        try:
            capture=utc(r['captured_at_utc']); kick=utc(r['kickoff_utc'])
            update=utc(r['market_last_update_utc'])
            if not capture or not kick or not update or capture>=kick or update>capture or update>=kick:
                stats['invalid_or_post_kickoff']+=1;continue
            spread=float(r['spread']);price=float(r['american_odds'])
            if price==0 or not r.get('projected_home_margin'):
                stats['missing_prediction_or_price']+=1;continue
        except (KeyError,TypeError,ValueError):
            stats['invalid_row']+=1;continue
        key=(r['season'],r['game_id'],r['sportsbook_key'],r['selection'])
        if key not in latest or capture>utc(latest[key]['captured_at_utc']):latest[key]=r
    stats['unique_latest_quotes']=len(latest)
    for r in latest.values():
        h=school(r['home_team']);a=school(r['away_team']);kick=utc(r['kickoff_utc'])
        matches=[g for dt,g in idx.get((h,a),[]) if abs(dt-kick)<=timedelta(hours=36)]
        if len(matches)!=1:
            stats['ungraded_not_final_or_ambiguous']+=1;continue
        g=matches[0]
        actual=float(g.get('homePoints',g.get('home_points')))-float(g.get('awayPoints',g.get('away_points')))
        if r['selection']==r['home_team']:selection_margin=actual
        elif r['selection']==r['away_team']:selection_margin=-actual
        else:stats['invalid_selection']+=1;continue
        against_spread=selection_margin+float(r['spread'])
        result='win' if against_spread>0 else 'loss' if against_spread<0 else 'push'
        price=float(r['american_odds'])
        profit=(price/100 if price>0 else 100/abs(price)) if result=='win' else -1 if result=='loss' else 0
        graded.append({k:r.get(k,'') for k in FIELDS})
        graded[-1].update(actual_home_margin=actual,selection_result=result,one_unit_profit=round(profit,6),cfbd_game_id=g.get('id'))
    stats['graded_quotes']=len(graded)
    stats['graded_games']=len(set(r['game_id'] for r in graded))
    stats['wins']=sum(r['selection_result']=='win' for r in graded)
    stats['losses']=sum(r['selection_result']=='loss' for r in graded)
    stats['pushes']=sum(r['selection_result']=='push' for r in graded)
    # Descriptive grading only: these are all available quoted sides, not
    # an implementable strategy or independently placed bets.
    return graded,dict(stats)

def main():
    paths=sorted(ROOT.glob('*/*.csv'))
    if not paths:print('No archived snapshots yet');return
    rows=[]
    for path in paths:
        with path.open(newline='',encoding='utf-8') as f:rows.extend(csv.DictReader(f))
    seasons=sorted({int(r['season']) for r in rows if r.get('season','').isdigit()})
    results=[g for year in seasons for g in fetch_results(year)]
    graded,stats=grade(rows,results)
    REPORTS.mkdir(exist_ok=True)
    with (REPORTS/'graded_quotes.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=FIELDS);writer.writeheader();writer.writerows(graded)
    with (REPORTS/'summary.json').open('w',encoding='utf-8') as f:json.dump(stats,f,indent=2,sort_keys=True)
    print(json.dumps(stats,indent=2,sort_keys=True))

if __name__=='__main__':main()
