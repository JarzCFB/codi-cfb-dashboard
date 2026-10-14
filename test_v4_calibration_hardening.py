import unittest
from v4_calibration import evaluate_candidate


def row(gid, season, **changes):
    record = {"game_id": gid, "season": season,
              "captured_at_utc": f"{season}-10-01T12:00:00Z",
              "kickoff_utc": f"{season}-10-02T12:00:00Z",
              "actual_home_margin": 7, "v3_home_margin": 5,
              "qb_out_diff": 0, "key_players_out_diff": 0,
              "rest_days_diff": 0, "travel_miles_diff": 0,
              "wind_mph": 5, "neutral_site": 0}
    record.update(changes)
    return record


class CalibrationHardeningTests(unittest.TestCase):
    def setUp(self):
        self.rows = [row("train", 2024), row("holdout", 2025)]

    def test_research_only_valid_data(self):
        result = evaluate_candidate(self.rows, min_train=1, min_holdout=1)
        self.assertFalse(result["release_ready"])

    def test_invalid_rest_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_candidate([row("train", 2024, rest_days_diff=31),
                                self.rows[1]], min_train=1, min_holdout=1)

    def test_invalid_travel_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_candidate([row("train", 2024, travel_miles_diff=10001),
                                self.rows[1]], min_train=1, min_holdout=1)

    def test_invalid_key_player_fraction_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_candidate([row("train", 2024, key_players_out_diff=0.5),
                                self.rows[1]], min_train=1, min_holdout=1)

    def test_invalid_wind_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_candidate([row("train", 2024, wind_mph=201),
                                self.rows[1]], min_train=1, min_holdout=1)

    def test_boolean_sample_size_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_candidate(self.rows, min_train=True, min_holdout=1)

    def test_post_kickoff_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_candidate([row("train", 2024,
                                    captured_at_utc="2024-10-03T12:00:00Z"),
                                self.rows[1]], min_train=1, min_holdout=1)


if __name__ == "__main__":
    unittest.main()
