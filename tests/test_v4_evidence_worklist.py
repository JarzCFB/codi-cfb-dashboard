"""Offline tests for prioritized V4 evidence collection worklist."""
import csv
import tempfile
import unittest
from pathlib import Path
from v4_evidence_worklist import generate

class V4WorklistTests(unittest.TestCase):
    def test_missing_baseline_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(FileNotFoundError):
                generate(root/"absent.csv", root/"absent_evidence.csv", root/"out.csv")

    def test_post_capture_evidence_rejected_before_worklist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root/"baseline.csv"
            evidence = root/"evidence.csv"
            base.write_text(
                "game_id,season,kickoff_utc,captured_at_utc,source_grading_status,actual_home_margin,v3_home_margin\\n"
                "abc,2026,2026-10-24T20:00:00Z,2026-10-23T10:00:00Z,settled,7,4\\n",
                encoding="utf-8")
            evidence.write_text(
                "game_id,feature,value,source_url,published_at_utc,observed_at_utc\\n"
                "abc,wind_mph,10,https://example.org/weather,2026-10-23T12:00:00Z,2026-10-23T12:00:00Z\\n",
                encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "before V3 capture"):
                generate(base, evidence, root/"out.csv")
            self.assertFalse((root/"out.csv").exists())

    def test_missing_evidence_yields_six_unknowns(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root/"baseline.csv"
            base.write_text(
                "game_id,season,kickoff_utc,captured_at_utc,source_grading_status\n"
                "abc,2026,2026-10-24T20:00:00Z,2026-10-23T10:00:00Z,settled\n",
                encoding="utf-8")
            result = generate(base, root/"missing.csv", root/"out.csv")
            with (root/"out.csv").open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
        self.assertEqual(result["games"], 1)
        self.assertEqual(result["settled_games"], 1)
        self.assertEqual(result["missing_feature_cells"], 6)
        self.assertEqual(rows[0]["missing_feature_count"], "6")
        self.assertEqual(rows[0]["priority"], "settled")

if __name__ == "__main__":
    unittest.main()
