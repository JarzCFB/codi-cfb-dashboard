# What historical data is actually available?

Run from the repository checkout:

```bash
python v4_historical_gap.py --output v4_historical_gap.json
```

This inspects two **existing** datasets:

- `backtests/v1_v2_game_results.csv`: 2024–25 historical games with
  V1 and V2 walk-forward projections and final margins.
- `prospective/graded_selections.csv`: official frozen V3 selections
  currently recorded for 2026.

The data is **not paired V3 versus V4**. Do not silently substitute a
recomputed 25%/75% blend for historical official V3 predictions, do not
pretend postgame information was available pregame, and do not fill
unknown player availability with zeros.

The JSON gives accurate coverage, observed historical V1/V2 MAE and
specific remaining requirements. No training or betting deployment
occurs. The historical V1/V2 sample is not automatically a verified
V4 feature dataset.
