"""Recover *selected-only* frozen V3 baseline, without altering source ledgers.

This dataset is NOT an all-FBS universe and cannot alone validate or train V4.
"""
import csv
from pathlib import Path
from v4_evidence_audit import _time

SELECTIONS = Path("prospective/selections.csv")
GRADED = Path("prospective/graded_selections.csv")
OUTPUT = Path("v4/recovered_v3_baseline.csv")
FIELDS = ("game_id", "season", "kickoff_utc", "captured_at_utc",
          "source_grading_status", "v3_home_margin", "actual_home_margin")

def _rows(path):
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))

def recover(selections, graded):
    frozen = {}
    for row in selections:
        if str(row.get("model_version", "")).strip().lower() != "v3":
            continue
        key = str(row["game_id"])
        if not key.strip():
            raise ValueError("V3 game ID missing")
        if key in frozen:
            raise ValueError("multiple V3 selections for game " + key)
        if _time(row["captured_at_utc"]) >= _time(row["kickoff_utc"]):
            raise ValueError("V3 selection captured after kickoff")
        frozen[key] = row
    grades = {}
    for row in graded:
        if str(row.get("model_version", "")).strip().lower() != "v3":
            continue
        key = str(row["game_id"])
        if key in grades:
            raise ValueError("duplicate V3 grade for game " + key)
        grades[key] = row
    if set(grades) - set(frozen):
        raise ValueError("graded V3 game missing frozen selection")
    result = []
    for gid, frozen_row in sorted(frozen.items()):
        grade = grades.get(gid)
        if grade and any(str(grade.get(k)) != str(frozen_row.get(k))
                         for k in ("game_id", "season", "kickoff_utc",
                                   "captured_at_utc", "projected_home_margin")):
            raise ValueError("graded V3 data differs from frozen selection for " + gid)
        settled = bool(grade and grade.get("grading_status") == "settled")
        actual = str(grade.get("actual_home_margin", "")).strip() if settled else ""
        if settled and not actual:
            raise ValueError("settled V3 grade missing actual margin")
        if settled:
            from math import isfinite
            if not isfinite(float(actual)):
                raise ValueError("settled V3 grade has nonfinite actual margin")
        result.append({
            "game_id": gid, "season": frozen_row["season"],
            "kickoff_utc": frozen_row["kickoff_utc"],
            "captured_at_utc": frozen_row["captured_at_utc"],
            "source_grading_status": "settled" if settled else "pending",
            "v3_home_margin": frozen_row["projected_home_margin"],
            "actual_home_margin": actual})
    return result

def main():
    rows = recover(_rows(SELECTIONS), _rows(GRADED))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Recovered {len(rows)} frozen V3 selected games; "
          f"{sum(r['source_grading_status'] == 'settled' for r in rows)} settled.")
    print("Selection-biased V3 picks ONLY. Do not use as all-FBS training sample.")

if __name__ == "__main__":
    main()
