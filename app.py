"""Personal CFB odds dashboard. API keys are server-side Streamlit secrets."""
import io
import math
import re
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd
import requests
import streamlit as st
from scipy.stats import norm
from scipy.optimize import minimize_scalar
from scipy.special import expit

st.set_page_config(page_title="Codi's CFB Dashboard", page_icon="🏈", layout="wide")
st.title("College football · Odds & value dashboard")
st.caption("Independent rating model • live bookmaker comparisons • personal bet journal")

ODDS_URL = "https://api.the-odds-api.com/v4/sports/americanfootball_ncaaf/odds/"
CFBD_URL = "https://api.collegefootballdata.com"

def secret(name):
    try: return st.secrets.get(name, "")
    except Exception: return ""

def api_get(url, **kwargs):
    r = requests.get(url, timeout=25, **kwargs)
    r.raise_for_status()
    return r.json(), r.headers

@st.cache_data(ttl=14400, show_spinner="Fetching bookmaker odds…")
def odds_data(key, markets):
    data, headers = api_get(ODDS_URL, params={"apiKey":key,"regions":"us","markets":markets,"oddsFormat":"american","dateFormat":"iso"})
    return data, headers.get("x-requests-remaining", "unknown")

@st.cache_data(ttl=86400, show_spinner="Fetching team results…")
def games_data(key, year):
    data,_ = api_get(f"{CFBD_URL}/games", params={"year":year,"seasonType":"regular"}, headers={"Authorization":f"Bearer {key}"})
    return data

from cfb_team_matching import canonical_school, match_rating

def key_name(s):
    return canonical_school(s)

def build_ratings(games, season, shrink=4.0, home_adv=2.5, asof=None):
    """Same ridge ratings as capture, with an optional strict as-of cutoff."""
    rows=[]
    cutoff=(asof-timedelta(hours=6)) if asof is not None else None
    for g in games:
        if not isinstance(g,dict) or not g.get("completed"): continue
        if str(g.get("seasonType",g.get("season_type","regular"))).lower()!="regular": continue
        if cutoff is not None:
            kick=pd.to_datetime(g.get("startDate",g.get("start_date")),utc=True,errors="coerce")
            if pd.isna(kick) or kick.to_pydatetime()>cutoff: continue
        a=g.get("home_team",g.get("homeTeam"));b=g.get("away_team",g.get("awayTeam"))
        hs=g.get("home_points",g.get("homePoints"));aws=g.get("away_points",g.get("awayPoints"))
        if not a or not b or hs is None or aws is None:continue
        try: margin=float(hs)-float(aws)
        except (TypeError,ValueError):continue
        if not math.isfinite(margin) or (float(hs)==0 and float(aws)==0):continue
        rows.append((key_name(a),key_name(b),margin))
    teams=sorted(set(t for a,b,_ in rows for t in (a,b)))
    if not teams:return {},0
    idx={t:i for i,t in enumerate(teams)}
    A=np.zeros((len(rows)+1,len(teams)));y=np.zeros(len(rows)+1)
    for j,(a,b,m) in enumerate(rows):
        A[j,idx[a]]=1;A[j,idx[b]]=-1;y[j]=m-home_adv
    A[-1,:]=1/len(teams)
    vals=np.linalg.solve(A.T@A+np.eye(len(teams))*shrink,A.T@y)
    return dict(zip(teams,map(float,vals))),len(rows)

def american_prob(price):
    p=float(price)
    if p == 0: raise ValueError("American odds cannot be zero")
    return 100/(p+100) if p>0 else -p/(-p+100)

def profit_per_dollar(price):
    p=float(price)
    if p == 0: raise ValueError("American odds cannot be zero")
    return p/100 if p>0 else 100/-p

def find_rating(team, ratings):
    value, school, method = match_rating(team, ratings)
    return value

def odds_frame(data, ratings, home_adv, sd):
    out=[]
    for g in data:
        if not isinstance(g, dict): continue
        h,a=g.get("home_team"),g.get("away_team")
        if not h or not a:continue
        hr,ar=find_rating(h,ratings),find_rating(a,ratings)
        pred=(hr-ar+home_adv) if hr is not None and ar is not None else None
        for bk in (g.get("bookmakers") or []):
            if not isinstance(bk, dict): continue
            for market in (bk.get("markets") or []):
                if not isinstance(market, dict): continue
                if market.get("key")!="spreads":continue
                for selection in (market.get("outcomes") or []):
                    if not isinstance(selection, dict): continue
                    name=selection.get("name")
                    point=selection.get("point")
                    price=selection.get("price")
                    if name not in (h,a) or point is None or price is None:continue
                    try:
                        point=float(point)
                        price=float(price)
                        if not math.isfinite(point) or not math.isfinite(price) or price == 0: continue
                        implied=american_prob(price)
                    except (TypeError, ValueError, OverflowError):
                        continue
                    is_home=name==h
                    # Team cover if (team margin + point) > 0. For a normal margin distribution.
                    model_margin=(pred if is_home else -pred) if pred is not None else None
                    p_cover=float(norm.cdf((model_margin+float(point))/sd)) if pred is not None else None
                    ev=p_cover*profit_per_dollar(price)-(1-p_cover) if p_cover is not None else None
                    out.append({"Kickoff UTC":g.get("commence_time"),"Matchup":f"{a} @ {h}","Team":name,"Book":bk.get("title"),"Spread":point,"Odds":price,"Projected home margin":round(pred,1) if pred is not None else None,"Cover probability":round(p_cover,3) if p_cover is not None else None,"Break-even":round(implied,3),"Expected ROI":round(ev,3) if ev is not None else None,"Model edge (pp)":round(100*(p_cover-implied),1) if p_cover is not None else None})
    return pd.DataFrame(out)

with st.sidebar:
    st.header("Settings")
    year=st.number_input("Season",min_value=2020,max_value=2030,value=2026,step=1)
    home_adv=st.slider("Home-field points",0.0,5.0,2.5,0.5)
    shrink=st.slider("Early-season rating shrinkage",0.5,12.0,4.0,0.5)
    sd=st.slider("Game-margin uncertainty (points)",8.0,22.0,14.0,0.5)
    min_roi=st.slider("Minimum estimated ROI to display",0,20,3,1)/100
    st.caption("Illustrative, uncalibrated probabilities. Historical spread tests have not demonstrated positive betting returns.")
    if st.button("Refresh now"):
        odds_data.clear();games_data.clear();st.rerun()

ok_odds=bool(secret("ODDS_API_KEY"));ok_cfbd=bool(secret("CFBD_API_KEY"))
if not ok_odds or not ok_cfbd:
    st.warning("Connect both free API keys in Streamlit → App settings → Secrets. See README for exact steps.")
    st.info("Your API keys belong in private server-side secrets, never in this app's public code.")

ratings={}; n_games=0
if ok_cfbd:
    try:
        games=games_data(secret("CFBD_API_KEY"),int(year))
        if not isinstance(games, list):
            st.error(f"CFBD returned {type(games).__name__} rather than a list of games. Check your API plan and response.")
            games=[]
        if games:
            for game in games:
                game["home_team"] = game.get("homeTeam")
                game["away_team"] = game.get("awayTeam")
                game["home_points"] = game.get("homePoints")
                game["away_points"] = game.get("awayPoints")
                game["season_type"] = game.get("seasonType")
        ratings,n_games=build_ratings(games,int(year),shrink,home_adv,asof=datetime.now(timezone.utc))
        st.caption(f"CFBD diagnostic: {len(games)} games returned; {sum(g.get('home_points') is not None and g.get('away_points') is not None for g in games if isinstance(g,dict))} have both scores.")
        if n_games == 0 and games:
            sample=next((g for g in games if isinstance(g,dict)),{})
            st.info(f"Sample game (no credentials): {sample.get('home_team','?')} vs {sample.get('away_team','?')}; completed={sample.get('completed','?')}; home_points={sample.get('home_points','?')}; away_points={sample.get('away_points','?')}. Check whether the API provides scores for your chosen season.")
        if n_games == 0:
            st.warning("CFBD returned no completed regular-season games with scores for this season. Verify the season and the returned game data. Model probabilities are unavailable until results load.")
        st.caption(f"Ratings fitted to {n_games} completed regular-season games. Refreshed daily.")
    except Exception as exc:st.error(f"CFBD data unavailable: {exc}")

if ok_odds:
    try:
        data,remaining=odds_data(secret("ODDS_API_KEY"),"spreads")
        st.caption(f"Odds cached for four hours · API credits remaining: {remaining} · Refresh uses additional credits")
        df=odds_frame(data,ratings,home_adv,sd)
        missing_names=sorted({team for game in data if isinstance(game,dict) for team in (game.get("home_team"),game.get("away_team")) if team and find_rating(team,ratings) is None})
        if missing_names:
            with st.expander(f"Missing model ratings: {len(missing_names)} teams (diagnostic)"):
                st.caption("An unmatched team may be absent from the eligible training games, or its sportsbook name may not map to the CFBD school name.")
                st.dataframe(pd.DataFrame([{"Sportsbook team":name,"Canonical school":canonical_school(name),"Matching method":match_rating(name,ratings)[2]} for name in missing_names]),hide_index=True,use_container_width=True)
        if df.empty and data:
            st.warning("The odds API returned events but no usable spread quotes. Some bookmakers may not have posted spreads yet.")
        if not df.empty:
            books=sorted(df["Book"].dropna().unique())
            selected=st.multiselect("Bookmakers",books,default=books)
            df=df[df["Book"].isin(selected)].copy()
            tab1,tab2,tab3=st.tabs(["Model comparisons","Best available price by team","All quoted lines"])
            with tab1:
                st.warning("RESEARCH ONLY: Original cover probabilities and expected ROI are unvalidated. Results are sorted by kickoff, not projected ROI; no betting advantage has been established.")
                st.caption("Research screen only. Missing team ratings are excluded.")
                candidates=df[df["Expected ROI"].notna() & (df["Expected ROI"]>=min_roi)].sort_values(["Kickoff UTC","Matchup","Team"])
                st.dataframe(candidates,hide_index=True,use_container_width=True)
            with tab2:
                best=df.assign(_has_roi=df["Expected ROI"].notna()).sort_values(["Matchup","Team","_has_roi","Expected ROI"],ascending=[True,True,False,False]).drop_duplicates(["Matchup","Team"]).drop(columns="_has_roi")
                st.dataframe(best,hide_index=True,use_container_width=True)
            with tab3:st.dataframe(df,hide_index=True,use_container_width=True)
            st.download_button("Export odds and model calculations",df.to_csv(index=False),file_name="cfb_odds_snapshot.csv",mime="text/csv")
        else:st.info("No upcoming spread lines returned by the provider.")
    except Exception as exc:st.error(f"Odds feed unavailable: {exc}")


