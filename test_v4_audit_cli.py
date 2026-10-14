import csv
import json
import tempfile
import unittest
from pathlib import Path

from v4_audit_cli import audit_local_files, main


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def baseline():
    return [{"game_id": "g1", "season": "2025",
             "captured_at_utc": "2025-10-01T12:00:00Z",
             "kickoff_utc": "2025-10-02T12:00:00Z",
             "v3_home_margin": "5", "actual_home_margin": "7",
             "source_grading_status": "settled",
             "home_team": "A", "away_team": "B"}]


def evidence():
    return [{"game_id": "g1", "feature": "wind_mph", "value": "10",
             "source_url": "https://example.org/weather",
             "published_at_utc": "2025-09-30T12:00:00Z",
             "observed_at_utc": "2025-10-01T10:00:00Z"}]


class AuditCLITests(unittest.TestCase):
    def test_empty_evidence_exports_six_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "base.csv"
            write_csv(base, baseline())
            summary, missing, queue = audit_local_files(base)
            self.assertEqual(summary["missing_feature_tasks"], 6)
            self.assertEqual(summary["review_claims"], 0)
            self.assertFalse(summary["release_ready"])
            self.assertEqual(len(missing.splitlines()), 7)
            self.assertEqual(len(queue.splitlines()), 1)

    def test_cli_writes_actionable_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            base, ev, out = (Path(tmp) / name for name in ("base.csv", "evidence.csv", "out"))
            write_csv(base, baseline())
            write_csv(ev, evidence())
            self.assertEqual(main(["--baseline", str(base), "--evidence", str(ev),
                                   "--output-dir", str(out)]), 0)
            summary = json.loads((out / "v4_audit_summary.json").read_text())
            self.assertEqual(summary["missing_feature_tasks"], 5)
            self.assertEqual(summary["review_claims"], 1)
            self.assertFalse(summary["source_authenticity_verified"])
            self.assertTrue((out / "v4_source_review_queue.csv").exists())

    def test_invalid_future_claim_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            base, ev, out = (Path(tmp) / name for name in ("base.csv", "evidence.csv", "out"))
            write_csv(base, baseline())
            bad = evidence()
            bad[0]["observed_at_utc"] = "2025-10-01T13:00:00Z"
            write_csv(ev, bad)
            with self.assertRaises(ValueError):
                main(["--baseline", str(base), "--evidence", str(ev),
                      "--output-dir", str(out)])
            self.assertFalse(out.exists())

    def test_reviews_without_evidence_rejected(self):
        with self.assertRaises(SystemExit):
            main(["--baseline", "missing.csv", "--reviews", "review.csv",
                  "--output-dir", "out"])


if __name__ == "__main__":
    unittest.main()
