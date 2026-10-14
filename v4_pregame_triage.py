"""Prioritize upcoming official V3 games for V4 manual pregame evidence review.

Never issues or modifies bets, V3 predictions, stakes, or grades.
"""
import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from v4_repo_baseline import repository_v3_baseline
from v4_evidence_audit import FEATURES, audit_evidence

ROOT = Path(__file__).resolve().parent


def _utc(raw):
    dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timezone-aware timestamp required")
    return dt.astimezone(timezone.utc)


def upcoming_triage(baseline, evidence, asof_utc):
    baseline, evidence = list(baseline), list(evidence)
    now = _utc(asof_utc)
    audit = audit_evidence(baseline, evidence)
    available = {(str(r["game_id"]), str(r["feature"])) for r in evidence}
    pending = []
    for game in baseline:
        if game["source_grading_status"] != "pending" or _utc(game["kickoff_utc"]) <= now:
            continue
        gid = str(game["game_id"])
        missing = [f for f in FEATURES if (gid, f) not in available]
        # Rank only by approaching kickoff and evidence completeness.
        # Not a predictive signal or evidence of a betting edge.
        pending.append({
            "game_id": gid,
            "home_team": game["home_team"],
            "away_team": game["away_team"],
            "kickoff_utc": game["kickoff_utc"],
            "v3_home_margin": game["v3_home_margin"],
            "hours_to_kickoff": round((_utc(game["kickoff_utc"]) - now).total_seconds() / 3600, 2),
            "missing_features": missing,
            "missing_feature_count": len(missing),
            "review_priority": "PREGAME_REVIEW" if missing else "SOURCE_AUTHENTICATION",
            "v3_official_status": "UNCHANGED",
            "betting_recommendation": "NONE",
        })
    pending.sort(key=lambda r: (r["hours_to_kickoff"], -r["missing_feature_count"], r["game_id"]))
    return {
        "status": "RESEARCH_ONLY_V3_UNCHANGED",
        "asof_utc": now.isoformat(),
        "upcoming_games": len(pending),
        "missing_feature_cells": sum(r["missing_feature_count"] for r in pending),
        "source_authenticity_verified": audit["source_authenticity_verified"],
        "betting_model_modified": False,
        "games": pending,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="V4 pregame evidence review priorities")
    parser.add_argument("--graded", type=Path, default=ROOT / "prospective/graded_selections.csv")
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--asof-utc", default=datetime.now(timezone.utc).isoformat())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    with args.graded.open(encoding="utf-8-sig", newline="") as handle:
        baseline = repository_v3_baseline(csv.DictReader(handle))
    evidence = []
    if args.evidence:
        with args.evidence.open(encoding="utf-8-sig", newline="") as handle:
            evidence = list(csv.DictReader(handle))
    result = upcoming_triage(baseline, evidence, args.asof_utc)
    rendered = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