# Historical validation: fit on earlier weeks only; never train on the game being predicted.
def historical_backtest(games, shrink, home_adv, sd, first_test_week=5):
    from collections import defaultdict
    weeks=defaultdict(list)
    for raw in games:
        if not isinstance(raw,dict): continue
        g=dict(raw)
        g["home_team"]=g.get("homeTeam",g.get("home_team"))
        g["away_team"]=g.get("awayTeam",g.get("away_team"))
        g["home_points"]=g.get("homePoints",g.get("home_points"))
        g["away_points"]=g.get("awayPoints",g.get("away_points"))
        if not g.get("completed") or g.get("home_points") is None or g.get("away_points") is None: continue
        if g.get("home_points") == 0 and g.get("away_points") == 0: continue
        if str(g.get("seasonType",g.get("season_type","regular"))).lower() != "regular": continue
        try: w=int(g.get("week")); float(g["home_points"]);float(g["away_points"])
        except (TypeError,ValueError): continue
        if not g.get("home_team") or not g.get("away_team"):continue
        weeks[w].append(g)
    # Deduplicate by provider game ID where available; otherwise by week and teams.
    seen=set()
    for week in sorted(weeks):
        unique=[]
        for g in weeks[week]:
            identifier=("id",g["id"]) if g.get("id") is not None else ("teams",week,key_name(g["home_team"]),key_name(g["away_team"]))
            if identifier in seen: continue
            seen.add(identifier);unique.append(g)
        weeks[week]=unique
    past=[];rows=[]
    for week in sorted(weeks):
        if week >= first_test_week and past:
            ratings,_=build_ratings(past,0,shrink,home_adv)
            for g in weeks[week]:
                hr=find_rating(g["home_team"],ratings);ar=find_rating(g["away_team"],ratings)
                if hr is None or ar is None: continue
                predicted=hr-ar+home_adv
                actual=float(g["home_points"])-float(g["away_points"])
                rows.append({"Week":week,"Matchup":f'{g["away_team"]} @ {g["home_team"]}',
                             "Predicted home margin":round(predicted,2),"Actual home margin":actual,
                             "Absolute error":abs(predicted-actual),
                             "Home win probability":float(norm.cdf(predicted/sd)),
                             "Home won":int(actual>0) if actual != 0 else None,
                             "Home team":g["home_team"],"Away team":g["away_team"],
                             "Game ID":g.get("id"),"Kickoff UTC":g.get("startDate",g.get("start_date")),
                             "Season":g.get("season") })
        past.extend(weeks[week])
    return pd.DataFrame(rows)

st.divider()
st.subheader("Historical model validation")
st.caption("Walk-forward test: each week's predictions use only results from earlier weeks. "
           "This evaluates game-margin and winner forecasts, not betting profitability; historical bookmaker spreads are not included.")
with st.expander("Run historical backtest",expanded=False):
    test_year=st.number_input("Completed season to test",min_value=2020,max_value=2025,value=2025,step=1)
    first_week=st.slider("First evaluation week",3,10,5)
    if st.button("Run backtest"):
        if not ok_cfbd:
            st.error("Add CFBD_API_KEY to Streamlit Secrets first.")
        else:
            try:
                hist=games_data(secret("CFBD_API_KEY"),int(test_year))
                bt=historical_backtest(hist,shrink,home_adv,sd,first_week)
                if bt.empty:
                    st.warning("No eligible historical games. Check season, data coverage, and first evaluation week.")
                else:
                    evaluated=bt[bt["Home won"].notna()].copy()
                    mae=bt["Absolute error"].mean()
                    winner_accuracy=((evaluated["Predicted home margin"]>0)==(evaluated["Home won"]==1)).mean() if len(evaluated) else float("nan")
                    baseline=bt["Actual home margin"].abs().mean() # predicts 0 margin for every game
                    brier=((evaluated["Home win probability"]-evaluated["Home won"])**2).mean() if len(evaluated) else float("nan")
                    c1,c2,c3,c4=st.columns(4)
                    c1.metric("Games tested",len(bt))
                    c2.metric("Margin MAE",f"{mae:.1f} pts")
                    c3.metric("Winner accuracy",f"{winner_accuracy:.1%}")
                    c4.metric("Brier score",f"{brier:.3f}")
                    st.caption(f"Zero-margin baseline MAE: {baseline:.1f} points. Lower MAE/Brier is better. "
                               "The historical test uses current slider settings; no tuning or calibration is performed.")
                    st.dataframe(bt,hide_index=True,use_container_width=True)
                    st.download_button("Download backtest results",bt.to_csv(index=False),
                                       file_name=f"cfb_backtest_{test_year}.csv",mime="text/csv")
            except Exception as exc:
                st.error(f"Backtest unavailable: {exc}")


# Historical odds must be supplied with a pre-kickoff capture timestamp.
# Current Odds API prices must NEVER be substituted for historical prices.
def validate_historical_lines(lines, predictions, season):
    required={"season","week","home_team","away_team","selection","spread","american_odds","captured_at_utc","kickoff_utc","sportsbook"}
    missing=required-set(lines.columns)
    if missing: raise ValueError("Historical odds CSV missing columns: "+", ".join(sorted(missing)))
    lines=lines.copy()
    lines["season"]=pd.to_numeric(lines["season"],errors="coerce")
    lines["week"]=pd.to_numeric(lines["week"],errors="coerce")
    lines["spread"]=pd.to_numeric(lines["spread"],errors="coerce")
    lines["american_odds"]=pd.to_numeric(lines["american_odds"],errors="coerce")
    lines["captured_at_utc"]=pd.to_datetime(lines["captured_at_utc"],utc=True,errors="coerce")
    lines["kickoff_utc"]=pd.to_datetime(lines["kickoff_utc"],utc=True,errors="coerce")
    initial=len(lines)
    lines=lines[(lines.season==int(season)) & lines.week.notna() & lines.spread.notna() & lines.american_odds.notna() &
                (lines.american_odds!=0) & lines.captured_at_utc.notna() & lines.kickoff_utc.notna() &
                (lines.captured_at_utc < lines.kickoff_utc)].copy()
    lines["hkey"]=lines.home_team.map(key_name);lines["akey"]=lines.away_team.map(key_name)
    lines["skey"]=lines.selection.map(key_name)
    lines=lines[lines.skey.isin(set(lines.hkey).union(set(lines.akey)))].copy()
    # One quote per sportsbook/market/selection/game: most recent strictly pre-kickoff snapshot.
    lines=lines.sort_values("captured_at_utc").drop_duplicates(["season","week","hkey","akey","sportsbook","skey"],keep="last")
    preds=predictions.copy()
    preds["hkey"]=preds["Home team"].map(key_name);preds["akey"]=preds["Away team"].map(key_name)
    joined=lines.merge(preds,on=["hkey","akey"],how="inner",suffixes=("","_prediction"))
    joined=joined[joined.week==joined.Week].copy()
    if "Kickoff UTC" in joined:
        pred_kick=pd.to_datetime(joined["Kickoff UTC"],utc=True,errors="coerce")
        joined=joined[pred_kick.notna() & ((pred_kick-joined.kickoff_utc).abs()<=pd.Timedelta(hours=3))].copy()
    joined=joined[joined.skey.eq(joined.hkey)|joined.skey.eq(joined.akey)].copy()
    if joined.empty: return joined,initial,len(lines)
    joined["Actual selection margin"]=np.where(joined.skey==joined.hkey,joined["Actual home margin"],-joined["Actual home margin"])
    joined["Predicted selection margin"]=np.where(joined.skey==joined.hkey,joined["Predicted home margin"],-joined["Predicted home margin"])
    joined["Result margin"]=joined["Actual selection margin"]+joined.spread
    joined["Settlement"]=np.select([joined["Result margin"]>0,joined["Result margin"]<0],["Win","Loss"],default="Push")
    joined["Break-even probability"]=joined.american_odds.map(american_prob)
    joined["Model cover probability"]=norm.cdf((joined["Predicted selection margin"]+joined.spread)/sd)
    joined["Estimated EV per $1"]=joined["Model cover probability"]*joined.american_odds.map(profit_per_dollar)-(1-joined["Model cover probability"])
    joined["Net per $1"]=np.where(joined.Settlement=="Win",joined.american_odds.map(profit_per_dollar),np.where(joined.Settlement=="Loss",-1.0,0.0))
    return joined,initial,len(lines)

st.divider()
st.subheader("Historical sportsbook validation")
st.caption("Upload real, timestamped historical spreads. Only quotes captured before kickoff are eligible. No paid historical API required; this does not fetch or fabricate historical prices.")
st.download_button("Download historical odds CSV template",
    "season,week,home_team,away_team,selection,spread,american_odds,captured_at_utc,kickoff_utc,sportsbook\n",
    "historical_odds_template.csv",mime="text/csv")
