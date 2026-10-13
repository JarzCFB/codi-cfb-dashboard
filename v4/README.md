# JarzCFB V4 — situational intelligence

V4 is an **independent research panel**, not a replacement for V3. Official selections, locked V3 margins, and grading are unchanged.

## Available on the V4 branch
- Upcoming-matchup panel with evidence verification status and source URLs.
- Select a matchup to fetch current-season CFBD player statistics for **both teams**, cached for six hours.
- Display metric-specific statistical leaders (passing, rushing, receiving, defensive and kicking when available). This is a **production list**, not a roster depth chart, starter confirmation, injury status, or player impact rating.
- Optional evidence ledger in `v4/evidence.csv` with columns `game_id,team,player,position,factor,status,source,observed_at_utc,notes,impact_points`.
- Factors: quarterback, star_player, injury, stadium, travel, rest, weather, rivalry, big_game. Evidence must have a matching game ID, exact matchup team, source URL, and timestamp known before the game.
- Missing injury information is **unknown**, not a declaration that a player is healthy.

## Not yet production-ready
- No verified automated college-football injury / availability feed is connected. CFBD season statistics do not provide this.
- No calibrated V4 point adjustments, betting edges, or historical walk-forward validation.
- No live deployed-app smoke test or confirmed passing CI checks for this branch.
- Do not merge this PR as a finished V4 model until the above are addressed and CI passes.

## Safety
`impact_points` is reserved for future independently calibrated research and is **not applied**. Never backfill future-known information into historical game predictions. Preserve V3 and prospective selections unchanged.
