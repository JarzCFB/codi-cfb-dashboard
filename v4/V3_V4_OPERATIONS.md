# V3 official + V4 advisory: consolidated operating procedure

**Official betting model:** V3 (unchanged). **V4:** research-only, never an automatic pick, margin, or staking override.

## Run it

1. Open GitHub > Actions > **V4 research safety tests** > **Run workflow**.
2. Open the successful run and download the `v4-research-evidence-gap` artifact.
3. Read `v3_v4_status.json` first, then `v4_upcoming_pregame_review.json` for approaching kickoffs, `v4_v3_advisory.json` for missing information, and `v4_missing_evidence.csv` for the collection queue.
4. Review source reports manually before kickoff. Do not treat missing injury data as confirmation a player is healthy.

## Optional evidence claims

A researcher may add `v4/evidence_claims.csv` in a reviewed PR with columns:

`game_id,feature,value,source_url,published_at_utc,observed_at_utc`

Allowed features: `qb_out_diff`, `key_players_out_diff`, `rest_days_diff`, `travel_miles_diff`, `wind_mph`, `neutral_site`. Both timestamps must be timezone-aware, and the publication and observation must precede the archived V3 capture. Use primary or reliably archived sources; verify that publication timestamps are genuine. **CSV URLs and timestamps are claims, not independent verification.** Audit rejection fails the workflow rather than silently assigning zeros. Do not include personal information or access tokens.

## What would justify a change

A V4-derived adjustment or bet-filter must be specified before outcomes are known, backed by authenticated pregame sources, tested against V3 on truly later games with the same available odds, and reviewed for selection bias, calibration, drawdown and net returns. The archived 2024–25 V1/V2 test cannot validate V4's six features or establish that a new filter improves returns. Until those conditions are met, V3 alone is official and V4 is an informational review aid.

This is the **last planned engineering integration PR**. Additional PRs should only be opened to fix a demonstrated defect or incorporate newly obtained verified evidence—not to increment PR numbers.
