"""Fail-closed, point-in-time feature evidence audit for V4 research.

Never writes V3 picks. Never infers health from a missing report.
"""
from datetime import datetime
from math import isfinite
from urllib.parse import urlparse

FEATURES = ("qb_out_diff", "key_players_out_diff", "rest_days_diff",
            "travel_miles_diff", "wind_mph", "neutral_site")
REQUIRED_EVIDENCE = ("game_id", "feature", "value", "source_url",
                     "published_at_utc", "observed_at_utc")

def _time(value):
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return dt

def _valid_feature(name, value):
    number = float(value)
    if not isfinite(number):
        raise ValueError("nonfinite feature")
    if name == "qb_out_diff" and number not in (-1, 0, 1):
        raise ValueError("QB status difference must be -1, 0 or 1")
    if name == "key_players_out_diff" and (number != int(number) or abs(number) > 11):
        raise ValueError("invalid key-player difference")
    if name == "rest_days_diff" and (abs(number) > 30 or number != int(number)):
        raise ValueError("invalid rest difference")
    if name == "travel_miles_diff" and abs(number) > 10000:
        raise ValueError("invalid travel difference")
    if name == "wind_mph" and not 0 <= number <= 200:
        raise ValueError("invalid wind")
    if name == "neutral_site" and number not in (0, 1):
        raise ValueError("neutral site must be 0 or 1")
    return number

def audit_evidence(baseline, evidence):
    """Return coverage and independently traceable candidates, not certified facts.

    A URL and timestamp are claims in an uploaded CSV, not authentication of the
    publication. Human/source verification remains mandatory.
    """
    baseline_by_id = {str(row["game_id"]): row for row in baseline}
    if len(baseline_by_id) != len(baseline):
        raise ValueError("duplicate baseline game")
    indexed = {}
    for item in evidence:
        if any(not str(item.get(k, "")).strip() for k in REQUIRED_EVIDENCE):
            raise ValueError("evidence must include feature, source URL and timestamps")
        gid, feature = str(item["game_id"]), str(item["feature"])
        if gid not in baseline_by_id:
            raise ValueError("evidence references unknown baseline game")
        if feature not in FEATURES:
            raise ValueError("unsupported V4 feature")
        key = (gid, feature)
        if key in indexed:
            raise ValueError("duplicate game/feature evidence")
        parsed = urlparse(str(item["source_url"]))
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("evidence requires a public HTTPS source URL")
        capture = _time(baseline_by_id[gid]["captured_at_utc"])
        kickoff = _time(baseline_by_id[gid]["kickoff_utc"])
        published, observed = _time(item["published_at_utc"]), _time(item["observed_at_utc"])
        if not published <= observed <= capture < kickoff:
            raise ValueError("feature not verifiably available before V3 capture")
        indexed[key] = _valid_feature(feature, item["value"])
    complete = []
    for gid, base in baseline_by_id.items():
        if base["source_grading_status"] != "settled":
            continue
        if all((gid, feature) in indexed for feature in FEATURES):
            row = {key: base[key] for key in ("game_id", "season", "kickoff_utc",
                    "captured_at_utc", "actual_home_margin", "v3_home_margin")}
            row.update({feature: indexed[(gid, feature)] for feature in FEATURES})
            complete.append(row)
    return {
        "baseline_games": len(baseline),
        "evidence_rows": len(evidence),
        "settled_games": sum(r["source_grading_status"] == "settled" for r in baseline),
        "complete_settled_games": len(complete),
        "missing_feature_cells": sum((gid, f) not in indexed for gid in baseline_by_id for f in FEATURES),
        "eligible_for_research_calibration": len({r["season"] for r in complete}) >= 2,
        "source_authenticity_verified": False,
        "warning": "Source URLs/timestamps are user-provided claims. Independent archival verification required before training or release.",
        "complete_rows": complete,
    }
