import unittest
from v4_source_review import source_review_queue
from v4_review_reconciliation import reconcile_review


def base():
    return [{"game_id": "g", "season": 2025, "source_grading_status": "settled",
             "captured_at_utc": "2025-10-01T12:00:00Z",
             "kickoff_utc": "2025-10-02T12:00:00Z",
             "actual_home_margin": 3, "v3_home_margin": 2}]


def evidence():
    return [{"game_id": "g", "feature": "wind_mph", "value": 10,
             "source_url": "https://example.org/weather",
             "published_at_utc": "2025-09-30T10:00:00Z",
             "observed_at_utc": "2025-10-01T10:00:00Z"}]


def review():
    return source_review_queue(base(), evidence())["review_queue"]


class ReconciliationTests(unittest.TestCase):
    def test_unreviewed_remains_blocked(self):
        result = reconcile_review(base(), evidence(), review())
        self.assertEqual(result["needs_followup"], 1)
        self.assertFalse(result["release_ready"])

    def test_manual_review_not_authentication(self):
        rows = review()
        rows[0].update(review_status="REVIEWED_CLAIM", reviewer="analyst",
                       reviewed_at_utc="2025-10-03T12:00:00Z",
                       verification_notes="Inspected archived publication")
        result = reconcile_review(base(), evidence(), rows)
        self.assertEqual(result["manually_reviewed_claims"], 1)
        self.assertFalse(result["source_authenticity_verified"])
        self.assertFalse(result["eligible_for_research_calibration"])

    def test_modified_claim_rejected(self):
        rows = review()
        rows[0]["claimed_value"] = "0"
        with self.assertRaises(ValueError):
            reconcile_review(base(), evidence(), rows)

    def test_duplicate_and_missing_rejected(self):
        with self.assertRaises(ValueError):
            reconcile_review(base(), evidence(), review() * 2)
        with self.assertRaises(ValueError):
            reconcile_review(base(), evidence(), [])

    def test_missing_reviewer_rejected(self):
        rows = review()
        rows[0]["review_status"] = "REJECTED"
        with self.assertRaises(ValueError):
            reconcile_review(base(), evidence(), rows)

    def test_empty(self):
        result = reconcile_review([], [], [])
        self.assertEqual(result["total_claims"], 0)
        self.assertFalse(result["release_ready"])


if __name__ == "__main__":
    unittest.main()
