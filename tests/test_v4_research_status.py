"""Regression tests for offline V4 status and source-verification boundaries."""
import csv
import tempfile
import unittest
from pathlib import Path
from v4_research_status import status
from v4_evidence_audit import FEATURES, audit_evidence

class V4StatusTests(unittest.TestCase):
    def test_capture_after_kickoff_rejected(self):
        baseline = [{"game_id": "x", "season": "2025",
            "captured_at_utc": "2025-10-06T00:00:00Z",
            "kickoff_utc": "2025-10-05T20:00:00Z",
            "source_grading_status": "settled",
            "v3_home_margin": "3", "actual_home_margin": "7"}]
        with self.assertRaisesRegex(ValueError, "capture must precede"):
            audit_evidence(baseline, [])

    def test_local_source_url_rejected(self):
        baseline = [{"game_id": "x", "season": "2025",
            "captured_at_utc": "2025-10-05T10:00:00Z",
            "kickoff_utc": "2025-10-05T20:00:00Z",
            "source_grading_status": "settled",
            "v3_home_margin": "3", "actual_home_margin": "7"}]
        evidence = [{"game_id": "x", "feature": "wind_mph", "value": "10",
            "source_url": "https://localhost/private",
            "published_at_utc": "2025-10-05T08:00:00Z",
            "observed_at_utc": "2025-10-05T09:00:00Z"}]
        with self.assertRaisesRegex(ValueError, "public HTTPS"):
            audit_evidence(baseline, evidence)

    def test_baseline_rejects_pending_outcome_and_bad_status(self):
        base = {"game_id": "x", "season": "2026",
                "captured_at_utc": "2026-10-23T10:00:00Z",
                "kickoff_utc": "2026-10-24T20:00:00Z",
                "source_grading_status": "pending",
                "v3_home_margin": "4", "actual_home_margin": ""}
        with self.assertRaisesRegex(ValueError, "pending baseline"):
            audit_evidence([dict(base, actual_home_margin="7")], [])
        with self.assertRaisesRegex(ValueError, "grading status"):
            audit_evidence([dict(base, source_grading_status="unknown")], [])
        with self.assertRaisesRegex(ValueError, "v3_home_margin"):
            audit_evidence([dict(base, v3_home_margin="nan")], [])

    def test_malformed_source_urls_rejected_without_crashing(self):
        baseline = [{"game_id": "x", "season": "2025",
            "captured_at_utc": "2025-10-05T10:00:00Z",
            "kickoff_utc": "2025-10-05T20:00:00Z",
            "source_grading_status": "settled",
            "v3_home_margin": "3", "actual_home_margin": "7"}]
        for url in ("https://[bad-ipv6]/", "https://example.org:bad/report",
                    "https://example.org:8443/report"):
            with self.subTest(url=url):
                evidence = [{"game_id": "x", "feature": "wind_mph", "value": "10",
                    "source_url": url,
                    "published_at_utc": "2025-10-05T08:00:00Z",
                    "observed_at_utc": "2025-10-05T09:00:00Z"}]
                with self.assertRaisesRegex(ValueError, "public HTTPS"):
                    audit_evidence(baseline, evidence)

    def test_private_and_reserved_sources_rejected(self):
        baseline = [{"game_id": "x", "season": "2025",
            "captured_at_utc": "2025-10-05T10:00:00Z",
            "kickoff_utc": "2025-10-05T20:00:00Z",
            "source_grading_status": "settled",
            "v3_home_margin": "3", "actual_home_margin": "7"}]
        for url in ("https://192.168.1.5/report", "https://10.0.0.2/news",
                    "https://127.0.0.2/weather", "https://[::1]/",
                    "https://reports.local/status", "https://localhost.localhost/"):
            with self.subTest(url=url):
                evidence = [{"game_id": "x", "feature": "wind_mph", "value": "10",
                    "source_url": url,
                    "published_at_utc": "2025-10-05T08:00:00Z",
                    "observed_at_utc": "2025-10-05T09:00:00Z"}]
                with self.assertRaisesRegex(ValueError, "public HTTPS"):
                    audit_evidence(baseline, evidence)

    def test_missing_data_is_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = status(Path(tmp)/"missing.csv", Path(tmp)/"absent.csv")
        self.assertFalse(result["release_ready"])
        self.assertEqual(result["evaluations"], [])
        self.assertFalse(result["baseline_file_present"])

    def test_unverified_csv_cannot_authorize_calibration(self):
        with tempfile.TemporaryDirectory() as tmp:
            b, e = Path(tmp)/"baseline.csv", Path(tmp)/"evidence.csv"
            with b.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=["game_id", "season", "kickoff_utc",
                    "captured_at_utc", "source_grading_status", "actual_home_margin",
                    "v3_home_margin"])
                w.writeheader()
                w.writerow({"game_id": "123", "season": "2025",
                    "kickoff_utc": "2025-10-05T20:00:00Z",
                    "captured_at_utc": "2025-10-05T10:00:00Z",
                    "source_grading_status": "settled",
                    "actual_home_margin": "7", "v3_home_margin": "6"})
            with e.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=["game_id", "feature", "value",
                    "source_url", "published_at_utc", "observed_at_utc"])
                w.writeheader()
                for feature in FEATURES:
                    w.writerow({"game_id": "123", "feature": feature, "value": "0",
                        "source_url": "https://example.org/unverified",
                        "published_at_utc": "2025-10-04T12:00:00Z",
                        "observed_at_utc": "2025-10-05T09:00:00Z"})
            result = status(b, e)
        self.assertEqual(result["baseline_rows"], 1)
        self.assertEqual(result["settled_baseline_rows"], 1)
        self.assertEqual(result["training_games_shortfall_minimum"], 199)
        self.assertEqual(result["holdout_games_shortfall_minimum"], 99)
        self.assertEqual(result["baseline_season_count"], 1)
        self.assertFalse(result["multi_season_baseline"])
        self.assertEqual(result["historical_season_gap"], 1)
        self.assertEqual(result["baseline_by_season"]["2025"]["settled_games"], 1)
        self.assertEqual(result["complete_settled_season_count"], 1)
        self.assertFalse(result["eligible_for_all_game_training"])
        self.assertEqual(result["complete_settled_games"], 1)
        self.assertEqual(result["missing_feature_cells"], 0)
        self.assertFalse(result["source_authenticity_verified"])
        self.assertFalse(result["release_ready"])
        self.assertEqual(result["evaluations"], [])

    def test_bad_baseline_rejected_without_feature_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            b = root/"baseline.csv"
            b.write_text(
                "game_id,season,kickoff_utc,captured_at_utc,source_grading_status,actual_home_margin,v3_home_margin\\n"
                "1,2025,2025-10-05T20:00:00Z,2025-10-06T10:00:00Z,settled,7,6\\n",
                encoding="utf-8")
            result = status(b, root/"missing_evidence.csv")
        self.assertIn("rejected", result["reason"])
        self.assertFalse(result["release_ready"])

    def test_future_publication_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            b, e = Path(tmp)/"baseline.csv", Path(tmp)/"evidence.csv"
            b.write_text("game_id,season,kickoff_utc,captured_at_utc,source_grading_status,actual_home_margin,v3_home_margin\n1,2025,2025-10-05T20:00:00Z,2025-10-05T10:00:00Z,settled,7,6\n")
            e.write_text("game_id,feature,value,source_url,published_at_utc,observed_at_utc\n1,qb_out_diff,1,https://example.org/news,2025-10-06T00:00:00Z,2025-10-06T00:00:00Z\n")
            result = status(b, e)
        self.assertIn("rejected", result["reason"])
        self.assertFalse(result["release_ready"])

if __name__ == "__main__":
    unittest.main()
