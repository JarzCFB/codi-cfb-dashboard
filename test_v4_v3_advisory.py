import unittest
from v4_v3_advisory import advisory_report


def game():
    return {"game_id": "abc", "season": 2026, "kickoff_utc": "2026-10-17T18:00:00Z",
            "captured_at_utc": "2026-10-16T18:00:00Z", "home_team": "Home",
            "away_team": "Away", "v3_home_margin": 4.5,
            "actual_home_margin": None, "source_grading_status": "pending"}


class AdvisoryTests(unittest.TestCase):
    def test_missing_evidence_never_changes_v3(self):
        source = game()
        result = advisory_report([source], [])
        item = result["games"][0]
        self.assertEqual(item["v3_home_margin"], 4.5)
        self.assertEqual(source["v3_home_margin"], 4.5)
        self.assertEqual(item["v4_advisory"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(len(item["missing_features"]), 6)
        self.assertFalse(result["v4_override_enabled"])
        self.assertFalse(item["verified_v4_override"])

    def test_duplicate_games_fail_closed(self):
        with self.assertRaises(ValueError):
            advisory_report([game(), game()], [])

    def test_unverifiable_source_claim_fails_closed(self):
        evidence = [{"game_id": "abc", "feature": "neutral_site", "value": "1",
                     "source_url": "http://example.com", "published_at_utc": "2026-10-15T00:00:00Z",
                     "observed_at_utc": "2026-10-15T01:00:00Z"}]
        with self.assertRaises(ValueError):
            advisory_report([game()], evidence)


if __name__ == "__main__":
    unittest.main()
