"""Run the existing V4 evidence safety workflow on local historical CSVs.

This is a read-only research audit, not a calibration or betting command.
"""
import argparse
import csv
import json
from pathlib import Path

from v4_collection_plan import collection_plan, collection_plan_csv
from v4_evidence_audit import audit_evidence
from v4_readiness import readiness_report
from v4_recover_v3 import recover_v3_upload, recovery_summary
from v4_research_dataset import research_dataset_inventory
from v4_source_review import source_review_queue, source_review_csv


def read_csv(path):
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def audit_local_files(baseline_csv, evidence_csv=None, review_csv=None):
    """Return research-only summary and human action CSVs; never fit a model."""
    baseline = recover_v3_upload(read_csv(baseline_csv))
    evidence = read_csv(evidence_csv) if evidence_csv is not None else []
    audited = audit_evidence(baseline, evidence)
    readiness = readiness_report(baseline, audited)
    plan = collection_plan(baseline, evidence)
    review_queue = source_review_queue(baseline, evidence)
    result = {
        "status": "RESEARCH_ONLY",
        "baseline": recovery_summary(baseline),
        "evidence": {
            "evidence_rows": audited["evidence_rows"],
            "complete_settled_games": audited["complete_settled_games"],
            "missing_feature_cells": audited["missing_feature_cells"],
            "coverage_by_feature_pct": audited["coverage_by_feature_pct"],
        },
        "readiness": {
            "checks": readiness["checks"],
            "historical_training_games": readiness["historical_training_games"],
            "latest_season_holdout_games": readiness["latest_season_holdout_games"],
        },
        "missing_feature_tasks": plan["missing_feature_tasks"],
        "review_claims": review_queue["claims_needing_review"],
        "source_authenticity_verified": False,
        "eligible_for_research_calibration": False,
        "release_ready": False,
    }
    if review_csv is not None:
        inventory = research_dataset_inventory(baseline, evidence, read_csv(review_csv))
        result["review_classifications"] = inventory["classifications"]
        result["trainable_rows"] = 0
    return result, collection_plan_csv(plan), source_review_csv(review_queue)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Research-only V4 historical evidence audit")
    parser.add_argument("--baseline", required=True, help="Original V3 audit or recovered baseline CSV")
    parser.add_argument("--evidence", help="Optional evidence claims CSV")
    parser.add_argument("--reviews", help="Optional completed review worksheet CSV")
    parser.add_argument("--output-dir", required=True, help="New or existing output directory")
    args = parser.parse_args(argv)
    if args.reviews and not args.evidence:
        parser.error("--reviews requires --evidence")
    # Validate all inputs before writing any files.
    summary, missing_csv, review_csv = audit_local_files(args.baseline, args.evidence, args.reviews)
    directory = Path(args.output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "v4_audit_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (directory / "v4_missing_evidence.csv").write_text(missing_csv, encoding="utf-8")
    (directory / "v4_source_review_queue.csv").write_text(review_csv, encoding="utf-8")
    print(json.dumps({
        "status": "RESEARCH_ONLY",
        "baseline_games": summary["baseline"]["total_games"],
        "missing_feature_tasks": summary["missing_feature_tasks"],
        "review_claims": summary["review_claims"],
        "release_ready": False,
        "output_dir": str(directory),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
