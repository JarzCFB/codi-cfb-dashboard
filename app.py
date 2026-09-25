"""Personal CFB odds dashboard. API keys are server-side Streamlit secrets."""
import io
import math
import re
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import requests
import streamlit as st
from scipy.stats import norm

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
    now=datetime.now(timezone.utc)
    rows=[]
    for g in games:
        a,b=g.get("home_team"),g.get("away_team")
        hs,aws=g.get("home_points"),g.get("away_points")
        if not a or not b or hs is None or aws is None: continue
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

def odds_frame(data, ratings, home_adv, sd):
    out=[]
    for g in data:
        if not isinstance(g, dict): continue
        h,a=g.get("home_team"),g.get("away_team")
        if not h or not a:continue
        hr,ar=ratings.get(key_name(h)),ratings.get(key_name(a))
        pred=(hr-ar+home_adv) if hr is not None and ar is not None else None
        for bk in (g.get("bookmakers") or []):
            for market in (bk.get("markets") or []):
                if market.get("key")!="spreads":continue
                for selection in (market.get("outcomes") or []):
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
st.caption("Model limitation: season-only margin ratings, basic home field and assumed uncertainty. No injury, roster, weather or closing-line adjustments. Not validated against historical out-of-sample results.")
