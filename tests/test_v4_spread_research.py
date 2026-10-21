"""Offline guardrails for V4 research-only spread adjustments."""
import unittest
from v4_spread_research import evaluate, fit, predict, MIN_TRAIN
from v4_evidence_audit import FEATURES

def game(season, i):
    row = {"season": season, "v3_home_margin": float(i % 11 - 5),
           "actual_home_margin": float(i % 11 - 5) + (1 if i % 2 else -1)}
    row.update({f: float((i + j) % 5) for j, f in enumerate(FEATURES)})
    return row

class V4SpreadResearchTests(unittest.TestCase):
    def test_unverified_evidence_cannot_fit(self):
        rows = [game(2024, i) for i in range(210)] + [game(2025, i) for i in range(110)]
        result = evaluate(rows, source_authenticity_verified=False)
        self.assertFalse(result["release_ready"])
        self.assertEqual(result["evaluations"], [])
    def test_insufficient_training_fails_closed(self):
        with self.assertRaises(ValueError):
            fit([game(2024, 1)])
    def test_missing_feature_fails_closed(self):
        rows = [game(2024, i) for i in range(210)] + [game(2025, i) for i in range(110)]
        del rows[0]["wind_mph"]
        with self.assertRaisesRegex(ValueError, "missing or nonfinite"):
            evaluate(rows, source_authenticity_verified=True)

    def test_season_holdout_remains_research_only(self):
        rows = [game(2024, i) for i in range(210)] + [game(2025, i) for i in range(110)]
        result = evaluate(rows, source_authenticity_verified=True)
        self.assertFalse(result["release_ready"])
        self.assertEqual(len(result["evaluations"]), 1)
        self.assertEqual(result["evaluations"][0]["holdout_season"], 2025)
        self.assertEqual(result["evaluations"][0]["holdout_games"], 110)
        self.assertIn("v3_rmse", result["evaluations"][0])
        self.assertIn("v4_rmse", result["evaluations"][0])
        self.assertIsInstance(result["evaluations"][0]["both_error_metrics_improved"], bool)
        self.assertFalse(result["evaluations"][0]["holdout_improvement_claim_allowed"])
        self.assertTrue(isinstance(predict(fit(rows[:210]), rows[210]), float))

if __name__ == "__main__":
    unittest.main()
