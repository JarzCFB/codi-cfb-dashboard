"""Read-only V3 research baseline from the repository's frozen graded picks."""
import argparse
import csv
import io
import json
from pathlib import Path
from collections import Counter

from v4_audit_cli import audit_local_files
from v4_recover_v3 import recover_v3_audit, recovery_summary

DEFAULT_SOURCE = Path(__file__).resolve().parent / "prospective" / "graded_selections.csv"


def repository_v3_baseline(rows):
    """Filter V3 before deduplication; reject ambiguous or invalid records."""
    rows = list(rows)
    v3 = [r for r in rows if str(r.get("model_version", "")).strip().lower() == "v3"]
    if not v3:
        raise ValueError("No frozen V3 selections found in graded source")
    return recover_v3_audit(v3)


def baseline_diagnostics(baseline):
    """Describe actual frozen V3 sample and hard-block single-season evaluation."""
    by_season = Counter(int(r["season"]) for r in baseline)
    settled = Counter(int(r["season"]) for r in baseline if r["source_grading_status"] == "settled")
    return {
        "games_by_season": dict(sorted(by_season.items())),
        "settled_by_season": dict(sorted(settled.items())),
        "multiple_seasons_present": len(by_season) >= 2,
        "eligible_for_walkforward": False,
        "reason": "Selected V3 picks lack verified V4 features and are not the all-FBS universe.",
    }


def baseline_csv(baseline):
    fields = ("game_id", "season", "kickoff_utc", "captured_at_utc",
              "home_team", "away_team", "v3_home_margin", "actual_home_margin",
              "source_grading_status")
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for row in baseline:
        writer.writerow({k: ("" if row.get(k) is None else row[k]) for k in fields})
    return output.getvalue()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Extract frozen V3 baseline without changing picks")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    with args.source.open(encoding="utf-8-sig", newline="") as handle:
        baseline = repository_v3_baseline(csv.DictReader(handle))
    # Audit the recovered baseline in memory before writing any output.
    from v4_evidence_audit import audit_evidence
    from v4_readiness import readiness_report
    from v4_collection_plan import collection_plan, collection_plan_csv
    from v4_source_review import source_review_queue, source_review_csv
    audit = audit_evidence(baseline, [])
    readiness = readiness_report(baseline, audit)
    tasks = collection_plan(baseline, [])
    queue = source_review_queue(baseline, [])
    summary = {
        "status": "RESEARCH_ONLY",
        "baseline": recovery_summary(baseline),
        "diagnostics": baseline_diagnostics(baseline),
        "missing_feature_tasks": tasks["missing_feature_tasks"],
        "evidence_rows": audit["evidence_rows"],
        "readiness_checks": readiness["checks"],
        "source_authenticity_verified": False,
        "release_ready": False,
        "caution": "Frozen V3 selected games are not the full FBS universe; no multi-season model training is authorized.",
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "v4_recovered_v3_baseline.csv").write_text(baseline_csv(baseline), encoding="utf-8")
    (args.output_dir / "v4_missing_evidence.csv").write_text(collection_plan_csv(tasks), encoding="utf-8")
    (args.output_dir / "v4_source_review_queue.csv").write_text(source_review_csv(queue), encoding="utf-8")
    (args.output_dir / "v4_repo_audit_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"v3_games": len(baseline), "missing_feature_tasks": tasks["missing_feature_tasks"],
                      "release_ready": False, "output_dir": str(args.output_dir)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
