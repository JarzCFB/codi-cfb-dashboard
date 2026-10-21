# V4 completion and release checklist (research only)

## Current state
The V4 situational review and ridge adjustment research code exist. No authenticated
multi-season feature dataset or independent forward V4 betting record has been established.
**V3 remains the official betting model.** Do not promote V4 from a green CI run.

## Required data
1. Recover an independently frozen, pregame V3 baseline covering all eligible FBS games,
   not just winning bets. Each row needs a stable game ID, season, kickoff and capture
   timestamps, frozen V3 home margin, settled actual home margin, and grading status.
   Do not substitute postgame V3 recalculations for original pregame predictions.
2. Record six V4 features per game using the schema in `v4_evidence_audit.py`:
   `qb_out_diff`, `key_players_out_diff`, `rest_days_diff`,
   `travel_miles_diff`, `wind_mph`, and `neutral_site`.
   Each observation needs a source URL and publication/observation timestamps
   **no later than its original V3 capture**.
3. Independently authenticate sources, timestamp claims, team and player identity,
   and feature definitions. A URL is not authentication. Missing injury reports
   mean unknown, not healthy. Do not backfill from retrospective articles.
4. Audit feature coverage and selection bias. Record who reviewed each source,
   when, and how publication timestamps were independently verified.
5. Require >=200 complete settled training games from earlier seasons and >=100
   complete settled games from a later season. Run chronological held-out
   MAE/RMSE comparisons, paired error and stability diagnostics.
6. Evaluate market-relative betting performance with authentic pregame odds,
   vigorish, missing-line rules and identical selection eligibility for V3/V4.
   Do not confuse spread prediction MAE with betting ROI.
7. Shadow-run V4 prospectively before kickoff with immutable inputs and outputs,
   no lookahead, no automated official bets, and an independent review of results.
8. Explicit human approval is required before any official V3 replacement.

## Commands
```bash
python -m unittest discover -v
python -m unittest discover -s tests -v
python v4_research_status.py
```

The generated `reports/v4_research_status.json` is an audit summary, not a
certification of feature truth. CSV files named `verified_feature_rows.csv`
are still unverified until an independent provenance review is completed.

## Fail-closed interpretation
- Missing files: research cannot be calibrated.
- Evidence after original capture: reject.
- Complete rows but unverified sources: report coverage, do not fit.
- Good held-out MAE alone: not sufficient for live betting deployment.
- Green tests: software functioning, **not** proof of profitable betting.

## Historical collection starter
Run `python v4_data_templates.py` to create blank CSV templates in
`v4/templates/`. These are headers only, not historical evidence. Populate
`v4/recovered_v3_baseline.csv` from original pregame capture records and
`v4/verified_feature_rows.csv` from individually sourced, timestamped
observations. A generated blank template is never evidence of a verified
feature, and no missing feature should be entered as zero.

## Frozen V3 baseline recovery (implemented)
Run `python v4_recover_frozen_baseline.py` to extract a *selected-only*
point-in-time baseline from `prospective/selections.csv` and
`prospective/graded_selections.csv`. It writes
`v4/recovered_v3_baseline.csv` without changing either original ledger.
The CI workflow runs recovery before the V4 readiness report and publishes
the resulting CSV as a downloadable artifact. **Do not treat this dataset
as all-FBS** or fill the remaining 2024–2025 seasons with postgame projections.
The separate all-game historical collection and independent source
authentication gates remain open.

## Prioritized evidence collection worklist
After baseline recovery, run `python v4_evidence_worklist.py`.
This creates `reports/v4_missing_evidence_worklist.csv` with each game's
original capture cutoff, missing feature names, and settled-first priority.
The validation workflow includes this CSV in the downloadable
`v4-research-readiness` artifact. This is a work queue, not a list of
verified facts. Review each missing feature against source publications
that demonstrably existed **before** its original capture.

The recovered baseline now carries original `home_team` and `away_team` values, so the worklist can be researched by matchup. These names are copied from frozen selections, never reconstructed from current schedules.

## Automated fail-closed baseline checks

The GitHub Actions research workflow now fails when frozen V3 recovery produces zero games or the offline V4 status reports `Evidence audit rejected data`. The separate evidence worklist treats valid-looking pre-capture source rows as **submitted claims**, not independently authenticated facts; feature coverage must never be interpreted as verified injury, weather, or player status. The workflow's success alone does not constitute a V4 performance or release approval.
