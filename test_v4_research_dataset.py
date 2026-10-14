import unittest

from v4_evidence_audit import FEATURES
from v4_source_review import source_review_queue
from v4_research_dataset import research_dataset_inventory


def baseline():
    return [{"game_id": "g", "season": 2025, "source_grading_status": "settled",
             "captured_at_utc": "2025-10-01T12:00:00Z",
             "kickoff_utc": "2025-10-02T12:00:00Z",
             "actual_home_margin": 3, "v3_home_margin": 2}]


def claim(feature):
    return {"game_id": "g", "feature": feature, "value": 0,
            "source_url": "https://example.org/data",
            "published_at_utc": "2025-09-30T10:00:00Z",
            "observed_at_utc": "2025-10-01T10:00:00Z"}


class DatasetInventoryTests(unittest.TestCase):
    def test_missing(self):
        result = research_dataset_inventory(baseline(), [], [])
        self.assertEqual(result["classifications"]["MISSING_EVIDENCE"], 1)
        self.assertEqual(result["trainable_rows"], [])

    def test_all_manual_review_still_unverified(self):
        evidence = [claim(f) for f in FEATURES]
        rows = source_review_queue(baseline(), evidence)["review_queue"]
        for r in rows:
            r.update(review_status="REVIEWED_CLAIM", reviewer="analyst",
                     reviewed_at_utc="2025-10-03T12:00:00Z",
                     verification_notes="Inspected archive")
        result = research_dataset_inventory(baseline(), evidence, rows)
        self.assertEqual(result["classifications"]["MANUALLY_REVIEWED_UNVERIFIED"], 1)
        self.assertFalse(result["source_authenticity_verified"])
        self.assertFalse(result["release_ready"])

    def test_rejection_overrides_review(self):
        evidence = [claim(f) for f in FEATURES]
        rows = source_review_queue(baseline(), evidence)["review_queue"]
        rows[0].update(review_status="REJECTED", reviewer="analyst",
                       reviewed_at_utc="2025-10-03T12:00:00Z",
                       verification_notes="Not from original publication")
        result = research_dataset_inventory(baseline(), evidence, rows)
        self.assertEqual(result["classifications"]["REJECTED_EVIDENCE"], 1)

    def test_modified_claim_fails(self):
        evidence = [claim("wind_mph")]
        rows = source_review_queue(baseline(), evidence)["review_queue"]
        rows[0]["claimed_value"] = "200"
        with self.assertRaises(ValueError):
            research_dataset_inventory(baseline(), evidence, rows)


if __name__ == "__main__":
    unittest.main()
