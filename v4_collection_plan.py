"""Read-only V4 historical evidence collection planning.

No missing feature is inferred to be zero, healthy, or verified.
"""
import csv
import io
from collections import Counter

from v4_evidence_audit import FEATURES, audit_evidence
from v4_evidence_triage import triage_rows


def collection_plan(baseline, evidence=()):
    """Return prioritized missing-feature tasks after strict evidence validation."""
    baseline = list(baseline)
    evidence = list(evidence)
    audit = audit_evidence(baseline, evidence)
    games = {str(r["game_id"]): r for r in baseline}
    tasks = []
    for row in triage_rows(baseline, evidence):
        for feature in row["missing_features"].split("|"):
            if not feature:
                continue
            tasks.append({
                "game_id": row["game_id"],
                "season": row["season"],
                "home_team": row["home_team"],
                "away_team": row["away_team"],
                "feature": feature,
                "captured_at_utc": row["captured_at_utc"],
                "kickoff_utc": row["kickoff_utc"],
                "source_grading_status": row["source_grading_status"],
                "evidence_status": "NOT_COLLECTED",
                "required_verification": "Authenticate source and publication time <= original capture",
            })
    tasks.sort(key=lambda r: (r["source_grading_status"] != "settled",
                              str(r["kickoff_utc"]), str(r["game_id"]),
                              FEATURES.index(r["feature"])))
    by_feature = Counter(t["feature"] for t in tasks)
    return {
        "status": "RESEARCH_ONLY",
        "baseline_games": len(games),
        "evidence_claims": len(evidence),
        "missing_feature_tasks": len(tasks),
        "missing_by_feature": {f: by_feature[f] for f in FEATURES},
        "tasks": tasks,
        "source_authenticity_verified": False,
        "release_ready": False,
        "warning": "Evidence URLs are claims, not authenticated facts. Never infer missing injuries or train on future-known information.",
    }


def collection_plan_csv(plan):
    """Export task list for manual research; never a model-training dataset."""
    fields = ("game_id", "season", "home_team", "away_team", "feature",
              "captured_at_utc", "kickoff_utc", "source_grading_status",
              "evidence_status", "required_verification")
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    writer.writerows(plan["tasks"])
    return output.getvalue()
