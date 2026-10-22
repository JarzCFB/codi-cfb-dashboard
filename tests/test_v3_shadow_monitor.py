"""Read-only V3 shadow monitor regression checks."""
import unittest
from v3_shadow_monitor import build, recent_window, forward_shadow, classification_coverage, pregame_agreement_report


def row(kickoff, edge, result="win", units=0.9):
    return {
        "model_version": "v3", "season": "2026", "game_id": kickoff,
        "kickoff_utc": kickoff, "edge_points": str(edge),
        "grading_status": "settled", "selection_result": result,
        "one_unit_profit": str(units),
    }


class ShadowMonitorTests(unittest.TestCase):
    def test_recent_window_excludes_older_kickoffs(self):
        rows = [
            row("2026-09-01T18:00:00Z", 8),
            row("2026-10-15T18:00:00Z", 6),
            row("2026-10-20T18:00:00Z", 4, "loss", -1),
        ]
        report = recent_window(rows, days=14)
        self.assertEqual(report["edge_thresholds"]["3"]["settled"], 2)
        self.assertEqual(report["edge_thresholds"]["5"]["settled"], 1)
        self.assertEqual(report["edge_thresholds"]["7"]["settled"], 0)

    def test_invalid_edges_cannot_crash_research_report(self):
        bad = [row("2026-10-24T18:00:00Z", "NaN"),
               row("2026-10-24T19:00:00Z", "broken"),
               row("2026-10-24T20:00:00Z", 6)]
        result = build(bad, [])
        self.assertEqual(result["edge_thresholds"]["5"]["settled"], 1)
        self.assertEqual(result["forward_shadow_comparison"]["thresholds"]["5"]["settled"], 1)

    def test_forward_shadow_never_uses_pre_cutoff_results(self):
        rows = [
            row("2026-10-19T23:59:59Z", 8),
            row("2026-10-20T00:00:00Z", 6),
            row("2026-10-24T18:00:00Z", 4, "loss", -1),
        ]
        result = forward_shadow(rows)
        self.assertEqual(result["start_kickoff_utc"], "2026-10-20T00:00:00Z")
        self.assertEqual(result["thresholds"]["3"]["settled"], 2)
        self.assertEqual(result["thresholds"]["5"]["settled"], 1)
        self.assertEqual(result["thresholds"]["7"]["settled"], 0)

    def test_classification_coverage_distinguishes_missing_picks(self):
        v3 = [row("2026-10-20T18:00:00Z", 6)]
        report = classification_coverage(v3, [
            {"season": "2026", "game_id": v3[0]["game_id"], "model_version": "v1"},
        ], [])
        self.assertEqual(report["counts"]["MISSING_V2"], 1)
        self.assertEqual(report["unclassified_details"][0]["reason"], "MISSING_V2")
        self.assertIn("does not imply", report["unclassified_details"][0]["note"])

    def test_same_capture_agreement_accepts_only_original_v3(self):
        v3 = [row("2026-10-24T18:00:00Z", 6)]
        v3[0].update(captured_at_utc="2026-10-20T13:00:00Z",
                     projected_home_margin="8.1")
        evidence = [
            {"season": "2026", "game_id": v3[0]["game_id"],
             "captured_at_utc": "2026-10-20T13:00:00Z",
             "v3_margin": "8.1", "investigation_status": "PASS",
             "source": "same_capture_v3_frozen_quote"},
            {"season": "2026", "game_id": v3[0]["game_id"],
             "captured_at_utc": "2026-10-21T13:00:00Z",
             "v3_margin": "8.1", "investigation_status": "UNSTABLE",
             "source": "same_capture_v3_frozen_quote"},
        ]
        report = pregame_agreement_report(v3, evidence)
        self.assertEqual(report["covered_v3"], 1)
        self.assertEqual(report["rejected_evidence"], 1)
        self.assertEqual(report["status_performance"]["PASS"]["settled"], 1)
        self.assertNotIn("UNSTABLE", report["status_performance"])

    def test_new_frozen_agreement_valid_before_grading(self):
        frozen = row("2026-10-25T18:00:00Z", 5)
        frozen.update(captured_at_utc="2026-10-22T13:00:00Z",
                      projected_home_margin="7.2", grading_status="pending",
                      selection_result="", one_unit_profit="")
        evidence = [{"season": "2026", "game_id": frozen["game_id"],
                     "captured_at_utc": frozen["captured_at_utc"],
                     "v3_margin": "7.2", "investigation_status": "PASS",
                     "source": "same_capture_v3_frozen_quote"}]
        report = build([], [], selections=[frozen], pregame_evidence=evidence,
                       agreement_selections=[frozen])
        self.assertEqual(report["pregame_agreement"]["covered_v3"], 1)
        self.assertEqual(report["pregame_agreement"]["rejected_evidence"], 0)
        self.assertEqual(report["pregame_agreement"]["status_performance"]["PASS"]["pending"], 1)
        self.assertEqual(report["edge_thresholds"]["3"]["selections"], 0)

    def test_build_preserves_unclassified_and_frozen_thresholds(self):
        rows = [row("2026-10-20T18:00:00Z", 6)]
        report = build(rows, [])
        self.assertEqual(report["unclassified_v3_count"], 1)
        self.assertEqual(report["edge_thresholds"]["5"]["wins"], 1)
        self.assertEqual(report["edge_thresholds"]["7"]["selections"], 0)
        self.assertIn("recent_settled_window", report)


if __name__ == "__main__":
    unittest.main()
