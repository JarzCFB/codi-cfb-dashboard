"""Personal CFB odds dashboard. API keys are server-side Streamlit secrets."""
import io
import math
import re
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
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

# Frozen V3 research monitor: separate from live projection confidence and official picks.
with st.sidebar.expander("Advanced · Frozen V3 research monitor", expanded=False):
    st.caption("Research-only. Official V3 remains the calibrated 25% V1 / 75% V2 model with a 3-point minimum edge. "
               "Shadow results do not change or recommend bets. Historical cohort labels are frozen, not live inferences.")
    try:
        _shadow_response = requests.get(
            "https://raw.githubusercontent.com/JarzCFB/codi-cfb-dashboard/main/reports/v3_shadow_monitor.json",
            timeout=8,
        )
        _shadow_response.raise_for_status()
        _shadow = _shadow_response.json()
        _threshold_rows = []
        for _threshold, _record in _shadow.get("edge_thresholds", {}).items():
            _threshold_rows.append({
                "Minimum frozen edge (pts)": _threshold,
                "Settled": _record.get("settled"),
                "Wins": _record.get("wins"),
                "Losses": _record.get("losses"),
                "Pushes": _record.get("pushes"),
                "Net units": _record.get("net_units"),
                "ROI per settled pick": _record.get("roi_per_settled_selection"),
            })
        st.markdown("**Frozen V3 shadow threshold comparison**")
        st.dataframe(pd.DataFrame(_threshold_rows), hide_index=True, use_container_width=True)
        _forward = _shadow.get("forward_shadow_comparison")
        if _forward:
            st.markdown("**Forward-only evaluation · from Oct 20, 2026**")
            st.caption("Only frozen picks kicking off after the locked cutoff. "
                       "Early results have small samples and do not change official V3.")
            st.dataframe(pd.DataFrame([
                {"Minimum edge": f"{_edge}+ pts", **_metrics}
                for _edge, _metrics in _forward.get("thresholds", {}).items()
            ]), hide_index=True, use_container_width=True)
        st.markdown("**Frozen V1/V2 agreement cohorts**")
        st.dataframe(pd.DataFrame([
            {"Status": _status, **_record}
            for _status, _record in _shadow.get("frozen_cohorts", {}).items()
        ]), hide_index=True, use_container_width=True)
        st.caption(f"UNCLASSIFIED frozen V3 picks: {_shadow.get('unclassified_v3_count', 0)}. "
                   "Missing classifications are not reconstructed after kickoff.")
        _agreement = _shadow.get("pregame_agreement")
        if _agreement:
            st.markdown("**New · Same-capture V3 model agreement**")
            st.caption("Independent pregame V1/V2 research evidence; not inferred from separate qualifying picks. "
                       "Older games without capture-time evidence remain uncovered.")
            st.write(f"Evidence for {_agreement.get('covered_v3', 0)} frozen V3 picks; "
                     f"{_agreement.get('uncovered_v3', 0)} without matching evidence.")
            _agreement_rows = [
                {"Agreement": _status, **_metrics}
                for _status, _metrics in _agreement.get("status_performance", {}).items()
            ]
            if _agreement_rows:
                st.dataframe(pd.DataFrame(_agreement_rows), hide_index=True, use_container_width=True)
            _agreement_games = _agreement.get("games", [])
            if _agreement_games:
                st.dataframe(pd.DataFrame(_agreement_games), hide_index=True, use_container_width=True)
            if _agreement.get("rejected_evidence", 0):
                st.warning(f"{_agreement['rejected_evidence']} agreement evidence rows failed validation.")
        st.markdown("**Upcoming frozen V3 selections — verification required**")
        _pending = _shadow.get("future_pending_v3", [])
        if _pending:
            st.dataframe(pd.DataFrame(_pending), hide_index=True, use_container_width=True)
        else:
            st.info("No pending frozen V3 selections in the latest committed report.")
        st.caption("Frozen odds are historical snapshots, NOT verified current sportsbook prices. "
                   "Quarterback and injury news requires independent source checks.")
    except (requests.RequestException, ValueError, KeyError) as _shadow_error:
        st.info("Frozen V3 shadow report is temporarily unavailable. Official projections remain unaffected.")



# Reserve the first dashboard panel for the existing complete 7-day V3 slate.
# It is populated later, after the same data and model inputs are available.
top_projection_slot = st.container()


ODDS_URL = "https://api.the-odds-api.com/v4/sports/americanfootball_ncaaf/odds/"
CFBD_URL = "https://api.collegefootballdata.com"
CENTRAL_TZ = ZoneInfo("America/Chicago")

def format_central(series):
    """Format timezone-aware timestamps for the dashboard in U.S. Central Time."""
    return pd.to_datetime(series, utc=True, errors="coerce").dt.tz_convert(CENTRAL_TZ).dt.strftime("%a %b %d · %I:%M %p CT")

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
from cfb_division_safety import matchup_status, model_allowed
from power_rankings import build_power_rankings
import json
from pathlib import Path

def load_published_power_rankings():
    """Read committed Sunday snapshot; never recalculate rankings on page refresh."""
    path = Path(__file__).resolve().parent / "rankings_history" / "latest.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload.get("rankings"), list):
            return None
        return payload
    except (OSError, ValueError, TypeError):
        return None


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
        status=matchup_status(h,a)
        pred=(hr-ar+home_adv) if model_allowed(h,a) and hr is not None and ar is not None else None
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
                    out.append({"Division status":status,"Kickoff UTC":g.get("commence_time"),"Matchup":f"{a} @ {h}","Team":name,"Book":bk.get("title"),"Spread":point,"Odds":price,"Projected home margin":round(pred,1) if pred is not None else None,"Cover probability":round(p_cover,3) if p_cover is not None else None,"Break-even":round(implied,3),"Expected ROI":round(ev,3) if ev is not None else None,"Model edge (pp)":round(100*(p_cover-implied),1) if p_cover is not None else None})
    return pd.DataFrame(out)


# Final headline model: the locked V3 calibrated blend, calculated for every
# upcoming eligible FBS-vs-FBS game rather than only games that qualify as picks.
FINAL_V2_WEIGHT = 0.75
FINAL_INTERCEPT = 0.56891
FINAL_SLOPE = 1.11323

def final_model_projection(v1_margin, v2_margin):
    blend=(1.0-FINAL_V2_WEIGHT)*float(v1_margin)+FINAL_V2_WEIGHT*float(v2_margin)
    return FINAL_INTERCEPT+FINAL_SLOPE*blend

def same_school_name(provider_name, cfbd_name):
    """Conservatively match a sportsbook team label to a CFBD school label."""
    target=key_name(cfbd_name)
    if key_name(provider_name)==target:
        return True
    # Reuse the shared alias/prefix matcher with a one-school rating dictionary.
    # This handles labels such as "Western Kentucky Hilltoppers" vs
    # "Western Kentucky" without allowing a match to a different school.
    value, school, method=match_rating(provider_name,{target:1.0})
    return school==target and value is not None


def current_market_home_spreads(odds_events):
    """Median currently quoted home spread by sportsbook matchup."""
    found={}
    for event in odds_events or []:
        if not isinstance(event,dict): continue
        home,away=event.get("home_team"),event.get("away_team")
        if not home or not away: continue
        points=[]
        for bk in event.get("bookmakers") or []:
            if not isinstance(bk,dict): continue
            for market in bk.get("markets") or []:
                if not isinstance(market,dict) or market.get("key")!="spreads": continue
                for outcome in market.get("outcomes") or []:
                    if not isinstance(outcome,dict): continue
                    name=outcome.get("name")
                    if not name or not same_school_name(name,home): continue
                    try:
                        p=float(outcome.get("point"))
                        if math.isfinite(p): points.append(p)
                    except (TypeError,ValueError):
                        pass
        if points:
            found[(str(home),str(away))]=float(np.median(points))
    return found


def market_home_spread_for_game(home, away, markets, odds_events):
    """Resolve a spread when CFBD and sportsbook team labels use different suffixes."""
    for event in odds_events or []:
        if not isinstance(event,dict): continue
        eh,ea=event.get("home_team"),event.get("away_team")
        if not eh or not ea: continue
        if same_school_name(eh,home) and same_school_name(ea,away):
            return markets.get((str(eh),str(ea)))
    return None

def final_projection_rows(schedule_games, v1_ratings, v2_ratings, home_adv, odds_events):
    now=pd.Timestamp.now(tz="UTC")
    markets=current_market_home_spreads(odds_events)
    rows=[]
    seen=set()
    for raw in schedule_games or []:
        if not isinstance(raw,dict): continue
        home=raw.get("homeTeam",raw.get("home_team"))
        away=raw.get("awayTeam",raw.get("away_team"))
        if not home or not away or not model_allowed(home,away): continue
        kickoff=pd.to_datetime(raw.get("startDate",raw.get("start_date")),utc=True,errors="coerce")
        if pd.isna(kickoff) or kickoff<=now or kickoff>now+pd.Timedelta(days=7): continue
        gid=raw.get("id")
        ident=(str(gid) if gid is not None else f"{key_name(away)}@{key_name(home)}@{kickoff.isoformat()}")
        if ident in seen: continue
        seen.add(ident)
        v1h,v1a=find_rating(home,v1_ratings),find_rating(away,v1_ratings)
        v2h,v2a=find_rating(home,v2_ratings),find_rating(away,v2_ratings)
        if None in (v1h,v1a,v2h,v2a): continue
        v1=float(v1h)-float(v1a)+float(home_adv)
        v2=float(v2h)-float(v2a)+float(home_adv)
        final=final_model_projection(v1,v2)
        favorite=home if final>=0 else away
        projection=f"{favorite} {(-abs(final)):+.1f}"
        home_spread=market_home_spread_for_game(home,away,markets,odds_events)
        if home_spread is None:
            market=""; edge_team=""; edge_points=np.nan
        else:
            market=f"{home} {home_spread:+.1f}"
            market_home_margin=-float(home_spread)
            signed_edge=final-market_home_margin
            edge_team=home if signed_edge>0 else away if signed_edge<0 else "Even"
            edge_points=abs(signed_edge)
        rows.append({
            "Kickoff UTC":kickoff,
            "Matchup":f"{away} @ {home}",
            "Final model projection":projection,
            "Projected home margin":round(final,1),
            "Market home spread":round(home_spread,1) if home_spread is not None else np.nan,
            "Market line":market,
            "Model edge team":edge_team,
            "Model edge (pts)":round(edge_points,1) if pd.notna(edge_points) else np.nan,
            "V1 margin":round(v1,1),
            "V2 margin":round(v2,1),
            "V3/final margin":round(final,1),
            "Game ID":gid
        })
    return pd.DataFrame(rows).sort_values(["Kickoff UTC","Matchup"]) if rows else pd.DataFrame()

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
games=[]
data=[]
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
        # V2 is an opt-in research comparison. V1 prices, probabilities and
        # immutable snapshot captures are unchanged.
        with st.expander("Experimental V2: compare projected margins (research only)", expanded=False):
            st.caption("Uses discounted prior-season FBS ratings plus completed current-season FBS games. No V2 cover probabilities or betting ROI are claimed; no live scores are used.")
            if st.button("Calculate V2 comparison (fetches previous-season CFBD results)"):
                try:
                    from cfb_v2_experimental import build_v2, projected_margin
                    prior_games=games_data(secret("CFBD_API_KEY"),int(year)-1)
                    v2_ratings,info=build_v2(prior_games,games,datetime.now(timezone.utc),home_adv,shrink)
                    from cfb_v2_comparison import comparison_rows
                    comparisons, suppressed = comparison_rows(data, ratings, v2_ratings, home_adv)
                    if suppressed:
                        st.warning(f"Division safety: {len(suppressed)} FCS/unverified matchup(s) excluded from BOTH V1 and V2 comparisons.")
                        with st.expander("View excluded matchups"):
                            st.dataframe(pd.DataFrame(suppressed), hide_index=True, use_container_width=True)
                    if not comparisons:
                        st.info("No verified FBS vs FBS matchups available for comparison.")
                    st.write(f"V2 training: {info['previous_games']} prior-season and {info['current_games']} eligible current-season FBS games.")
                    st.dataframe(pd.DataFrame(comparisons),hide_index=True,use_container_width=True)
                except Exception as exc:st.error(f"V2 comparison unavailable: {exc}")
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
            excluded=df[df["Division status"]!="FBS vs FBS"]
            if not excluded.empty:
                st.warning(f"Safety filter: {excluded['Matchup'].nunique()} matchup(s) have unverified/FCS division status. Their model predictions, cover probabilities and estimated ROI are suppressed; sportsbook quotes remain visible in All quoted lines.")
            tab1,tab2,tab3=st.tabs(["Model comparisons","Best available price by team","All quoted lines"])
            with tab1:
                st.warning("RESEARCH ONLY: Original cover probabilities and expected ROI are unvalidated. Results are sorted by kickoff, not projected ROI; no betting advantage has been established.")
                st.caption("Research screen only. Missing team ratings are excluded.")
                candidates=df[df["Expected ROI"].notna() & (df["Expected ROI"]>=min_roi)].sort_values(["Kickoff UTC","Matchup","Team"])
                candidates_display=candidates.copy()
                candidates_display["Kickoff CT"]=format_central(candidates_display["Kickoff UTC"])
                candidates_display=candidates_display.drop(columns=["Kickoff UTC"])
                cols=["Division status","Kickoff CT"]+[c for c in candidates_display.columns if c not in ("Division status","Kickoff CT")]
                candidates_display=candidates_display[cols]
                st.dataframe(candidates_display,hide_index=True,use_container_width=True)

            with tab2:
                best=df[df["Expected ROI"].notna()].assign(_has_roi=True).sort_values(["Matchup","Team","_has_roi","Expected ROI"],ascending=[True,True,False,False]).drop_duplicates(["Matchup","Team"]).drop(columns="_has_roi")
                best_display=best.copy()
                best_display["Kickoff CT"]=format_central(best_display["Kickoff UTC"])
                best_display=best_display.drop(columns=["Kickoff UTC"])
                cols=["Division status","Kickoff CT"]+[c for c in best_display.columns if c not in ("Division status","Kickoff CT")]
                best_display=best_display[cols]
                st.dataframe(best_display,hide_index=True,use_container_width=True)

            with tab3:
                all_lines_display=df.copy()
                all_lines_display["Kickoff CT"]=format_central(all_lines_display["Kickoff UTC"])
                all_lines_display=all_lines_display.drop(columns=["Kickoff UTC"])
                cols=["Division status","Kickoff CT"]+[c for c in all_lines_display.columns if c not in ("Division status","Kickoff CT")]
                all_lines_display=all_lines_display[cols]
                st.dataframe(all_lines_display,hide_index=True,use_container_width=True)
            st.download_button("Export odds and model calculations",df.to_csv(index=False),file_name="cfb_odds_snapshot.csv",mime="text/csv")
        else:st.info("No upcoming spread lines returned by the provider.")
    except Exception as exc:st.error(f"Odds feed unavailable: {exc}")


