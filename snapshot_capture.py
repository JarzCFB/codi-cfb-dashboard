"""Capture actual pre-kickoff NCAAF spread quotes and as-of team ratings.
Run via GitHub Actions; never put API keys in this file or output.
"""
import csv
import hashlib
import json
import math
import os
import re
from datetime import timedelta
from datetime import datetime, timezone
from pathlib import Path
import requests

ODDS = 'https://api.the-odds-api.com/v4/sports/americanfootball_ncaaf/odds/'
CFBD = 'https://api.collegefootballdata.com/games'
COLUMNS = ['captured_at_utc','game_id','kickoff_utc','home_team','away_team','sportsbook_key','sportsbook','bookmaker_last_update_utc','market_last_update_utc','selection','spread','american_odds','season','ratings_asof_utc','ratings_training_games','home_rating','away_rating','projected_home_margin','ratings_input_sha256','capture_status']

def utc(dt):
    if not dt: return None
    try: return datetime.fromisoformat(str(dt).replace('Z','+00:00')).astimezone(timezone.utc)
    except (TypeError, ValueError): return None

def iso(dt): return dt.isoformat(timespec='seconds').replace('+00:00','Z')

def fetch(url, **kw):
    r=requests.get(url,timeout=40,**kw)
    r.raise_for_status()
    return r.json(),r.headers

# Explicit, unambiguous Odds API names -> CFBD school names.
# Unknown names are left unmatched rather than assigned a possibly wrong rating.
from cfb_team_matching import canonical_school, normalize as normalize_team, match_rating, ALIASES as TEAM_ALIASES

def ratings_from_prior_games(games, now, home_adv=2.5, shrink=4.0):
    # Use only completed regular-season games that kicked off at least six
    # hours before capture. This is a conservative publication-time proxy.
    import numpy as np
    eligible=[]
    cutoff=now-timedelta(hours=6)
    for g in games:
        kick=utc(g.get('startDate') or g.get('start_date'))
        h=g.get('homeTeam') or g.get('home_team')
        a=g.get('awayTeam') or g.get('away_team')
        hp=g.get('homePoints',g.get('home_points'))
        ap=g.get('awayPoints',g.get('away_points'))
        if not kick or kick>cutoff or not g.get('completed') or not h or not a or hp is None or ap is None:continue
        if str(g.get('seasonType',g.get('season_type','regular'))).lower()!='regular':continue
        if float(hp)==0 and float(ap)==0:continue
        eligible.append((canonical_school(h),canonical_school(a),float(hp)-float(ap),str(g.get('id'))))
    payload=json.dumps(sorted(eligible),separators=(',',':'))
    digest=hashlib.sha256(payload.encode()).hexdigest()
    teams=sorted(set(t for h,a,_,_ in eligible for t in (h,a)))
    if not teams:return {},0,digest
    ix={t:i for i,t in enumerate(teams)}
    A=np.zeros((len(eligible)+1,len(teams)));y=np.zeros(len(eligible)+1)
    for j,(h,a,margin,_) in enumerate(eligible):
        A[j,ix[h]]=1;A[j,ix[a]]=-1;y[j]=margin-home_adv
    A[-1,:]=1/len(teams)
    values=np.linalg.solve(A.T@A+np.eye(len(teams))*shrink,A.T@y)
    return dict(zip(teams,map(float,values))),len(eligible),digest

def capture(now=None, odds=None, games=None, output_dir='snapshots', season=None):
    now=now or datetime.now(timezone.utc)
    season=season or now.year
    if odds is None:
        key=os.environ['ODDS_API_KEY']
        odds,headers=fetch(ODDS,params={'apiKey':key,'regions':'us','markets':'spreads','oddsFormat':'american','dateFormat':'iso'})
        print('Odds API credits remaining:',headers.get('x-requests-remaining','unknown'))
    if games is None:
        games,_=fetch(CFBD,params={'year':season,'seasonType':'regular'},headers={'Authorization':'Bearer '+os.environ['CFBD_API_KEY']})
    ratings,n_train,digest=ratings_from_prior_games(games,now)
    rows=[]
    matched_games=set(); unmatched_teams=set()
    for g in odds:
        kick=utc(g.get('commence_time'))
        if not kick or kick<=now:continue
        home=g.get('home_team');away=g.get('away_team')
        if not home or not away:continue
        hr,hkey,hmethod=match_rating(home,ratings)
        ar,akey,amethod=match_rating(away,ratings)
        if hr is not None and ar is not None:matched_games.add(g.get('id'))
        else:
            if hr is None:unmatched_teams.add(home)
            if ar is None:unmatched_teams.add(away)
        projected=hr-ar+2.5 if hr is not None and ar is not None else None
        for bk in g.get('bookmakers',[]):
            for m in bk.get('markets',[]):
                if m.get('key')!='spreads':continue
                for o in m.get('outcomes',[]):
                    if o.get('name') not in (home,away):continue
                    try:
                        spread=float(o['point']);price=float(o['price'])
                        if not math.isfinite(spread) or not math.isfinite(price) or price==0:continue
                    except (KeyError,ValueError,TypeError):continue
                    rows.append(dict(captured_at_utc=iso(now),game_id=g.get('id'),kickoff_utc=iso(kick),home_team=home,away_team=away,sportsbook_key=bk.get('key'),sportsbook=bk.get('title'),bookmaker_last_update_utc=bk.get('last_update'),market_last_update_utc=m.get('last_update'),selection=o['name'],spread=spread,american_odds=price,season=season,ratings_asof_utc=iso(now),ratings_training_games=n_train,home_rating=hr,away_rating=ar,projected_home_margin=projected,ratings_input_sha256=digest,capture_status='timestamped_live_quote'))
    folder=Path(output_dir)/str(season);folder.mkdir(parents=True,exist_ok=True)
    path=folder/(now.strftime('%Y%m%dT%H%M%SZ')+'.csv')
    # Atomic write: no partially written snapshots.
    temp=path.with_suffix('.tmp')
    with temp.open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=COLUMNS);writer.writeheader();writer.writerows(rows)
    temp.replace(path)
    print(f'Saved {len(rows)} pregame quotes; {n_train} completed rating inputs; {len(matched_games)} games with both ratings; file {path}')
    if unmatched_teams:
        print('Teams missing ratings (name mismatch OR no eligible prior games):')
        for team in sorted(unmatched_teams):
            alias=TEAM_ALIASES.get(normalize_team(team),team)
            candidate=canonical_school(alias)
            print(f'  {team!r} -> {candidate!r}; in training={candidate in ratings}; method={match_rating(team,ratings)[2]}')
        print('No rating is fabricated for teams absent from the training set.')
    return rows,path

if __name__=='__main__':capture()
