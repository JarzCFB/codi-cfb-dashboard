import unittest
from v4_readiness import readiness_report

class ReadinessTests(unittest.TestCase):
    def test_no_evidence_is_research_only(self):
        baseline = [{"game_id":"g", "season":2026, "source_grading_status":"settled"}]
        audit = {"complete_rows": [], "source_authenticity_verified": False}
        report = readiness_report(baseline, audit)
        self.assertFalse(report["release_ready"])
        self.assertEqual(report["complete_settled_feature_games"], 0)
        self.assertFalse(next(c for c in report["checks"] if c["gate"]=="training_sample")["passed"])

    def test_many_claims_never_unlock_release(self):
        baseline = [{"game_id":str(i), "season":2025 if i<250 else 2026, "source_grading_status":"settled"} for i in range(400)]
        complete = [{"season":r["season"]} for r in baseline]
        report = readiness_report(baseline, {"complete_rows":complete, "source_authenticity_verified":False})
        self.assertTrue(next(c for c in report["checks"] if c["gate"]=="holdout_sample")["passed"])
        self.assertFalse(report["release_ready"])
        self.assertFalse(next(c for c in report["checks"] if c["gate"]=="verified_evidence")["passed"])

if __name__ == "__main__":
    unittest.main()
