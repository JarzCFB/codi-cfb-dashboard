import unittest
from v4_research_bundle import build_bundle


def row():
    return {"rule_version": "locked", "model_version": "v3", "season": "2026",
            "game_id": "abc", "kickoff_utc": "2026-10-17T18:00:00Z",
            "captured_at_utc": "2026-10-13T12:00:00Z", "home_team": "Home",
            "away_team": "Away", "projected_home_margin": "4.5",
            "actual_home_margin": "", "grading_status": "pending"}


class ResearchBundleTests(unittest.TestCase):
    def test_uses_real_v3_recovery_and_never_changes_picks(self):
        original = row()
        snapshot = dict(original)
        result = build_bundle([original], [], "2026-10-14T00:00:00Z")
        self.assertEqual(original, snapshot)
        self.assertEqual(result["summary"]["official_model"], "V3")
        self.assertFalse(result["summary"]["official_picks_modified"])
        self.assertFalse(result["summary"]["v4_performance_validated"])
        self.assertEqual(result["summary"]["upcoming_games_for_review"], 1)
        self.assertEqual(result["summary"]["missing_feature_cells_all_v3"], 6)

    def test_unverifiable_evidence_fails_closed(self):
        claim = {"game_id": "abc", "feature": "neutral_site", "value": "1",
                 "source_url": "http://example.com",
                 "published_at_utc": "2026-10-13T00:00:00Z",
                 "observed_at_utc": "2026-10-13T01:00:00Z"}
        with self.assertRaises(ValueError):
            build_bundle([row()], [claim], "2026-10-14T00:00:00Z")


if __name__ == "__main__":
    unittest.main()
