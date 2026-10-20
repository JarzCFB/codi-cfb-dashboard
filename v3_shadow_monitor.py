"""Read-only shadow V3 edge-threshold and frozen classification audit.

Uses only original frozen V3 selections and graded outcomes. Never rewrites selections,
results, thresholds or model parameters. No look-ahead in selection membership.
"""
import csv
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path("prospective")
REPORT = Path("reports/v3_shadow_monitor.json")
THRESHOLDS = (3, 5, 7, 10)
# Locked before the next weekend. Only games kicking off on/after this UTC
# cutoff enter the prospective comparison; earlier results are excluded.
FORWARD_START_UTC = "2026-10-20T00:00:00Z"



def read(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def summarize(rows):
    settled = [r for r in rows if r.get("grading_status") == "settled"
               and r.get("selection_result") in ("win", "loss", "push")]
    return {
        "selections": len(rows),
        "settled": len(settled),
        "pending": sum(r.get("grading_status") == "pending" for r in rows),
        "wins": sum(r["selection_result"] == "win" for r in settled),
        "losses": sum(r["selection_result"] == "loss" for r in settled),
        "pushes": sum(r["selection_result"] == "push" for r in settled),
        "net_units": round(sum(float(r["one_unit_profit"]) for r in settled), 6),
        "roi_per_settled_selection": round(
            sum(float(r["one_unit_profit"]) for r in settled) / len(settled), 6
        ) if settled else None,
    }


def recent_window(rows, days=14):
    """Descriptive recent results, using kickoff dates rather than grading run time."""
    settled = [r for r in rows if r.get("grading_status") == "settled"
               and r.get("selection_result") in ("win", "loss", "push")]
    dates = []
    for r in settled:
        try:
            dates.append(datetime.fromisoformat(r["kickoff_utc"].replace("Z", "+00:00")))
        except (ValueError, TypeError, KeyError):
            pass
    if not dates:
        return {"window_days": days, "through_kickoff_utc": None, "edge_thresholds": {}}
    end = max(dates)
    start = end - timedelta(days=days)
    window = []
    for r in settled:
        try:
            dt = datetime.fromisoformat(r["kickoff_utc"].replace("Z", "+00:00"))
            if start < dt <= end:
                window.append(r)
        except (ValueError, TypeError, KeyError):
            continue
    return {
        "window_days": days,
        "through_kickoff_utc": end.isoformat().replace("+00:00", "Z"),
        "edge_thresholds": {
            str(t): summarize([r for r in window if r.get("edge_points")
                               and float(r["edge_points"]) >= t])
            for t in THRESHOLDS
        },
    }


def forward_shadow(rows, cutoff=FORWARD_START_UTC):
    """Forward-only paper comparison, using frozen original edges and quotes.

    No historical pre-cutoff results enter this record. A settled row is
    included only when its kickoff is on/after the fixed cutoff.
    """
    start = datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
    eligible = []
    for r in rows:
        try:
            kickoff = datetime.fromisoformat(r["kickoff_utc"].replace("Z", "+00:00"))
            if kickoff >= start:
                eligible.append(r)
        except (ValueError, TypeError, KeyError):
            continue
    return {
        "start_kickoff_utc": cutoff,
        "method": "forward-only paper tracking of existing frozen V3 selections; no retrospective pre-cutoff games",
        "warning": "Descriptive shadow comparison, not a betting recommendation or a change to official V3",
        "thresholds": {
            str(t): summarize([r for r in eligible if r.get("edge_points")
                               and float(r["edge_points"]) >= t])
            for t in THRESHOLDS
        },
    }


def build(graded, cohorts):
    v3 = [r for r in graded if r.get("model_version") == "v3"]
    frozen = {(r.get("season"), r.get("game_id")): r for r in cohorts}
    missing = [r for r in v3 if (r.get("season"), r.get("game_id")) not in frozen]
    # A frozen cohort may only exist if V1 and V2 pregame selections both existed.
    # Do not backfill or infer a cohort from scores or from current projections.
    classified = defaultdict(list)
    for r in v3:
        c = frozen.get((r.get("season"), r.get("game_id")))
        label = c.get("investigation_status", "UNCLASSIFIED") if c else "UNCLASSIFIED"
        classified[label].append(r)
    return {
        "method": "read-only frozen V3 shadow thresholds; one unit per frozen selection",
        "warning": "Retrospective performance is exploratory; no threshold is validated or applied to official V3",
        "edge_thresholds": {
            str(t): summarize([r for r in v3 if r.get("edge_points")
                               and float(r["edge_points"]) >= t])
            for t in THRESHOLDS
        },
        "frozen_cohorts": {k: summarize(v) for k, v in sorted(classified.items())},
        "recent_settled_window": recent_window(v3),
        "forward_shadow_comparison": forward_shadow(v3),
        "research_guardrail": "Recent windows are descriptive and end at the latest settled kickoff. Do not choose or change an official threshold based on in-sample results.",
        "unclassified_v3_count": len(missing),
        "unclassified_games": [
            {"season": r.get("season"), "game_id": r.get("game_id"),
             "kickoff_utc": r.get("kickoff_utc"), "matchup": r.get("away_team", "") +
             " at " + r.get("home_team", "")}
            for r in missing
        ],
        "future_pending_v3": [
            {"kickoff_utc": r.get("kickoff_utc"), "selection": r.get("selection"),
             "spread": r.get("spread"), "american_odds": r.get("american_odds"),
             "edge_points": r.get("edge_points"), "sportsbook": r.get("sportsbook"),
             "verification": "FROZEN QUOTE ONLY - current price and QB/injury status not verified"}
            for r in v3 if r.get("grading_status") == "pending"
        ],
    }


def main():
    report = build(read(ROOT / "graded_selections.csv"),
                   read(ROOT / "investigation_cohort.csv"))
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("V3 shadow monitor:", {k: v["settled"] for k, v in report["edge_thresholds"].items()},
          "unclassified:", report["unclassified_v3_count"])


if __name__ == "__main__":
    main()
