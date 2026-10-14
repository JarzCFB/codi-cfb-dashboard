"""Read-only V4 source review queue. Human attestations are not authentication."""
import csv
import io
from datetime import datetime, timezone

from v4_evidence_audit import audit_evidence


def _utc(value):
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamp requires timezone")
    return dt.astimezone(timezone.utc)


def source_review_queue(baseline, evidence):
    """Generate one review task per valid evidence claim.

    Rejects all invalid claims through the existing audit. Never marks any
    source authenticated or enables training/release.
    """
    baseline, evidence = list(baseline), list(evidence)
    audit_evidence(baseline, evidence)
    captures = {str(row["game_id"]): _utc(row["captured_at_utc"]) for row in baseline}
    queue = []
    for claim in evidence:
        capture = captures[str(claim["game_id"])]
        published = _utc(claim["published_at_utc"])
        observed = _utc(claim["observed_at_utc"])
        queue.append({
            "game_id": str(claim["game_id"]),
            "feature": str(claim["feature"]),
            "source_url": str(claim["source_url"]),
            "claimed_value": str(claim["value"]),
            "claimed_published_at_utc": published.isoformat(),
            "claimed_observed_at_utc": observed.isoformat(),
            "original_capture_at_utc": capture.isoformat(),
            "hours_before_capture": round((capture - observed).total_seconds() / 3600, 3),
            "review_status": "UNREVIEWED",
            "reviewer": "",
            "reviewed_at_utc": "",
            "verification_notes": "",
        })
    queue.sort(key=lambda r: (r["original_capture_at_utc"], r["game_id"], r["feature"]))
    return {
        "status": "RESEARCH_ONLY",
        "claims_needing_review": len(queue),
        "review_queue": queue,
        "source_authenticity_verified": False,
        "release_ready": False,
        "warning": "Review rows are unauthenticated source claims; editing CSV review fields does not certify source provenance.",
    }


def source_review_csv(report):
    fields = ("game_id", "feature", "source_url", "claimed_value",
              "claimed_published_at_utc", "claimed_observed_at_utc",
              "original_capture_at_utc", "hours_before_capture",
              "review_status", "reviewer", "reviewed_at_utc", "verification_notes")
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    writer.writerows(report["review_queue"])
    return output.getvalue()