with st.expander("Audit existing backtest and test historical spreads"):
    uploaded_predictions=st.file_uploader("Upload walk-forward backtest CSV (or rerun above)",type="csv",key="pred_csv")
    uploaded_lines=st.file_uploader("Upload timestamped historical sportsbook odds CSV",type="csv",key="hist_lines")
    audit_year=st.number_input("Historical odds season",2020,2025,2025,key="audit_year")
    if uploaded_predictions is not None:
        try:
            preds=pd.read_csv(uploaded_predictions)
            required_pred={"Week","Home team","Away team","Predicted home margin","Actual home margin","Kickoff UTC"}
            missing=required_pred-set(preds.columns)
            if missing:
                st.error("Backtest CSV missing: "+", ".join(sorted(missing))+". Rerun and download using this updated app.")
            else:
                duplicated=preds.duplicated(["Week","Home team","Away team"],keep=False)
                invalid=preds["Actual home margin"].isna() | preds["Predicted home margin"].isna()
                suspicious=(preds["Actual home margin"]==0)
                a,b,c=st.columns(3)
                a.metric("Duplicate matchup rows",int(duplicated.sum()))
                b.metric("Missing margin rows",int(invalid.sum()))
                c.metric("Zero-margin rows to inspect",int(suspicious.sum()))
                if duplicated.any():st.dataframe(preds.loc[duplicated].sort_values("Week"),hide_index=True)
                st.info("Week-by-week predictions use earlier weeks, not the evaluated week. However, this audit cannot independently prove source data was available before each kickoff or exclude earlier-week corrections published later.")
                if uploaded_lines is not None:
                    try:
                        odds=pd.read_csv(uploaded_lines)
                        joined,total,eligible=validate_historical_lines(odds,preds,audit_year)
                        st.caption(f"Historical odds: {total} uploaded rows; {eligible} valid distinct pre-kickoff quotes; {len(joined)} matched predictions.")
                        if joined.empty:st.warning("No eligible matched historical odds. Check exact teams, season, week, kickoff and capture timestamps.")
                        else:
                            st.warning("Each sportsbook quote is correlated with other quotes for the same game. These results are descriptive, not an independent sample of bets. No selection strategy was optimized or validated here.")
                            c1,c2,c3=st.columns(3)
                            c1.metric("Matched quotes",len(joined))
                            c2.metric("All-quote flat-stake ROI",f"{joined['Net per $1'].mean():.1%}")
                            c3.metric("Pushes",int((joined.Settlement=="Push").sum()))
                            st.dataframe(joined[["Week","Matchup","sportsbook","selection","spread","american_odds","captured_at_utc","Settlement","Net per $1","Estimated EV per $1"]],hide_index=True)
                            st.download_button("Download historical quote audit",joined.to_csv(index=False),"cfb_historical_quote_audit.csv",mime="text/csv")
                    except Exception as exc:st.error(f"Historical odds validation failed: {exc}")
        except Exception as exc:st.error(f"Backtest audit failed: {exc}")

# CFBD historical spreads: free-tier /lines data generally has no quote timestamps
# or spread-side prices. Treat these as historical reference lines, NOT verified
# pre-kickoff offers. Never report realized betting ROI from this source.
@st.cache_data(ttl=86400, show_spinner="Fetching CFBD historical spreads…")
def cfbd_historical_spreads(key, season):
    response, _ = api_get(f"{CFBD_URL}/lines", params={"year": int(season), "seasonType": "regular"},
                          headers={"Authorization": f"Bearer {key}"})
    if not isinstance(response, list):
        raise ValueError("CFBD returned an unexpected response for /lines")
    return response

def match_cfbd_spreads(predictions, games_with_lines, min_edge=3.0, provider="All providers (median)"):
    required={"Game ID","Predicted home margin","Actual home margin","Home team","Away team"}
    missing=required-set(predictions.columns)
    if missing: raise ValueError("Backtest is missing: "+", ".join(sorted(missing)))
    # Match on CFBD's game ID; do not guess matches using similarly named teams.
    preds=predictions.copy()
    preds["Game ID"]=pd.to_numeric(preds["Game ID"],errors="coerce")
    preds=preds.dropna(subset=["Game ID","Predicted home margin","Actual home margin"])
    preds=preds.drop_duplicates("Game ID",keep="first")
    raw=[]
    for game in games_with_lines:
        if not isinstance(game,dict): continue
        gid=game.get("id") or game.get("gameId") or game.get("game_id")
        for quote in (game.get("lines") or []):
            if not isinstance(quote,dict):continue
            spread=quote.get("spread")
            if spread is None:continue
            try: spread=float(spread)
            except (ValueError,TypeError):continue
            if not math.isfinite(spread):continue
            raw.append({"Game ID":gid,"Provider":str(quote.get("provider") or "Unknown"),
                        "Home spread":spread,"Opening home spread":quote.get("spreadOpen"),
                        "Home moneyline":quote.get("homeMoneyline"),"Away moneyline":quote.get("awayMoneyline")})
    quotes=pd.DataFrame(raw)
    if quotes.empty:return pd.DataFrame(),quotes
    quotes["Game ID"]=pd.to_numeric(quotes["Game ID"],errors="coerce")
    quotes=quotes.dropna(subset=["Game ID"]).drop_duplicates(["Game ID","Provider"],keep="last")
    if provider != "All providers (median)":
        quotes=quotes[quotes.Provider==provider].copy()
    if quotes.empty:return pd.DataFrame(),quotes
    # A single representative spread per game avoids counting several correlated
    # sportsbook listings as independent betting opportunities.
    grouped=quotes.groupby("Game ID",as_index=False).agg({"Home spread":"median","Provider":"first"})
    if provider=="All providers (median)":grouped["Provider"]="Median of available providers"
    joined=preds.merge(grouped,on="Game ID",how="inner",validate="one_to_one")
    if joined.empty:return joined,quotes
    joined["Market-implied home margin"]=-joined["Home spread"]
    joined["Model vs market (pts)"]=joined["Predicted home margin"]-joined["Market-implied home margin"]
    joined["Model selection"]=np.where(joined["Model vs market (pts)"]>0,joined["Home team"],joined["Away team"])
    joined["Selected spread"]=np.where(joined["Model vs market (pts)"]>0,joined["Home spread"],-joined["Home spread"])
    joined["Selected final margin"]=np.where(joined["Model vs market (pts)"]>0,joined["Actual home margin"],-joined["Actual home margin"])
    joined["Against-spread result"]=np.select(
        [joined["Selected final margin"]+joined["Selected spread"]>0,
         joined["Selected final margin"]+joined["Selected spread"]<0],
        ["Cover","Miss"],default="Push")
    joined["Absolute market edge (pts)"]=joined["Model vs market (pts)"].abs()
    joined=joined[joined["Absolute market edge (pts)"]>=float(min_edge)].copy()
    return joined,quotes

st.divider()
st.subheader("Automatic CFBD historical spread comparison")
st.caption("Uses the free-tier CFBD /lines endpoint and matches game IDs to your walk-forward backtest. "
           "CFBD's reference spreads are not guaranteed to be timestamped pre-kickoff quotes. "
           "No historical spread-side prices are assumed and no realized ROI is claimed.")
