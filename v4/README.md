# JarzCFB V4 — situational intelligence

V4 is an **independent research panel**, not a replacement for V3. Official selections, locked V3 margins, and grading are unchanged.

## Available on the V4 branch
- Upcoming-matchup panel with evidence verification status and source URLs.
- Select a matchup to fetch current-season CFBD player statistics for **both teams**, cached for six hours.
- Display metric-specific statistical leaders (passing, rushing, receiving, defensive and kicking when available). This is a **production list**, not a roster depth chart, starter confirmation, injury status, or player impact rating.
- Optional session-only CSV upload and downloadable template in the dashboard, or a checked-in evidence ledger in `v4/evidence.csv`, with columns `game_id,team,player,position,factor,status,source,observed_at_utc,notes,impact_points`.
- Factors: quarterback, star_player, injury, stadium, travel, rest, weather, rivalry, big_game. Evidence must have a matching game ID, exact matchup team, source URL, and timestamp known before the game.
- Missing injury information is **unknown**, not a declaration that a player is healthy.

## Not yet production-ready
- No verified automated college-football injury / availability feed is connected. CFBD season statistics do not provide this.
- No calibrated V4 point adjustments, betting edges, or historical walk-forward validation.
- Automated Streamlit startup smoke test (without credentials) and isolated V4 unit tests pass in GitHub Actions. **Live deployed-app testing with API keys has not been completed.**
- This PR can be deployed as a clearly labeled **research preview** after an authorized merge and live verification; it must not be presented as a finished predictive V4 model.

## Safety
`impact_points` is reserved for future independently calibrated research and is **not applied**. Never backfill future-known information into historical game predictions. Preserve V3 and prospective selections unchanged.

## How to use the V4 preview
1. Open the V4 evidence input expander and download the CSV template.
2. Use a game ID from the final projections, a matching team, an actual HTTPS source URL and an observed-at UTC timestamp that predates kickoff.
3. Upload the CSV. The evidence is displayed only in the research panel; source links are **not** independently verified and the upload is not a live feed.
4. Select a matchup to view season-to-date CFBD statistical leaders for both teams. Statistical leadership does not establish starter status or injury availability.

## Release gates
- CI must pass on the PR head, including `app.py` compilation and V4 unit tests.
- Streamlit preview must load the expander, template, upload and player stats with the configured CFBD key.
- A reliable, licensed, timestamped injury/availability provider and source-review policy must be established before claiming automatic injury tracking.
- Historical, point-in-time datasets must be assembled; situational adjustment coefficients must be fit and validated on later held-out seasons before displaying any V4 betting projections.
- Locked V3 prospective selections and grading must remain unchanged.
