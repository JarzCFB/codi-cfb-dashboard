import unittest
from v4_historical_gap import historical_gap_report


def backtest(season, gid):
    return {"season": str(season), "game_id": gid, "actual_home_margin": "10",
            "v1_home_margin": "4", "v2_home_margin": "7"}


def graded(season, gid, status="settled"):
    return {"season": str(season), "game_id": gid, "model_version": "v3",
            "grading_status": status}


class HistoricalGapTests(unittest.TestCase):
    def test_seasons_are_not_falsely_joined(self):
        report = historical_gap_report(
            [backtest(2024, "a"), backtest(2025, "b")],
            [graded(2026, "c"), graded(2026, "d", "pending")])
        self.assertEqual(report["historical_v1_v2"]["games_by_season"], {2024: 1, 2025: 1})
        self.assertEqual(report["prospective_v3"]["settled_by_season"], {2026: 1})
        self.assertFalse(report["v4_vs_v3_comparison_possible"])
        self.assertFalse(report["release_ready"])

    def test_duplicate_historical_game_rejected(self):
        with self.assertRaises(ValueError):
            historical_gap_report([backtest(2024, "a")] * 2, [graded(2026, "c")])

    def test_duplicate_v3_game_rejected(self):
        with self.assertRaises(ValueError):
            historical_gap_report([backtest(2024, "a")], [graded(2026, "c")] * 2)

    def test_nonfinite_rejected(self):
        with self.assertRaises(ValueError):
            historical_gap_report([dict(backtest(2024, "a"), v2_home_margin="nan")],
                                  [graded(2026, "c")])


if __name__ == "__main__":
    unittest.main()
