"""Offline V4 readiness snapshot; read-only, never trains on unverified evidence."""
import csv
import json
from pathlib import Path
from v4_spread_research import evaluate
from v4_evidence_audit import FEATURES

BASELINE = Path("v4/recovered_v3_baseline.csv")
EVIDENCE = Path("v4/verified_feature_rows.csv")
OUTPUT = Path("reports/v4_research_status.json")

def status():
    result = {"status": "RESEARCH_ONLY", "release_ready": False,
              "required_training_games": 200, "required_holdout_games": 100,
              "features": list(FEATURES), "source_authenticity_verified": False,
              "baseline_file_present": BASELINE.exists(),
              "feature_file_present": EVIDENCE.exists(),
              "warning": "CSV filenames or URLs do not independently authenticate source evidence."}
    if not BASELINE.exists() or not EVIDENCE.exists():
        result["reason"] = "Verified historical baseline and/or feature rows not available"
        result["evaluations"] = []
        return result
    with BASELINE.open(newline="", encoding="utf-8") as handle:
        baseline = list(csv.DictReader(handle))
    with EVIDENCE.open(newline="", encoding="utf-8") as handle:
        evidence = list(csv.DictReader(handle))
    result["baseline_rows"] = len(baseline)
    result["feature_rows"] = len(evidence)
    result["evaluations"] = []
    result["reason"] = "Evidence requires independent authentication before calibration"
    return result

def main():
    report = status()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))

if __name__ == "__main__":
    main()
