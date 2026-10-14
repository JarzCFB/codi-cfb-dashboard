import unittest
from v4_holdout_robustness import paired_holdout_report


def row(game_id, season, actual, v3, v4):
    return {"game_id": game_id, "season": season,
            "kickoff_utc": f"{season}-10-02T12:00:00Z",
            "captured_at_utc": f"{season}-10-01T12:00:00Z",
            "actual_home_margin": actual,
            "v3_home_margin": v3, "v4_home_margin": v4}


class PairedHoldoutTests(unittest.TestCase):
    def test_improvement_and_release_stays_closed(self):
        rows = [row("train", 2024, 7, 3, 4)]
        rows += [row("a", 2025, 10, 4, 8), row("b", 2025, 0, 2, 2)]
        report = paired_holdout_report(rows, min_holdout_games=2)
        self.assertEqual(report["holdout_season"], 2025)
        self.assertEqual(report["v4_better_games"], 1)
        self.assertEqual(report["equal_error_games"], 1)
        self.assertAlmostEqual(report["paired_mean_improvement"], 2)
        self.assertFalse(report["release_ready"])

    def test_worse_v4(self):
        rows = [row("train", 2024, 0, 0, 0),
                row("hold", 2025, 0, 0, 10)]
        report = paired_holdout_report(rows, min_holdout_games=1)
        self.assertEqual(report["v3_better_games"], 1)
        self.assertLess(report["paired_mean_improvement"], 0)
        self.assertFalse(report["v4_positive_lower_bound"])

    def test_insufficient_holdout_rejected(self):
        with self.assertRaises(ValueError):
            paired_holdout_report([row("train", 2024, 0, 0, 0),
                                   row("hold", 2025, 0, 0, 0)], min_holdout_games=2)

    def test_duplicate_rejected(self):
        with self.assertRaises(ValueError):
            paired_holdout_report([row("same", 2024, 0, 0, 0),
                                   row("same", 2025, 0, 0, 0)], min_holdout_games=1)


if __name__ == "__main__":
    unittest.main()
