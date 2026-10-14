"""Conservative V4 research dataset inventory; no certified training export."""
from collections import Counter

from v4_evidence_audit import FEATURES, audit_evidence
from v4_review_reconciliation import reconcile_review


def research_dataset_inventory(baseline, evidence, reviewed_rows):
    """Classify settled games using immutable claims and reconciled reviews.

    A manually reviewed claim is not independently authenticated.
    Accordingly this function never returns trainable feature rows.
    """
    baseline, evidence, reviewed_rows = list(baseline), list(evidence), list(reviewed_rows)
    audit = audit_evidence(baseline, evidence)
    reconciliation = reconcile_review(baseline, evidence, reviewed_rows)
    statuses = {(str(r["game_id"]), str(r["feature"])): r["review_status"]
                for r in reviewed_rows}
    summary = Counter()
    games = []
    for row in baseline:
        gid = str(row["game_id"])
        claims = [statuses.get((gid, f), "MISSING") for f in FEATURES]
        if row["source_grading_status"] != "settled":
            classification = "PENDING_OUTCOME"
        elif "REJECTED" in claims:
            classification = "REJECTED_EVIDENCE"
        elif "MISSING" in claims:
            classification = "MISSING_EVIDENCE"
        elif "NEEDS_FOLLOWUP" in claims or "UNREVIEWED" in claims:
            classification = "AWAITING_REVIEW"
        else:
            classification = "MANUALLY_REVIEWED_UNVERIFIED"
        summary[classification] += 1
        games.append({"game_id": gid, "season": int(row["season"]),
                      "classification": classification,
                      "reviewed_claims": claims.count("REVIEWED_CLAIM"),
                      "missing_claims": claims.count("MISSING"),
                      "rejected_claims": claims.count("REJECTED")})
    games.sort(key=lambda r: (r["season"], r["game_id"]))
    return {
        "status": "RESEARCH_ONLY",
        "baseline_games": len(baseline),
        "complete_claimed_settled_games": audit["complete_settled_games"],
        "reviewed_claims": reconciliation["manually_reviewed_claims"],
        "classifications": dict(sorted(summary.items())),
        "games": games,
        "trainable_rows": [],
        "source_authenticity_verified": False,
        "eligible_for_research_calibration": False,
        "release_ready": False,
        "warning": "Manual review does not authenticate provenance; no trainable V4 dataset is emitted.",
    }
