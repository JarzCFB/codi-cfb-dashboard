import unittest
from v4_calibration import evaluate_candidate, FEATURES

def data():
    result = []
    for season, count in ((2024, 6), (2025, 4)):
        for i in range(count):
            row = {"game_id": f"{season}-{i}", "season": season,
                   "kickoff_utc": f"{season}-10-10T19:00:00Z",
                   "captured_at_utc": f"{season}-10-10T12:00:00Z",
                   "actual_home_margin": i + 3, "v3_home_margin": i + 2}
            row.update(dict.fromkeys(FEATURES, 0))
            result.append(row)
    return result

class CalibrationTests(unittest.TestCase):
    def test_prior_season_training_and_holdout(self):
        report = evaluate_candidate(data(), min_train=6, min_holdout=4)
        self.assertEqual(report["training_games"], 6)
        self.assertEqual(report["holdout_games"], 4)
        self.assertEqual(report["holdout_season"], 2025)
        self.assertFalse(report["release_ready"])

    def test_missing_feature_fails_closed(self):
        rows = data()
        del rows[0]["qb_out_diff"]
        with self.assertRaisesRegex(ValueError, "missing"):
            evaluate_candidate(rows, 1, 1)

    def test_future_information_rejected(self):
        rows = data()
        rows[0]["captured_at_utc"] = rows[0]["kickoff_utc"]
        with self.assertRaisesRegex(ValueError, "post-kickoff"):
            evaluate_candidate(rows, 1, 1)

    def test_duplicate_game_rejected(self):
        rows = data()
        rows[1]["game_id"] = rows[0]["game_id"]
        with self.assertRaisesRegex(ValueError, "duplicate"):
            evaluate_candidate(rows, 1, 1)

    def test_single_season_rejected(self):
        rows = data()[:6]
        with self.assertRaisesRegex(ValueError, "earlier and later"):
            evaluate_candidate(rows, 1, 1)

if __name__ == "__main__":
    unittest.main()
