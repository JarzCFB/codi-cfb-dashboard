import unittest
from v4_ensemble_validation import validate_ensemble


def row(season, i, actual, v1, v2):
    return {"season": season, "game_id": f"{season}-{i}", "actual_home_margin": actual,
            "v1_home_margin": v1, "v2_home_margin": v2}


class EnsembleValidationTests(unittest.TestCase):
    def test_holdout_is_not_used_for_weight_selection(self):
        train = [row(2024, i, 10, 0, 10) for i in range(100)]
        holdout = [row(2025, i, 0, 0, 10) for i in range(100)]
        report = validate_ensemble(train + holdout)
        self.assertEqual(report["selected_v2_weight"], 1.0)
        self.assertEqual(report["holdout_mae_selected"], 10)
        self.assertFalse(report["release_ready"])
        self.assertFalse(report["official_v3_equivalent"])

    def test_duplicate_rejected(self):
        train = [row(2024, i, 1, 2, 3) for i in range(100)]
        test = [row(2025, i, 1, 2, 3) for i in range(100)]
        with self.assertRaises(ValueError):
            validate_ensemble(train + test + [train[0]])

    def test_missing_season_rejected(self):
        with self.assertRaises(ValueError):
            validate_ensemble([row(2025, i, 1, 2, 3) for i in range(200)])

    def test_nan_rejected(self):
        train = [row(2024, i, 1, 2, 3) for i in range(100)]
        test = [row(2025, i, 1, 2, 3) for i in range(100)]
        test[0]["v1_home_margin"] = "nan"
        with self.assertRaises(ValueError):
            validate_ensemble(train + test)


if __name__ == "__main__":
    unittest.main()
