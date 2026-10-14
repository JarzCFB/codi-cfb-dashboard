"""Single entry point for V3 official / V4 advisory pregame research.

No automatic betting decisions, V3 edits, or claims of source authentication.
"""
import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from v4_repo_baseline import repository_v3_baseline
from v4_v3_advisory import advisory_report
from v4_pregame_triage import upcoming_triage
from v4_evidence_audit import audit_evidence

ROOT = Path(__file__).resolve().parent


def build_bundle(graded_rows, evidence_rows, asof_utc):
    baseline = repository_v3_baseline(graded_rows)
    evidence = list(evidence_rows)
    advisory = advisory_report(baseline, evidence)
    triage = upcoming_triage(baseline, evidence, asof_utc)
    audit = audit_evidence(baseline, evidence)
    return {
        "summary": {
            "official_model": "V3",
            "v4_role": "ADVISORY_ONLY",
            "official_picks_modified": False,
            "automatic_v4_bet_override": False,
            "v3_games": len(baseline),
            "upcoming_games_for_review": triage["upcoming_games"],
            "missing_feature_cells_all_v3": audit["missing_feature_cells"],
            "evidence_claims_submitted": len(evidence),
            "source_authenticity_verified": False,
            "v4_performance_validated": False,
            "v4_improvement_claimed": False,
            "next_action": "Authenticate source timestamps and evaluate prospective paired betting outcomes before changing betting decisions.",
        },
        "advisory": advisory,
        "pregame_triage": triage,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="One-stop V3/V4 research-only integration")
    parser.add_argument("--graded", type=Path, default=ROOT / "prospective/graded_selections.csv")
    parser.add_argument("--evidence", type=Path, help="Optional V4 evidence claims CSV; claims are not authenticated facts")
    parser.add_argument("--asof-utc", default=datetime.now(timezone.utc).isoformat())
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    with args.graded.open(encoding="utf-8-sig", newline="") as stream:
        graded = list(csv.DictReader(stream))
    evidence = []
    if args.evidence:
        with args.evidence.open(encoding="utf-8-sig", newline="") as stream:
            evidence = list(csv.DictReader(stream))
    result = build_bundle(graded, evidence, args.asof_utc)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, value in (
        ("v3_v4_status.json", result["summary"]),
        ("v4_v3_advisory.json", result["advisory"]),
        ("v4_upcoming_pregame_review.json", result["pregame_triage"]),
    ):
        (args.output_dir / name).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
