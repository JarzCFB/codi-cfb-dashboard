"""V4 advisory overlay for official frozen V3 selections.

Only an evidence checklist: NEVER recalculates V3 or asserts V4 edge.
"""
import argparse
import csv
import json
from pathlib import Path

from v4_evidence_audit import FEATURES, audit_evidence
from v4_repo_baseline import repository_v3_baseline

ROOT = Path(__file__).resolve().parent


def advisory_report(baseline, evidence):
    baseline = list(baseline)
    evidence = list(evidence)
    audit = audit_evidence(baseline, evidence)
    # Audit output is not source authentication. Even complete claimed evidence
    # cannot authorize an unvalidated betting model to override V3.
    evidence_keys = {(str(row["game_id"]), str(row["feature"])) for row in evidence}
    items = []
    for game in baseline:
        gid = str(game["game_id"])
        missing = [feature for feature in FEATURES if (gid, feature) not in evidence_keys]
        items.append({
            "game_id": gid,
            "season": int(game["season"]),
            "home_team": game["home_team"],
            "away_team": game["away_team"],
            "v3_home_margin": game["v3_home_margin"],
            "v3_selection_unchanged": True,
            "v4_advisory": "SOURCE_REVIEW_REQUIRED" if not missing else "INSUFFICIENT_EVIDENCE",
            "missing_features": missing,
            "verified_v4_override": False,
            "recommended_v3_action": "UNCHANGED",
        })
    return {
        "status": "V3_OFFICIAL_V4_ADVISORY_ONLY",
        "official_model": "V3",
        "v4_override_enabled": False,
        "source_claims_are_not_authentication": True,
        "total_v3_games": len(items),
        "games_with_six_claimed_features": sum(not item["missing_features"] for item in items),
        "games_needing_evidence": sum(bool(item["missing_features"]) for item in items),
        "audit_coverage": {"missing_feature_cells": audit["missing_feature_cells"], "feature_coverage": audit["feature_coverage"], "source_authenticity_verified": audit["source_authenticity_verified"]},
        "games": items,
        "note": "No V4 recommendation or staking change until independent source verification and prospective model validation.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only V4 advisory checklist for V3")
    parser.add_argument("--graded", type=Path, default=ROOT / "prospective/graded_selections.csv")
    parser.add_argument("--evidence", type=Path, help="Optional claims CSV; not proof of verification")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    with args.graded.open(encoding="utf-8-sig", newline="") as stream:
        baseline = repository_v3_baseline(csv.DictReader(stream))
    evidence = []
    if args.evidence:
        with args.evidence.open(encoding="utf-8-sig", newline="") as stream:
            evidence = list(csv.DictReader(stream))
    report = advisory_report(baseline, evidence)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
