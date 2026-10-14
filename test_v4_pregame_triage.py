import unittest
from v4_pregame_triage import upcoming_triage


def game(gid, kickoff, status="pending"):
    return {"game_id": gid, "season": 2026, "kickoff_utc": kickoff,
            "captured_at_utc": "2026-10-13T00:00:00Z", "source_grading_status": status,
            "home_team": "A", "away_team": "B", "v3_home_margin": 3.5,
            "actual_home_margin": None}


class PregameTriageTests(unittest.TestCase):
    def test_only_future_pending_games_prioritized(self):
        rows = [game("later", "2026-10-17T18:00:00Z"),
                game("soon", "2026-10-15T18:00:00Z"),
                game("past", "2026-10-13T18:00:00Z"),
                game("settled", "2026-10-15T18:00:00Z", "settled")]
        report = upcoming_triage(rows, [], "2026-10-14T00:00:00Z")
        self.assertEqual([x["game_id"] for x in report["games"]], ["soon", "later"])
        self.assertEqual(report["missing_feature_cells"], 12)
        self.assertFalse(report["betting_model_modified"])
        self.assertTrue(all(x["betting_recommendation"] == "NONE" for x in report["games"]))

    def test_duplicates_fail_closed(self):
        with self.assertRaises(ValueError):
            upcoming_triage([game("a", "2026-10-17T18:00:00Z")] * 2, [], "2026-10-14T00:00:00Z")

    def test_bad_timestamp_fails_closed(self):
        with self.assertRaises(ValueError):
            upcoming_triage([game("a", "2026-10-17T18:00:00Z")], [], "2026-10-14T00:00:00")


if __name__ == "__main__":
    unittest.main()
