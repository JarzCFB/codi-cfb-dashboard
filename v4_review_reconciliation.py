"""Fail-closed reconciliation of manual V4 review worksheets.

Human review notes are not proof of source authenticity or model eligibility.
"""
from datetime import datetime, timezone

from v4_evidence_audit import audit_evidence
from v4_source_review import source_review_queue

ALLOWED_STATUSES = frozenset(("UNREVIEWED", "NEEDS_FOLLOWUP", "REJECTED", "REVIEWED_CLAIM"))


def _utc(value):
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("review timestamp must be timezone-aware")
    return dt.astimezone(timezone.utc)


def reconcile_review(baseline, evidence, reviewed_rows):
    """Compare an edited review worksheet with the original generated claims.

    Detect altered evidence, unknown or missing rows, duplicate keys, and
    unsupported statuses. REVIEWED_CLAIM means manual review only.
    """
    baseline, evidence, reviewed_rows = list(baseline), list(evidence), list(reviewed_rows)
    audit_evidence(baseline, evidence)
    original = source_review_queue(baseline, evidence)["review_queue"]
    originals = {(r["game_id"], r["feature"]): r for r in original}
    immutable = ("game_id", "feature", "source_url", "claimed_value",
                 "claimed_published_at_utc", "claimed_observed_at_utc",
                 "original_capture_at_utc", "hours_before_capture")
    seen, counts = set(), {s: 0 for s in sorted(ALLOWED_STATUSES)}
    for row in reviewed_rows:
        key = (str(row.get("game_id", "")), str(row.get("feature", "")))
        if key in seen:
            raise ValueError("duplicate review row")
        seen.add(key)
        if key not in originals:
            raise ValueError("unknown review row")
        expected = originals[key]
        if any(str(row.get(field, "")) != str(expected[field]) for field in immutable):
            raise ValueError("review worksheet modified immutable source claim")
        status = str(row.get("review_status", ""))
        if status not in ALLOWED_STATUSES:
            raise ValueError("unsupported review status")
        if status != "UNREVIEWED":
            if not str(row.get("reviewer", "")).strip() or not str(row.get("verification_notes", "")).strip():
                raise ValueError("review decision requires reviewer and notes")
            reviewed_at = _utc(row.get("reviewed_at_utc", ""))
            capture = _utc(expected["original_capture_at_utc"])
            if reviewed_at < capture:
                raise ValueError("review timestamp predates historical capture")
        counts[status] += 1
    if seen != set(originals):
        raise ValueError("review worksheet omitted source claims")
    return {
        "status": "RESEARCH_ONLY",
        "total_claims": len(original),
        "review_status_counts": counts,
        "needs_followup": counts["NEEDS_FOLLOWUP"] + counts["UNREVIEWED"],
        "rejected_claims": counts["REJECTED"],
        "manually_reviewed_claims": counts["REVIEWED_CLAIM"],
        "source_authenticity_verified": False,
        "eligible_for_research_calibration": False,
        "release_ready": False,
        "warning": "Manual review status and notes do not independently authenticate historical evidence or authorize V4 model training.",
    }
