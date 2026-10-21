"""V4 offline research status: fail closed on missing or unauthenticated evidence.

A file or URL is not proof of source authenticity. This script never promotes V4.
"""
import csv
import json
from pathlib import Path
from v4_spread_research import evaluate, MIN_TRAIN, MIN_HOLDOUT
from v4_evidence_audit import FEATURES, audit_evidence

BASELINE = Path("v4/recovered_v3_baseline.csv")
EVIDENCE = Path("v4/verified_feature_rows.csv")
OUTPUT = Path("reports/v4_research_status.json")

def _csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))

def status(baseline_path=BASELINE, evidence_path=EVIDENCE):
    baseline_path, evidence_path = Path(baseline_path), Path(evidence_path)
    result = {
        "status": "RESEARCH_ONLY", "release_ready": False,
        "required_training_games": MIN_TRAIN, "required_holdout_games": MIN_HOLDOUT,
        "features": list(FEATURES), "source_authenticity_verified": False,
        "baseline_file_present": baseline_path.exists(),
        "feature_file_present": evidence_path.exists(),
        "evaluations": [],
        "warning": "Evidence URL and timestamp claims are not independently authenticated; no official V4 promotion."
    }
    baseline = _csv(baseline_path) if baseline_path.exists() else []
    evidence = _csv(evidence_path) if evidence_path.exists() else []
    result["baseline_rows"] = len(baseline)
    result["settled_baseline_rows"] = sum(
        row.get("source_grading_status") == "settled" for row in baseline)
    result["feature_rows"] = len(evidence)
    result["selected_only_baseline"] = True
    result["eligible_for_all_game_training"] = False
    if not evidence_path.exists() and baseline_path.exists():
        result["missing_feature_cells"] = len(baseline) * len(FEATURES)
        result["feature_coverage"] = {feature: 0 for feature in FEATURES}
        result["coverage_by_feature_pct"] = {feature: 0.0 for feature in FEATURES}
        result["complete_settled_games"] = 0
    if not baseline_path.exists() or not evidence_path.exists():
        result["reason"] = "Historical baseline and/or pregame feature evidence missing"
        return result
    try:
        audit = audit_evidence(baseline, evidence)
    except (KeyError, ValueError, TypeError, OverflowError) as exc:
        result["reason"] = "Evidence audit rejected data: " + str(exc)
        return result
    result["complete_settled_games"] = audit["complete_settled_games"]
    result["missing_feature_cells"] = audit["missing_feature_cells"]
    result["feature_coverage"] = audit["feature_coverage"]
    result["coverage_by_feature_pct"] = audit["coverage_by_feature_pct"]
    # audit_evidence explicitly does not authenticate URLs. Do not permit caller
    # supplied CSV fields to turn this flag on.
    comparison = evaluate(audit["complete_rows"],
                          source_authenticity_verified=audit["source_authenticity_verified"])
    result["evaluations"] = comparison["evaluations"]
    result["reason"] = comparison["reason"]
    return result

def main():
    report = status()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))

if __name__ == "__main__":
    main()
