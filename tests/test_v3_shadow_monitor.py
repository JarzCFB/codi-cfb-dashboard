"""Read-only V3 shadow monitor regression checks."""
import unittest
from v3_shadow_monitor import build, recent_window, forward_shadow


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

    def test_build_preserves_unclassified_and_frozen_thresholds(self):
        rows = [row("2026-10-20T18:00:00Z", 6)]
        report = build(rows, [])
        self.assertEqual(report["unclassified_v3_count"], 1)
        self.assertEqual(report["edge_thresholds"]["5"]["wins"], 1)
        self.assertEqual(report["edge_thresholds"]["7"]["selections"], 0)
        self.assertIn("recent_settled_window", report)


if __name__ == "__main__":
    unittest.main()
