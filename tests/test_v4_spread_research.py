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
    def test_season_holdout_remains_research_only(self):
        rows = [game(2024, i) for i in range(210)] + [game(2025, i) for i in range(110)]
        result = evaluate(rows, source_authenticity_verified=True)
        self.assertFalse(result["release_ready"])
        self.assertEqual(len(result["evaluations"]), 1)
        self.assertEqual(result["evaluations"][0]["holdout_season"], 2025)
        self.assertEqual(result["evaluations"][0]["holdout_games"], 110)
        self.assertTrue(isinstance(predict(fit(rows[:210]), rows[210]), float))

if __name__ == "__main__":
    unittest.main()