with top_projection_slot:
    st.divider()
    st.subheader("Final model projections · next 7 days")
    st.caption(
        "One headline projection per eligible FBS-vs-FBS game kicking off in the next 7 days. The final projection uses the locked V3 calibrated "
        "blend of V1 and V2. A game appears even when it does not meet the frozen-selection edge threshold. "
        "Market line and edge are shown only when a current spread is available."
    )
    
    if not ok_cfbd:
        st.info("CFBD data is required to build the complete upcoming projection slate.")
    else:
        try:
            from cfb_v2_experimental import build_v2
            prior_games=games_data(secret("CFBD_API_KEY"),int(year)-1)
            final_v2_ratings,final_v2_info=build_v2(
                prior_games,games,datetime.now(timezone.utc),home_adv,shrink
            )
            # Use the last published weekly V2 strength for forward projections.
            # Live sportsbook odds remain independently refreshable.
            published_snapshot = load_published_power_rankings()
            if published_snapshot and int(published_snapshot.get("season", -1)) == int(year):
                frozen_v2 = {
                    row["team"]: float(row["power_rating"])
                    for row in published_snapshot["rankings"]
                    if row.get("power_rating") is not None
                }
                if frozen_v2:
                    final_v2_ratings = frozen_v2
                    st.caption("V2 power ratings frozen to the published Sunday snapshot; sportsbook odds remain live.")
            final_projections=final_projection_rows(
                games,ratings,final_v2_ratings,home_adv,data
            )
            # V4 is a separate research-only layer. No changes to V3 margins or official picks.
            from cfb_v4_situational import load_evidence, review_games, fetch_player_stats, standout_players, evidence_coverage, parse_evidence_csv, player_availability, player_report_details, report_freshness
            @st.cache_data(ttl=21600, show_spinner=False)
            def v4_team_leaders(key, season, team):
                stats, error = fetch_player_stats(key, season, team)
                return standout_players(stats), error
            from v4_public_sources import public_source_directory
            with st.expander("V4 official public availability sources — manual review", expanded=False):
                st.caption("Public entry points only; coverage differs by conference and matchup. No automatic status verification. Missing report does not imply healthy.")
                for _v4_source in public_source_directory():
                    st.markdown(f"**{_v4_source['conference']}** — [{_v4_source['url']}]({_v4_source['url']})")
                    st.caption(_v4_source["coverage"])
            with st.expander("V4 historical evaluation — pregame snapshots (research only)", expanded=False):
                st.caption("Held-out-season comparison requires real, timestamped V3/V4 pregame predictions and final scores. Does not change official picks.")
                st.download_button(
                    "Download historical evaluation CSV template",
                    data="game_id,season,kickoff_utc,captured_at_utc,actual_home_margin,v3_home_margin,v4_home_margin\n",
                    file_name="v4_walkforward_template.csv", mime="text/csv", key="v4_walkforward_template",
                )
                _v4_history_upload = st.file_uploader("Historical pregame snapshots CSV", type=["csv"], key="v4_history_upload")
                if _v4_history_upload is not None:
                    try:
                        from v4_walkforward import evaluate_walkforward
                        import csv as _v4_csv
                        import io as _v4_io
                        _v4_rows = list(_v4_csv.DictReader(_v4_io.StringIO(_v4_history_upload.getvalue().decode("utf-8-sig"))))
                        st.json(evaluate_walkforward(_v4_rows, min_holdout_games=100))
                        st.warning("Research only; input provenance and model calibration require independent verification.")
                    except (ValueError, TypeError, UnicodeError, OverflowError) as _v4_exc:
                        st.warning(f"Historical evaluation unavailable: {_v4_exc}")
            with st.expander("V4 predictive calibration — historical holdout test (research only)", expanded=False):
                st.caption("Train a situational residual model on prior seasons and score the latest held-out season. No official picks, live V4 edges, or model release without independently verified pregame data.")
                from v4_calibration import FEATURES as _v4_features
                _v4_columns = ["game_id", "season", "kickoff_utc", "captured_at_utc", "actual_home_margin", "v3_home_margin", *_v4_features]
                st.download_button(
                    "Download V4 calibration CSV template",
                    data=",".join(_v4_columns) + "\n",
                    file_name="v4_calibration_template.csv", mime="text/csv", key="v4_calibration_template",
                )
                _v4_calibration_upload = st.file_uploader("Verified historical feature ledger CSV", type=["csv"], key="v4_calibration_upload")
                if _v4_calibration_upload is not None:
                    try:
                        import csv as _v4_cal_csv
                        import io as _v4_cal_io
                        from v4_calibration import evaluate_candidate as _v4_evaluate_candidate
                        _v4_cal_rows = list(_v4_cal_csv.DictReader(_v4_cal_io.StringIO(_v4_calibration_upload.getvalue().decode("utf-8-sig"))))
                        _v4_cal_result = _v4_evaluate_candidate(_v4_cal_rows)
                        st.metric("Held-out V3 MAE", f"{_v4_cal_result['v3_mae']:.2f} pts")
                        st.metric("Held-out experimental V4 MAE", f"{_v4_cal_result['v4_candidate_mae']:.2f} pts")
                        st.json(_v4_cal_result)
                        st.warning("Research only: improvement on one holdout is not production validation. Verify source provenance and test prospectively.")
                    except (ValueError, TypeError, UnicodeError, OverflowError, KeyError) as _v4_cal_exc:
                        st.warning(f"V4 calibration not run: {_v4_cal_exc}")
            with st.expander("V4 recover archived V3 predictions (read-only)", expanded=False):
                st.caption("Upload either the original V3 ATS investigation audit CSV or the already recovered V3 baseline CSV. This does not modify frozen picks or fill missing situational factors.")
                _v4_recovery_upload = st.file_uploader("Original V3 audit or recovered baseline CSV", type=["csv"], key="v4_recovery_upload")
                if _v4_recovery_upload is not None:
                    try:
                        import csv as _v4_recovery_csv
                        import io as _v4_recovery_io
                        from v4_recover_v3 import recover_v3_upload, recovery_summary
                        _v4_recovery_rows = recover_v3_upload(list(_v4_recovery_csv.DictReader(_v4_recovery_io.StringIO(_v4_recovery_upload.getvalue().decode("utf-8-sig")))))
                        st.json(recovery_summary(_v4_recovery_rows))
                        _v4_export_fields = ["game_id", "season", "kickoff_utc", "captured_at_utc", "home_team", "away_team", "v3_home_margin", "actual_home_margin", "source_grading_status", "v4_feature_verification"]
                        _v4_output = _v4_recovery_io.StringIO()
                        _v4_writer = _v4_recovery_csv.DictWriter(_v4_output, fieldnames=_v4_export_fields)
                        _v4_writer.writeheader()
                        _v4_writer.writerows(_v4_recovery_rows)
                        st.download_button("Download recovered V3 baseline", data=_v4_output.getvalue(), file_name="v4_recovered_v3_baseline.csv", mime="text/csv", key="v4_recovered_baseline_download")
                        st.warning("This is a selected-play V3 baseline, not all FBS games or a trained V4 model. Situational features still require timestamped independent verification.")
                        st.divider()
                        st.markdown("**V4 point-in-time feature evidence audit**")
                        st.caption("Evidence is optional. Blank features stay unknown; URLs and timestamps are not independently authenticated by this app.")
                        _v4_evidence_template = "game_id,feature,value,source_url,published_at_utc,observed_at_utc\\n"
                        st.download_button("Download V4 feature provenance template", data=_v4_evidence_template, file_name="v4_feature_provenance_template.csv", mime="text/csv", key="v4_provenance_template")
                        _v4_provenance_upload = st.file_uploader("Optional V4 feature provenance CSV", type=["csv"], key="v4_provenance_upload")
                        from v4_evidence_audit import audit_evidence
                        _v4_evidence_rows = []
                        if _v4_provenance_upload is not None:
                            _v4_evidence_rows = list(_v4_recovery_csv.DictReader(_v4_recovery_io.StringIO(_v4_provenance_upload.getvalue().decode("utf-8-sig"))))
                        _v4_evidence_result = audit_evidence(_v4_recovery_rows, _v4_evidence_rows)
                        st.json({k: v for k, v in _v4_evidence_result.items() if k not in ("complete_rows", "missing_rows")})
                        import json as _v4_readiness_json
                        from v4_readiness import readiness_report
                        _v4_readiness = readiness_report(_v4_recovery_rows, _v4_evidence_result)
                        st.subheader("V4 operational readiness (research only)")
                        st.json(_v4_readiness)
                        st.download_button("Download V4 readiness report", data=_v4_readiness_json.dumps(_v4_readiness, indent=2), file_name="v4_readiness_report.json", mime="application/json", key="v4_readiness_report")
                        _v4_missing_output = _v4_recovery_io.StringIO()
                        _v4_missing_fields = ["game_id", "season", "kickoff_utc", "source_grading_status", "missing_features", "present_feature_count"]
                        _v4_missing_writer = _v4_recovery_csv.DictWriter(_v4_missing_output, fieldnames=_v4_missing_fields)
                        _v4_missing_writer.writeheader()
                        _v4_missing_writer.writerows(_v4_evidence_result["missing_rows"])
                        st.download_button("Download per-game missing feature report", data=_v4_missing_output.getvalue(), file_name="v4_missing_feature_report.csv", mime="text/csv", key="v4_missing_feature_report")
                        from v4_evidence_triage import triage_rows, triage_csv
                        _v4_triage = triage_rows(_v4_recovery_rows, _v4_evidence_rows)
                        _v4_windows = {}
                        for _v4_row in _v4_triage:
                            _v4_windows[_v4_row["capture_window"]] = _v4_windows.get(_v4_row["capture_window"], 0) + 1
                        st.caption("Original prediction lead-time distribution (not proof of available injury reports)")
                        st.json(_v4_windows)
                        st.download_button("Download V4 evidence collection priorities", data=triage_csv(_v4_triage), file_name="v4_evidence_collection_priorities.csv", mime="text/csv", key="v4_evidence_collection_priorities")
                        st.info("Missing-feature report is available without an evidence upload. No V4 calibration runs; source authenticity and multiple seasons remain unverified.")
    
                    except (ValueError, TypeError, UnicodeError, OverflowError) as _v4_recovery_exc:
                        st.warning(f"V3 audit recovery unavailable: {_v4_recovery_exc}")
            with st.expander("V4 evidence input (optional, research only)", expanded=False):
                st.caption("Upload source-linked reports for this session. Uploads are not stored or used for official picks.")
                st.download_button(
                    "Download evidence CSV template",
                    data="game_id,team,player,position,factor,status,source,observed_at_utc,notes,impact_points\n",
                    file_name="v4_evidence_template.csv",
                    mime="text/csv",
                    key="v4_template_download",
                )
                v4_upload = st.file_uploader("V4 evidence CSV", type=["csv"], key="v4_evidence_upload")
            try:
                if v4_upload is not None:
                    import io as _v4_io
                    v4_evidence = parse_evidence_csv(_v4_io.StringIO(v4_upload.getvalue().decode("utf-8-sig")))
                else:
                    v4_evidence = load_evidence()
            except (ValueError, UnicodeError) as exc:
                st.warning(f"V4 evidence could not be loaded: {exc}")
                v4_evidence = []
            v4_review = review_games(final_projections, v4_evidence)
            with st.expander("V4 Situational Intelligence — standout players, injuries and game context", expanded=False):
                st.caption("Evidence-gated research preview. Outstanding players, quarterback status, injuries, stadium difficulty, travel, rest, weather, rivalry and big-game factors require verified timestamped sources. Unknown is not healthy. No V4 betting edge is claimed; V3 and frozen picks remain unchanged.")
                if v4_review.empty:
                    st.info("No eligible upcoming games for V4 review.")
                else:
                    coverage = evidence_coverage(v4_review)
                    st.caption(f"Evidence coverage: {coverage['source_linked']} / {coverage['games']} matchups have source-linked reports; {coverage['unverified']} lack them. Source links are not independently verified.")
                    if coverage["source_linked"] == 0:
                        st.warning("V4 availability feed: NOT CONNECTED. CFBD player statistics do not include injuries. All player availability remains unknown unless you upload game-specific source-linked reports.")
                    else:
                        st.info("V4 reports come from the uploaded/manual evidence ledger, not a verified automatic injury feed. Independently check every source before use.")
                    st.dataframe(v4_review[["Kickoff UTC", "Matchup", "V3/final margin", "V4 verification", "V4 key players", "V4 situational notes", "V4 evidence sources", "V4 action"]], use_container_width=True, hide_index=True)
                    st.markdown("**Standout players by current-season production**")
                    st.caption("CFBD season statistical leaders, not confirmed starters or availability reports. Missing stats and missing injury reports are shown explicitly. No unvalidated point changes.")
                    selected_game = st.selectbox("Select matchup for team player leaders", v4_review["Matchup"].tolist(), key="v4_player_matchup")
                    if selected_game and " @ " in selected_game:
                        away_team, home_team = selected_game.split(" @ ", 1)
                        for team in (away_team, home_team):
                            leaders, error = v4_team_leaders(secret("CFBD_API_KEY"), int(year), team)
                            st.markdown(f"**{team}**")
                            if error:
                                st.warning(error)
                            elif leaders:
                                selected_row = v4_review[v4_review["Matchup"] == selected_game].iloc[0]
                                leaders_table = pd.DataFrame(leaders)
                                leaders_table["Availability"] = [
                                    player_availability(r["player"], team, v4_evidence, selected_row.get("Game ID"), selected_row.get("Kickoff UTC"))
                                    for _, r in leaders_table.iterrows()
                                ]
                                details = [player_report_details(r["player"], team, v4_evidence, selected_row.get("Game ID"), selected_row.get("Kickoff UTC")) for _, r in leaders_table.iterrows()]
                                leaders_table["Report timestamp UTC"] = [d["observed_at_utc"] for d in details]
                                leaders_table["Report source"] = [d["sources"] for d in details]
                                leaders_table["Report age"] = [report_freshness(d["observed_at_utc"]) for d in details]
                                st.dataframe(leaders_table.rename(columns={"player":"Player", "category":"Category", "stat_type":"Metric", "value":"Season total"}), hide_index=True, use_container_width=True)
                            else:
                                st.info("No compatible season production statistics returned; player availability remains unknown.")
    
            if final_projections.empty:
                st.info("No upcoming eligible FBS-vs-FBS games currently have both V1 and V2 ratings.")
            else:
                st.caption(
                    f"{len(final_projections):,} games projected in the next 7 days · "
                    f"V2 training: {final_v2_info.get('previous_games',0)} prior-season and "
                    f"{final_v2_info.get('current_games',0)} current-season eligible games."
                )
                # Automatic model sanity check: investigate large V1/V2 disagreements.
                # This is diagnostic only and does not change the locked V3/final projection.
                final_projections["V1/V2 disagreement (pts)"]=(
                    final_projections["V1 margin"]-final_projections["V2 margin"]
                ).abs().round(1)
                final_projections["Model check"]=np.select(
                    [
                        final_projections["V1/V2 disagreement (pts)"]>=10.0,
                        final_projections["V1/V2 disagreement (pts)"]>=5.0,
                    ],
                    [
                        "HIGH DISAGREEMENT - inspect",
                        "Moderate disagreement",
                    ],
                    default="Strong agreement",
                )
                # Automatic investigation. The dashboard makes the stability assessment itself.
                edge = pd.to_numeric(final_projections["Model edge (pts)"], errors="coerce")
                disagree = pd.to_numeric(final_projections["V1/V2 disagreement (pts)"], errors="coerce")
                v1 = pd.to_numeric(final_projections["V1 margin"], errors="coerce")
                v2 = pd.to_numeric(final_projections["V2 margin"], errors="coerce")
                same_winner = ((v1 >= 0) & (v2 >= 0)) | ((v1 < 0) & (v2 < 0))
    
                # Preserve the legacy live diagnostic for comparison. This does not
                # change the frozen historical investigation cohort or V3 predictions.
                final_projections["Legacy investigation status"] = np.select(
                    [edge.isna(), (~same_winner) | (disagree >= 10.0), disagree >= 5.0],
                    ["NO MARKET", "UNSTABLE", "CAUTION"], default="PASS"
                )
                # Diagnostic v2: classify by absolute V1/V2 margin disagreement;
                # report projected-winner disagreement independently.
                final_projections["Investigation status"] = np.select(
                    [edge.isna(), disagree >= 10.0, disagree >= 5.0],
                    ["NO MARKET", "UNSTABLE", "CAUTION"], default="PASS"
                )
                final_projections["Winner disagreement"] = np.where(
                    ~same_winner, "YES - opposite projected winners", "No"
                )
                final_projections["Automatic investigation"] = np.select(
                    [edge.isna(), disagree >= 10.0, disagree >= 5.0, ~same_winner],
                    ["NO MARKET - projection only", "UNSTABLE - margins differ by 10+ pts",
                     "CAUTION - margins differ by 5 to <10 pts",
                     "PASS on margin gap - opposite projected winners (review)"],
                    default="PASS - margins differ by <5 pts"
                )
    
                # Schedule display reconciliation: correct a demonstrably stale CFBD
                # kickoff ONLY for this independently verified matchup. Keep the
                # original CFBD timestamp for audit; never alter frozen records.
                final_projections["CFBD kickoff (original UTC)"] = final_projections["Kickoff UTC"]
                for _idx, _row in final_projections.iterrows():
                    if str(_row.get("Matchup", "")) == "Nebraska @ Oregon" and int(year) == 2026:
                        _official = pd.Timestamp("2026-10-18T03:00:00Z")
                        _original = pd.to_datetime(_row["Kickoff UTC"], utc=True, errors="coerce")
                        if pd.notna(_original) and abs((_official - _original).total_seconds()) > 90 * 60:
                            final_projections.at[_idx, "Kickoff UTC"] = _official
                            final_projections.at[_idx, "Kickoff verification"] = "Nebraska/Oregon athletics: Oct 17, 10 PM CT (CFBD differs)"
                if "Kickoff verification" not in final_projections.columns:
                    final_projections["Kickoff verification"] = "CFBD schedule (not independently checked)"
                final_projections["Kickoff verification"] = final_projections["Kickoff verification"].fillna("CFBD schedule (not independently checked)")
    
                # Research overlay INSIDE the existing final-projections table.
                # Left join: never filter or remove a live projection (including Nebraska).
                # Frozen confidence and refreshed same-book spreads are distinct from live V3.
                # IMPORTANT: CFBD uses numeric game IDs, while the frozen Odds API
                # journal uses UUIDs. Never join these two providers on game_id.
                # Use BOTH independently matched home/away identities and kickoff.
                _coverage = st.session_state.get("jarz_latest_confidence_coverage")
                _extra = {
                    "selection": "Frozen V3 selection",
                    "experimental_confidence_1_to_10": "Confidence (1–10)",
                    "decision_status": "Bet review status",
                    "current_sportsbook": "Verified sportsbook",
                    "current_spread": "Fresh frozen-pick spread",
                    "current_american_odds": "Fresh odds",
                    "current_edge_points": "Frozen V3 edge at fresh line",
                    "edge_change_points": "Frozen edge movement",
                    "match_status": "Market verification",
                    "division_check_current": "Division check",
                    "confidence_explanation": "Confidence notes",
                }
                for _display_name in _extra.values():
                    final_projections[_display_name] = pd.NA
                if isinstance(_coverage, pd.DataFrame) and not _coverage.empty:
                    _matched = 0
                    _ambiguous = 0
                    for _idx, _projection in final_projections.iterrows():
                        _matchup = str(_projection.get("Matchup", ""))
                        if " @ " not in _matchup:
                            continue
                        _away, _home = _matchup.rsplit(" @ ", 1)
                        _kick = pd.to_datetime(_projection["Kickoff UTC"], utc=True, errors="coerce")
                        if pd.isna(_kick):
                            continue
                        _candidates = []
                        _team_matches = []
                        for _, _frozen in _coverage.iterrows():
                            if not (same_school_name(str(_frozen.get("home_team", "")), _home)
                                    and same_school_name(str(_frozen.get("away_team", "")), _away)):
                                continue
                            _team_matches.append(_frozen)
                            _verified = pd.to_datetime(_frozen.get("verified_kickoff_utc"), utc=True, errors="coerce")
                            _frozen_kick = pd.to_datetime(_frozen.get("kickoff_utc"), utc=True, errors="coerce")
                            _times = [_verified] if pd.notna(_verified) else [_frozen_kick]
                            if any(pd.notna(_t) and abs((_t - _kick).total_seconds()) <= 3 * 3600 for _t in _times):
                                _candidates.append(_frozen)
                            else:
                                # Reconcile only when the independent live Odds API event
                                # agrees with CFBD's kickoff, AND the frozen selection has
                                # a verified same-book market match. Do not use team names
                                # alone to override conflicting dates.
                                _matching_events = [
                                    _ev for _ev in (data if isinstance(data, list) else [])
                                    if isinstance(_ev, dict)
                                    and same_school_name(str(_ev.get("home_team", "")), _home)
                                    and same_school_name(str(_ev.get("away_team", "")), _away)
                                    and pd.notna(pd.to_datetime(_ev.get("commence_time"), utc=True, errors="coerce"))
                                    and abs((pd.to_datetime(_ev.get("commence_time"), utc=True) - _kick).total_seconds()) <= 90 * 60
                                ]
                                if (len(_matching_events) == 1
                                        and str(_frozen.get("match_status", "")) == "MATCHED_ORIGINAL_BOOK"):
                                    _reconciled = _frozen.copy()
                                    _reconciled["match_status"] = "RECONCILED — CFBD + LIVE ODDS AGREE"
                                    _reconciled["decision_status"] = "REVIEW — frozen kickoff differs"
                                    _reconciled["confidence_explanation"] = (
                                        str(_frozen.get("confidence_explanation", ""))
                                        + "; frozen kickoff differs; live CFBD and Odds API event agree")
                                    _candidates.append(_reconciled)
                        # Ambiguous or repeated matches must not silently attach a rating.
                        if len(_candidates) == 1:
                            _frozen = _candidates[0]
                            for _source, _display_name in _extra.items():
                                if _source in _frozen.index:
                                    final_projections.at[_idx, _display_name] = _frozen[_source]
                            _matched += 1
                        elif len(_candidates) > 1:
                            final_projections.at[_idx, "Market verification"] = "AMBIGUOUS_MATCH"
                            _ambiguous += 1
                        elif len(_team_matches) == 1:
                            # Show the data-quality issue without assigning a misleading
                            # rating or spread to a game with conflicting kickoff dates.
                            final_projections.at[_idx, "Market verification"] = "KICKOFF_CONFLICT — REVIEW"
                            final_projections.at[_idx, "Bet review status"] = "HOLD — schedule mismatch"
                            _frozen_only = _team_matches[0]
                            _frozen_date = pd.to_datetime(_frozen_only.get("kickoff_utc"), utc=True, errors="coerce")
                            _verified_date = pd.to_datetime(_frozen_only.get("verified_kickoff_utc"), utc=True, errors="coerce")
                            _cfbd_date = _kick.strftime("%Y-%m-%d %H:%M UTC")
                            _notes = ["CFBD " + _cfbd_date]
                            if pd.notna(_frozen_date):
                                _notes.append("frozen " + _frozen_date.strftime("%Y-%m-%d %H:%M UTC"))
                            if pd.notna(_verified_date):
                                _notes.append("verified " + _verified_date.strftime("%Y-%m-%d %H:%M UTC"))
                            final_projections.at[_idx, "Confidence notes"] = " | ".join(_notes)
                        elif len(_team_matches) > 1:
                            final_projections.at[_idx, "Market verification"] = "AMBIGUOUS_TEAM_MATCH"
                            _ambiguous += 1
                    st.caption(f"Automatic confidence overlay: {_matched} of {len(final_projections)} live projections "
                               f"matched to a frozen V3 selection; {_ambiguous} ambiguous. "
                               "Other games remain in the table without an invented rating.")
                else:
                    _err = st.session_state.get("jarz_auto_coverage_error")
                    if _err:
                        st.warning("Automatic market coverage failed: " + str(_err))
                    else:
                        st.caption("Automatic sportsbook check is pending. Refreshing after first load; "
                                   "unmatched live games will have blank frozen-pick fields.")
    
                # Independent LIVE slate confidence for EVERY projected game. This is
                # an experimental ordinal research score, not a frozen-pick score,
                # probability, staking instruction, or backtested betting signal.
                # No modification to locked V3, frozen selection, or grading.
                def _live_confidence(row):
                    e = pd.to_numeric(row.get("Model edge (pts)"), errors="coerce")
                    gap = pd.to_numeric(row.get("V1/V2 disagreement (pts)"), errors="coerce")
                    v1m = pd.to_numeric(row.get("V1 margin"), errors="coerce")
                    v2m = pd.to_numeric(row.get("V2 margin"), errors="coerce")
                    if pd.isna(e):
                        return 1, "No current spread; provisional 1/10 (not actionable)"
                    # Edge rewards are intentionally bounded. Larger edges alone
                    # cannot produce a high confidence rating.
                    score = 2 + min(4, int(float(e) // 2.5))
                    if pd.notna(gap):
                        if gap >= 10:
                            score -= 3
                        elif gap >= 5:
                            score -= 2
                        elif gap >= 3:
                            score -= 1
                    if pd.notna(v1m) and pd.notna(v2m) and (v1m >= 0) != (v2m >= 0):
                        score -= 1
                    score = max(1, min(7, score))
                    note = (f"Live V3 edge {float(e):.1f} pts; "
                            f"V1/V2 gap {float(gap):.1f} pts" if pd.notna(gap)
                            else f"Live V3 edge {float(e):.1f} pts; V1/V2 gap unavailable")
                    return score, note + "; experimental, not validated"
    
                _live_ratings = final_projections.apply(_live_confidence, axis=1)
                final_projections["Live confidence (1–10)"] = _live_ratings.map(lambda x: x[0]).astype(int)
                final_projections["Live confidence basis"] = _live_ratings.map(lambda x: x[1])
                final_projections["Official frozen pick status"] = final_projections["Frozen V3 selection"].map(
                    lambda x: "Official frozen V3 pick" if pd.notna(x) and str(x).strip() else "Projection only"
                )
                # Preserve original frozen confidence distinctly from the new live score.
                final_projections = final_projections.rename(columns={"Confidence (1–10)": "Frozen pick confidence (1–10)"})
    
                # Every projection gets an explicit data-availability explanation.
                # Missing frozen picks are NOT manufactured, and absent market
                # prices are NOT presented as executable offers.
                for _idx, _row in final_projections.iterrows():
                    _has_pick = pd.notna(_row.get("Frozen V3 selection"))
                    _has_market = pd.notna(_row.get("Market home spread"))
                    if not _has_pick:
                        if pd.isna(_row.get("Market verification")):
                            final_projections.at[_idx, "Market verification"] = "NO FROZEN V3 PICK"
                        if pd.isna(_row.get("Bet review status")):
                            final_projections.at[_idx, "Bet review status"] = "PROJECTION ONLY — not a frozen bet"
                        final_projections.at[_idx, "Frozen V3 selection"] = "NOT SELECTED"
                        final_projections.at[_idx, "Frozen pick confidence (1–10)"] = "NOT RATED — no frozen pick"
                        if pd.isna(_row.get("Confidence notes")):
                            final_projections.at[_idx, "Confidence notes"] = "No frozen V3 selection for this matchup; confidence cannot be validated"
                    if _has_pick and pd.isna(_row.get("Frozen pick confidence (1–10)")):
                        final_projections.at[_idx, "Frozen pick confidence (1–10)"] = "NOT RATED — verification hold"
                    if _has_pick and pd.isna(_row.get("Bet review status")):
                        final_projections.at[_idx, "Bet review status"] = "HOLD — incomplete market verification"
                    if _has_pick and pd.isna(_row.get("Market verification")):
                        final_projections.at[_idx, "Market verification"] = "VERIFICATION PENDING"
                    if _has_pick and pd.isna(_row.get("Confidence notes")):
                        final_projections.at[_idx, "Confidence notes"] = "Frozen pick exists; verification incomplete"
                    if pd.isna(_row.get("Verified sportsbook")):
                        final_projections.at[_idx, "Verified sportsbook"] = "NOT VERIFIED"
                    if pd.isna(_row.get("Fresh frozen-pick spread")):
                        final_projections.at[_idx, "Fresh frozen-pick spread"] = "NOT AVAILABLE"
                    if pd.isna(_row.get("Fresh odds")):
                        final_projections.at[_idx, "Fresh odds"] = "NOT AVAILABLE"
                    if pd.isna(_row.get("Frozen V3 edge at fresh line")):
                        final_projections.at[_idx, "Frozen V3 edge at fresh line"] = "NOT CALCULABLE"
                    if pd.isna(_row.get("Frozen edge movement")):
                        final_projections.at[_idx, "Frozen edge movement"] = "NOT CALCULABLE"
                    if pd.isna(_row.get("Division check")):
                        final_projections.at[_idx, "Division check"] = "NOT VERIFIED FOR FROZEN PICK"
                    if not _has_market:
                        if not _has_pick:
                            final_projections.at[_idx, "Confidence notes"] = "No current market line or frozen V3 selection; projection only"
                # Live slate coverage is independent of the smaller frozen-pick cohort.
                # A blank field is replaced with an explicit reason, not invented data.
                final_projections["Market line"] = final_projections["Market line"].replace("", "NO CURRENT LINE")
                final_projections["Model edge team"] = final_projections["Model edge team"].replace("", "NOT CALCULABLE — no line")
                final_projections["Model edge (pts)"] = final_projections["Model edge (pts)"].astype(object).where(
                    final_projections["Model edge (pts)"].notna(), "NOT CALCULABLE — no line")
                st.caption("Availability audit: all games have explicit statuses. NOT SELECTED is not a new wager; "
                           "NOT AVAILABLE means no verified same-book quote. No odds or confidence are fabricated.")
    
                # Clean, single 7-day table: every game has a LIVE rating.
                # Full frozen-market diagnostics remain in the CSV export, not
                # crowded into the main projection view.
                headline = final_projections[[
                    "Live confidence (1–10)", "Final model projection", "Investigation status",
                    "Kickoff UTC", "Matchup", "Market line", "Model edge team",
                    "Model edge (pts)", "Winner disagreement", "Official frozen pick status",
                ]].copy()
                headline.insert(3, "Kickoff CT", format_central(headline["Kickoff UTC"]))
                headline = headline.drop(columns=["Kickoff UTC"])
                st.caption("LIVE confidence: experimental 1–7/10 scale for every game; "
                           "not an ATS win probability, guarantee, or suggested unit stake. "
                           "Frozen V3 picks are identified separately; full verification details are in the CSV.")
    
                # View-only filtering of the existing slate; never modifies frozen picks.
                _edge_view = st.radio(
                    "Show games with minimum model edge",
                    options=["All games", "3+ pts", "5+ pts", "7+ pts"],
                    index=0,
                    horizontal=True,
                    key="v3_slate_edge_view",
                    help="Display filter only. The official V3 frozen-pick rule remains 3+ points.",
                )
                _agreement_view = st.checkbox(
                    "Show PASS agreement only",
                    value=False,
                    key="v3_slate_pass_only",
                    help="Live V1/V2 diagnostic; not a frozen historical classification.",
                )
                if _edge_view != "All games":
                    _minimum_edge = float(_edge_view.split("+")[0])
                    headline = headline.loc[
                        pd.to_numeric(headline["Model edge (pts)"], errors="coerce") >= _minimum_edge
                    ].copy()
                if _agreement_view:
                    headline = headline.loc[headline["Investigation status"] == "PASS"].copy()
                st.caption(f"Showing {len(headline)} games with selected display filters. "
                           "Full unfiltered model projections remain available in the CSV export.")

                sort_view=st.radio(
                    "Table order",
                    ["Highest confidence first", "Biggest model edges first", "Kickoff time"],
                    horizontal=True,
                    key="final_projection_sort_v2"
                )
                if sort_view == "Highest confidence first":
                    headline = headline.assign(
                        _sort_edge=pd.to_numeric(headline["Model edge (pts)"], errors="coerce")
                    ).sort_values(
                        ["Live confidence (1–10)", "_sort_edge"],
                        ascending=[False, False], na_position="last"
                    ).drop(columns="_sort_edge").reset_index(drop=True)
                elif sort_view == "Biggest model edges first":
                    headline = headline.assign(
                        _sort_edge=pd.to_numeric(headline["Model edge (pts)"], errors="coerce")
                    ).sort_values("_sort_edge", ascending=False, na_position="last").drop(
                        columns="_sort_edge"
                    ).reset_index(drop=True)
    
                def highlight_model_edges(row):
                    edge=pd.to_numeric(row.get("Model edge (pts)"),errors="coerce")
                    status=str(row.get("Investigation status",""))
                    if status=="UNSTABLE":
                        bg="#ffd6d6"; weight="font-weight:700;"
                    elif status=="CAUTION":
                        bg="#fff1a8"; weight="font-weight:700;"
                    elif status=="PASS" and pd.notna(edge) and edge>=7.0:
                        bg="#b7f7c5"; weight="font-weight:700;"
                    elif status=="PASS" and pd.notna(edge) and edge>=3.0:
                        bg="#fff8d6"; weight=""
                    else:
                        return [""]*len(row)
                    return [f"background-color:{bg};color:#111827;{weight}" for _ in row]
    
                st.caption(
                    "Diagnostic v2 (live only): PASS = V1/V2 margin difference <5 points; "
                    "CAUTION = 5 to <10; UNSTABLE = 10+. Opposite projected winners are "
                    "flagged separately, even on PASS games. Legacy status is shown for comparison. "
                    "Frozen historical cohorts and the locked V3/final projection are unchanged."
                )
                styled_headline=headline.style.apply(highlight_model_edges,axis=1).format(
                    {},na_rep=""
                )
    
                export_final=final_projections.copy()
                export_final.insert(1,"Kickoff CT",format_central(export_final["Kickoff UTC"]))
                st.dataframe(styled_headline,hide_index=True,use_container_width=True)
                st.caption("All projected games have a live confidence score. Frozen-pick research and market verification details are retained in the downloadable CSV.")
                st.download_button(
                    "Download complete final model projections",
                    export_final.to_csv(index=False),
                    file_name="cfb_complete_model_projections.csv",
                    mime="text/csv",
                    key="download_complete_final_model_projections"
                )
        except Exception as exc:
            st.error(f"Complete final projections unavailable: {exc}")


# Predictive FBS power rankings using the same V2 ratings that feed the final model.
# Ratings are neutral-field team strength in points and do not alter game projections.

# Clear navigation: primary V3 games remain at the top; supporting views are grouped below.
st.divider()
st.caption("More details · select a tab below. Official V3 calculations and frozen picks are unchanged.")
_results_tab, _upcoming_tab, _journal_tab, _research_tab = st.tabs(
    ["Results & frozen picks", "Upcoming pick review", "My bet journal", "Advanced research"]
)

with _research_tab:
    st.divider()
    st.subheader("Codi Model Power Rankings")
    st.caption(
        "Predictive rankings based on the current V2 neutral-field team strength ratings. "
        "Higher is stronger. A +10 rating means roughly 10 points better than an average "
        "FBS team on a neutral field. These rankings do not change V1, V2, V3, frozen "
        "selections, or the Final Model."
    )

    try:
        snapshot = load_published_power_rankings()
        if snapshot is None:
            st.info("Weekly rankings have not been published yet. The first snapshot will appear after Sunday's 1 PM Central scheduled run.")
        else:
            history_dir = Path(__file__).resolve().parent / "rankings_history"
            available = sorted(history_dir.glob("????-??-??.json"), reverse=True)
            choices = [p.stem for p in available]
            if choices:
                chosen = st.selectbox("Published Sunday", choices, index=0, key="weekly_power_rankings_date")
                snapshot = json.loads((history_dir / f"{chosen}.json").read_text(encoding="utf-8"))
            st.caption(f"Published: {snapshot.get('published_central', 'unknown')} · Rankings frozen until next Sunday at 1 PM CT.")
            power_df = pd.DataFrame(snapshot["rankings"])
            if power_df.empty:
                st.info("The published rankings snapshot is empty.")
            else:
                power_df["Rank"] = pd.to_numeric(power_df["rank"], errors="coerce")
                power_df["Team"] = power_df["team"].map(lambda x: str(x).title())
                power_df["Power Rating"] = pd.to_numeric(power_df["power_rating"], errors="coerce").round(1)
                power_df["Last Week"] = pd.to_numeric(power_df["last_week_rank"], errors="coerce")
                def movement_text(value):
                    if pd.isna(value): return "NEW"
                    if value > 0: return f"↑ {int(value)}"
                    if value < 0: return f"↓ {abs(int(value))}"
                    return "—"
                power_df["Movement"] = pd.to_numeric(power_df["movement"], errors="coerce").map(movement_text)
                power_display = power_df[["Rank", "Team", "Power Rating", "Last Week", "Movement"]].copy()
                st.dataframe(power_display, hide_index=True, use_container_width=True)
                st.download_button("Download power rankings", power_display.to_csv(index=False),
                                   file_name=f"codi_cfb_power_rankings_{snapshot.get('season', 'current')}.csv",
                                   mime="text/csv", key="download_power_rankings")
    except Exception as exc:
        st.warning(f"Published power rankings unavailable: {exc}")


    # Investigation cohort CSV contains classifications only. The scheduled grader
    # publishes settlement metrics separately in investigation_summary.json.
    st.divider()
    st.subheader("Investigation performance")
    st.caption(
        "Historical frozen investigation cohorts (legacy rules, unchanged). Winner accuracy and margin error "
        "are forecast metrics, NOT against-the-spread betting returns. "
        "For ATS ROI, use Official prospective performance → V3 investigation ATS."
    )
    try:
        import json as _json
        from pathlib import Path as _Path
        _summary_path = _Path("prospective/investigation_summary.json")
        _cohort_path = _Path("prospective/investigation_cohort.csv")
        if not _summary_path.exists():
            st.info("The investigation summary has not been generated yet. Run the investigation grading workflow.")
        else:
            with _summary_path.open("r", encoding="utf-8") as _handle:
                _summary = _json.load(_handle)
            _groups = _summary.get("groups", {})
            _rows = []
            for _status in ("PASS", "CAUTION", "UNSTABLE"):
                _g = _groups.get(_status, {})
                _tracked = int(_g.get("classified_games", 0))
                _settled = int(_g.get("settled_games", 0))
                if _settled > _tracked:
                    raise ValueError(f"{_status}: settled count exceeds classified count")
                _rows.append({
                    "Status": _status,
                    "Tracked": _tracked,
                    "Settled": _settled,
                    "Pending": _tracked - _settled,
                    "Winner accuracy": _g.get("winner_accuracy"),
                    "Margin MAE": _g.get("margin_mae"),
                    "Within 7 pts": _g.get("within_7_rate"),
                })
            _perf = pd.DataFrame(_rows)
            if _cohort_path.exists():
                _cohort = pd.read_csv(_cohort_path)
                if "investigation_status" in _cohort.columns:
                    _counts = _cohort["investigation_status"].astype(str).str.upper().value_counts()
                    _mismatches = [status for status in ("PASS", "CAUTION", "UNSTABLE")
                                   if int(_counts.get(status, 0)) != int(_perf.loc[_perf["Status"] == status, "Tracked"].iloc[0])]
                    if _mismatches:
                        st.warning("Investigation cohort CSV and summary JSON disagree for: " + ", ".join(_mismatches))
            _display = _perf.copy()
            for _col in ("Winner accuracy", "Within 7 pts"):
                _display[_col] = _display[_col].map(lambda x: f"{float(x):.1%}" if pd.notna(x) else "—")
            _display["Margin MAE"] = _display["Margin MAE"].map(lambda x: f"{float(x):.2f} pts" if pd.notna(x) else "—")
            st.dataframe(_display, hide_index=True, use_container_width=True)
            st.caption(
                f"{int(_perf['Tracked'].sum()):,} classified games · "
                f"{int(_perf['Settled'].sum()):,} settled · "
                f"{int(_perf['Pending'].sum()):,} pending. "
                "Settlement metrics come from the scheduled investigation summary."
            )
    except Exception as _exc:
        st.warning(f"Investigation performance report unavailable: {_exc}")


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


with _journal_tab:
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

    # Read-only official prospective performance reconciliation.
    # All grading is sourced from the committed frozen-selection files; this view
    # never recomputes, replaces, or grades selections from current odds.

with _results_tab:
    st.divider()
    st.subheader("JarzCFB · Official prospective performance")
    st.caption("Frozen first qualifying selection per game/model · hypothetical flat 1-unit stakes. Status cohorts are descriptive, not a betting rule.")
    try:
        from pathlib import Path as _ReportPath
        _graded_path = _ReportPath("prospective/graded_selections.csv")
        _cohorts_path = _ReportPath("prospective/investigation_cohort.csv")
        _selections_path = _ReportPath("prospective/selections.csv")
        if not _graded_path.exists():
            st.info("Run the prospective grading workflow to generate the official results file.")
        else:
            _graded = pd.read_csv(_graded_path)
            _required = {"season", "game_id", "model_version", "kickoff_utc", "edge_points", "selection_result", "one_unit_profit", "grading_status"}
            if not _required.issubset(_graded.columns):
                st.warning("Graded results missing columns: " + ", ".join(sorted(_required - set(_graded.columns))))
            else:
                _graded["model_version"] = _graded["model_version"].astype(str).str.lower()
                _graded["season"] = pd.to_numeric(_graded["season"], errors="coerce")
                _graded["game_id"] = _graded["game_id"].astype(str)
                _graded["one_unit_profit"] = pd.to_numeric(_graded["one_unit_profit"], errors="coerce")
                _graded["edge_points"] = pd.to_numeric(_graded["edge_points"], errors="coerce")
                _graded["kickoff_dt"] = pd.to_datetime(_graded["kickoff_utc"], utc=True, errors="coerce")
                _graded["result"] = _graded["selection_result"].fillna("").astype(str).str.lower()
                _graded["settled"] = _graded["grading_status"].fillna("").astype(str).str.lower().eq("settled") & _graded["result"].isin(["win", "loss", "push"])
                _dupes = int(_graded.duplicated(["season", "game_id", "model_version"]).sum())
                if _dupes:
                    st.error(f"Audit warning: {_dupes} duplicate game/model keys in graded results; check the grading pipeline.")
                if _selections_path.exists():
                    _original = pd.read_csv(_selections_path)
                    _keys = ["season", "game_id", "model_version"]
                    _original["season"] = pd.to_numeric(_original["season"], errors="coerce")
                    _original["game_id"] = _original["game_id"].astype(str)
                    _original["model_version"] = _original["model_version"].astype(str).str.lower()
                    _missing_grades = len(_original[_keys].drop_duplicates().merge(_graded[_keys].drop_duplicates(), on=_keys, how="left", indicator=True).query("_merge == 'left_only'"))
                    if _missing_grades:
                        st.warning(f"{_missing_grades} frozen selections have no corresponding graded record.")
                def _summarize_bets(_frame):
                    _done = _frame[_frame["settled"]]
                    _n = len(_done)
                    _units = float(_done["one_unit_profit"].sum())
                    return {"Selections": len(_frame), "Settled": _n, "Pending": len(_frame) - _n,
                            "W": int((_done["result"] == "win").sum()),
                            "L": int((_done["result"] == "loss").sum()),
                            "P": int((_done["result"] == "push").sum()),
                            "Units": round(_units, 3), "ROI": round(100 * _units / _n, 2) if _n else float("nan")}
                _model_rows = [{"Model": _model.upper(), **_summarize_bets(_graded[_graded["model_version"] == _model])} for _model in ("v1", "v2", "v3")]
                st.markdown("**Official V1 / V2 / V3 results**")
                st.dataframe(pd.DataFrame(_model_rows), hide_index=True, use_container_width=True)
                _v3 = _graded[_graded["model_version"] == "v3"].copy()
                _v3["Edge bucket"] = pd.cut(_v3["edge_points"], bins=[-float("inf"), 5, 7, 10, float("inf")], right=False, labels=["Below 5", "5 to <7", "7 to <10", "10+"])
                _edge_summary = [{"Edge bucket": str(_bucket), **_summarize_bets(_group)} for _bucket, _group in _v3.groupby("Edge bucket", observed=True)]
                _t1, _t2, _t3 = st.tabs(["V3 edge buckets", "V3 investigation ATS", "Weekly results & audit"])
                with _t1:
                    st.dataframe(pd.DataFrame(_edge_summary), hide_index=True, use_container_width=True)
                with _t2:
                    if not _cohorts_path.exists():
                        st.info("Run the investigation workflow to populate cohort classifications.")
                    else:
                        _cohort = pd.read_csv(_cohorts_path)
                        _ckeys = ["season", "game_id"]
                        if not set(_ckeys + ["investigation_status"]).issubset(_cohort.columns):
                            st.warning("Investigation cohort file is missing required join/status columns.")
                        else:
                            _cohort["season"] = pd.to_numeric(_cohort["season"], errors="coerce")
                            _cohort["game_id"] = _cohort["game_id"].astype(str)
                            _cohort = _cohort.sort_values("classified_at_utc" if "classified_at_utc" in _cohort else "game_id").drop_duplicates(_ckeys, keep="first")
                            _joined = _v3.merge(_cohort[_ckeys + ["investigation_status"]], on=_ckeys, how="left", validate="many_to_one")
                            _joined["Status"] = _joined["investigation_status"].fillna("NOT CLASSIFIED")
                            _status_rows = [{"Status": _status, **_summarize_bets(_g)} for _status, _g in _joined.groupby("Status")]
                            st.dataframe(pd.DataFrame(_status_rows), hide_index=True, use_container_width=True)
                            _unclassified = _joined[_joined["Status"] == "NOT CLASSIFIED"]
                            st.caption(f"{len(_unclassified)} V3 selections have no frozen investigation classification. They remain unclassified; no retrospective labels are assigned.")
                            st.download_button("Download V3 ATS cohort audit", _joined.drop(columns=["kickoff_dt"]).to_csv(index=False), "jarzcfb_v3_cohort_audit.csv", mime="text/csv", key="download_v3_cohort_audit")
                with _t3:
                    _graded["Week starting (CT)"] = _graded["kickoff_dt"].dt.tz_convert(CENTRAL_TZ).dt.to_period("W-SUN").astype(str)
                    _weekly = [{"Week (CT)": _week, "Model": _model.upper(), **_summarize_bets(_g)} for (_week, _model), _g in _graded.groupby(["Week starting (CT)", "model_version"], dropna=False)]
                    st.dataframe(pd.DataFrame(_weekly).sort_values(["Week (CT)", "Model"], ascending=[False, True]), hide_index=True, use_container_width=True)
                    _pending = _graded[~_graded["settled"]].copy()
                    st.caption(f"Pending/unsettled: {len(_pending)} selections. These are not automatically assumed to be future games.")
                    st.dataframe(_pending[[c for c in ["model_version", "kickoff_utc", "away_team", "home_team", "selection", "grading_status"] if c in _pending.columns]], hide_index=True, use_container_width=True)
                    st.download_button("Download official weekly results", pd.DataFrame(_weekly).to_csv(index=False), "jarzcfb_weekly_results.csv", mime="text/csv", key="download_weekly_official")
    except Exception as _report_exc:
        st.warning(f"Official prospective report unavailable: {_report_exc}")

    # Frozen prospective V1 / V2 / V3 selections
    st.divider()
    st.subheader("Frozen prospective selections · V1 vs V2 vs V3")
    st.caption(
        "First qualifying pregame selections frozen by GitHub Actions. "
        "Selections are never recreated after results are known. "
        "V3 is the live shadow model and is being evaluated prospectively against V1 and V2."
    )

    from pathlib import Path

    prospective_file = Path("prospective/selections.csv")
    graded_file = Path("prospective/graded_selections.csv")

    if not prospective_file.exists():
        st.info("No frozen prospective selections have been recorded yet.")
    else:
        try:
            prospective = pd.read_csv(prospective_file)

            required = {
                "model_version", "season", "game_id", "kickoff_utc",
                "home_team", "away_team", "selection", "spread",
                "american_odds", "projected_home_margin", "edge_points"
            }

            missing = required - set(prospective.columns)

            if missing:
                st.error(
                    "Prospective selections file is missing columns: "
                    + ", ".join(sorted(missing))
                )
            else:
                prospective["kickoff_utc"] = pd.to_datetime(
                    prospective["kickoff_utc"], utc=True, errors="coerce"
                )
                prospective["spread"] = pd.to_numeric(
                    prospective["spread"], errors="coerce"
                )
                prospective["american_odds"] = pd.to_numeric(
                    prospective["american_odds"], errors="coerce"
                )
                prospective["projected_home_margin"] = pd.to_numeric(
                    prospective["projected_home_margin"], errors="coerce"
                )
                prospective["edge_points"] = pd.to_numeric(
                    prospective["edge_points"], errors="coerce"
                )

                prospective["Model"] = prospective["model_version"].str.upper()
                prospective["Matchup"] = (
                    prospective["away_team"] + " @ " + prospective["home_team"]
                )

                # Attach grading results when available.
                if graded_file.exists():
                    graded = pd.read_csv(graded_file)

                    grade_cols = [
                        "season", "game_id", "model_version",
                        "selection_result", "one_unit_profit", "grading_status"
                    ]

                    if set(grade_cols).issubset(graded.columns):
                        prospective = prospective.merge(
                            graded[grade_cols],
                            on=["season", "game_id", "model_version"],
                            how="left"
                        )

                for col in ["selection_result", "one_unit_profit", "grading_status"]:
                    if col not in prospective.columns:
                        prospective[col] = ""

                counts = (
                    prospective.groupby("Model")
                    .size()
                    .reindex(["V1", "V2", "V3"], fill_value=0)
                )

                c1, c2, c3, c4 = st.columns(4)

                c1.metric("V1 frozen picks", int(counts["V1"]))
                c2.metric("V2 frozen picks", int(counts["V2"]))
                c3.metric("V3 frozen picks", int(counts["V3"]))
                c4.metric("Total frozen picks", len(prospective))

                st.caption(
                    "Current ledger totals include selections from every captured week. "
                    "Use the table below to compare the models game by game."
                )

                model_filter = st.multiselect(
                    "Models",
                    ["V1", "V2", "V3"],
                    default=["V1", "V2", "V3"],
                    key="prospective_model_filter"
                )

                display = prospective[
                    prospective["Model"].isin(model_filter)
                ].copy()

                display = display.sort_values(
                    ["kickoff_utc", "Matchup", "Model"]
                )

                display["Kickoff"] = format_central(display["kickoff_utc"])

                display["Result"] = display["selection_result"].replace(
                    {"win": "WIN", "loss": "LOSS", "push": "PUSH"}
                )
                display["projected_home_margin"] = display["projected_home_margin"].round(1)
                display["edge_points"] = display["edge_points"].round(1)
                display["Status"] = display["grading_status"].replace(
                    {
                        "pending": "Pending",
                        "settled": "Settled",
                        "invalid_selection": "Invalid",
                        "ambiguous_result": "Ambiguous"
                    }
                )

                table = display[
                    [
                        "Kickoff",
                        "Matchup",
                        "Model",
                        "selection",
                        "spread",
                        "american_odds",
                        "projected_home_margin",
                        "edge_points",
                        "Status",
                        "Result"
                    ]
                ].rename(
                    columns={
                        "selection": "Selection",
                        "spread": "Spread",
                        "american_odds": "Odds",
                        "projected_home_margin": "Projected home margin",
                        "edge_points": "Model edge"
                    }
                )

                st.dataframe(
                    table,
                    hide_index=True,
                    use_container_width=True
                )

                st.download_button(
                    "Download V1 V2 V3 projections",
                    prospective.to_csv(index=False),
                    file_name="cfb_v1_v2_v3_projections.csv",
                    mime="text/csv",
                    key="download_v1_v2_v3_projections"
                )

                # Compare which models agree on the same game.
                agreement = (
                    prospective.pivot_table(
                        index=["season", "game_id", "Matchup", "kickoff_utc"],
                        columns="Model",
                        values="selection",
                        aggfunc="first"
                    )
                    .reset_index()
                )

                for version in ["V1", "V2", "V3"]:
                    if version not in agreement.columns:
                        agreement[version] = ""

                agreement["All 3 agree"] = (
                    agreement["V1"].ne("")
                    & agreement["V1"].eq(agreement["V2"])
                    & agreement["V2"].eq(agreement["V3"])
                )

                agreement["Kickoff"] = format_central(agreement["kickoff_utc"])

                st.write("Model agreement")
                st.dataframe(
                    agreement[
                        ["Kickoff", "Matchup", "V1", "V2", "V3", "All 3 agree"]
                    ].sort_values("Kickoff"),
                    hide_index=True,
                    use_container_width=True
                )

        except Exception as exc:
            st.error(f"Could not load frozen prospective selections: {exc}")


    # ---------------------------------------------------------------------------
    # Research-only V1 training eligibility audit. This does NOT replace ratings,
    # change V3, alter selections, or write to prospective/ files.
    # ---------------------------------------------------------------------------
    def _v1_fbs_training_audit(all_games, shrinkage, home_field, first_week):
        from collections import defaultdict
        weeks = defaultdict(list)
        seen = set()
        for g in all_games:
            if not isinstance(g, dict) or not g.get("completed"):
                continue
            if str(g.get("seasonType", g.get("season_type", "regular"))).lower() != "regular":
                continue
            h = g.get("homeTeam", g.get("home_team"))
            a = g.get("awayTeam", g.get("away_team"))
            hp = g.get("homePoints", g.get("home_points"))
            ap = g.get("awayPoints", g.get("away_points"))
            try:
                week = int(g.get("week"))
                hp, ap = float(hp), float(ap)
            except (TypeError, ValueError):
                continue
            if not h or not a or not math.isfinite(hp) or not math.isfinite(ap) or (hp == 0 and ap == 0):
                continue
            gid = g.get("id")
            ident = ("id", gid) if gid is not None else ("teams", week, key_name(h), key_name(a))
            if ident in seen:
                continue
            seen.add(ident)
            weeks[week].append(g)

        prior = []
        records = []
        audit = []
        for week in sorted(weeks):
            if week >= first_week and prior:
                eligible_prior = [g for g in prior if model_allowed(
                    g.get("homeTeam", g.get("home_team")),
                    g.get("awayTeam", g.get("away_team")))]
                baseline, baseline_count = build_ratings(prior, 0, shrinkage, home_field)
                fbs_only, fbs_count = build_ratings(eligible_prior, 0, shrinkage, home_field)
                audit.append({"Week": week, "All training games": baseline_count,
                              "FBS-only training games": fbs_count,
                              "Excluded training games": baseline_count - fbs_count})
                for g in weeks[week]:
                    h = g.get("homeTeam", g.get("home_team"))
                    a = g.get("awayTeam", g.get("away_team"))
                    if not model_allowed(h, a):
                        continue
                    old_h, old_a = find_rating(h, baseline), find_rating(a, baseline)
                    new_h, new_a = find_rating(h, fbs_only), find_rating(a, fbs_only)
                    if any(v is None for v in (old_h, old_a, new_h, new_a)):
                        continue  # paired comparison only; identical test set
                    actual = float(g.get("homePoints", g.get("home_points"))) - float(g.get("awayPoints", g.get("away_points")))
                    old = float(old_h) - float(old_a) + home_field
                    new = float(new_h) - float(new_a) + home_field
                    records.append({"Week": week, "Game ID": g.get("id"),
                        "Matchup": f"{a} @ {h}", "Actual home margin": actual,
                        "Current V1 margin": old, "FBS-only V1 margin": new,
                        "Current V1 abs error": abs(old-actual),
                        "FBS-only V1 abs error": abs(new-actual),
                        "Current V1 winner correct": (old > 0) == (actual > 0) if actual != 0 else np.nan,
                        "FBS-only V1 winner correct": (new > 0) == (actual > 0) if actual != 0 else np.nan,
                        "Margin change": new-old})
            prior.extend(weeks[week])
        return pd.DataFrame(records), pd.DataFrame(audit)



with _research_tab:
    st.divider()
    st.subheader("Research audit · Current V1 vs FBS-only V1")
    st.caption("Historical walk-forward, paired-game diagnostic only. No changes to V1/V2/V3 production ratings, frozen picks, grading or files. Historical eligibility is evaluated using the currently installed FBS membership list; past seasons may have different membership.")
    with st.expander("Compare V1 training eligibility (research only)", expanded=False):
        audit_season = st.number_input("Audit season", min_value=2020, max_value=2025, value=2025, step=1, key="v1_fbs_audit_season")
        audit_start = st.slider("First held-out evaluation week", 3, 10, 5, key="v1_fbs_audit_week")
        if st.button("Run paired V1 comparison", key="run_v1_fbs_audit"):
            if not ok_cfbd:
                st.error("CFBD API key required.")
            else:
                try:
                    audit_games = games_data(secret("CFBD_API_KEY"), int(audit_season))
                    paired, training = _v1_fbs_training_audit(audit_games, shrink, home_adv, audit_start)
                    if paired.empty:
                        st.warning("No common eligible evaluation games were found.")
                    else:
                        old_mae = paired["Current V1 abs error"].mean()
                        new_mae = paired["FBS-only V1 abs error"].mean()
                        wins = paired[paired["Actual home margin"] != 0]
                        c1, c2, c3, c4 = st.columns(4)
                        c1.metric("Same FBS games tested", len(paired))
                        c2.metric("Current V1 MAE", f"{old_mae:.2f} pts")
                        c3.metric("FBS-only V1 MAE", f"{new_mae:.2f} pts", delta=f"{old_mae-new_mae:+.2f} pts improvement")
                        c4.metric("Training exclusions (latest week)", int(training.iloc[-1]["Excluded training games"]))
                        st.write("Winner accuracy on the same non-tied games")
                        st.write(f"Current V1: {wins['Current V1 winner correct'].mean():.1%} · FBS-only V1: {wins['FBS-only V1 winner correct'].mean():.1%}")
                        st.caption("Positive MAE improvement means FBS-only V1 was better on this historical sample. This does not establish an improvement in betting ROI or the locked V3 model.")
                        st.dataframe(training, hide_index=True, use_container_width=True)
                        st.dataframe(paired.sort_values("Current V1 abs error", ascending=False), hide_index=True, use_container_width=True)
                        st.download_button("Download paired V1 audit CSV", paired.to_csv(index=False),
                            file_name=f"JarzCFB_v1_fbs_audit_{audit_season}.csv", mime="text/csv", key="v1_audit_download")
                except Exception as exc:
                    st.error(f"V1 eligibility audit failed: {exc}")


    # ---------------------------------------------------------------------------
    # SHADOW V3 research audit. Production V3 and frozen records are NOT modified.
    # Both variants use identical historical V2, 25/75 blend and fixed calibration.
    # ---------------------------------------------------------------------------
    def _shadow_v3_walkforward(prior_season_games, season_games, first_test_week, shrinkage, home_field):
        from collections import defaultdict
        from cfb_v2_experimental import build_v2
        grouped = defaultdict(list)
        seen = set()
        for raw in season_games:
            if not isinstance(raw, dict) or not raw.get("completed"):
                continue
            if str(raw.get("seasonType", raw.get("season_type", "regular"))).lower() != "regular":
                continue
            h = raw.get("homeTeam", raw.get("home_team"))
            a = raw.get("awayTeam", raw.get("away_team"))
            hp = raw.get("homePoints", raw.get("home_points"))
            ap = raw.get("awayPoints", raw.get("away_points"))
            kickoff = pd.to_datetime(raw.get("startDate", raw.get("start_date")), utc=True, errors="coerce")
            try:
                week = int(raw.get("week"))
                hp, ap = float(hp), float(ap)
            except (ValueError, TypeError):
                continue
            if not h or not a or pd.isna(kickoff) or not np.isfinite(hp) or not np.isfinite(ap) or (hp == 0 and ap == 0):
                continue
            gid = raw.get("id")
            identity = ("id", gid) if gid is not None else ("match", week, key_name(h), key_name(a))
            if identity in seen:
                continue
            seen.add(identity)
            grouped[week].append(raw)

        past = []
        results = []
        training_counts = []
        for week in sorted(grouped):
            week_games = grouped[week]
            if week >= first_test_week and past:
                first_kickoff = min(pd.to_datetime(g.get("startDate", g.get("start_date")), utc=True) for g in week_games)
                asof = first_kickoff.to_pydatetime()
                eligible_past = [g for g in past if model_allowed(
                    g.get("homeTeam", g.get("home_team")),
                    g.get("awayTeam", g.get("away_team")))]
                v1_base, base_count = build_ratings(past, 0, shrinkage, home_field, asof=asof)
                v1_fbs, fbs_count = build_ratings(eligible_past, 0, shrinkage, home_field, asof=asof)
                # Build historical V2 at the same as-of timestamp for BOTH challengers.
                v2, info = build_v2(prior_season_games, past, asof, home_field, shrinkage)
                training_counts.append({"Week": week, "V1 all training": base_count,
                    "V1 FBS-only training": fbs_count, "V2 current training": info["current_games"]})
                for g in week_games:
                    h = g.get("homeTeam", g.get("home_team"))
                    a = g.get("awayTeam", g.get("away_team"))
                    if not model_allowed(h, a):
                        continue
                    ratings = [find_rating(h, r) for r in (v1_base, v1_fbs, v2)] + [find_rating(a, r) for r in (v1_base, v1_fbs, v2)]
                    if any(x is None or not np.isfinite(float(x)) for x in ratings):
                        continue
                    bh, fh, vh, ba, fa, va = map(float, ratings)
                    old_v1 = bh-ba+home_field
                    new_v1 = fh-fa+home_field
                    v2_margin = vh-va+home_field
                    old_v3 = final_model_projection(old_v1, v2_margin)
                    new_v3 = final_model_projection(new_v1, v2_margin)
                    actual = float(g.get("homePoints", g.get("home_points")))-float(g.get("awayPoints", g.get("away_points")))
                    results.append({"Week": week, "Game ID": g.get("id"), "Matchup": f"{a} @ {h}",
                        "Kickoff UTC": g.get("startDate", g.get("start_date")),
                        "Actual home margin": actual, "Current V1 margin": old_v1,
                        "FBS-only V1 margin": new_v1, "Common V2 margin": v2_margin,
                        "Official-formula baseline V3 margin": old_v3,
                        "Shadow FBS-only V3 margin": new_v3,
                        "Baseline V3 absolute error": abs(old_v3-actual),
                        "Shadow V3 absolute error": abs(new_v3-actual),
                        "Baseline V3 winner correct": ((old_v3>0)==(actual>0)) if actual!=0 else np.nan,
                        "Shadow V3 winner correct": ((new_v3>0)==(actual>0)) if actual!=0 else np.nan,
                        "Shadow minus baseline absolute error": abs(new_v3-actual)-abs(old_v3-actual)})
            past.extend(week_games)
        return pd.DataFrame(results), pd.DataFrame(training_counts)


    st.divider()
    st.subheader("Research audit · Shadow V3 vs current V3")
    st.caption("Historical paired walk-forward research only. Both variants use the same V2 ratings, fixed V3 25%/75% blend and fixed calibration. No prospective files, frozen picks, production ratings, or grades are changed. Current FBS membership is applied retrospectively; interpret older seasons cautiously.")
    with st.expander("Run shadow V3 comparison (research only)", expanded=False):
        shadow_year = st.number_input("Shadow audit season", min_value=2021, max_value=2025, value=2025, step=1, key="shadow_v3_year")
        shadow_week = st.slider("First test week", min_value=3, max_value=10, value=5, key="shadow_v3_week")
        if st.button("Run paired shadow V3 comparison", key="run_shadow_v3"):
            if not ok_cfbd:
                st.error("CFBD API key required.")
            else:
                try:
                    with st.spinner("Building historical V1/V2 ratings for each week…"):
                        shadow_games = games_data(secret("CFBD_API_KEY"), int(shadow_year))
                        shadow_prior = games_data(secret("CFBD_API_KEY"), int(shadow_year)-1)
                        shadow_rows, shadow_training = _shadow_v3_walkforward(
                            shadow_prior, shadow_games, shadow_week, shrink, home_adv)
                    if shadow_rows.empty:
                        st.warning("No common historical FBS games could be projected. Check season and source data.")
                    else:
                        baseline_mae = shadow_rows["Baseline V3 absolute error"].mean()
                        challenger_mae = shadow_rows["Shadow V3 absolute error"].mean()
                        settled = shadow_rows[shadow_rows["Actual home margin"] != 0]
                        baseline_wins = settled["Baseline V3 winner correct"].mean()
                        challenger_wins = settled["Shadow V3 winner correct"].mean()
                        a,b,c,d = st.columns(4)
                        a.metric("Same games tested", len(shadow_rows))
                        b.metric("Baseline V3 MAE", f"{baseline_mae:.3f} pts")
                        c.metric("Shadow V3 MAE", f"{challenger_mae:.3f} pts", delta=f"{baseline_mae-challenger_mae:+.3f} pts improvement")
                        d.metric("Shadow better / worse", f"{int((shadow_rows['Shadow minus baseline absolute error']<0).sum())} / {int((shadow_rows['Shadow minus baseline absolute error']>0).sum())}")
                        st.write(f"Outright winner accuracy (non-tied games): baseline **{baseline_wins:.2%}**, shadow **{challenger_wins:.2%}**")
                        st.caption("Lower MAE is better. This comparison does not test ATS returns or establish profitability. A single historical season is insufficient for promotion.")
                        st.dataframe(shadow_training, hide_index=True, use_container_width=True)
                        st.dataframe(shadow_rows.sort_values("Baseline V3 absolute error", ascending=False), hide_index=True, use_container_width=True)
                        st.download_button("Download paired shadow V3 audit CSV", shadow_rows.to_csv(index=False),
                            file_name=f"JarzCFB_shadow_v3_audit_{shadow_year}.csv", mime="text/csv", key="shadow_v3_download")
                except Exception as exc:
                    st.error(f"Shadow V3 audit failed: {exc}")


    # --- Research-only: frozen V3 edge reliability audit ---
    # Reads historical frozen selections and optional existing classification snapshot.
    # Does not modify, regrade, or filter production records.
    def _edge_reliability_research(graded, cohort=None):
        x = graded.copy()
        required = {"season", "game_id", "model_version", "edge_points", "grading_status", "selection_result", "one_unit_profit"}
        missing = required - set(x.columns)
        if missing:
            raise ValueError("Missing required graded columns: " + ", ".join(sorted(missing)))
        x = x[x["model_version"].astype(str).str.lower().eq("v3")].copy()
        x["edge_points"] = pd.to_numeric(x["edge_points"], errors="coerce").abs()
        x["one_unit_profit"] = pd.to_numeric(x["one_unit_profit"], errors="coerce")
        x["captured_at_utc"] = pd.to_datetime(x.get("captured_at_utc", pd.Series(index=x.index, dtype="object")), utc=True, errors="coerce")
        # Preserve the first frozen qualifying quote for each game/model, rather than cherry-picking later lines.
        x = x.sort_values("captured_at_utc", kind="stable").drop_duplicates(["season", "game_id", "model_version"], keep="first")
        x["result"] = x["selection_result"].astype(str).str.lower().str.strip()
        x["settled"] = x["grading_status"].astype(str).str.lower().eq("settled") & x["result"].isin(["win", "loss", "push"])
        x["edge_band"] = pd.cut(x["edge_points"], [-0.00001, 3, 5, 7, 10, float("inf")], labels=["0–3", "3–5", "5–7", "7–10", "10+"]) 
        x["market_age_hours"] = (x["captured_at_utc"] - pd.to_datetime(x.get("market_last_update_utc", pd.Series(index=x.index, dtype="object")), utc=True, errors="coerce")).dt.total_seconds() / 3600
        if cohort is not None and not cohort.empty and {"season", "game_id"}.issubset(cohort.columns):
            c = cohort.copy()
            keep = [v for v in ["season", "game_id", "investigation_status", "v1_v2_disagreement"] if v in c.columns]
            c = c[keep].drop_duplicates(["season", "game_id"], keep="first")
            x = x.merge(c, on=["season", "game_id"], how="left", suffixes=("", "_audit"))
            for field in ["investigation_status", "v1_v2_disagreement"]:
                if field + "_audit" in x:
                    if field in x:
                        x[field] = x[field].combine_first(x[field + "_audit"])
                    else:
                        x[field] = x[field + "_audit"]
                    x.drop(columns=[field + "_audit"], inplace=True)
        if "v1_v2_disagreement" in x:
            x["v1_v2_disagreement"] = pd.to_numeric(x["v1_v2_disagreement"], errors="coerce")
            x["agreement_band"] = pd.cut(x["v1_v2_disagreement"], [-0.00001, 3, 7, float("inf")], labels=["Close (≤3)", "Moderate (3–7)", "Wide (>7)"])
            x["agreement_band"] = x["agreement_band"].astype("object").fillna("Unknown")
        else:
            x["agreement_band"] = "Unknown"
        x["investigation_status"] = x.get("investigation_status", pd.Series("Unknown", index=x.index)).fillna("Unknown").astype(str).str.upper()
        return x


    def _edge_audit_summary(data, groups):
        rows = []
        for group, part in data.groupby(groups, observed=True, dropna=False):
            if not isinstance(group, tuple):
                group = (group,)
            done = part[part["settled"]]
            wins = int((done["result"] == "win").sum())
            losses = int((done["result"] == "loss").sum())
            pushes = int((done["result"] == "push").sum())
            units = done["one_unit_profit"].sum(min_count=1)
            rows.append(dict(zip(groups, group)) | {"Frozen picks": len(part), "Settled": len(done), "Wins": wins,
                "Losses": losses, "Pushes": pushes, "Win % (ex push)": 100*wins/(wins+losses) if wins+losses else float("nan"),
                "Units": units, "ROI %": 100*units/len(done) if len(done) and pd.notna(units) else float("nan")})
        return pd.DataFrame(rows)

    st.divider()
    st.subheader("Research audit · Extreme-edge reliability (frozen V3)")
    st.caption("Read-only analysis of first frozen V3 selection per game. No retroactive reclassification, pick deletion, or production filter changes. Small cohorts are descriptive, not validated betting strategies.")
    with st.expander("Analyze edge bands, V1/V2 agreement, and market freshness", expanded=False):
        from pathlib import Path as _EdgePath
        _edge_graded_path = _EdgePath("prospective/graded_selections.csv")
        _edge_cohort_path = _EdgePath("prospective/investigation_cohort.csv")
        if not _edge_graded_path.exists():
            st.info("No local prospective/graded_selections.csv found. The research audit requires your frozen grading data.")
        elif st.button("Run frozen V3 edge audit", key="run_frozen_v3_edge_audit"):
            try:
                _edge_graded = pd.read_csv(_edge_graded_path)
                _edge_cohort = pd.read_csv(_edge_cohort_path) if _edge_cohort_path.exists() else None
                _edge_data = _edge_reliability_research(_edge_graded, _edge_cohort)
                _edge_settled = _edge_data[_edge_data["settled"]]
                st.write(f"Frozen V3 games: **{len(_edge_data)}** · Settled: **{len(_edge_settled)}** · Pending/unsettled: **{len(_edge_data)-len(_edge_settled)}**")
                if len(_edge_settled) < 30:
                    st.warning("Fewer than 30 settled V3 games. Treat all subgroup results as highly uncertain.")
                st.markdown("**By edge magnitude**")
                st.dataframe(_edge_audit_summary(_edge_data, ["edge_band"]), hide_index=True, use_container_width=True)
                st.markdown("**Extreme edges (10+) by model agreement**")
                _edge_extreme = _edge_data[_edge_data["edge_points"] >= 10]
                st.dataframe(_edge_audit_summary(_edge_extreme, ["agreement_band"]), hide_index=True, use_container_width=True)
                st.markdown("**Extreme edges (10+) by existing investigation status**")
                st.dataframe(_edge_audit_summary(_edge_extreme, ["investigation_status"]), hide_index=True, use_container_width=True)
                st.markdown("**By V1/V2 agreement (all edge sizes)**")
                st.dataframe(_edge_audit_summary(_edge_data, ["agreement_band"]), hide_index=True, use_container_width=True)
                st.markdown("**Market freshness diagnostic**")
                _edge_data["freshness_band"] = pd.cut(_edge_data["market_age_hours"], [-float("inf"), 0, 1, 6, 24, float("inf")], labels=["Future timestamp", "≤1 hour", "1–6 hours", "6–24 hours", ">24 hours"])
                _edge_data["freshness_band"] = _edge_data["freshness_band"].astype("object").fillna("Unknown")
                st.dataframe(_edge_audit_summary(_edge_data, ["freshness_band"]), hide_index=True, use_container_width=True)
                st.caption("Market freshness is calculated from captured_at_utc minus market_last_update_utc; missing timestamps are Unknown. The research does not assume the quoted spread was available at another time.")
                _edge_export_cols = [c for c in ["season", "game_id", "kickoff_utc", "captured_at_utc", "home_team", "away_team", "selection", "sportsbook", "spread", "edge_points", "edge_band", "v1_v2_disagreement", "agreement_band", "investigation_status", "market_age_hours", "freshness_band", "selection_result", "one_unit_profit", "grading_status", "settled"] if c in _edge_data.columns]
                st.download_button("Download frozen V3 edge reliability audit CSV", _edge_data[_edge_export_cols].to_csv(index=False), file_name="JarzCFB_frozen_V3_edge_reliability.csv", mime="text/csv", key="edge_audit_csv")
            except Exception as _edge_exc:
                st.error(f"Edge audit failed: {_edge_exc}")


    # --- Research-only weekly pick quality monitor ---
    # Existing frozen selections remain unchanged. This view never writes source CSVs.
    def _weekly_quality_monitor(graded, cohort=None):
        x = _edge_reliability_research(graded, cohort)
        x["kickoff_at"] = pd.to_datetime(x.get("kickoff_utc", pd.Series(index=x.index, dtype="object")), utc=True, errors="coerce")
        x["hours_before_kickoff"] = (x["kickoff_at"] - x["captured_at_utc"]).dt.total_seconds() / 3600
        x["capture_timing"] = pd.cut(x["hours_before_kickoff"],
            [-float("inf"), 0, 1, 6, 24, 72, float("inf")],
            labels=["After kickoff / invalid", "0–1h before", "1–6h before", "6–24h before", "1–3 days before", ">3 days before"])
        x["capture_timing"] = x["capture_timing"].astype("object").fillna("Unknown")
        x["quote_freshness"] = pd.cut(x["market_age_hours"],
            [-float("inf"), -0.001, 1, 6, 24, float("inf")],
            labels=["Future update / invalid", "≤1h old at capture", "1–6h old", "6–24h old", ">24h old"])
        x["quote_freshness"] = x["quote_freshness"].astype("object").fillna("Unknown")
        x["division_check_current"] = x.apply(lambda r: matchup_status(str(r.get("home_team", "")), str(r.get("away_team", ""))), axis=1)
        x["division_review"] = x["division_check_current"].ne("FBS vs FBS")
        # Current eligibility gate is NOT a season-specific historical membership registry.
        x["season_membership_verified"] = False
        x["edge_10plus_review"] = x["edge_points"].ge(10)
        x["edge_5to7_observation"] = x["edge_points"].ge(5) & x["edge_points"].lt(7)
        x["timestamp_review"] = x["hours_before_kickoff"].lt(0) | x["market_age_hours"].lt(-0.001) | x["hours_before_kickoff"].isna()
        x["review_reasons"] = x.apply(lambda r: "; ".join(v for condition,v in [
            (r["edge_10plus_review"], "Extreme edge ≥10: review"),
            (r["division_review"], "Division match unresolved by current gate"),
            (r["timestamp_review"], "Invalid or missing timestamp"),
            (pd.isna(r["market_age_hours"]), "Missing market-update time")
        ] if condition) or "No automatic alert", axis=1)
        x["kickoff_week_utc"] = x["kickoff_at"].dt.strftime("%G-W%V")
        return x

    st.divider()
    st.subheader("Research monitor · Weekly frozen V3 pick quality")
    st.caption("Read-only diagnostics. Extreme edges are review flags, not exclusions; the 5–7 band is descriptive, not a proven strategy. Historical division membership is not independently verified. North Dakota State and Sacramento State are conservatively flagged for season-specific review.")
    with st.expander("Review frozen picks, kickoff timing, and data-quality flags", expanded=False):
        from pathlib import Path as _QualityPath
        _quality_graded_path = _QualityPath("prospective/graded_selections.csv")
        _quality_cohort_path = _QualityPath("prospective/investigation_cohort.csv")
        if not _quality_graded_path.exists():
            st.info("No prospective/graded_selections.csv found; frozen selection data is required.")
        elif st.button("Run weekly pick quality monitor", key="run_weekly_pick_quality"):
            try:
                _quality_graded = pd.read_csv(_quality_graded_path)
                _quality_cohort = pd.read_csv(_quality_cohort_path) if _quality_cohort_path.exists() else None
                _quality_data = _weekly_quality_monitor(_quality_graded, _quality_cohort)
                _quality_settled = _quality_data[_quality_data["settled"]]
                st.write(f"Frozen V3 games: **{len(_quality_data)}** · Settled: **{len(_quality_settled)}** · Pending: **{len(_quality_data)-len(_quality_settled)}**")
                a,b,c = st.columns(3)
                a.metric("Extreme-edge review flags", int(_quality_data["edge_10plus_review"].sum()))
                b.metric("Current division-gate alerts", int(_quality_data["division_review"].sum()))
                c.metric("Timestamp review flags", int(_quality_data["timestamp_review"].sum()))
                st.warning("Division check uses the current FBS school gate, not a verified season-by-season registry. A 'FBS vs FBS' result does not certify historical membership.")
                st.markdown("**Results by edge band (observational)**")
                st.dataframe(_edge_audit_summary(_quality_data, ["edge_band"]), hide_index=True, use_container_width=True)
                st.markdown("**Results by kickoff week**")
                st.dataframe(_edge_audit_summary(_quality_data, ["kickoff_week_utc"]), hide_index=True, use_container_width=True)
                st.markdown("**Results by time from capture to kickoff**")
                st.dataframe(_edge_audit_summary(_quality_data, ["capture_timing"]), hide_index=True, use_container_width=True)
                st.markdown("**Results by quote freshness at capture**")
                st.dataframe(_edge_audit_summary(_quality_data, ["quote_freshness"]), hide_index=True, use_container_width=True)
                st.markdown("**Review queue (includes pending and settled; no picks are removed)**")
                _quality_cols = [v for v in ["season","game_id","kickoff_week_utc","kickoff_utc","home_team","away_team","selection","edge_points","edge_band","investigation_status","division_check_current","hours_before_kickoff","market_age_hours","capture_timing","quote_freshness","review_reasons","grading_status","selection_result","one_unit_profit"] if v in _quality_data.columns]
                st.dataframe(_quality_data.loc[_quality_data["review_reasons"].ne("No automatic alert"), _quality_cols], hide_index=True, use_container_width=True)
                st.download_button("Download weekly pick quality monitor CSV", _quality_data[_quality_cols].to_csv(index=False), file_name="JarzCFB_weekly_pick_quality.csv", mime="text/csv", key="weekly_pick_quality_csv")
            except Exception as _quality_exc:
                st.error(f"Weekly pick quality monitor failed: {_quality_exc}")


    # --- Research-only weekly betting decision board ---
    # Never alters, filters, or overwrites frozen prospective records.
    def _weekly_decision_board(graded, cohort=None):
        q = _weekly_quality_monitor(graded, cohort).copy()
        q = q.loc[~q["settled"].fillna(False)].copy()
        q["kickoff_at"] = pd.to_datetime(q["kickoff_utc"], utc=True, errors="coerce")
        q["division_alert"] = q["division_check_current"].ne("FBS vs FBS")
        q["extreme_alert"] = pd.to_numeric(q["edge_points"], errors="coerce").ge(10)
        q["timing_alert"] = (q["hours_before_kickoff"].isna() | q["hours_before_kickoff"].lt(0)
                              | q["market_age_hours"].isna() | q["market_age_hours"].lt(0))
        q["early_capture"] = q["hours_before_kickoff"].gt(72)
        q["review_priority"] = q.apply(lambda r: (
            "VERIFY DIVISION / HOLD" if r["division_alert"] else
            "VERIFY TIMESTAMPS" if r["timing_alert"] else
            "REVIEW EXTREME EDGE" if r["extreme_alert"] else
            "STANDARD REVIEW"), axis=1)
        q["observed_edge_band"] = q["edge_points"].between(5, 7, inclusive="left")
        q["review_notes"] = q.apply(lambda r: "; ".join(z for ok,z in [
            (r["division_alert"], "Team eligibility unresolved; do not treat as verified FBS"),
            (r["timing_alert"], "Check capture and market timestamps"),
            (r["extreme_alert"], "10+ edge: independently confirm teams, injuries and spread"),
            (r["early_capture"], "Captured >72h before kickoff; compare fresh market before betting"),
            (r["observed_edge_band"], "5–7 band: historically positive, not a validated advantage")
        ] if ok) or "Standard pre-bet checks", axis=1)
        q["review_sort"] = q["review_priority"].map({"VERIFY DIVISION / HOLD":0,
            "VERIFY TIMESTAMPS":1,"REVIEW EXTREME EDGE":2,"STANDARD REVIEW":3})
        return q.sort_values(["review_sort","kickoff_at","edge_points"], ascending=[True,True,False])


with _upcoming_tab:
    st.divider()
    st.subheader("Research board · Upcoming frozen V3 decisions")
    st.caption("Read-only review queue, NOT a betting recommendation or confidence score. No production selections, spreads, model weights or grading are changed. Review statuses do not prove a positive expected value.")
    with st.expander("Inspect pending picks and export review queue", expanded=False):
        from pathlib import Path as _DecisionPath
        _decision_graded_path = _DecisionPath("prospective/graded_selections.csv")
        _decision_cohort_path = _DecisionPath("prospective/investigation_cohort.csv")
        if not _decision_graded_path.exists():
            st.info("The board requires prospective/graded_selections.csv.")
        elif st.button("Build upcoming decision board", key="build_v3_decision_board"):
            try:
                _dg = pd.read_csv(_decision_graded_path)
                _dc = pd.read_csv(_decision_cohort_path) if _decision_cohort_path.exists() else None
                _board = _weekly_decision_board(_dg, _dc)
                st.write(f"**{len(_board)} pending frozen V3 selections**")
                _bc1,_bc2,_bc3,_bc4 = st.columns(4)
                _bc1.metric("Division holds", int((_board["review_priority"] == "VERIFY DIVISION / HOLD").sum()))
                _bc2.metric("Timestamp reviews", int((_board["review_priority"] == "VERIFY TIMESTAMPS").sum()))
                _bc3.metric("Extreme edge reviews", int((_board["review_priority"] == "REVIEW EXTREME EDGE").sum()))
                _bc4.metric("Standard review", int((_board["review_priority"] == "STANDARD REVIEW").sum()))
                st.caption("Priority counts are mutually exclusive. An item can have multiple flags, shown in review notes. No automatic betting approval is given.")
                _weeks = sorted(_board["kickoff_week_utc"].dropna().unique().tolist())
                _week_filter = st.selectbox("Kickoff week (UTC)", ["All pending weeks"] + _weeks, key="decision_week_filter")
                _view = _board if _week_filter == "All pending weeks" else _board[_board["kickoff_week_utc"] == _week_filter]
                _columns = [c for c in ["kickoff_week_utc","kickoff_utc","home_team","away_team","selection","edge_points","edge_band","investigation_status","division_check_current","review_priority","hours_before_kickoff","market_age_hours","review_notes","game_id"] if c in _view.columns]
                st.dataframe(_view[_columns], hide_index=True, use_container_width=True)
                st.download_button("Download pending V3 decision board CSV", _board[_columns].to_csv(index=False),
                    file_name="JarzCFB_upcoming_decision_board.csv", mime="text/csv", key="download_v3_decision_board")
                st.info("Before placing any wager, verify the matchup and division, confirm the current available sportsbook line, and check major roster/news changes. Early-week frozen lines may no longer be available.")
            except Exception as _board_exc:
                st.error(f"Decision board failed: {_board_exc}")


    # --- Research-only fresh-market revalidation of frozen V3 selections ---
    # Quotes are fetched only on request; original captured prices and predictions are never changed.
    def _fresh_market_revalidation(frozen, odds_events, checked_at):
        """Return exactly one coverage row per pending frozen V3 pick; never alter the source."""
        rows = []
        events = odds_events if isinstance(odds_events, list) else []
        for _, pick in frozen.iterrows():
            home, away, selected = (str(pick.get(k) or "") for k in ("home_team", "away_team", "selection"))
            book_key = str(pick.get("sportsbook_key") or "").strip()
            kickoff = pd.to_datetime(pick.get("kickoff_utc"), utc=True, errors="coerce")
            projection = pd.to_numeric(pick.get("projected_home_margin"), errors="coerce")
            old_edge = pd.to_numeric(pick.get("edge_points"), errors="coerce")
            base = {"season": pick.get("season"), "game_id": pick.get("game_id"),
                    "captured_at_utc": pick.get("captured_at_utc"), "kickoff_utc": pick.get("kickoff_utc"),
                    "home_team": home, "away_team": away, "selection": selected,
                    "original_sportsbook_key": book_key, "original_sportsbook": pick.get("sportsbook"),
                    "original_spread": pd.to_numeric(pick.get("spread"), errors="coerce"),
                    "original_edge_points": old_edge, "frozen_projected_home_margin": projection,
                    "checked_at_utc": checked_at, "current_sportsbook": None,
                    "current_spread": float("nan"), "current_american_odds": float("nan"),
                    "current_edge_points": float("nan"), "edge_change_points": float("nan"),
                    "quote_last_update_utc": None, "match_status": "", "coverage_detail": "",
                    "event_candidates": 0, "kickoff_candidates": 0, "same_book_candidates": 0}
            def finish(status, detail):
                base["match_status"] = status
                base["coverage_detail"] = detail
                rows.append(base)
            if not (same_school_name(selected, home) or same_school_name(selected, away)):
                finish("SELECTION_IDENTITY_UNRESOLVED", "Frozen selection does not match either listed team")
                continue
            if pd.isna(projection) or pd.isna(kickoff):
                finish("MISSING_FROZEN_DATA", "Frozen projection or kickoff is missing")
                continue
            if not book_key or book_key.lower() in ("nan", "none"):
                finish("MISSING_ORIGINAL_BOOK", "Frozen selection has no sportsbook key")
                continue
            matchup_events = [ev for ev in events if isinstance(ev, dict) and ev.get("home_team") and ev.get("away_team")
                              and same_school_name(str(ev["home_team"]), home)
                              and same_school_name(str(ev["away_team"]), away)]
            base["event_candidates"] = len(matchup_events)
            if not matchup_events:
                finish("EVENT_NOT_FOUND", "No same-home-and-away event returned by current odds feed")
                continue
            timed = []
            for ev in matchup_events:
                event_time = pd.to_datetime(ev.get("commence_time"), utc=True, errors="coerce")
                if pd.notna(event_time) and abs((event_time-kickoff).total_seconds()) <= 6*3600:
                    timed.append(ev)
            base["kickoff_candidates"] = len(timed)
            if not timed:
                finish("KICKOFF_MISMATCH", "Team names matched, but event kickoff differs by more than 6 hours")
                continue
            same_books = [bk for ev in timed for bk in (ev.get("bookmakers") or [])
                          if isinstance(bk, dict) and str(bk.get("key", "")) == book_key]
            base["same_book_candidates"] = len(same_books)
            if not same_books:
                finish("ORIGINAL_BOOK_UNAVAILABLE", "Event found but original sportsbook was absent")
                continue
            spread_markets = [m for bk in same_books for m in (bk.get("markets") or [])
                              if isinstance(m, dict) and m.get("key") == "spreads"]
            if not spread_markets:
                finish("SPREAD_MARKET_UNAVAILABLE", "Original sportsbook returned no spread market")
                continue
            candidates = []
            selected_outcomes = 0
            for bk in same_books:
                for market in (bk.get("markets") or []):
                    if not isinstance(market, dict) or market.get("key") != "spreads":
                        continue
                    for outcome in (market.get("outcomes") or []):
                        if not isinstance(outcome, dict) or not same_school_name(str(outcome.get("name", "")), selected):
                            continue
                        selected_outcomes += 1
                        try:
                            point, price = float(outcome["point"]), float(outcome["price"])
                            if not (math.isfinite(point) and math.isfinite(price) and price != 0):
                                continue
                        except (ValueError, TypeError, KeyError):
                            continue
                        updated = pd.to_datetime(market.get("last_update", bk.get("last_update")), utc=True, errors="coerce")
                        candidates.append((updated, point, price, str(bk.get("title", book_key))))
            if not selected_outcomes:
                finish("SELECTION_OUTCOME_UNAVAILABLE", "Spread market lacks an outcome matching the frozen selection")
                continue
            if not candidates:
                finish("INVALID_QUOTE", "Selection found but spread or odds was invalid")
                continue
            last, point, price, book = max(candidates, key=lambda z: z[0].timestamp() if pd.notna(z[0]) else -1)
            current_edge = (float(projection) if same_school_name(selected, home) else -float(projection)) + point
            base.update({"current_sportsbook": book, "current_spread": point,
                         "current_american_odds": price, "current_edge_points": round(current_edge, 5),
                         "edge_change_points": round(current_edge-float(old_edge), 5) if pd.notna(old_edge) else float("nan"),
                         "quote_last_update_utc": last.isoformat() if pd.notna(last) else None})
            finish("MATCHED_ORIGINAL_BOOK", "Verified same matchup, kickoff, original sportsbook and selected-team spread")
        return pd.DataFrame(rows)

    # --- Research-only authoritative kickoff reconciliation (2026 Week 7) ---
    # A verified event kickoff may resolve a stale frozen kickoff, but NEVER overwrites it.
    # Exact home/away matching and a 90-minute tolerance to the independently verified kickoff
    # are still required; no blanket widening of the six-hour matching rule.
    _KICKOFF_RECONCILIATION_2026 = {
        ("nebraska", "oregon"): ("2026-10-18T03:00:00Z", "https://www.cornnation.com/football/103316/fox-and-nebraska-announce-nu-oregon-as-late-10-pm-kickoff"),
        ("kent state", "south florida"): ("2026-10-17T23:00:00Z", "https://fbschedules.com/college-football-schedule-tv-selections-for-october-17-2026/"),
        ("louisville", "syracuse"): ("2026-10-17T23:30:00Z", "https://www.nunesmagician.com/syracuse-orange-football-fran/113814/syracuse-football-orange-will-host-louisville-in-primetime"),
        ("ohio state", "indiana"): ("2026-10-17T16:00:00Z", "https://ohiostatebuckeyes.com/sports/football/schedule/print"),
    }

    def _verified_kickoff_for_pick(pick):
        season = pd.to_numeric(pick.get("season"), errors="coerce")
        if pd.isna(season) or int(season) != 2026:
            return None
        for (away_name, home_name), (kickoff, source) in _KICKOFF_RECONCILIATION_2026.items():
            if same_school_name(str(pick.get("away_team", "")), away_name) and same_school_name(str(pick.get("home_team", "")), home_name):
                return kickoff, source
        return None

    _fresh_market_revalidation_unreconciled = _fresh_market_revalidation

    def _fresh_market_revalidation(frozen, odds_events, checked_at):
        # Work on an ephemeral copy only. The frozen records and stored kickoff remain intact.
        adjusted = frozen.copy()
        adjustments = {}
        for position, (_, pick) in enumerate(adjusted.iterrows()):
            verification = _verified_kickoff_for_pick(pick)
            if not verification:
                continue
            verified_time, source = verification
            original = pick.get("kickoff_utc")
            # Do not repair an already-consistent kickoff.
            old_dt = pd.to_datetime(original, utc=True, errors="coerce")
            new_dt = pd.to_datetime(verified_time, utc=True)
            if pd.isna(old_dt) or abs((old_dt-new_dt).total_seconds()) <= 90*60:
                continue
            # Only reconcile if the odds feed itself independently agrees with the schedule.
            matching = [ev for ev in (odds_events if isinstance(odds_events, list) else [])
                        if isinstance(ev, dict)
                        and same_school_name(str(ev.get("home_team", "")), str(pick.get("home_team", "")))
                        and same_school_name(str(ev.get("away_team", "")), str(pick.get("away_team", "")))
                        and pd.notna(pd.to_datetime(ev.get("commence_time"), utc=True, errors="coerce"))
                        and abs((pd.to_datetime(ev.get("commence_time"), utc=True)-new_dt).total_seconds()) <= 90*60]
            if matching:
                adjusted.iloc[position, adjusted.columns.get_loc("kickoff_utc")] = verified_time
                adjustments[position] = (str(original), verified_time, source)
        result = _fresh_market_revalidation_unreconciled(adjusted, odds_events, checked_at)
        result["frozen_kickoff_utc"] = frozen["kickoff_utc"].to_numpy()
        result["schedule_reconciliation"] = "NOT_NEEDED_OR_UNVERIFIED"
        result["verified_kickoff_utc"] = None
        result["schedule_source"] = None
        for position, (original, verified, source) in adjustments.items():
            result.at[position, "kickoff_utc"] = original
            result.at[position, "verified_kickoff_utc"] = verified
            result.at[position, "schedule_source"] = source
            result.at[position, "schedule_reconciliation"] = "VERIFIED_WITH_SCHEDULE_AND_ODDS_EVENT"
            if result.at[position, "match_status"] == "MATCHED_ORIGINAL_BOOK":
                result.at[position, "coverage_detail"] += "; frozen kickoff differs from independently verified schedule; original preserved"
        return result

    # Research-only confidence rubric. This is an uncalibrated ordinal score,
    # NOT a probability of covering and NOT a recommended cash stake.
    def _jarz_weekly_confidence(coverage):
        import numpy as _np
        data = coverage.copy()
        output = []
        for _, r in data.iterrows():
            reasons = []
            status = str(r.get("match_status", ""))
            div = str(r.get("division_check_current", ""))
            inv = str(r.get("investigation_status", "")).upper()
            edge = pd.to_numeric(r.get("current_edge_points"), errors="coerce")
            original = pd.to_numeric(r.get("original_edge_points"), errors="coerce")
            odds = pd.to_numeric(r.get("current_american_odds"), errors="coerce")
            is_fbs = div.strip().upper() == "FBS VS FBS"
            valid = (status == "MATCHED_ORIGINAL_BOOK" and is_fbs and pd.notna(edge)
                     and str(r.get("frozen_record_match", "both")) == "both")
            if not valid:
                if status != "MATCHED_ORIGINAL_BOOK": reasons.append("No verified same-book spread")
                if not is_fbs: reasons.append("Division eligibility unresolved")
                if pd.isna(edge): reasons.append("Missing current edge")
                if str(r.get("frozen_record_match", "both")) != "both": reasons.append("Frozen record mismatch")
                output.append((1, "HOLD", 0, "; ".join(reasons), _np.nan))
                continue
            # 100-point *heuristic* rubric. These weights are not trained on outcomes.
            # The edge component is deliberately capped to avoid rewarding huge outliers.
            if edge <= 0: edge_pts = 0
            elif edge < 3: edge_pts = 5 * edge / 3
            elif edge < 5: edge_pts = 5 + 10 * (edge-3)/2
            elif edge < 7: edge_pts = 15 + 10 * (edge-5)/2
            elif edge < 10: edge_pts = 25 + 5 * (edge-7)/3
            else: edge_pts = 20; reasons.append("Extreme current edge: manual review")
            # Historical bands are exploratory, not a reliable estimated win rate.
            if 5 <= edge < 7: historical = 17
            elif 7 <= edge < 10: historical = 14
            elif 3 <= edge < 5: historical = 12
            elif edge >= 10: historical = 5
            else: historical = 6
            inv_pts = {"PASS":18,"CAUTION":12,"UNSTABLE":5,"UNKNOWN":8}.get(inv,8)
            if inv != "PASS": reasons.append("Investigation status: " + inv)
            quote_time = pd.to_datetime(r.get("quote_last_update_utc"), utc=True, errors="coerce")
            check_time = pd.to_datetime(r.get("checked_at_utc"), utc=True, errors="coerce")
            age = (check_time - quote_time).total_seconds()/3600 if pd.notna(check_time) and pd.notna(quote_time) else _np.nan
            market = 0
            if pd.notna(age):
                market = 12 if 0 <= age <= 1 else (8 if 0 <= age <= 6 else (4 if 0 <= age <= 24 else 0))
            else: reasons.append("Quote age unavailable")
            if pd.notna(odds) and -125 <= odds <= 125: market += 3
            if pd.notna(original) and edge < original - 2: reasons.append("Edge deteriorated by over 2 points")
            data_pts = 10
            total = max(0, min(100, edge_pts + historical + inv_pts + market + data_pts))
            # Conservative cap until confidence bands are calibrated on future outcomes.
            rating = min(7, max(1, int(total / 12)))
            if edge <= 0:
                rating = 1
                reasons.append("No positive current edge")
            elif edge < 3:
                rating = min(rating, 3)
                reasons.append("Current edge below 3 points")
            if edge >= 10: rating = min(rating, 5)
            if pd.notna(original) and edge < original - 2: rating = min(rating, 5)
            if pd.notna(age) and age > 6: rating = min(rating, 5)
            output.append((rating, "REVIEW" if reasons else "ELIGIBLE FOR REVIEW", total,
                           "; ".join(reasons) if reasons else "No automated warning", age))
        data[["experimental_confidence_1_to_10", "decision_status", "rubric_points_100",
              "confidence_explanation", "quote_age_hours"]] = pd.DataFrame(output, index=data.index)
        # Explicitly separate model-confidence score from financial stake.
        data["suggested_cash_units"] = _np.nan
        data["confidence_scale_validated"] = False
        return data

    # Automatic same-book coverage for the inline Final Projections table.
    # Runs on first page load and refreshes at most once every 15 minutes per session.
    # Never writes to prospective files, modifies model predictions, or changes grades.
    from pathlib import Path as _AutoCoveragePath
    import time as _jarz_time
    _auto_now = _jarz_time.time()
    _auto_last = st.session_state.get("jarz_auto_coverage_attempt_at", 0.0)
    _auto_ttl = 900  # seconds; avoid burning Odds API credits on every Streamlit rerun
    if _auto_now - _auto_last >= _auto_ttl:
        st.session_state["jarz_auto_coverage_attempt_at"] = _auto_now
        _auto_file = _AutoCoveragePath("prospective/graded_selections.csv")
        _auto_key = secret("ODDS_API_KEY")
        if not _auto_file.exists():
            st.session_state["jarz_auto_coverage_error"] = "Frozen selection file missing; live projections still work."
        elif not _auto_key:
            st.session_state["jarz_auto_coverage_error"] = "ODDS_API_KEY missing; fresh same-book fields unavailable."
        else:
            try:
                with st.spinner("Automatically refreshing verified sportsbook lines and confidence…"):
                    _auto_graded = pd.read_csv(_auto_file)
                    _auto_cohort_file = _AutoCoveragePath("prospective/investigation_cohort.csv")
                    _auto_cohort = pd.read_csv(_auto_cohort_file) if _auto_cohort_file.exists() else None
                    _auto_pending = _weekly_decision_board(_auto_graded, _auto_cohort)
                    _auto_v3 = _auto_graded.loc[_auto_graded["model_version"].astype(str).str.lower().eq("v3")].copy()
                    _auto_v3["captured_at_utc"] = pd.to_datetime(_auto_v3["captured_at_utc"], utc=True, errors="coerce")
                    _auto_v3 = (_auto_v3.sort_values("captured_at_utc", kind="stable")
                                .drop_duplicates(["season", "game_id", "model_version"], keep="first"))
                    _auto_pending["captured_at_utc"] = pd.to_datetime(_auto_pending["captured_at_utc"], utc=True, errors="coerce")
                    _auto_join = ["season", "game_id", "captured_at_utc"]
                    _auto_original = ["sportsbook_key", "sportsbook", "spread", "projected_home_margin", "model_version"]
                    _auto_pending = _auto_pending.drop(columns=[c for c in _auto_original if c in _auto_pending.columns])
                    _auto_pending = _auto_pending.merge(_auto_v3[_auto_join + _auto_original], on=_auto_join,
                                                        how="left", validate="one_to_one", indicator=True)
                    _auto_pending["frozen_record_match"] = _auto_pending.pop("_merge").astype(str)
                    # Reuse the existing four-hour odds cache; do not spend an extra
                    # API request every 15 minutes just to populate the inline board.
                    _auto_events, _auto_remaining = odds_data(_auto_key, "spreads")
                    _auto_checked = datetime.now(timezone.utc).isoformat()
                    _auto_result = _fresh_market_revalidation(_auto_pending, _auto_events, _auto_checked)
                    _auto_result["frozen_record_match"] = _auto_pending["frozen_record_match"].to_numpy()
                    _auto_result.loc[_auto_result["frozen_record_match"].ne("both"), "match_status"] = "FROZEN_RECORD_JOIN_FAILED"
                    for _auto_col in ["review_priority", "division_check_current", "investigation_status", "review_notes", "edge_band"]:
                        if _auto_col in _auto_pending.columns:
                            _auto_result[_auto_col] = _auto_pending[_auto_col].to_numpy()
                    if len(_auto_result) != len(_auto_pending):
                        raise ValueError("Auto coverage row-count invariant failed")
                    st.session_state["jarz_latest_confidence_coverage"] = _jarz_weekly_confidence(_auto_result)
                    st.session_state["jarz_latest_confidence_checked"] = _auto_checked
                    st.session_state.pop("jarz_auto_coverage_error", None)
                st.rerun()  # Populate inline columns at the top on the next pass
            except Exception as _auto_exc:
                st.session_state["jarz_auto_coverage_error"] = str(_auto_exc)

    st.divider()
    st.subheader("Research · Complete market coverage for frozen V3")
    if st.session_state.get("jarz_auto_coverage_error"):
        st.warning("Automatic market refresh unavailable: " + str(st.session_state["jarz_auto_coverage_error"]))
    elif st.session_state.get("jarz_latest_confidence_checked"):
        st.caption("Automatic market check: " + str(st.session_state["jarz_latest_confidence_checked"]) + " · refreshes at most every 15 minutes per session; manual refresh remains optional.")
    st.caption("Read-only: every pending frozen V3 selection receives a market-coverage status. No original pick, line, grade or model parameter is modified. A model edge is not a guarantee of profitability.")
    with st.expander("Fetch sportsbook quotes, diagnose missing markets, and export all pending V3 picks", expanded=False):
        st.info("Requires ODDS_API_KEY in Streamlit secrets and prospective/graded_selections.csv. The Odds API may not offer every matchup or sportsbook at the time of the request.")
        if st.button("Run complete V3 market coverage", key="fresh_v3_coverage"):
            try:
                from pathlib import Path as _CoveragePath
                _graded_path = _CoveragePath("prospective/graded_selections.csv")
                if not _graded_path.exists():
                    st.error("Missing prospective/graded_selections.csv")
                elif not secret("ODDS_API_KEY"):
                    st.error("ODDS_API_KEY is not configured in Streamlit secrets")
                else:
                    _graded = pd.read_csv(_graded_path)
                    _cohort_path = _CoveragePath("prospective/investigation_cohort.csv")
                    _cohort = pd.read_csv(_cohort_path) if _cohort_path.exists() else None
                    _pending = _weekly_decision_board(_graded, _cohort)
                    # CRITICAL: select V3 *before* deduplicating. V1/V2/V3 can share game_id and captured_at_utc.
                    _v3 = _graded.loc[_graded["model_version"].astype(str).str.lower().eq("v3")].copy()
                    _v3["captured_at_utc"] = pd.to_datetime(_v3["captured_at_utc"], utc=True, errors="coerce")
                    _v3 = (_v3.sort_values("captured_at_utc", kind="stable")
                             .drop_duplicates(["season", "game_id", "model_version"], keep="first"))
                    _pending["captured_at_utc"] = pd.to_datetime(_pending["captured_at_utc"], utc=True, errors="coerce")
                    _join = ["season", "game_id", "captured_at_utc"]
                    _original = ["sportsbook_key", "sportsbook", "spread", "projected_home_margin", "model_version"]
                    _pending = _pending.drop(columns=[c for c in _original if c in _pending.columns])
                    _pending = _pending.merge(_v3[_join+_original], on=_join, how="left", validate="one_to_one", indicator=True)
                    # No silent row loss: a missing frozen match remains visible with a diagnostic status.
                    _pending["frozen_record_match"] = _pending.pop("_merge").astype(str)
                    _raw, _headers = api_get(ODDS_URL, params={"apiKey":secret("ODDS_API_KEY"),
                        "regions":"us", "markets":"spreads", "oddsFormat":"american", "dateFormat":"iso"})
                    _checked = datetime.now(timezone.utc).isoformat()
                    _result = _fresh_market_revalidation(_pending, _raw, _checked)
                    _result["frozen_record_match"] = _pending["frozen_record_match"].to_numpy()
                    _result.loc[_result["frozen_record_match"].ne("both"), "match_status"] = "FROZEN_RECORD_JOIN_FAILED"
                    for c in ["review_priority", "division_check_current", "investigation_status", "review_notes", "edge_band"]:
                        if c in _pending.columns:
                            _result[c] = _pending[c].to_numpy()
                    if len(_result) != len(_pending):
                        raise ValueError("Coverage invariant failed: exported row count differs from pending V3 count")
                    _matched = _result["match_status"].eq("MATCHED_ORIGINAL_BOOK")
                    a,b,c = st.columns(3)
                    a.metric("All pending frozen V3 picks", len(_result))
                    b.metric("Verified same-book spreads", int(_matched.sum()))
                    c.metric("Unmatched / requiring review", int((~_matched).sum()))
                    st.caption(f"Fetched at {_checked} · API credits remaining: {_headers.get('x-requests-remaining','unknown')} · No unmatched pick is treated as zero edge.")
                    st.markdown("**Coverage status for every pending selection**")
                    st.dataframe(_result["match_status"].value_counts(dropna=False).rename_axis("Status").reset_index(name="Picks"), hide_index=True, use_container_width=True)
                    st.markdown("**Complete coverage and decision review queue**")
                    st.dataframe(_result, hide_index=True, use_container_width=True)
                    st.download_button("Download COMPLETE V3 market coverage CSV", _result.to_csv(index=False),
                        file_name="JarzCFB_complete_market_coverage.csv", mime="text/csv", key="download_complete_v3_coverage")
                    st.divider()
                    st.markdown("### Weekly Betting Decision Board · experimental 1–10 confidence")
                    st.caption("Scores are provisional research ratings, not cover probabilities or cash staking instructions. 10/10 is never a lock. Current calibration caps ratings at 7/10 until future games validate higher tiers.")
                    _rated = _jarz_weekly_confidence(_result)
                    st.session_state["jarz_latest_confidence_coverage"] = _rated.copy()
                    st.session_state["jarz_latest_confidence_checked"] = _checked
                    _ranked = _rated.sort_values(["decision_status", "experimental_confidence_1_to_10", "current_edge_points"],
                                                 ascending=[True, False, False], na_position="last")
                    _eligible = _rated[_rated["decision_status"].ne("HOLD")].sort_values(
                        ["experimental_confidence_1_to_10", "current_edge_points"], ascending=False)
                    d1,d2,d3 = st.columns(3)
                    d1.metric("Eligible for review", len(_eligible))
                    d2.metric("Division / market holds", int((_rated["decision_status"] == "HOLD").sum()))
                    d3.metric("Highest provisional rating", f"{int(_eligible['experimental_confidence_1_to_10'].max())}/10" if len(_eligible) else "N/A")
                    _cols = ["selection", "home_team", "away_team", "current_sportsbook", "current_spread",
                             "current_american_odds", "current_edge_points", "experimental_confidence_1_to_10",
                             "decision_status", "investigation_status", "confidence_explanation"]
                    st.markdown("**Top 10 research candidates (not automatic wagers)**")
                    st.dataframe(_eligible[_cols].head(10), hide_index=True, use_container_width=True)
                    st.markdown("**All picks — including holds and warnings**")
                    st.dataframe(_ranked[_cols], hide_index=True, use_container_width=True)
                    st.download_button("Download WEEKLY confidence decision board CSV", _rated.to_csv(index=False),
                        file_name="JarzCFB_weekly_confidence_board.csv", mime="text/csv", key="download_v3_confidence_board")
                    st.info("Official grading remains flat 1 unit per frozen selection. The experimental 1–10 rating is not a recommended wager size. Recheck injuries, market prices, and eligibility before any decision.")
                    st.warning("Research only. Verify current book availability, injuries and eligibility before wagering. An unmatched pick is not a losing or zero-edge pick.")
                    st.rerun()  # Show refreshed confidence data inside the Final projections section
            except Exception as _coverage_exc:
                st.error(f"Complete market coverage failed: {_coverage_exc}")
