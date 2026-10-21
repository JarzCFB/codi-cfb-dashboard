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
