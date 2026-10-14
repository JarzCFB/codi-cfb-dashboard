import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

from v4_repo_baseline import repository_v3_baseline, baseline_csv, baseline_diagnostics, main


def row(model="v3", gid="g1"):
    return {"model_version": model, "game_id": gid, "season": "2026",
            "kickoff_utc": "2026-10-03T12:00:00Z",
            "captured_at_utc": "2026-09-27T12:00:00Z",
            "projected_home_margin": "7", "grading_status": "settled",
            "actual_home_margin": "3", "home_team": "A", "away_team": "B"}


class RepoBaselineTests(unittest.TestCase):
    def test_filters_before_dedup(self):
        recovered = repository_v3_baseline([row("v1"), row("v2"), row()])
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0]["v3_home_margin"], 7)

    def test_duplicate_v3_rejected(self):
        with self.assertRaises(ValueError):
            repository_v3_baseline([row(), row()])

    def test_pending_margin_blank_in_csv(self):
        r = row()
        r["grading_status"] = "pending"
        r["actual_home_margin"] = ""
        recovered = repository_v3_baseline([r])
        parsed = list(csv.DictReader(io.StringIO(baseline_csv(recovered))))
        self.assertEqual(parsed[0]["actual_home_margin"], "")

    def test_repo_csv_generates_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, out = Path(tmp) / "graded.csv", Path(tmp) / "out"
            with source.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(row()))
                writer.writeheader()
                writer.writerows([row("v1"), row()])
            self.assertEqual(main(["--source", str(source), "--output-dir", str(out)]), 0)
            result = json.loads((out / "v4_repo_audit_summary.json").read_text())
            self.assertEqual(result["baseline"]["total_games"], 1)
            self.assertEqual(result["missing_feature_tasks"], 6)
            self.assertFalse(result["release_ready"])
            self.assertTrue((out / "v4_recovered_v3_baseline.csv").exists())

    def test_diagnostics_block_single_season(self):
        baseline = repository_v3_baseline([row()])
        diagnostics = baseline_diagnostics(baseline)
        self.assertEqual(diagnostics["games_by_season"], {2026: 1})
        self.assertEqual(diagnostics["settled_by_season"], {2026: 1})
        self.assertFalse(diagnostics["multiple_seasons_present"])
        self.assertFalse(diagnostics["eligible_for_walkforward"])

    def test_invalid_input_no_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, out = Path(tmp) / "graded.csv", Path(tmp) / "out"
            bad = row()
            bad["captured_at_utc"] = "2026-10-04T12:00:00Z"
            with source.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(bad))
                writer.writeheader()
                writer.writerow(bad)
            with self.assertRaises(ValueError):
                main(["--source", str(source), "--output-dir", str(out)])
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
