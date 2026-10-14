import unittest
from v4_evidence_audit import audit_evidence, FEATURES

BASE = {"game_id":"g", "season":2026, "kickoff_utc":"2026-10-03T18:00:00Z",
        "captured_at_utc":"2026-09-29T18:00:00Z", "v3_home_margin":4.0,
        "actual_home_margin":7.0, "source_grading_status":"settled"}
VALUES = {"qb_out_diff":1, "key_players_out_diff":2, "rest_days_diff":3,
          "travel_miles_diff":500, "wind_mph":10, "neutral_site":0}
def evidence():
    return [{"game_id":"g","feature":f,"value":VALUES[f],
             "source_url":"https://example.org/archive",
             "published_at_utc":"2026-09-28T18:00:00Z",
             "observed_at_utc":"2026-09-29T17:00:00Z"} for f in FEATURES]

class EvidenceTests(unittest.TestCase):
    def test_complete_is_not_certified(self):
        result = audit_evidence([BASE], evidence())
        self.assertEqual(result["complete_settled_games"], 1)
        self.assertFalse(result["source_authenticity_verified"])
        self.assertFalse(result["eligible_for_research_calibration"])
        self.assertEqual(result["feature_coverage"]["qb_out_diff"], 1)
        self.assertEqual(result["missing_rows"][0]["missing_features"], "")

    def test_missing_stays_missing(self):
        result = audit_evidence([BASE], evidence()[:-1])
        self.assertEqual(result["complete_settled_games"], 0)
        self.assertEqual(result["missing_feature_cells"], 1)
        self.assertEqual(result["missing_rows"][0]["missing_features"], "neutral_site")
        self.assertEqual(result["coverage_by_feature_pct"]["neutral_site"], 0.0)

    def test_post_capture_publication_rejected(self):
        rows = evidence()
        rows[0]["published_at_utc"] = "2026-10-01T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "before V3 capture"):
            audit_evidence([BASE], rows)

    def test_future_observation_rejected(self):
        rows = evidence()
        rows[0]["observed_at_utc"] = "2026-10-01T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "before V3 capture"):
            audit_evidence([BASE], rows)

    def test_invalid_qb_status_rejected(self):
        rows = evidence()
        rows[0]["value"] = 0.5
        with self.assertRaisesRegex(ValueError, "QB status"):
            audit_evidence([BASE], rows)

    def test_pending_not_in_training(self):
        base = dict(BASE, source_grading_status="pending", actual_home_margin=None)
        self.assertEqual(audit_evidence([base], evidence())["complete_settled_games"], 0)

    def test_two_seasons_do_not_automatically_qualify(self):
        old = dict(BASE, game_id="old", season=2025)
        old_evidence = [dict(r, game_id="old") for r in evidence()]
        result = audit_evidence([BASE, old], evidence() + old_evidence)
        self.assertTrue(result["multi_season_complete_data"])
        self.assertFalse(result["eligible_for_research_calibration"])

    def test_duplicate_feature_rejected(self):
        rows = evidence()
        with self.assertRaisesRegex(ValueError, "duplicate"):
            audit_evidence([BASE], rows + [rows[0]])

if __name__ == "__main__":
    unittest.main()
