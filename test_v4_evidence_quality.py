import unittest
from v4_evidence_quality import quality_report
from v4_evidence_audit import FEATURES


def baseline():
    return [{"game_id": "g1", "season": 2025, "source_grading_status": "settled",
             "captured_at_utc": "2025-10-01T12:00:00Z",
             "kickoff_utc": "2025-10-02T12:00:00Z",
             "actual_home_margin": 7, "v3_home_margin": 4}]


def evidence():
    return [{"game_id": "g1", "feature": f, "value": 0,
             "source_url": "https://example.org/report",
             "published_at_utc": "2025-09-30T12:00:00Z",
             "observed_at_utc": "2025-10-01T10:00:00Z"} for f in FEATURES]


class QualityTests(unittest.TestCase):
    def test_complete_claims_never_verify_or_release(self):
        report = quality_report(baseline(), evidence())
        self.assertEqual(report["complete_settled_games"], 1)
        self.assertEqual(report["unverified_complete_games"], 1)
        self.assertEqual(report["missing_games"], 0)
        self.assertEqual(report["oldest_observation_lag_hours"], 2)
        self.assertFalse(report["source_authenticity_verified"])
        self.assertFalse(report["release_ready"])

    def test_missing_features_are_prioritized(self):
        report = quality_report(baseline(), evidence()[:1])
        self.assertEqual(report["missing_feature_cells"], 5)
        self.assertEqual(report["missing_games"], 1)
        self.assertEqual(report["priority_missing_games"][0]["present_feature_count"], 1)

    def test_duplicate_claims_rejected(self):
        with self.assertRaises(ValueError):
            quality_report(baseline(), evidence() + evidence()[:1])

    def test_post_capture_claim_rejected(self):
        rows = evidence()
        rows[0]["observed_at_utc"] = "2025-10-01T13:00:00Z"
        with self.assertRaises(ValueError):
            quality_report(baseline(), rows)

    def test_empty_inputs(self):
        report = quality_report([], [])
        self.assertEqual(report["baseline_games"], 0)
        self.assertFalse(report["release_ready"])


if __name__ == "__main__":
    unittest.main()
