import csv
import io
import unittest

from v4_collection_plan import collection_plan, collection_plan_csv
from v4_evidence_audit import FEATURES


def baseline():
    return [{"game_id": "g", "season": 2025, "home_team": "A", "away_team": "B",
             "source_grading_status": "settled",
             "captured_at_utc": "2025-10-01T12:00:00Z",
             "kickoff_utc": "2025-10-02T12:00:00Z",
             "actual_home_margin": 7, "v3_home_margin": 4}]


def evidence(feature):
    return {"game_id": "g", "feature": feature, "value": 0,
            "source_url": "https://example.org/report",
            "published_at_utc": "2025-09-30T12:00:00Z",
            "observed_at_utc": "2025-10-01T10:00:00Z"}


class CollectionPlanTests(unittest.TestCase):
    def test_missing_tasks_and_csv(self):
        plan = collection_plan(baseline(), [evidence(FEATURES[0])])
        self.assertEqual(plan["missing_feature_tasks"], len(FEATURES) - 1)
        self.assertFalse(plan["release_ready"])
        self.assertFalse(plan["source_authenticity_verified"])
        exported = list(csv.DictReader(io.StringIO(collection_plan_csv(plan))))
        self.assertEqual(len(exported), len(FEATURES) - 1)
        self.assertTrue(all(r["evidence_status"] == "NOT_COLLECTED" for r in exported))

    def test_complete_claims_not_authenticated(self):
        plan = collection_plan(baseline(), [evidence(f) for f in FEATURES])
        self.assertEqual(plan["missing_feature_tasks"], 0)
        self.assertFalse(plan["release_ready"])

    def test_duplicate_claims_fail_closed(self):
        with self.assertRaises(ValueError):
            collection_plan(baseline(), [evidence(FEATURES[0])] * 2)

    def test_future_publication_fails_closed(self):
        claim = evidence(FEATURES[0])
        claim["published_at_utc"] = "2025-10-01T13:00:00Z"
        claim["observed_at_utc"] = "2025-10-01T14:00:00Z"
        with self.assertRaises(ValueError):
            collection_plan(baseline(), [claim])

    def test_empty_baseline_exports_header(self):
        plan = collection_plan([], [])
        self.assertEqual(plan["missing_feature_tasks"], 0)
        self.assertEqual(len(collection_plan_csv(plan).splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
