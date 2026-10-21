"""Create a research-only, prioritized missing-feature worklist from frozen V3 data.

Never guesses player availability, weather, rest, or travel values.
"""
import csv
from pathlib import Path
from v4_evidence_triage import triage_rows, triage_csv
from v4_evidence_audit import audit_evidence

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
    baseline, evidence = _read(baseline_path), _read(Path(evidence_path))
    # Do not mark invalid, post-capture, or duplicate claims as present.
    audit = audit_evidence(baseline, evidence)
    worklist = triage_rows(baseline, evidence)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(triage_csv(worklist), encoding="utf-8")
    return {
        "games": len(worklist),
        "settled_games": sum(r["priority"] == "settled" for r in worklist),
        "source_authenticity_verified": False,
        "submitted_claims": len(evidence),
        "complete_settled_games_with_claims": audit["complete_settled_games"],
        "missing_feature_cells": sum(r["missing_feature_count"] for r in worklist),
        "output": str(destination),
        "warning": "Present means submitted timestamp/URL claims, NOT authenticated evidence. Cannot train V4.",
    }

if __name__ == "__main__":
    print(generate())