with st.expander("Fetch 2025 spreads and compare against my predictions",expanded=False):
    cfbd_year=st.number_input("Season to compare",min_value=2020,max_value=2025,value=2025,step=1,key="cfbd_lines_year")
    cfbd_first_week=st.slider("First evaluation week for new backtest",3,10,5,key="cfbd_lines_first_week")
    cfbd_edge=st.slider("Minimum model-versus-market difference (points)",0.0,14.0,3.0,0.5,key="cfbd_lines_edge")
    cfbd_uploaded=st.file_uploader("Optional: use your existing backtest CSV instead of rerunning",type="csv",key="cfbd_bt_upload")
    if st.button("Fetch CFBD spreads and evaluate",key="cfbd_lines_run"):
        if not ok_cfbd:st.error("Add CFBD_API_KEY to Streamlit Secrets first.")
        else:
            try:
                if cfbd_uploaded is not None:
                    model_predictions=pd.read_csv(cfbd_uploaded)
                    if "Season" in model_predictions:
                        model_predictions=model_predictions[pd.to_numeric(model_predictions["Season"],errors="coerce")==int(cfbd_year)]
                else:
                    historical_games=games_data(secret("CFBD_API_KEY"),int(cfbd_year))
                    model_predictions=historical_backtest(historical_games,shrink,home_adv,sd,cfbd_first_week)
                if model_predictions.empty:
                    st.warning("No eligible predictions for this season. Upload a matching backtest CSV or rerun.")
                else:
                    fetched=cfbd_historical_spreads(secret("CFBD_API_KEY"),int(cfbd_year))
                    all_providers=sorted({str(q.get("provider")) for g in fetched if isinstance(g,dict)
                                         for q in (g.get("lines") or []) if isinstance(q,dict) and q.get("provider")})
                    st.session_state["cfbd_fetched"]=fetched
                    st.session_state["cfbd_predictions"]=model_predictions
                    st.success(f"Retrieved {len(fetched):,} CFBD game records with historical line data.")
                    st.caption("Available providers: "+(", ".join(all_providers) if all_providers else "none returned"))
            except requests.HTTPError as exc:
                st.error(f"CFBD /lines request failed: {exc}. Check the key, endpoint access and monthly call allowance.")
            except Exception as exc:st.error(f"Historical spread import failed: {exc}")
    if "cfbd_fetched" in st.session_state and "cfbd_predictions" in st.session_state:
        stored=st.session_state["cfbd_fetched"]
        options=["All providers (median)"]+sorted({str(q.get("provider")) for g in stored if isinstance(g,dict)
                           for q in (g.get("lines") or []) if isinstance(q,dict) and q.get("provider")})
        chosen=st.selectbox("Historical line provider",options,key="cfbd_provider_choice")
        try:
            compared,raw_quotes=match_cfbd_spreads(st.session_state["cfbd_predictions"],stored,cfbd_edge,chosen)
            # Diagnose the join separately from the edge threshold so an ID/schema
            # mismatch is not mistaken for a lack of model/market opportunities.
            baseline, all_quotes = match_cfbd_spreads(st.session_state["cfbd_predictions"],stored,0.0,chosen)
            st.caption(f"Backtest predictions: {len(st.session_state['cfbd_predictions']):,} · "
                       f"Valid provider quotes: {len(all_quotes):,} · "
                       f"Matched games before edge filter: {len(baseline):,} · "
                       f"Qualifying games: {len(compared):,}")
            if compared.empty:
                if baseline.empty:
                    st.warning("No games matched by CFBD game ID. Check the season, uploaded backtest, and returned game IDs.")
                else:
                    st.warning("Games matched, but none reached the minimum model/market difference. Lower the threshold.")
            else:
                decided=compared[compared["Against-spread result"]!="Push"]
                a,b,c,d=st.columns(4)
                a.metric("Games with qualifying differences",len(compared))
                b.metric("Cover rate (excluding pushes)",f"{(decided['Against-spread result']=='Cover').mean():.1%}" if len(decided) else "N/A")
                c.metric("Pushes",int((compared["Against-spread result"]=="Push").sum()))
                d.metric("Average model/market gap",f"{compared['Absolute market edge (pts)'].mean():.1f} pts")
                st.warning("Exploratory comparison only: CFBD does not establish that each reference spread "
                           "was offered before kickoff at a bettable price. These are not verified historical wagers or ROI.")
                cols=["Week","Matchup","Game ID","Provider","Predicted home margin","Actual home margin",
                      "Home spread","Model selection","Selected spread","Absolute market edge (pts)","Against-spread result"]
                st.dataframe(compared[[c for c in cols if c in compared.columns]],hide_index=True,use_container_width=True)
                st.download_button("Download CFBD spread comparison",compared.to_csv(index=False),
                                   file_name=f"cfbd_spread_comparison_{cfbd_year}.csv",mime="text/csv")
        except Exception as exc:st.error(f"Spread comparison failed: {exc}")

# Optional retrospective probability calibration using a separate, prior-season
# comparison export. Never use the same games to fit and score a calibration.
def prepare_calibration(df, sd):
    required={"Week","Game ID","Predicted home margin","Actual home margin","Home spread"}
    missing=required-set(df.columns)
    if missing:raise ValueError("Missing columns: "+", ".join(sorted(missing)))
    d=df.copy()
    for c in ["Week","Game ID","Predicted home margin","Actual home margin","Home spread"]:
        d[c]=pd.to_numeric(d[c],errors="coerce")
    d=d.dropna(subset=list(required)).drop_duplicates("Game ID")
    d=d[np.isfinite(d["Predicted home margin"]) & np.isfinite(d["Actual home margin"]) & np.isfinite(d["Home spread"])].copy()
    d["Model gap"]=d["Predicted home margin"]+d["Home spread"]
    d=d[d["Model gap"]!=0].copy()
    d["Signed gap"]=d["Model gap"].abs()
    d["Selected margin"]=np.where(d["Model gap"]>0,d["Actual home margin"],-d["Actual home margin"])
    d["Selected line"]=np.where(d["Model gap"]>0,d["Home spread"],-d["Home spread"])
    d["Settlement margin"]=d["Selected margin"]+d["Selected line"]
    d["Outcome"]=np.where(d["Settlement margin"]>0,1,np.where(d["Settlement margin"]<0,0,np.nan))
    d["Raw probability"]=norm.cdf(d["Signed gap"]/sd)
    return d

def fit_cover_slope(training):
    t=training.dropna(subset=["Outcome"])
    if len(t)<100 or t["Outcome"].nunique()<2:
        raise ValueError("Need at least 100 settled training games with both covers and misses.")
    x=t["Signed gap"].to_numpy(dtype=float)
    y=t["Outcome"].to_numpy(dtype=float)
    # A one-parameter monotone model, with neutral 50% at zero model/market gap.
    # Fit only on the earlier-week training partition.
    def loss(beta):
        p=np.clip(expit(beta*x),1e-7,1-1e-7)
        return float(-np.mean(y*np.log(p)+(1-y)*np.log1p(-p)))
    result=minimize_scalar(loss,bounds=(0.0,0.5),method="bounded")
    if not result.success:raise ValueError("Calibration optimizer did not converge")
    return float(result.x)

def calibration_metrics(df, col):
    d=df.dropna(subset=["Outcome",col])
    if d.empty:return float("nan"),float("nan")
    y=d["Outcome"].to_numpy(dtype=float)
    p=np.clip(d[col].to_numpy(dtype=float),1e-7,1-1e-7)
    return float(np.mean((p-y)**2)),float(-np.mean(y*np.log(p)+(1-y)*np.log1p(-p)))

st.divider()
st.subheader("Spread-cover probability calibration")
st.caption("Upload your prior-season CFBD comparison CSV. Fit on earlier weeks and test on later, untouched weeks. "
           "Reference spreads have unverified quote times; this is a retrospective probability check, not proven bettable ROI.")
with st.expander("Calibrate against historical spread results",expanded=False):
    calibration_upload=st.file_uploader("Historical CFBD comparison CSV (use your 2025 export)",type="csv",key="calibration_csv")
    training_last_week=st.slider("Last training week (later weeks held out)",7,12,9,key="calibration_train_week")
    if calibration_upload is not None:
        try:
            source=pd.read_csv(calibration_upload)
            d=prepare_calibration(source,sd)
            # A comparison CSV may already have been filtered by an edge threshold.
            min_observed=float(d["Signed gap"].min()) if len(d) else float("nan")
            training=d[d["Week"]<=training_last_week].copy()
            testing=d[d["Week"]>training_last_week].copy()
            st.caption(f"Distinct games: {len(d):,} · Earlier-week training: {len(training):,} · "
                       f"Later-week holdout: {len(testing):,} · Smallest included gap: {min_observed:.2f} pts")
            if len(training)<100 or len(testing)<60:
                st.warning("Insufficient training or holdout sample. Use a broader export with a zero-point minimum gap and a suitable split.")
            else:
                slope=fit_cover_slope(training)
                training["Calibrated probability"]=expit(slope*training["Signed gap"])
                testing["Calibrated probability"]=expit(slope*testing["Signed gap"])
                raw_brier,raw_log=calibration_metrics(testing,"Raw probability")
                cal_brier,cal_log=calibration_metrics(testing,"Calibrated probability")
                a,b,c,dcol=st.columns(4)
                a.metric("Held-out settled games",int(testing["Outcome"].notna().sum()))
                b.metric("Raw Brier (lower better)",f"{raw_brier:.4f}")
                c.metric("Calibrated Brier",f"{cal_brier:.4f}",delta=f"{raw_brier-cal_brier:+.4f}",delta_color="normal")
                dcol.metric("Calibrated slope",f"{slope:.4f}")
                st.caption(f"Held-out log loss: raw {raw_log:.4f}; calibrated {cal_log:.4f}. "
                           "These metrics exclude pushes and use only the untouched later-week partition.")
                testing["Probability bucket"]=pd.cut(testing["Calibrated probability"],
                    bins=[0,.55,.60,.65,.70,.75,.80,.90,1.0],include_lowest=True)
                buckets=testing.dropna(subset=["Outcome"]).groupby("Probability bucket",observed=True).agg(
                    Games=("Outcome","size"),Observed_cover_rate=("Outcome","mean"),
                    Mean_predicted=("Calibrated probability","mean")).reset_index()
                buckets["Probability bucket"]=buckets["Probability bucket"].astype(str)
                st.dataframe(buckets,hide_index=True,use_container_width=True)
                st.download_button("Download held-out calibration audit",testing.to_csv(index=False),
                    file_name="cfb_cover_calibration_holdout.csv",mime="text/csv")
                if min_observed>1.0:
                    st.warning("Your uploaded comparison excludes near-zero model/market differences. "
                               "For a less selected calibration sample, rerun the CFBD comparison with minimum difference 0 and upload that export.")
                if slope < 0.001:
                    st.warning("The fitted slope is effectively zero: on the training weeks, larger model/market gaps did not reliably imply higher cover probability. The fitted model stays near 50%; do not treat this as a betting signal.")
                if cal_brier < raw_brier and cal_log < raw_log:
                    st.success("The fitted probabilities improved both held-out scores in this split. "
                               "Repeat across other seasons and training splits before using them in live ROI estimates.")
                else:
                    st.warning("Calibration did not improve both held-out scores. Keep the live model's "
                               "probabilities labeled illustrative; do not apply this fitted slope automatically.")
                st.info("A probability model fitted to median historical reference spreads is not a "
                        "verified betting edge. Prices, line availability, and independent season tests remain necessary.")
        except Exception as exc:st.error(f"Calibration failed: {exc}")

