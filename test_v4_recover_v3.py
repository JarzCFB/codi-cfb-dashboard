import unittest
from v4_recover_v3 import recover_v3_audit, recovery_summary

def row(status="settled"):
    return {"game_id": "abc", "season": "2026", "kickoff_utc": "2026-10-03T18:00:00Z",
            "captured_at_utc": "2026-09-29T18:00:00Z",
            "projected_home_margin": "4.5", "actual_home_margin": "7" if status == "settled" else "",
            "grading_status": status, "model_version": "v3"}

class RecoveryTests(unittest.TestCase):
    def test_settled(self):
        rows = recover_v3_audit([row()])
        self.assertEqual(recovery_summary(rows)["settled_v3_mae"], 2.5)
        self.assertFalse(recovery_summary(rows)["v4_training_ready"])

    def test_pending_not_fabricated(self):
        rows = recover_v3_audit([row("pending")])
        self.assertIsNone(rows[0]["actual_home_margin"])

    def test_pending_outcome_leakage_rejected_in_both_upload_formats(self):
        from v4_recover_v3 import recover_v3_upload
        original = row("pending")
        original["actual_home_margin"] = "9"
        with self.assertRaisesRegex(ValueError, "pending game"):
            recover_v3_audit([original])
        recovered = {
            "game_id": "abc", "season": "2026",
            "kickoff_utc": "2026-10-17T18:00:00Z",
            "captured_at_utc": "2026-10-05T18:00:00Z",
            "v3_home_margin": "4.5", "actual_home_margin": "9",
            "source_grading_status": "pending"
        }
        with self.assertRaisesRegex(ValueError, "pending game"):
            recover_v3_upload([recovered])

    def test_future_leakage_rejected(self):
        r = row()
        r["captured_at_utc"] = r["kickoff_utc"]
        with self.assertRaisesRegex(ValueError, "post-kickoff"):
            recover_v3_audit([r])

    def test_duplicate_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            recover_v3_audit([row(), row()])

    def test_other_model_rejected(self):
        r = row()
        r["model_version"] = "v2"
        with self.assertRaisesRegex(ValueError, "V3-only"):
            recover_v3_audit([r])


    def test_recovered_baseline(self):
        from v4_recover_v3 import recover_v3_upload
        r = {"game_id": "abc", "season": "2026",
             "kickoff_utc": "2026-10-03T18:00:00Z",
             "captured_at_utc": "2026-09-29T18:00:00Z",
             "v3_home_margin": "4.5", "actual_home_margin": "7",
             "source_grading_status": "settled",
             "v4_feature_verification": "NOT_COLLECTED"}
        result = recover_v3_upload([r])
        self.assertEqual(result[0]["v3_home_margin"], 4.5)
        self.assertEqual(result[0]["v4_feature_verification"], "NOT_COLLECTED")

    def test_recovered_pending(self):
        from v4_recover_v3 import recover_v3_upload
        r = {"game_id": "abc", "season": "2026",
             "kickoff_utc": "2026-10-17T18:00:00Z",
             "captured_at_utc": "2026-10-05T18:00:00Z",
             "v3_home_margin": "4.5", "actual_home_margin": "",
             "source_grading_status": "pending"}
        self.assertIsNone(recover_v3_upload([r])[0]["actual_home_margin"])

if __name__ == "__main__":
    unittest.main()
