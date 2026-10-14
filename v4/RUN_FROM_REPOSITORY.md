# Run the V4 baseline audit from the existing GitHub data

The repo already contains `prospective/graded_selections.csv` with
mixed V1/V2/V3 frozen selections. No Streamlit export is necessary.

```bash
python v4_repo_baseline.py --output-dir v4_audit_output
```

The command filters to V3 **before** enforcing one record per game,
validates that every snapshot preceded kickoff, and outputs:

- `v4_recovered_v3_baseline.csv` — read-only research copy
- `v4_missing_evidence.csv` — six missing-feature tasks per game
- `v4_source_review_queue.csv` — empty until claims are supplied
- `v4_repo_audit_summary.json` — game counts and closed readiness gates

It never changes `prospective/` or V3 grading. These are selected
prospective V3 plays, not a representative all-FBS training universe.
Historical data currently stored in this file may cover only 2026;
multi-season model calibration remains blocked until authentic earlier
seasons and independent point-in-time feature evidence exist.

Run `python -m unittest test_v4_repo_baseline`.