# Independent-season validation: prior seasons fit calibration; the latest season
# is evaluated exactly once. This is a research audit, not verified betting ROI.
def independent_season_audit(season_data, sd, first_week):
    prepared=[]; diagnostics=[]
    for season in sorted(season_data):
        games, lines = season_data[season]
        predictions=historical_backtest(games,shrink,home_adv,sd,first_week)
        if predictions.empty:
            diagnostics.append({"Season":season,"Backtest games":0,"Valid quotes":0,"Matched":0,"Settled":0})
            continue
        matched, quotes=match_cfbd_spreads(predictions,lines,0.0,"All providers (median)")
        diagnostics.append({"Season":season,"Backtest games":len(predictions),"Valid quotes":len(quotes),
                            "Matched":len(matched),"Settled":int((matched.get("Against-spread result",pd.Series(dtype=str))!="Push").sum()) if len(matched) else 0})
        if matched.empty:continue
        d=prepare_calibration(matched,sd)
        d["Season"]=season
        prepared.append(d)
    if not prepared:return pd.DataFrame(),pd.DataFrame(diagnostics)
    return pd.concat(prepared,ignore_index=True),pd.DataFrame(diagnostics)

def season_score(d, col):
    settled=d.dropna(subset=["Outcome",col])
    if settled.empty:return {"Settled":0,"Cover rate":float("nan"),"Brier":float("nan"),"Log loss":float("nan")}
    brier,log=calibration_metrics(settled,col)
    return {"Settled":len(settled),"Cover rate":settled["Outcome"].mean(),"Brier":brier,"Log loss":log}

st.divider()
st.subheader("Independent-season model audit")
st.caption("Fetch 2023–2025 results and CFBD reference spreads. Fit calibration on 2023–2024; "
           "evaluate on 2025 without fitting to 2025 outcomes. This checks probabilities, not verified bettable ROI. "
           "Your rating settings may already have been chosen after viewing 2025, so 2025 is not a pristine holdout for rating-model selection.")
with st.expander("Run 3-season validation",expanded=False):
    audit_first_week=st.slider("First evaluation week (all seasons)",3,10,5,key="independent_first_week")
    st.info("Uses six CFBD requests across three seasons (games and lines), with cached responses where available. "
            "The median historical line has no verified pre-kickoff timestamp or spread-side price.")
    if st.button("Fetch and validate 2023–2025",key="independent_run"):
        if not ok_cfbd:st.error("Add CFBD_API_KEY to Streamlit Secrets first.")
        else:
            try:
                season_data={}
                progress=st.progress(0,text="Fetching historical data")
                for i,season in enumerate((2023,2024,2025)):
                    games=games_data(secret("CFBD_API_KEY"),season)
                    lines=cfbd_historical_spreads(secret("CFBD_API_KEY"),season)
                    season_data[season]=(games,lines)
                    progress.progress((i+1)/3,text=f"Fetched {season}")
                full,coverage=independent_season_audit(season_data,sd,audit_first_week)
                st.session_state["independent_audit"]=(full,coverage,audit_first_week)
            except requests.HTTPError as exc:st.error(f"CFBD request failed: {exc}. Check your plan and call allowance.")
            except Exception as exc:st.error(f"Audit failed: {exc}")
    if "independent_audit" in st.session_state:
        full,coverage,used_week=st.session_state["independent_audit"]
        st.write(f"Evaluation starts week {used_week}; each game's team ratings use only earlier weeks.")
        st.dataframe(coverage,hide_index=True,use_container_width=True)
        if full.empty:st.warning("No matching games. Review season coverage and CFBD IDs.")
        else:
            # Training on past seasons only; 2025 never influences the fitted slope.
            train=full[full["Season"].isin([2023,2024])].copy()
            holdout=full[full["Season"]==2025].copy()
            if train["Outcome"].notna().sum()<100 or holdout["Outcome"].notna().sum()<60:
                st.warning("Not enough settled matched games for a prior-season fit and 2025 holdout.")
            else:
                slope=fit_cover_slope(train)
                full["Prior-season calibrated probability"]=expit(slope*full["Signed gap"])
                summary=[]
                for season,part in full.groupby("Season"):
                    raw=season_score(part,"Raw probability")
                    calibrated=season_score(part,"Prior-season calibrated probability")
                    summary.append({"Season":int(season),"Role":"Holdout" if season==2025 else "Calibration training",
                                    "Settled":raw["Settled"],"Observed cover rate":raw["Cover rate"],
                                    "Raw Brier":raw["Brier"],"Calibrated Brier":calibrated["Brier"],
                                    "Raw log loss":raw["Log loss"],"Calibrated log loss":calibrated["Log loss"]})
                st.metric("Prior-season calibration slope",f"{slope:.5f}")
                st.dataframe(pd.DataFrame(summary).style.format({"Observed cover rate":"{:.1%}","Raw Brier":"{:.4f}",
                    "Calibrated Brier":"{:.4f}","Raw log loss":"{:.4f}","Calibrated log loss":"{:.4f}"}),
                    hide_index=True,use_container_width=True)
                holdout=full[full["Season"]==2025].copy()
                holdout=holdout.dropna(subset=["Outcome"])
                holdout["Gap bucket"]=pd.cut(holdout["Signed gap"],bins=[0,3,5,7,10,14,20,float("inf")],include_lowest=True)
                buckets=holdout.groupby("Gap bucket",observed=True).agg(
                    Games=("Outcome","size"),Observed_cover_rate=("Outcome","mean"),
                    Raw_probability=("Raw probability","mean"),Calibrated_probability=("Prior-season calibrated probability","mean")).reset_index()
                buckets["Gap bucket"]=buckets["Gap bucket"].astype(str)
                st.write("2025 holdout by model/market gap (descriptive; not thresholds optimized for betting)")
                st.dataframe(buckets,hide_index=True,use_container_width=True)
                st.download_button("Download independent-season audit",full.to_csv(index=False),
                    file_name="cfb_independent_season_audit_2023_2025.csv",mime="text/csv")
                st.warning("Reference spreads are not confirmed pre-kickoff quotes, and no historical spread prices "
                           "are known. Do not interpret these scores as verified profit. The live model remains uncalibrated.")


# Research lab: strictly chronological, season-held-out comparisons against market.
# Uses user-supplied historical audit; no additional API credits required.
def model_lab_frame(raw):
    required=["Season","Game ID","Predicted home margin","Actual home margin","Home spread"]
    missing=[c for c in required if c not in raw.columns]
    if missing: raise ValueError("Missing required audit columns: "+", ".join(missing))
    d=raw.copy()
    for c in ["Season","Predicted home margin","Actual home margin","Home spread"]:
        d[c]=pd.to_numeric(d[c],errors="coerce")
    d=d.dropna(subset=required).copy()
    d=d[d["Season"].isin([2023,2024,2025])].copy()
    d["Game ID"]=d["Game ID"].astype(str)
    # One game per season and ID; reject contradictory duplicates rather than selecting favorable quotes.
    contradictory=d.groupby(["Season","Game ID"])[["Actual home margin","Predicted home margin"]].nunique()
    bad=contradictory[(contradictory>1).any(axis=1)].index
    if len(bad):
        d=d.set_index(["Season","Game ID"]).drop(index=bad).reset_index()
    d=d.drop_duplicates(["Season","Game ID"]).copy()
    d["Market home margin"]=-d["Home spread"]
    d["Model minus market"]=d["Predicted home margin"]-d["Market home margin"]
    return d

def model_lab_fit(train):
    # Fit a single regularized blend coefficient; market-only is alpha=0,
    # original model is alpha=1. Nonnegative constrained blending avoids
    # inverting a model just because a past season was noisy.
    gap=train["Model minus market"].to_numpy(dtype=float)
    residual=(train["Actual home margin"]-train["Market home margin"]).to_numpy(dtype=float)
    alpha=float(np.clip(np.dot(gap,residual)/(np.dot(gap,gap)+250.0),0,1))
    return alpha

def model_lab_score(d,alpha,label):
    prediction=d["Market home margin"]+alpha*d["Model minus market"]
    actual=d["Actual home margin"]
    # Settlement of selection against reference spread, not historical bets.
    selected_home=(prediction-d["Market home margin"])>=0
    selected_margin=np.where(selected_home,actual-d["Market home margin"],d["Market home margin"]-actual)
    wins=int((selected_margin>0).sum()); losses=int((selected_margin<0).sum()); pushes=int((selected_margin==0).sum())
    return {"Evaluation":label,"Games":len(d),"Margin MAE":float((prediction-actual).abs().mean()),
            "Margin RMSE":float(np.sqrt(np.mean((prediction-actual)**2))),
            "Winner accuracy":float(np.mean((prediction>0)==(actual>0))),
            "Reference ATS W":wins,"Reference ATS L":losses,"Pushes":pushes,
            "Reference cover rate":wins/(wins+losses) if wins+losses else float('nan')}

st.divider()
st.subheader("Model development lab · market baseline")
st.caption("Compare the original rating model with the historical market and a regularized blend. "
           "Train on 2023, check 2024, and report 2025 separately. Historical market spreads may not have been available before kickoff; this is a retrospective benchmark, not verified betting performance.")
