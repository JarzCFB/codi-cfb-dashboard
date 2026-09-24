# Codi's CFB dashboard — free online deployment

## What you get
- A Streamlit web dashboard for college football spreads across supported US bookmakers.
- Odds refresh on page visits after a 4-hour cache; team results refresh daily. Manual Refresh Now is available and consumes API credits.
- Independent **illustrative** team ratings from completed season game scores, with adjustable home field and uncertainty. It calculates break-even probability, estimated cover probability and expected ROI for each quoted spread.
- Best available quoted price per team, CSV exports and a personal bet journal.

**Important:** It is a research prototype, not a proven profitable predictive model. It does not automatically identify winning bets, and early-season ratings can be unstable. Ratings for unmatched team names are excluded. A free plan cannot guarantee always-on background updates or a permanent hosted database.

## 1. Get two free API keys
1. The Odds API: https://the-odds-api.com/ — sign up for the free plan (advertised 500 credits/month as of Sep 2026). It provides supported US bookmaker spreads.
2. CollegeFootballData: https://collegefootballdata.com/key — request the free key (advertised 1,000 calls/month). It supplies completed game scores for independent ratings.

**Never put API keys in GitHub files, messages or public browser code.**

## 2. Put these files on GitHub
1. Sign in at https://github.com/ and create a **private** repository called `codi-cfb-dashboard`.
2. Upload `app.py`, `requirements.txt`, and `.gitignore` from this ZIP to the root of the repository. `secrets.toml.example` is documentation only; do NOT upload any real secrets.
3. Sign in at https://share.streamlit.io/ with GitHub and select **Create app**, then select the repository, branch `main`, and entry point `app.py`.
4. In **Advanced settings → Secrets**, enter the following, substituting your own keys:

```toml
ODDS_API_KEY = "YOUR_ODDS_KEY"
CFBD_API_KEY = "YOUR_CFBD_KEY"
```

5. Deploy. For an existing app, set secrets under app settings and reboot.

## 3. Weekly use
- Open the dashboard. After four hours the next visit refreshes odds; game results refresh daily. Refresh Now bypasses both caches and consumes more API credits.
- Compare model probability to break-even probability, and check whether your exact sportsbook is included. If not, compare your pasted line manually to the displayed market, or export the table.
- Enter any actual bets into the journal. Download `my_cfb_bet_journal.csv` after every update, and upload it next time. The free app's temporary filesystem is NOT a durable database.
- Export odds snapshots if you want a history of market prices; historical API odds are not included in the free plan.

## Free-tier limits
- The Odds API free tier advertises 500 credits/month, but credit cost varies by region and markets. This app requests **US spreads only** to conserve credits. Refreshing every 4 hours during active use should usually be within the quota, but check the displayed remaining balance.
- CFBD free tier advertises 1,000 calls/month; this app calls `/games` at most once per day per season during normal operation.
- Cloud app sleeps when idle; refresh-on-visit is not a guaranteed background scheduler.
- CFBD team aliases may require additions to `ALIASES` in `app.py` for a few schools.
- Keep private bet records in your downloaded journal. For true cross-device automatic history, add a hosted database later.

## Formulas
For team with spread `s`, model team margin `m` and assumed game-margin standard deviation `σ`:
`P(cover) = Φ((m+s)/σ)`. A spread push is approximated as continuous, which is imperfect around key numbers (3, 7, 10). Expected ROI = `P(cover) × net_profit_per_$1 − (1 − P(cover))`. Odds-derived break-even probability uses the quoted American price. Ratings use regularized least-squares margin-of-victory estimates based on completed current-season games, adjusted for home field. These are not calibrated or validated probabilities.
