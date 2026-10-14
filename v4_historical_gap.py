"""Compare available historical backtests with the official V3 prospective record.

This is a coverage report, not a synthetic V3 backtest or V4 evaluation.
"""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _rows(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def historical_gap_report(backtest_rows, graded_rows):
    historical = list(backtest_rows)
    graded = list(graded_rows)
    seen = set()
    seasons = Counter()
    v1_error = v2_error = 0.0
    for r in historical:
        key = (int(r["season"]), str(r["game_id"]))
        if key in seen:
            raise ValueError("duplicate historical game")
        seen.add(key)
        actual = float(r["actual_home_margin"])
        v1 = float(r["v1_home_margin"])
        v2 = float(r["v2_home_margin"])
        from math import isfinite
        if not all(isfinite(v) for v in (actual, v1, v2)):
            raise ValueError("nonfinite historical margin")
        seasons[key[0]] += 1
        v1_error += abs(actual - v1)
        v2_error += abs(actual - v2)
    if not historical:
        raise ValueError("historical backtest empty")
    v3 = [r for r in graded if str(r.get("model_version", "")).strip().lower() == "v3"]
    if not v3:
        raise ValueError("no prospective V3 selections")
    v3_seasons = Counter()
    v3_settled = Counter()
    ids = set()
    for r in v3:
        key = str(r["game_id"])
        if key in ids:
            raise ValueError("duplicate V3 selection")
        ids.add(key)
        season = int(r["season"])
        v3_seasons[season] += 1
        if r["grading_status"] == "settled":
            v3_settled[season] += 1
    return {
        "status": "RESEARCH_ONLY",
        "historical_v1_v2": {
            "games": len(historical),
            "games_by_season": dict(sorted(seasons.items())),
            "v1_mae": round(v1_error / len(historical), 4),
            "v2_mae": round(v2_error / len(historical), 4),
        },
        "prospective_v3": {
            "games": len(v3),
            "games_by_season": dict(sorted(v3_seasons.items())),
            "settled_by_season": dict(sorted(v3_settled.items())),
        },
        "historical_official_v3_predictions_available": False,
        "historical_v4_verified_features_available": False,
        "v4_vs_v3_comparison_possible": False,
        "release_ready": False,
        "next_required": [
            "Recover genuine historical V3 pregame predictions for multiple seasons; do not reconstruct them with invented calibration.",
            "Acquire six historical V4 features with independently authenticated pre-capture timestamps.",
            "Use a season-separated holdout to compare genuine paired V3 and V4 predictions.",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="V4 historical data gap report")
    parser.add_argument("--backtest", type=Path, default=ROOT / "backtests/v1_v2_game_results.csv")
    parser.add_argument("--graded", type=Path, default=ROOT / "prospective/graded_selections.csv")
    parser.add_argument("--output", type=Path, help="Optional JSON output path")
    args = parser.parse_args(argv)
    report = historical_gap_report(_rows(args.backtest), _rows(args.graded))
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