with st.expander("Compare models using the 2023–2025 audit",expanded=False):
    lab_upload=st.file_uploader("Upload cfb_independent_season_audit_2023_2025.csv",type="csv",key="model_lab_csv")
    if lab_upload is not None:
        try:
            lab=model_lab_frame(pd.read_csv(lab_upload))
            counts=lab.groupby("Season").size()
            st.write("Unique matched games by season")
            st.dataframe(counts.rename("Games").reset_index(),hide_index=True,use_container_width=True)
            if not all(counts.get(y,0)>=100 for y in (2023,2024,2025)):
                st.warning("Need at least 100 matched games in each of 2023, 2024 and 2025 to run this comparison.")
            else:
                train=lab[lab["Season"]==2023]
                validation=lab[lab["Season"]==2024]
                holdout=lab[lab["Season"]==2025]
                a23=model_lab_fit(train)
                # Predeclared refit using all earlier seasons for 2025; 2025 is not used in the fit.
                a24=model_lab_fit(lab[lab["Season"].isin([2023,2024])])
                rows=[]
                for season,part,alpha in [(2024,validation,a23),(2025,holdout,a24)]:
                    for name,a in [("Market reference",0.0),("Original ratings",1.0),("Past-season blend",alpha)]:
                        row=model_lab_score(part,a,name);row["Season"]=season;row["Model weight"]=a;rows.append(row)
                result=pd.DataFrame(rows)[["Season","Evaluation","Games","Model weight","Margin MAE","Margin RMSE","Winner accuracy","Reference ATS W","Reference ATS L","Pushes","Reference cover rate"]]
                st.write("2024 evaluation: blend trained on 2023 only. 2025 evaluation: blend refitted on 2023–2024 only.")
                st.dataframe(result.style.format({"Model weight":"{:.3f}","Margin MAE":"{:.2f}","Margin RMSE":"{:.2f}","Winner accuracy":"{:.1%}","Reference cover rate":"{:.1%}"}),hide_index=True,use_container_width=True)
                st.download_button("Download model comparison",result.to_csv(index=False),file_name="cfb_model_lab_comparison.csv",mime="text/csv",key="model_lab_download")
                st.info("The market baseline is the benchmark, not an executable strategy. Its ATS record is not meaningful: at zero gap it selects the home team by convention. Compare ATS only for original ratings and the blend when its gap is nonzero.")
                st.warning("2025 results have already been viewed during development, so this is not a pristine holdout for choosing the overall model. Keep live ROI unvalidated until prospective, timestamped tests establish otherwise.")
        except Exception as exc:st.error(f"Model lab could not read the audit: {exc}")


# Market-residual research lab: every historical feature uses earlier kickoffs only.
def residual_lab_features(raw):
    d=model_lab_frame(raw)
    needed=["Kickoff UTC","Home team","Away team"]
    missing=[c for c in needed if c not in d.columns]
    if missing: raise ValueError("Missing columns: "+", ".join(missing))
    d["Kickoff parsed"]=pd.to_datetime(d["Kickoff UTC"],utc=True,errors="coerce")
    d=d.dropna(subset=["Kickoff parsed"]).sort_values(["Kickoff parsed","Game ID"]).copy()
    # Games with identical kickoffs are featurized before any of their results enter history.
    history={}
    records=[]
    for kickoff, group in d.groupby("Kickoff parsed",sort=True):
        for _,g in group.iterrows():
            h,a=str(g["Home team"]),str(g["Away team"])
            def previous(team):
                old=[x for x in history.get(team,[]) if x[0]<kickoff and (kickoff-x[0]).days<=365]
                recent=old[-5:]
                if not recent:return (0.,0.,0.,0.)
                residuals=[x[1] for x in recent]
                margins=[x[2] for x in recent]
                rest=float(min((kickoff-recent[-1][0]).days,21))
                return (float(np.mean(residuals)),float(np.mean(margins)),float(len(recent))/5,rest)
            hr,hm,hcount,hrest=previous(h)
            ar,am,acount,arest=previous(a)
            r=g.to_dict()
            r.update({"rating_gap":float(g["Model minus market"]),
                      "recent_residual_gap":hr-ar,"recent_margin_gap":hm-am,
                      "recent_sample_gap":hcount-acount,"rest_gap":hrest-arest,
                      "history_min":min(hcount,acount),
                      "market_margin":float(g["Market home margin"]),
                      "target_residual":float(g["Actual home margin"]-g["Market home margin"])})
            records.append(r)
        for _,g in group.iterrows():
            h,a=str(g["Home team"]),str(g["Away team"])
            margin=float(g["Actual home margin"])
            residual=margin-float(g["Market home margin"])
            history.setdefault(h,[]).append((kickoff,residual,margin))
            history.setdefault(a,[]).append((kickoff,-residual,-margin))
    return pd.DataFrame(records)

RESIDUAL_FEATURES=["rating_gap","recent_residual_gap","recent_margin_gap","recent_sample_gap","rest_gap","history_min","market_margin"]

def fit_residual_ridge(training, penalty=100.0):
    x=training[RESIDUAL_FEATURES].to_numpy(float)
    y=training["target_residual"].to_numpy(float)
    center=x.mean(axis=0)
    scale=np.maximum(x.std(axis=0),1.0)
    z=np.column_stack([np.ones(len(x)),(x-center)/scale])
    reg=np.diag([0.0]+[penalty]*len(RESIDUAL_FEATURES))
    coef=np.linalg.solve(z.T@z+reg,z.T@y)
    return center,scale,coef

def predict_residual_ridge(test, fitted):
    center,scale,coef=fitted
    x=test[RESIDUAL_FEATURES].to_numpy(float)
    return np.column_stack([np.ones(len(x)),(x-center)/scale])@coef

def residual_lab_evaluate(test,predictions,label,season,threshold=2.0):
    actual=test["Actual home margin"].to_numpy(float)
    market=test["Market home margin"].to_numpy(float)
    gap=predictions-market
    # A predicted gap of exactly zero means no selection, not a home bet.
    selected=np.abs(gap)>=threshold
    ats=np.sign(gap[selected])*(actual[selected]-market[selected])
    w=int((ats>0).sum());l=int((ats<0).sum());p=int((ats==0).sum())
    return {"Season":season,"Model":label,"Games":len(test),
            "Margin MAE":float(np.mean(np.abs(predictions-actual))),
            "Margin RMSE":float(np.sqrt(np.mean((predictions-actual)**2))),
            "Winner accuracy":float(np.mean((predictions>0)==(actual>0))),
            "Selected reference games":int(selected.sum()),"ATS wins":w,"ATS losses":l,
            "ATS pushes":p,"Reference cover rate":w/(w+l) if w+l else np.nan,
            "Illustrative ROI at -110":(w*(100/110)-l)/(w+l+p) if (w+l+p) else np.nan}

st.divider()
st.subheader("Market-residual research lab · pregame form")
st.caption("Research whether your ratings, earlier opponent-relative results, recent margins and rest explain errors in the historical market line. "
           "Features are constructed in kickoff order; simultaneous games cannot use one another's results. "
           "Historical CFBD median lines are not verified pregame quotes, so results are retrospective, not executable returns.")
with st.expander("Evaluate past-only residual model on 2024 and 2025",expanded=False):
    residual_upload=st.file_uploader("Upload cfb_independent_season_audit_2023_2025.csv",type="csv",key="residual_lab_upload")
    min_pred_gap=st.number_input("Minimum predicted difference for illustrative ATS selections (points)",min_value=0.5,max_value=20.0,value=2.0,step=0.5,key="residual_min_gap")
    if residual_upload is not None:
        try:
            feature_data=residual_lab_features(pd.read_csv(residual_upload))
            counts=feature_data.groupby("Season").size()
            st.dataframe(counts.rename("Matched games").reset_index(),hide_index=True,use_container_width=True)
            if not all(counts.get(y,0)>=100 for y in (2023,2024,2025)):
                st.warning("Need at least 100 valid matched games in each of 2023–2025.")
            else:
                score_rows=[]; detail=[]
                for season,train_years in [(2024,[2023]),(2025,[2023,2024])]:
                    train=feature_data[feature_data["Season"].isin(train_years)]
                    test=feature_data[feature_data["Season"]==season].copy()
                    fitted=fit_residual_ridge(train)
                    residual=predict_residual_ridge(test,fitted)
                    market=test["Market home margin"].to_numpy(float)
                    rating=test["Predicted home margin"].to_numpy(float)
                    blend_weight=model_lab_fit(train)
                    models={"Market reference":market,"Original ratings":rating,
                            "Past-season blend":market+blend_weight*(rating-market),
                            "Past-season residual ridge":market+residual}
                    for name,pred in models.items():
                        score_rows.append(residual_lab_evaluate(test,pred,name,season,min_pred_gap))
                        out=test[["Season","Week","Game ID","Kickoff UTC","Home team","Away team","Actual home margin","Home spread"]].copy()
                        out["Model"]=name;out["Predicted home margin"]=pred
                        out["Model vs reference gap"]=pred-market
                        out["Illustrative selection"]=np.where(np.abs(pred-market)>=min_pred_gap,
                            np.where(pred>market,"Home","Away"),"No selection")
                        detail.append(out)
                scores=pd.DataFrame(score_rows)
                st.dataframe(scores.style.format({"Margin MAE":"{:.2f}","Margin RMSE":"{:.2f}",
                    "Winner accuracy":"{:.1%}","Reference cover rate":"{:.1%}",
                    "Illustrative ROI at -110":"{:.1%}"}),hide_index=True,use_container_width=True)
                st.download_button("Download residual model comparison",scores.to_csv(index=False),
                    file_name="cfb_residual_model_comparison.csv",mime="text/csv",key="residual_scores_download")
                st.download_button("Download game-by-game predictions",pd.concat(detail,ignore_index=True).to_csv(index=False),
                    file_name="cfb_residual_game_predictions.csv",mime="text/csv",key="residual_games_download")
                st.warning("This audit does not establish a betting edge. Median CFBD lines may be closing or postgame references; "
                    "the 2025 season has already informed development. Rest-day and recent-form features require accurate kickoff timestamps. "
                    "For a genuine live model, capture timestamped pre-kickoff lines and run forward without changing parameters after viewing results.")
        except Exception as exc:st.error(f"Residual lab failed: {exc}")


