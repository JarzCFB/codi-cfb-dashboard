"""Read-only V4 evidence quality diagnostics; URL claims are never verified facts."""
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urlparse

from v4_evidence_audit import FEATURES, audit_evidence


def _utc(value):
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamps must include timezone")
    return dt.astimezone(timezone.utc)


def quality_report(baseline, evidence):
    """Produce actionable diagnostics without changing V3 or promoting V4.

    Invalid records are rejected by the underlying fail-closed audit.
    A complete row means only that all required claims are present.
    """
    baseline = list(baseline)
    evidence = list(evidence)
    audited = audit_evidence(baseline, evidence)
    by_id = {str(row["game_id"]): row for row in baseline}
    sources = Counter()
    feature_sources = {feature: set() for feature in FEATURES}
    lag_hours = []
    for item in evidence:
        host = urlparse(str(item["source_url"])).hostname.lower()
        sources[host] += 1
        feature_sources[str(item["feature"])].add(host)
        capture = _utc(by_id[str(item["game_id"])]["captured_at_utc"])
        observed = _utc(item["observed_at_utc"])
        lag_hours.append(round((capture - observed).total_seconds() / 3600, 3))

    missing = [row for row in audited["missing_rows"] if row["missing_features"]]
    missing.sort(key=lambda r: (r["present_feature_count"], str(r["game_id"])))
    complete = audited["complete_rows"]
    return {
        "status": "RESEARCH_ONLY",
        "baseline_games": audited["baseline_games"],
        "settled_games": audited["settled_games"],
        "evidence_claims": audited["evidence_rows"],
        "complete_settled_games": audited["complete_settled_games"],
        "missing_feature_cells": audited["missing_feature_cells"],
        "feature_coverage": audited["feature_coverage"],
        "coverage_by_feature_pct": audited["coverage_by_feature_pct"],
        "missing_games": len(missing),
        "missing_by_feature": {f: audited["baseline_games"] - audited["feature_coverage"][f] for f in FEATURES},
        "source_host_claims": dict(sorted(sources.items())),
        "distinct_source_hosts_by_feature": {f: len(feature_sources[f]) for f in FEATURES},
        "oldest_observation_lag_hours": max(lag_hours) if lag_hours else None,
        "unverified_complete_games": len(complete),
        "source_authenticity_verified": False,
        "release_ready": False,
        "priority_missing_games": missing,
        "warning": "URLs and timestamps are unverified claims, not authenticated evidence. Completeness does not authorize training, betting, or release.",
    }
