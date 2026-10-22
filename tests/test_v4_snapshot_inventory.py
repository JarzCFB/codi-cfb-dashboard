"""Snapshot inventory remains distinct from official V3 predictions."""
import csv
import tempfile
import unittest
from pathlib import Path
from v4_snapshot_inventory import inventory

class SnapshotInventoryTests(unittest.TestCase):
    def test_missing_directory_is_empty_and_research_only(self):
        with tempfile.TemporaryDirectory() as root:
            report = inventory(str(Path(root) / "missing"))
            self.assertEqual(report["snapshot_files"], 0)
            self.assertEqual(report["official_v3_predictions_recovered"], 0)
            self.assertFalse(report["release_ready"])

    def test_priced_fbs_games_require_valid_spread_and_odds(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "capture.csv"
            fields = ["captured_at_utc", "game_id", "kickoff_utc",
                      "sportsbook_key", "selection", "projected_home_margin",
                      "capture_status", "division_status", "spread", "american_odds"]
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                for gid, spread, odds in [
                    ("valid", "-3.5", "-110"), ("missing", "", "-110"),
                    ("bad_odds", "2.5", "50"), ("nan", "nan", "120")]:
                    writer.writerow(dict(captured_at_utc="2026-10-01T12:00:00Z",
                        game_id=gid, kickoff_utc="2026-10-02T20:00:00Z",
                        sportsbook_key="book", selection="Home",
                        projected_home_margin="2.5", capture_status="timestamped_live_quote",
                        division_status="FBS vs FBS", spread=spread, american_odds=odds))
            report = inventory(root)
            self.assertEqual(report["fbs_games_with_timestamped_quotes_at_least_6h_pregame"], 4)
            self.assertEqual(report["fbs_games_with_valid_prices_at_least_6h_pregame"], 1)
            self.assertEqual(report["six_hour_fbs_rows_without_valid_prices"], 3)
            self.assertEqual(report["official_v3_predictions_recovered"], 0)

    def test_fbs_six_hour_coverage_requires_division_and_live_quote(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "capture.csv"
            fields = ["captured_at_utc", "game_id", "kickoff_utc",
                      "sportsbook_key", "selection", "projected_home_margin",
                      "capture_status", "division_status"]
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                for gid, division, status in [
                    ("fbs", "FBS vs FBS", "timestamped_live_quote"),
                    ("other", "FBS vs FCS", "timestamped_live_quote"),
                    ("unknown", "", "timestamped_live_quote"),
                    ("not_live", "FBS vs FBS", "stale_quote")]:
                    writer.writerow(dict(captured_at_utc="2026-10-01T12:00:00Z",
                        game_id=gid, kickoff_utc="2026-10-02T20:00:00Z",
                        sportsbook_key="book", selection="Home",
                        projected_home_margin="2.5", capture_status=status,
                        division_status=division))
            report = inventory(root)
            self.assertEqual(report["distinct_games_captured_at_least_6h_before_kickoff"], 4)
            self.assertEqual(report["fbs_games_with_timestamped_quotes_at_least_6h_pregame"], 1)
            self.assertEqual(report["six_hour_rows_missing_division_status"], 1)
            self.assertEqual(report["six_hour_rows_not_fbs_vs_fbs"], 1)
            self.assertFalse(report["release_ready"])

    def test_missing_and_nonfinite_ratings_are_not_eligible(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "capture.csv"
            fields = ["captured_at_utc", "game_id", "kickoff_utc",
                      "sportsbook_key", "selection", "projected_home_margin",
                      "capture_status"]
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                for gid, projection in [("valid", "2.5"), ("missing", ""),
                                        ("nan", "nan"), ("infinite", "inf")]:
                    writer.writerow(dict(captured_at_utc="2026-10-01T12:00:00Z",
                        game_id=gid, kickoff_utc="2026-10-02T20:00:00Z",
                        sportsbook_key="book", selection="Home",
                        projected_home_margin=projection,
                        capture_status="timestamped_live_quote"))
            report = inventory(root)
            self.assertEqual(report["snapshot_quote_rows"], 4)
            self.assertEqual(report["invalid_ratings_projection_rows"], 3)
            self.assertEqual(report["distinct_pregame_game_ids"], 1)
            self.assertEqual(report["distinct_games_captured_at_least_6h_before_kickoff"], 1)
            self.assertEqual(report["official_v3_predictions_recovered"], 0)

    def test_future_bookmaker_and_ratings_timestamps_are_excluded(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "capture.csv"
            fields = ["captured_at_utc", "game_id", "kickoff_utc",
                      "sportsbook_key", "selection", "projected_home_margin",
                      "capture_status", "bookmaker_last_update_utc", "ratings_asof_utc"]
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                for gid, bookmaker, ratings in [
                    ("good", "2026-10-01T11:00:00Z", "2026-10-01T12:00:00Z"),
                    ("future_book", "2026-10-01T13:00:00Z", "2026-10-01T11:00:00Z"),
                    ("future_rating", "2026-10-01T11:00:00Z", "2026-10-01T13:00:00Z")]:
                    writer.writerow(dict(captured_at_utc="2026-10-01T12:00:00Z",
                        game_id=gid, kickoff_utc="2026-10-02T20:00:00Z",
                        sportsbook_key="book", selection="Home",
                        projected_home_margin="2.5", capture_status="timestamped_live_quote",
                        bookmaker_last_update_utc=bookmaker, ratings_asof_utc=ratings))
            report = inventory(root)
            self.assertEqual(report["bookmaker_update_after_capture_rows"], 1)
            self.assertEqual(report["ratings_asof_after_capture_rows"], 1)
            self.assertEqual(report["distinct_pregame_game_ids"], 1)
            self.assertEqual(report["invalid_rows_or_files"], 2)
            self.assertEqual(report["official_v3_predictions_recovered"], 0)

    def test_future_market_update_is_not_eligible(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "capture.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                fields = ["captured_at_utc", "game_id", "kickoff_utc",
                          "sportsbook_key", "selection", "projected_home_margin",
                          "capture_status", "market_last_update_utc"]
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                for gid, update in [
                    ("good", "2026-10-01T11:00:00Z"),
                    ("future", "2026-10-01T13:00:00Z")]:
                    writer.writerow(dict(captured_at_utc="2026-10-01T12:00:00Z",
                        game_id=gid, kickoff_utc="2026-10-02T20:00:00Z",
                        sportsbook_key="book", selection="Home",
                        projected_home_margin="2", capture_status="timestamped_live_quote",
                        market_last_update_utc=update))
            report = inventory(root)
            self.assertEqual(report["market_update_after_capture_rows"], 1)
            self.assertEqual(report["distinct_pregame_game_ids"], 1)
            self.assertEqual(report["distinct_games_captured_at_least_6h_before_kickoff"], 1)
            self.assertEqual(report["invalid_rows_or_files"], 1)

    def test_pregame_and_postgame_quotes_not_confused_with_v3(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "capture.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=[
                    "captured_at_utc", "game_id", "kickoff_utc", "sportsbook_key",
                    "selection", "projected_home_margin", "capture_status"])
                writer.writeheader()
                for gid, capture in [("a", "2026-10-01T12:00:00Z"),
                                     ("a", "2026-10-01T13:00:00Z"),
                                     ("b", "2026-10-02T15:00:00Z")]:
                    writer.writerow(dict(captured_at_utc=capture, game_id=gid,
                        kickoff_utc="2026-10-02T14:00:00Z",
                        sportsbook_key="book", selection="Home",
                        projected_home_margin="3.2", capture_status="timestamped_live_quote"))
            report = inventory(root)
            self.assertEqual(report["snapshot_quote_rows"], 3)
            self.assertEqual(report["distinct_game_ids"], 2)
            self.assertEqual(report["distinct_pregame_game_ids"], 1)
            self.assertEqual(report["invalid_rows_or_files"], 1)
            self.assertEqual(report["official_v3_predictions_recovered"], 0)

if __name__ == "__main__":
    unittest.main()
