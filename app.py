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

def norm_name(s):
    s = str(s).lower().replace("&", "and")
    s = re.sub(r"\([^)]*\)", "", s)
    s = re.sub(r"[^a-z0-9]", "", s)
    return s.replace("university", "")

ALIASES = {"mississippi":"olemiss","mississippist":"mississippistate","miamifl":"miami","miamioh":"miamiohio","ucf":"centralflorida","utsa":"texassanantonio","unlv":"nevadalasvegas","southerncalifornia":"usc","texasam":"texasam","pennst":"pennstate","ohiost":"ohiostate","iowast":"iowastate","kansasst":"kansasstate","michiganst":"michiganstate","floridast":"floridastate","coloradost":"coloradostate","georgiast":"georgiastate","georgiasouthern":"georgiasouthern","coastalcarolina":"coastalcarolina","old dominion":"olddominion"}
def key_name(s):
    x=norm_name(s)
    return ALIASES.get(x,x)

def build_ratings(games, season, shrink=4.0, home_adv=2.5):
    """Ridge-like iterative margin-of-victory team strength estimates; no bookmaker input."""
    rows=[]
    for g in games:
        if not isinstance(g, dict): continue
        a,b=g.get("home_team"),g.get("away_team")
        hs,aws=g.get("home_points"),g.get("away_points")
        if not a or not b or hs is None or aws is None or g.get("completed") is False: continue
        try: margin=float(hs)-float(aws)
        except (TypeError,ValueError): continue
        rows.append((key_name(a),key_name(b),margin))
    teams=sorted(set(t for a,b,_ in rows for t in (a,b)))
    if not teams: return {},0
    idx={t:i for i,t in enumerate(teams)}
    A=np.zeros((len(rows)+1,len(teams)))
    y=np.zeros(len(rows)+1)
    for j,(a,b,m) in enumerate(rows):
        A[j,idx[a]]=1; A[j,idx[b]]=-1; y[j]=m-home_adv
    A[-1,:]=1/len(teams)
    reg=np.eye(len(teams))*shrink
    vals=np.linalg.solve(A.T@A+reg,A.T@y)
    return dict(zip(teams,vals)),len(rows)

def american_prob(price):
    p=float(price)
    if p == 0: raise ValueError("American odds cannot be zero")
    return 100/(p+100) if p>0 else -p/(-p+100)

def profit_per_dollar(price):
    p=float(price)
    if p == 0: raise ValueError("American odds cannot be zero")
    return p/100 if p>0 else 100/-p

TEAM_ALIASES = {
    "alabama crimson tide": "alabama",
    "auburn tigers": "auburn",
    "georgia bulldogs": "georgia",
    "ohio state buckeyes": "ohio state",
    "michigan wolverines": "michigan",
    "tennessee volunteers": "tennessee",
    "texas longhorns": "texas",
    "penn state nittany lions": "penn state",
    "notre dame fighting irish": "notre dame",
    "nevada wolf pack": "nevada",
    "air force falcons": "air force",
    "mississippi state bulldogs": "mississippi state",
    "nc state wolfpack": "nc state",
    "arizona wildcats": "arizona",
    "washington state cougars": "washington state",
    "army black knights": "army",
    "temple owls": "temple",
    "byu cougars": "byu",
    "tcu horned frogs": "tcu",
    "appalachian state mountaineers": "appalachian state",
    "ball state cardinals": "ball state",
    "kent state golden flashes": "kent state",
}

# Normalize both sides: key_name() removes spaces and punctuation.
NORMALIZED_TEAM_ALIASES = {key_name(full): key_name(short) for full, short in TEAM_ALIASES.items()}

def find_rating(team, ratings):
    name = key_name(team)
    if name in ratings:
        return ratings[name]

    alias = NORMALIZED_TEAM_ALIASES.get(name)
    if alias:
        return ratings.get(key_name(alias))

    return None

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
    st.caption("Assumptions are illustrative and not calibrated to historical out-of-sample results.")
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
        ratings,n_games=build_ratings(games,int(year),shrink,home_adv)
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
        if df.empty and data:
            st.warning("The odds API returned events but no usable spread quotes. Some bookmakers may not have posted spreads yet.")
        if not df.empty:
            books=sorted(df["Book"].dropna().unique())
            selected=st.multiselect("Bookmakers",books,default=books)
            df=df[df["Book"].isin(selected)].copy()
            tab1,tab2,tab3=st.tabs(["Model comparisons","Best available price by team","All quoted lines"])
            with tab1:
                st.caption("Research screen only. Positive modeled ROI is not a verified profitable bet. Missing team ratings are excluded.")
                candidates=df[df["Expected ROI"].notna() & (df["Expected ROI"]>=min_roi)].sort_values("Expected ROI",ascending=False)
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
