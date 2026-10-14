import csv
import io
import unittest

from v4_source_review import source_review_queue, source_review_csv


def baseline():
    return [{"game_id": "one", "season": 2025,
             "source_grading_status": "settled",
             "captured_at_utc": "2025-10-01T12:00:00Z",
             "kickoff_utc": "2025-10-02T12:00:00Z",
             "actual_home_margin": 3, "v3_home_margin": 2}]


def claim():
    return {"game_id": "one", "feature": "wind_mph", "value": 10,
            "source_url": "https://example.org/weather",
            "published_at_utc": "2025-09-30T10:00:00Z",
            "observed_at_utc": "2025-10-01T10:00:00Z"}


class SourceReviewTests(unittest.TestCase):
    def test_queue_never_auto_verifies(self):
        report = source_review_queue(baseline(), [claim()])
        self.assertEqual(report["claims_needing_review"], 1)
        self.assertFalse(report["source_authenticity_verified"])
        self.assertFalse(report["release_ready"])
        self.assertEqual(report["review_queue"][0]["review_status"], "UNREVIEWED")
        self.assertEqual(report["review_queue"][0]["hours_before_capture"], 2)
        self.assertEqual(list(csv.DictReader(io.StringIO(source_review_csv(report))))[0]["reviewer"], "")

    def test_duplicate_rejected(self):
        with self.assertRaises(ValueError):
            source_review_queue(baseline(), [claim(), claim()])

    def test_future_observation_rejected(self):
        bad = claim()
        bad["observed_at_utc"] = "2025-10-01T13:00:00Z"
        with self.assertRaises(ValueError):
            source_review_queue(baseline(), [bad])

    def test_empty(self):
        report = source_review_queue([], [])
        self.assertEqual(report["claims_needing_review"], 0)
        self.assertFalse(report["release_ready"])


if __name__ == "__main__":
    unittest.main()
