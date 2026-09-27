"""Freeze V1 and V2 paper selections at capture time, never from graded reports.

Fixed rule v1: 3+ point edge; v2: 3+ point edge (margin only, not cover probability).
One pick per game and model, first qualifying capture >=6h before kickoff.
Odds -200..+200; quote timestamps cannot be later than capture.
Selections are research-only, never claims of actual bets or guaranteed immutable storage.
"""
import csv
import hashlib
import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests
from cfb_division_safety import model_allowed
from cfb_v2_experimental import build_v2, projected_margin

FIELDS = ['rule_version','model_version','season','game_id','kickoff_utc','captured_at_utc',
          'home_team','away_team','division_status','selection','sportsbook_key','sportsbook',
          'spread','american_odds','projected_home_margin','edge_points',
          'market_last_update_utc','v2_previous_games','v2_current_games','v2_inputs_sha256']
RULE = 'prospective_v1_20260927_edge3_cutoff6h_price200_first_qualifying'

def dt(value):
    if not value: return None
    try:
        v=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return v.astimezone(timezone.utc) if v.tzinfo else None
    except (ValueError,TypeError): return None

def number(value):
    try:
        v=float(value)
        return v if math.isfinite(v) else None
    except (TypeError,ValueError): return None

def pick_rows(rows, v2_ratings, existing=None):
    existing=set(existing or ())
    grouped={}
    for r in rows:
        try:
            capture=dt(r['captured_at_utc']);kick=dt(r['kickoff_utc'])
            if not capture or not kick or capture>kick-timedelta(hours=6):continue
            if not model_allowed(r['home_team'],r['away_team']):continue
            market=dt(r.get('market_last_update_utc'))
            book=dt(r.get('bookmaker_last_update_utc'))
            if market and market>capture or book and book>capture:continue
            price=number(r.get('american_odds'));spread=number(r.get('spread'))
            if price is None or price==0 or not -200<=price<=200 or spread is None:continue
            if r['selection'] not in (r['home_team'],r['away_team']):continue
            season=str(r['season']);gid=str(r['game_id'])
            for version in ('v1','v2'):
                if (season,gid,version) in existing:continue
                margin=(number(r.get('projected_home_margin')) if version=='v1'
                        else projected_margin(r['home_team'],r['away_team'],v2_ratings))
                if margin is None:continue
                edge=(margin if r['selection']==r['home_team'] else -margin)+spread
                if edge<3.0:continue
                key=(season,gid,version)
                # Deterministic tie break: maximum edge, then best payout, then sportsbook/side.
                rank=(-edge,-price,str(r.get('sportsbook_key') or ''),r['selection'])
                if key not in grouped or rank<grouped[key][0]:grouped[key]=(rank,r,margin,edge)
        except (KeyError,TypeError):continue
    return grouped

def freeze(rows, v2_ratings, ledger, meta):
    ledger=Path(ledger);ledger.parent.mkdir(parents=True,exist_ok=True)
    if ledger.exists():
        with ledger.open(newline='',encoding='utf-8') as f:old=list(csv.DictReader(f))
    else:old=[]
    existing={(r['season'],r['game_id'],r['model_version']) for r in old}
    picks=pick_rows(rows,v2_ratings,existing)
    new=[]
    for (season,gid,version),(_,r,margin,edge) in sorted(picks.items()):
        new.append({'rule_version':RULE,'model_version':version,'season':season,'game_id':gid,
            'kickoff_utc':r['kickoff_utc'],'captured_at_utc':r['captured_at_utc'],
            'home_team':r['home_team'],'away_team':r['away_team'],'division_status':r['division_status'],
            'selection':r['selection'],'sportsbook_key':r['sportsbook_key'],'sportsbook':r['sportsbook'],
            'spread':r['spread'],'american_odds':r['american_odds'],
            'projected_home_margin':round(margin,5),'edge_points':round(edge,5),
            'market_last_update_utc':r.get('market_last_update_utc') or '',
            'v2_previous_games':meta.get('previous_games','') if version=='v2' else '',
            'v2_current_games':meta.get('current_games','') if version=='v2' else '',
            'v2_inputs_sha256':meta.get('inputs_sha256','') if version=='v2' else ''})
    if new:
        tmp=ledger.with_suffix('.tmp')
        with tmp.open('w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(old+new)
        tmp.replace(ledger)
    return new

def capture_prospective(snapshot_rows, season, ledger='prospective/selections.csv',
                        previous_games=None, current_games=None):
    if not snapshot_rows:return []
    capture=dt(snapshot_rows[0]['captured_at_utc'])
    if capture is None:raise ValueError('Snapshot must have a valid UTC capture time')
    def fetch_games(year):
        response=requests.get('https://api.collegefootballdata.com/games',
            params={'year':year,'seasonType':'regular'},
            headers={'Authorization':'Bearer '+os.environ['CFBD_API_KEY']},timeout=45)
        response.raise_for_status();return response.json()
    if previous_games is None:previous_games=fetch_games(season-1)
    if current_games is None:current_games=fetch_games(season)
    ratings,meta=build_v2(previous_games,current_games,capture)
    # Hash complete fetched game payloads for reproducibility; only eligible pregame
    # rows enter V2 through build_v2's as-of cutoff.
    meta['inputs_sha256']=hashlib.sha256(json.dumps(
        [previous_games,current_games],sort_keys=True,separators=(',',':')).encode()).hexdigest()
    new=freeze(snapshot_rows,ratings,ledger,meta)
    print(json.dumps({'prospective_new_v1':sum(x['model_version']=='v1' for x in new),
                      'prospective_new_v2':sum(x['model_version']=='v2' for x in new),
                      'ledger':str(ledger),'rule':RULE},indent=2))
    return new