# Strict model audit: inspect exported predictions before promoting any live model.
st.divider()
st.subheader("Strict model audit · sign, bias and walk-forward checks")
st.caption("Upload the two CSVs exported by the Market-residual research lab. This audit uses exported predictions, never refits on the evaluation games, and does not imply historical lines were bettable.")
with st.expander("Audit model predictions and spread selections", expanded=False):
    audit_games_upload=st.file_uploader("cfb_residual_game_predictions.csv", type="csv", key="strict_audit_games")
    audit_summary_upload=st.file_uploader("cfb_residual_model_comparison.csv (optional)", type="csv", key="strict_audit_summary")
    if audit_games_upload is not None:
        try:
            detail=pd.read_csv(audit_games_upload)
            required={"Season","Week","Game ID","Kickoff UTC","Home team","Away team","Actual home margin","Home spread","Model","Predicted home margin"}
            missing=required-set(detail.columns)
            if missing: raise ValueError("Missing columns: "+", ".join(sorted(missing)))
            for c in ("Season","Week","Actual home margin","Home spread","Predicted home margin"):
                detail[c]=pd.to_numeric(detail[c],errors="coerce")
            detail["Kickoff parsed"]=pd.to_datetime(detail["Kickoff UTC"],utc=True,errors="coerce")
            bad_numeric=detail[list(("Season","Week","Actual home margin","Home spread","Predicted home margin"))].isna().any(axis=1)
            bad_kickoff=detail["Kickoff parsed"].isna()
            duplicate=detail.duplicated(["Season","Game ID","Model"],keep=False)
            st.write({"Rows":len(detail),"Invalid numeric rows":int(bad_numeric.sum()),"Missing kickoff timestamps":int(bad_kickoff.sum()),"Duplicate game/model rows":int(duplicate.sum())})
            clean=detail[~bad_numeric & ~bad_kickoff & ~duplicate].copy()
            clean["Market home margin"]=-clean["Home spread"]
            clean["Model gap"]=clean["Predicted home margin"]-clean["Market home margin"]
            clean["Market residual"]=clean["Actual home margin"]-clean["Market home margin"]
            clean["Model error"]=clean["Predicted home margin"]-clean["Actual home margin"]
            clean["Market error"]=clean["Market home margin"]-clean["Actual home margin"]
            clean["Home pick"]=clean["Model gap"]>0
            clean["ATS signed result"]=np.sign(clean["Model gap"])*clean["Market residual"]
            clean["Home actual cover"]=clean["Market residual"]>0
            clean["Home actual loss"]=clean["Market residual"]<0
            # A selection exists only when the predicted gap is nonzero and exceeds the chosen threshold.
            threshold=st.number_input("Minimum absolute model/market gap",0.5,20.0,2.0,0.5,key="strict_audit_gap")
            selected=clean[(clean["Model gap"].abs()>=threshold)&(clean["Model"]!="Market reference")].copy()
            selected["ATS outcome"]=np.select([selected["ATS signed result"]>0,selected["ATS signed result"]<0],["Win","Loss"],default="Push")
            audit_rows=[]
            for (season,model),g in clean.groupby(["Season","Model"],sort=True):
                picks=selected[(selected["Season"]==season)&(selected["Model"]==model)]
                w=int((picks["ATS outcome"]=="Win").sum());l=int((picks["ATS outcome"]=="Loss").sum());p=int((picks["ATS outcome"]=="Push").sum())
                home_picks=int(picks["Home pick"].sum())
                audit_rows.append({"Season":int(season),"Model":model,"Games":len(g),"Margin MAE":g["Model error"].abs().mean(),"Market MAE":g["Market error"].abs().mean(),"Home-margin bias (pts)":g["Model error"].mean(),"Mean predicted gap (pts)":g["Model gap"].mean(),"Selections":len(picks),"Home selections":home_picks,"Home selection %":home_picks/len(picks) if len(picks) else np.nan,"W":w,"L":l,"P":p,"Cover rate":w/(w+l) if w+l else np.nan,"Illustrative ROI at -110":(w*100/110-l)/len(picks) if len(picks) else np.nan})
            audit_table=pd.DataFrame(audit_rows)
            st.dataframe(audit_table.style.format({"Margin MAE":"{:.3f}","Market MAE":"{:.3f}","Home-margin bias (pts)":"{:+.2f}","Mean predicted gap (pts)":"{:+.2f}","Home selection %":"{:.1%}","Cover rate":"{:.1%}","Illustrative ROI at -110":"{:+.1%}"}),hide_index=True,use_container_width=True)
            st.download_button("Download strict audit summary",audit_table.to_csv(index=False),file_name="cfb_strict_audit_summary.csv",mime="text/csv",key="strict_summary_dl")
            # Sign-consistency check on every game: home spread plus actual home margin decides home cover.
            sign_checks=clean[(clean["Model"]=="Past-season residual ridge") & (clean["Model gap"].abs()>=threshold)].copy()
            sign_checks["Predicted side"]=np.where(sign_checks["Model gap"]>0,"Home","Away")
            sign_checks["Correct signed ATS margin"]=np.sign(sign_checks["Model gap"])*(sign_checks["Actual home margin"]+sign_checks["Home spread"])
            sign_checks["Opposite-side ATS margin"]=-sign_checks["Correct signed ATS margin"]
            if "Illustrative selection" in sign_checks:
                mismatch=(sign_checks["Illustrative selection"]!=sign_checks["Predicted side"]).sum()
                st.metric("Exported selection/sign mismatches",int(mismatch))
                if mismatch:st.error("Selection labels disagree with the independently recomputed model-versus-market sign.")
            st.caption("A positive model gap selects the home side. Settlement is sign(gap) × (actual home margin + home spread). Pushes return the illustrative stake.")
            st.dataframe(sign_checks[["Season","Week","Game ID","Home team","Away team","Home spread","Predicted side","Correct signed ATS margin"]].head(100),hide_index=True,use_container_width=True)
            st.download_button("Download signed selection audit",sign_checks.drop(columns=["Kickoff parsed"]).to_csv(index=False),file_name="cfb_signed_selection_audit.csv",mime="text/csv",key="strict_selection_dl")
            if audit_summary_upload is not None:
                reported=pd.read_csv(audit_summary_upload)
                st.caption("Original model lab summary, for comparison with independently recomputed results:")
                st.dataframe(reported,hide_index=True,use_container_width=True)
            st.warning("Integrity limit: these exports cannot prove that CFBD historical spreads or the original ratings were known before kickoff. To certify that, archive each odds quote with its retrieval timestamp and each rating snapshot before games start. Do not use the 2025 results for further parameter tuning and then call 2025 an untouched test.")
        except Exception as exc:st.error(f"Strict audit could not complete: {exc}")

# Conservative home-bias correction and walk-forward audit.
# Historical CFBD reference spreads have no verified quote timestamp; these
# results must never be described as executable historical wagers.
def conservative_walkforward(raw, fbs_names=None, threshold=2.0, ridge_penalty=100.0):
    d=residual_lab_features(raw)
    if d.empty: raise ValueError("No valid historical games")
    if fbs_names is not None:
        fbs={key_name(x) for x in fbs_names if str(x).strip()}
        d=d[d["Home team"].map(lambda x:key_name(x) in fbs) &
            d["Away team"].map(lambda x:key_name(x) in fbs)].copy()
    if d.empty: raise ValueError("No games remain after division filter")
    d=d.sort_values(["Kickoff parsed","Game ID"]).copy()
    rows=[]; diagnostics=[]
    for season in (2024,2025):
        test=d[d["Season"]==season].copy()
        if test.empty: continue
        for week in sorted(test["Week"].dropna().unique()):
            block=test[test["Week"]==week].copy()
            # All games in the evaluation week are withheld from training,
            # including earlier kickoffs in the same week.
            first=block["Kickoff parsed"].min()
            prior=d[(d["Kickoff parsed"]<first)&
                    ((d["Season"]<season)|((d["Season"]==season)&(d["Week"]<week)))].copy()
            if len(prior)<150:continue
            # Remove the learned unconditional home residual offset, then fit
            # regularized, centered slopes using past results only.
            fitted=fit_residual_ridge(prior, penalty=ridge_penalty)
            raw_res=predict_residual_ridge(block,fitted)
            # Intercept-free correction is an experimental alternative, not
            # assumed to be better. Evaluate against uncorrected ridge and market.
            centered_res=raw_res-fitted[2][0]
            market=block["Market home margin"].to_numpy(float)
            actual=block["Actual home margin"].to_numpy(float)
            predictions={"Market reference":market,
                         "Residual ridge":market+raw_res,
                         "Intercept-free ridge":market+centered_res}
            for name,pred in predictions.items():
                gap=pred-market
                signed=np.sign(gap)*(actual-market)
                chosen=(np.abs(gap)>=threshold)&(gap!=0) if name!="Market reference" else np.zeros(len(block),bool)
                part=block[["Season","Week","Game ID","Kickoff UTC","Home team","Away team","Actual home margin","Home spread"]].copy()
                part["Model"]=name
                part["Market home margin"]=market
                part["Predicted home margin"]=pred
                part["Predicted gap"]=gap
                part["Signed reference ATS margin"]=signed
                part["Selected"]=chosen
                part["Side"]=np.where(chosen,np.where(gap>0,"Home","Away"),"None")
                part["Training games"]=len(prior)
                part["Training cutoff UTC"]=first.isoformat()
                rows.append(part)
            diagnostics.append({"Season":season,"Week":week,"Evaluation games":len(block),
                                "Prior training games":len(prior),"Training cutoff UTC":first.isoformat(),
                                "Fitted intercept":float(fitted[2][0])})
    if not rows:raise ValueError("Insufficient prior data to evaluate 2024–2025")
    details=pd.concat(rows,ignore_index=True)
    summary=[]
    for (season,model),g in details.groupby(["Season","Model"]):
        selected=g[g["Selected"]]
        signed=selected["Signed reference ATS margin"]
        w=int((signed>0).sum());l=int((signed<0).sum());push=int((signed==0).sum())
        errors=g["Predicted home margin"]-g["Actual home margin"]
        market_errors=g["Market home margin"]-g["Actual home margin"]
        summary.append({"Season":season,"Model":model,"Games":len(g),
                        "Margin MAE":float(errors.abs().mean()),
                        "Market MAE":float(market_errors.abs().mean()),
                        "Home-margin error bias":float(errors.mean()),
                        "Mean model-market gap":float(g["Predicted gap"].mean()),
                        "Selected":len(selected),"Home selections":int((selected["Side"]=="Home").sum()),
                        "Away selections":int((selected["Side"]=="Away").sum()),
                        "Wins":w,"Losses":l,"Pushes":push,
                        "Reference cover rate":w/(w+l) if w+l else np.nan,
                        "Illustrative ROI -110":(w*100/110-l)/len(selected) if len(selected) else np.nan})
    return pd.DataFrame(summary),details,pd.DataFrame(diagnostics)

