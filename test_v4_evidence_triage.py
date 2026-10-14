import unittest
from v4_evidence_triage import triage_rows, triage_csv

BASE = {"game_id": "g", "season": 2026, "home_team": "Home", "away_team": "Away",
        "captured_at_utc": "2026-09-28T12:00:00Z",
        "kickoff_utc": "2026-10-03T18:00:00Z", "source_grading_status": "settled"}

class TriageTests(unittest.TestCase):
    def test_far_ahead_is_not_injury_evidence(self):
        rows = triage_rows([BASE])
        self.assertEqual(rows[0]["capture_window"], "more_than_72h")
        self.assertEqual(rows[0]["missing_feature_count"], 6)
        self.assertIn("never substitute later reports", rows[0]["caution"])
        self.assertIn("game_id", triage_csv(rows))

    def test_known_feature_is_only_counted_not_inferred(self):
        rows = triage_rows([BASE], [{"game_id": "g", "feature": "neutral_site"}])
        self.assertEqual(rows[0]["missing_feature_count"], 5)
        self.assertNotIn("neutral_site", rows[0]["missing_features"])

    def test_capture_after_kickoff_rejected(self):
        with self.assertRaises(ValueError):
            triage_rows([dict(BASE, captured_at_utc="2026-10-04T00:00:00Z")])

    def test_duplicate_rejected(self):
        with self.assertRaises(ValueError):
            triage_rows([BASE, BASE])

if __name__ == "__main__":
    unittest.main()
