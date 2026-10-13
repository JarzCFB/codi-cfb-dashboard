import unittest
from v4_walkforward import evaluate_walkforward

def sample():
    return [
        {"game_id":"one","season":2024,"kickoff_utc":"2024-10-10T19:00:00Z",
         "captured_at_utc":"2024-10-10T12:00:00Z","actual_home_margin":7,
         "v3_home_margin":3,"v4_home_margin":5},
        {"game_id":"two","season":2025,"kickoff_utc":"2025-10-10T19:00:00Z",
         "captured_at_utc":"2025-10-10T12:00:00Z","actual_home_margin":10,
         "v3_home_margin":4,"v4_home_margin":8},
    ]

class WalkforwardTests(unittest.TestCase):
    def test_held_out_later_season(self):
        result = evaluate_walkforward(sample(), min_holdout_games=1)
        self.assertEqual(result["holdout_season"], 2025)
        self.assertEqual(result["holdout_games"], 1)
        self.assertEqual(result["v3_mae"], 6)
        self.assertEqual(result["v4_mae"], 2)
        self.assertTrue(result["v4_beats_v3_on_mae"])
        self.assertFalse(result["release_ready"])

    def test_rejects_duplicate_games(self):
        rows = sample()
        rows[1]["game_id"] = "one"
        with self.assertRaisesRegex(ValueError, "duplicate"):
            evaluate_walkforward(rows, 1)

    def test_rejects_post_kickoff_snapshot(self):
        rows = sample()
        rows[1]["captured_at_utc"] = rows[1]["kickoff_utc"]
        with self.assertRaisesRegex(ValueError, "before kickoff"):
            evaluate_walkforward(rows, 1)

    def test_rejects_missing_heldout_sample(self):
        with self.assertRaisesRegex(ValueError, "insufficient"):
            evaluate_walkforward(sample(), 100)

    def test_rejects_nonfinite_margin(self):
        rows = sample()
        rows[1]["v4_home_margin"] = "nan"
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            evaluate_walkforward(rows, 1)

    def test_rejects_single_season(self):
        rows = sample()
        rows[0]["season"] = 2025
        with self.assertRaisesRegex(ValueError, "separate"):
            evaluate_walkforward(rows, 1)

if __name__ == "__main__":
    unittest.main()
