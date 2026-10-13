# V4 research calibration: data contract and release gate

The V4 calibration panel accepts a **historical CSV** containing one record per game:
`game_id,season,kickoff_utc,captured_at_utc,actual_home_margin,v3_home_margin,qb_out_diff,key_players_out_diff,rest_days_diff,travel_miles_diff,wind_mph,neutral_site`.

- `actual_home_margin`: home final points minus away final points, only for historical games.
- `v3_home_margin`: archived V3 pregame projection as originally published. Never reconstruct it using later ratings.
- `qb_out_diff`: verified **away QB out minus home QB out**, in [-1,1]. Only 1/0/-1 when both sides have independently checked statuses. Unknown is **blank**, not 0.
- `key_players_out_diff`: verified away key absences minus home key absences, in [-11,11]. Define "key" consistently *before* examining outcomes. Unknown is blank.
- `rest_days_diff`: home days since prior game minus away days since prior game, from scheduled pregame records.
- `travel_miles_diff`: away travel distance minus home travel distance, using one documented reproducible convention.
- `wind_mph`: archived pregame forecast for game location and capture time; **not** observed game weather.
- `neutral_site`: 1 for a verified neutral-site designation, else 0.

Use UTC timestamps with timezone, with `captured_at_utc` strictly before kickoff. Every feature must have been available at capture time, with original source URL, publication time, and evidence preserved in an auditable **separate provenance ledger**. The app cannot independently verify source authenticity or publication timing.

The current implementation uses ridge-regularized V3 residuals, training only on seasons preceding the latest season and evaluating the latest season once. It is an **experimental candidate**, not a released model. A single holdout comparison cannot establish a betting edge. Do not use the results to place bets.

## Required before activation

1. Gather sufficient *real* historical rows with contemporaneous archived V3 predictions and independently sourced pregame situational facts. Reject unknowns; document selection bias and missing coverage.
2. Freeze the feature definitions, preprocessing, regularization and evaluation plan before opening the holdout; use multiple rolling-origin holdouts and compare V3/V4 MAE and calibrated against-the-spread performance with uncertainty intervals.
3. Validate ingestion against dated official conference/team reports and archived forecasts; maintain a reproducible provenance ledger. Conference landing pages alone are not injury evidence.
4. Run prospective, timestamped shadow predictions for a meaningful sample, without changing official V3 picks or grading; verify performance and reliability.
5. Review and explicitly approve a separate production deployment. No current V4 calibration weights or real-data performance are claimed.

**Safety rule:** Missing or unverified status is unknown, not healthy. This module never writes official picks or frozen V3 history.