st.divider()
st.subheader("Conservative bias correction · weekly walk-forward")
st.caption("Compares the original residual model against an intercept-free variant. Fits on earlier games only, "
           "withholds the entire evaluation week, and keeps the sportsbook market as a baseline. "
           "This is retrospective research, not verified betting performance.")
with st.expander("Audit home bias and test a corrected model",expanded=False):
    corrected_upload=st.file_uploader("Upload cfb_independent_season_audit_2023_2025.csv",type="csv",key="corrected_raw")
    fbs_upload=st.file_uploader("Optional FBS team names CSV (column: team)",type="csv",key="fbs_team_names")
    threshold_corrected=st.number_input("Minimum model-versus-market difference",min_value=0.5,max_value=20.0,value=2.0,step=0.5,key="corrected_threshold")
    penalty_corrected=st.number_input("Ridge regularization (fixed before evaluation)",min_value=1.0,max_value=1000.0,value=100.0,step=25.0,key="corrected_penalty")
    if corrected_upload is not None and st.button("Run conservative walk-forward audit",key="corrected_run"):
        try:
            raw=pd.read_csv(corrected_upload)
            teams=None
            if fbs_upload is not None:
                teams_df=pd.read_csv(fbs_upload)
                if "team" not in teams_df:raise ValueError("FBS team CSV must contain a 'team' column")
                teams=teams_df["team"].dropna().tolist()
            summary,detail,diagnostics=conservative_walkforward(raw,teams,threshold_corrected,penalty_corrected)
            st.session_state["corrected_audit"]=(summary,detail,diagnostics)
        except Exception as exc:st.error(f"Audit failed: {exc}")
    if "corrected_audit" in st.session_state:
        summary,detail,diagnostics=st.session_state["corrected_audit"]
        st.dataframe(summary.style.format({"Margin MAE":"{:.2f}","Market MAE":"{:.2f}",
            "Home-margin error bias":"{:+.2f}","Mean model-market gap":"{:+.2f}",
            "Reference cover rate":"{:.1%}","Illustrative ROI -110":"{:+.1%}"}),
            hide_index=True,use_container_width=True)
        st.dataframe(diagnostics,hide_index=True,use_container_width=True)
        st.download_button("Download corrected model summary",summary.to_csv(index=False),
            file_name="cfb_corrected_model_summary.csv",mime="text/csv",key="corrected_summary_dl")
        st.download_button("Download corrected game predictions",detail.to_csv(index=False),
            file_name="cfb_corrected_game_predictions.csv",mime="text/csv",key="corrected_detail_dl")
        st.download_button("Download training cutoff diagnostics",diagnostics.to_csv(index=False),
            file_name="cfb_training_cutoff_audit.csv",mime="text/csv",key="corrected_cutoff_dl")
        if fbs_upload is None:st.info("All divisions included. Upload a verified season-appropriate FBS team list to run the FBS-only comparison.")
        st.warning("Integrity remains unverified: CFBD historical median spreads may not have been available before kickoff, "
            "and exported original ratings lack pregame snapshot timestamps. Weekly cutoffs prevent fitting on evaluation-week "
            "results but cannot certify the source data. 2025 has already influenced development; use future archived quotes "
            "and ratings for an untouched prospective test. Do not promote this model to live ROI based on these results.")

st.divider();st.subheader("Bet journal")
st.caption("Upload your existing journal CSV, add bets, then DOWNLOAD the updated CSV. Free cloud hosting does not guarantee persistent local storage.")
upload=st.file_uploader("Load previous journal (CSV)",type="csv")
columns=["Date","Matchup","Selection","Market","Line","American odds","Stake","Result","Net P/L","Notes"]
if upload:
    try:journal=pd.read_csv(upload).reindex(columns=columns)
    except Exception as exc:st.error(str(exc));journal=pd.DataFrame(columns=columns)
else:journal=pd.DataFrame(columns=columns)
with st.form("add_bet"):
    c1,c2,c3=st.columns(3)
    date=c1.date_input("Date");match=c2.text_input("Matchup");selection=c3.text_input("Your selection")
    c4,c5,c6=st.columns(3)
    market=c4.selectbox("Market",["Spread","Moneyline","Total"]);line=c5.text_input("Line (e.g. +5.5)");odds=c6.number_input("American odds",value=-110,step=1)
    c7,c8=st.columns(2)
    stake=c7.number_input("Stake ($)",min_value=0.0,value=25.0,step=5.0)
    result=c8.selectbox("Result",["Pending","Win","Loss","Push"])
    notes=st.text_input("Notes")
    submitted=st.form_submit_button("Add to this journal")
    if submitted:
        net={"Win":stake*profit_per_dollar(odds),"Loss":-stake,"Push":0,"Pending":None}[result]
        new=dict(zip(columns,[str(date),match,selection,market,line,odds,stake,result,net,notes]))
        journal=pd.concat([journal,pd.DataFrame([new])],ignore_index=True)
        st.session_state["journal"]=journal
if "journal" in st.session_state:
    journal=st.session_state["journal"]
if len(journal):
    st.dataframe(journal,hide_index=True,use_container_width=True)
    net=pd.to_numeric(journal["Net P/L"],errors="coerce").sum()
    settled=journal[journal["Result"].isin(["Win","Loss","Push"])]
    risk=pd.to_numeric(settled["Stake"],errors="coerce").sum()
    st.metric("Recorded net P/L",f"${net:,.2f}")
    st.metric("Return on settled stakes",f"{100*net/risk:.1f}%" if risk else "N/A")
st.download_button("Download updated journal (save this file)",journal.to_csv(index=False),file_name="my_cfb_bet_journal.csv",mime="text/csv")
st.caption("Model limitation: season-only margin ratings, basic home field and assumed uncertainty. No injury, roster, weather or closing-line adjustments. Historical ROI requires genuine timestamped sportsbook quotes.")

st.divider()
st.subheader("Prospective snapshot audit")
st.caption("Upload CSV files generated by the scheduled snapshot_capture.py workflow. Quotes and predictions are retained exactly as recorded; no retrospective reconstruction.")
snapshot_files=st.file_uploader("Upload pregame snapshot CSV files",type=["csv"],accept_multiple_files=True,key="prospective_snapshots")
if snapshot_files:
    try:
        parts=[pd.read_csv(f) for f in snapshot_files]
        snap=pd.concat(parts,ignore_index=True)
        required={"captured_at_utc","kickoff_utc","home_team","away_team","sportsbook_key","selection","spread","american_odds","projected_home_margin","ratings_asof_utc"}
        missing=required-set(snap.columns)
        if missing:st.error("Missing snapshot columns: "+", ".join(sorted(missing)))
        else:
            snap["captured_at_utc"]=pd.to_datetime(snap["captured_at_utc"],utc=True,errors="coerce")
            snap["kickoff_utc"]=pd.to_datetime(snap["kickoff_utc"],utc=True,errors="coerce")
            snap["ratings_asof_utc"]=pd.to_datetime(snap["ratings_asof_utc"],utc=True,errors="coerce")
            snap["spread"]=pd.to_numeric(snap["spread"],errors="coerce")
            snap["american_odds"]=pd.to_numeric(snap["american_odds"],errors="coerce")
            snap["projected_home_margin"]=pd.to_numeric(snap["projected_home_margin"],errors="coerce")
            snap["valid_pregame"]=(snap.captured_at_utc.notna() & snap.kickoff_utc.notna() & (snap.captured_at_utc<snap.kickoff_utc) & snap.ratings_asof_utc.notna() & (snap.ratings_asof_utc<=snap.captured_at_utc) & snap.spread.notna() & snap.american_odds.notna() & (snap.american_odds!=0))
            st.write({"Uploaded quotes":len(snap),"Valid timestamped pregame quotes":int(snap.valid_pregame.sum()),"Quotes with rating prediction":int((snap.valid_pregame & snap.projected_home_margin.notna()).sum()),"Unique games":int(snap.loc[snap.valid_pregame,["home_team","away_team","kickoff_utc"]].drop_duplicates().shape[0])})
            valid=snap[snap.valid_pregame].copy()
            if not valid.empty:
                valid=valid.sort_values("captured_at_utc").drop_duplicates(["kickoff_utc","home_team","away_team","sportsbook_key","selection"],keep="last")
                st.dataframe(valid,hide_index=True,use_container_width=True)
                st.download_button("Download audited pregame snapshots",valid.to_csv(index=False),file_name="cfb_prospective_pregame_quotes.csv",mime="text/csv",key="prospective_export")
            st.warning("The source captures quote and rating request time, not a verified historical result-publication timestamp. No profit or cover-rate claim is made before games settle and actual bettable prices are verified.")
    except Exception as exc:st.error(f"Could not validate snapshots: {exc}")


from prospective_results import render
render()
