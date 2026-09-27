"""Experimental V2 margin ratings. Research only; does not alter V1 snapshots.

Prior-season team strengths are discounted by 50% and regularized toward zero.
Current-season results update those priors using ridge regression. Completed games
must have started at least six hours before `asof`; never ingest live scores.
"""
from datetime import datetime, timedelta, timezone
import math
import numpy as np
from cfb_team_matching import canonical_school, match_rating
from cfb_division_safety import FBS_SCHOOLS, model_allowed


def _eligible(games, cutoff=None):
    rows=[]
    for g in games:
        if not isinstance(g,dict) or not g.get('completed'): continue
        if str(g.get('seasonType',g.get('season_type','regular'))).lower()!='regular':continue
        raw=g.get('startDate') or g.get('start_date')
        if cutoff is not None:
            if not raw: continue
            try: kick=datetime.fromisoformat(str(raw).replace('Z','+00:00'))
            except ValueError:continue
            if kick.tzinfo is None:continue
            if kick.astimezone(timezone.utc)>cutoff:continue
        h=canonical_school(g.get('homeTeam') or g.get('home_team'))
        a=canonical_school(g.get('awayTeam') or g.get('away_team'))
        if h not in FBS_SCHOOLS or a not in FBS_SCHOOLS or not model_allowed(h,a):continue
        hp=g.get('homePoints',g.get('home_points'))
        ap=g.get('awayPoints',g.get('away_points'))
        try:
            if hp is None or ap is None:continue
            hp,ap=float(hp),float(ap)
        except (ValueError,TypeError):continue
        if not (math.isfinite(hp) and math.isfinite(ap)) or (hp==0 and ap==0):continue
        rows.append((h,a,hp-ap))
    return rows


def _fit(rows, home_adv, shrink, prior=None):
    teams=sorted(set(prior or {}) | {t for h,a,_ in rows for t in (h,a)})
    if not teams:return {}
    ix={t:i for i,t in enumerate(teams)}
    X=np.zeros((len(rows),len(teams)))
    y=np.zeros(len(rows))
    for i,(h,a,margin) in enumerate(rows):
        X[i,ix[h]]=1;X[i,ix[a]]=-1;y[i]=margin-home_adv
    center=np.array([(prior or {}).get(t,0.) for t in teams])
    # A zero-centered constraint prevents arbitrary common shifts.
    matrix=X.T@X+np.eye(len(teams))*shrink+np.ones((len(teams),len(teams)))/len(teams)
    rhs=X.T@y+shrink*center
    result=np.linalg.solve(matrix,rhs)
    return dict(zip(teams,map(float,result)))


def build_v2(previous_games,current_games,asof,home_adv=2.5,shrink=4.,prior_weight=.5):
    if asof.tzinfo is None:raise ValueError('asof must include a timezone')
    if shrink<=0 or not 0<=prior_weight<=1:raise ValueError('invalid parameters')
    prev=_eligible(previous_games)
    prior_raw=_fit(prev,home_adv,shrink)
    prior={team:prior_weight*rating for team,rating in prior_raw.items()}
    current=_eligible(current_games,asof.astimezone(timezone.utc)-timedelta(hours=6))
    ratings=_fit(current,home_adv,shrink,prior)
    return ratings,{'previous_games':len(prev),'current_games':len(current),'prior_teams':len(prior)}


def projected_margin(home,away,ratings,home_adv=2.5):
    if not model_allowed(home,away):return None
    h,_,_=match_rating(home,ratings)
    a,_,_=match_rating(away,ratings)
    return h-a+home_adv if h is not None and a is not None else None
