"""Conservative V4 research readiness assessment; never deploys a model."""
from collections import Counter

def readiness_report(baseline, audit):
    seasons = sorted({int(r["season"]) for r in baseline})
    settled = [r for r in baseline if r["source_grading_status"] == "settled"]
    complete = audit["complete_rows"]
    complete_seasons = Counter(int(r["season"]) for r in complete)
    last_season = max(complete_seasons) if complete_seasons else None
    historical_train = sum(n for season, n in complete_seasons.items() if season != last_season)
    heldout = complete_seasons.get(last_season, 0)
    checks = [
        ("recovered_baseline", bool(baseline), "Recovered V3 game records"),
        ("outcomes_available", bool(settled), "Settled V3 results"),
        ("verified_evidence", bool(audit["source_authenticity_verified"]), "Independent source authentication"),
        ("multiple_seasons", len(complete_seasons) >= 2, "At least two seasons of complete feature evidence"),
        ("training_sample", historical_train >= 200, "At least 200 prior-season complete settled games"),
        ("holdout_sample", heldout >= 100 and len(complete_seasons) >= 2, "At least 100 later-season complete settled games"),
        ("independent_holdout_improvement", False, "Documented out-of-sample V4 advantage over locked V3"),
        ("live_point_in_time_feed", False, "Verified pre-capture live feature ingestion"),
    ]
    return {
        "status": "RESEARCH_ONLY",
        "total_baseline_games": len(baseline),
        "settled_baseline_games": len(settled),
        "complete_settled_feature_games": len(complete),
        "complete_seasons": dict(sorted(complete_seasons.items())),
        "historical_training_games": historical_train,
        "latest_season_holdout_games": heldout,
        "checks": [{"gate": key, "passed": passed, "requirement": label} for key, passed, label in checks],
        "release_ready": False,
        "warning": "Selected V3 bets are not a representative all-FBS training universe; no automatic V4 release.",
    }
