"""Research-only V1/V2 combination validation on archived weekly predictions.

Candidate weights are fitted on 2024 only, evaluated once on 2025.
This does NOT recreate official calibrated V3 or evaluate V4 injuries.
"""
import argparse
import csv
import json
from pathlib import Path
from math import isfinite

ROOT = Path(__file__).resolve().parent
WEIGHTS = tuple(i / 20 for i in range(21))


def _mae(rows, weight):
    return sum(abs(r[0] - ((1 - weight) * r[1] + weight * r[2])) for r in rows) / len(rows)


def validate_ensemble(rows):
    data, seen = [], set()
    for row in rows:
        key = (int(row["season"]), str(row["game_id"]))
        if key in seen:
            raise ValueError("duplicate historical game")
        seen.add(key)
        values = tuple(float(row[k]) for k in ("actual_home_margin", "v1_home_margin", "v2_home_margin"))
        if not all(isfinite(x) for x in values):
            raise ValueError("nonfinite prediction or outcome")
        data.append((key[0], values))
    train = [values for year, values in data if year == 2024]
    test = [values for year, values in data if year == 2025]
    if len(train) < 100 or len(test) < 100 or len(data) != len(train) + len(test):
        raise ValueError("requires at least 100 games each in 2024 and 2025 and no other years")
    # Fixed grid, deterministic tie-break toward the current protected 75% V2 weight.
    weight = min(WEIGHTS, key=lambda w: (_mae(train, w), abs(w - .75), w))
    result = {
        "status": "RESEARCH_ONLY",
        "training_season": 2024,
        "holdout_season": 2025,
        "training_games": len(train),
        "holdout_games": len(test),
        "selected_v2_weight": weight,
        "selected_v1_weight": 1 - weight,
        "training_mae_selected": round(_mae(train, weight), 4),
        "holdout_mae_v1": round(_mae(test, 0), 4),
        "holdout_mae_v2": round(_mae(test, 1), 4),
        "holdout_mae_fixed_25v1_75v2": round(_mae(test, .75), 4),
        "holdout_mae_selected": round(_mae(test, weight), 4),
        "selected_improves_fixed_blend": _mae(test, weight) < _mae(test, .75),
        "official_v3_equivalent": False,
        "v4_evaluated": False,
        "release_ready": False,
        "limitations": "Archived V1/V2 predictions only. Fixed 25/75 blend excludes V3 calibration; historical tuning provenance is unverified; no market odds, ROI, verified injury evidence or prospective validation. Do not change V3.",
    }
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Research-only historical V1/V2 ensemble test")
    parser.add_argument("--source", type=Path, default=ROOT / "backtests/v1_v2_game_results.csv")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    with args.source.open(encoding="utf-8-sig", newline="") as stream:
        report = validate_ensemble(csv.DictReader(stream))
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
