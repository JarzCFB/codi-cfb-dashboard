"""Create a research-only, prioritized missing-feature worklist from frozen V3 data.

Never guesses player availability, weather, rest, or travel values.
"""
import csv
from pathlib import Path
from v4_evidence_triage import triage_rows, triage_csv

BASELINE = Path("v4/recovered_v3_baseline.csv")
EVIDENCE = Path("v4/verified_feature_rows.csv")
OUTPUT = Path("reports/v4_missing_evidence_worklist.csv")

def _read(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))

def generate(baseline_path=BASELINE, evidence_path=EVIDENCE, output_path=OUTPUT):
    baseline_path = Path(baseline_path)
    if not baseline_path.exists():
        raise FileNotFoundError("Frozen baseline must be recovered first")
    worklist = triage_rows(_read(baseline_path), _read(Path(evidence_path)))
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(triage_csv(worklist), encoding="utf-8")
    return {
        "games": len(worklist),
        "settled_games": sum(r["priority"] == "settled" for r in worklist),
        "missing_feature_cells": sum(r["missing_feature_count"] for r in worklist),
        "output": str(destination),
        "warning": "Worklist is NOT authenticated evidence and cannot train V4.",
    }

if __name__ == "__main__":
    print(generate())
