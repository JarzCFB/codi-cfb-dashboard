"""Offline regression tests for the five-part V3 audit."""
import unittest
from v3_five_part_audit import run, summary, side_spread

def pick(**updates):
    r = dict(model_version="v3", season="2026", game_id="g1",
             kickoff_utc="2026-11-14T20:00:00Z",
             captured_at_utc="2026-11-13T10:00:00Z",
             home_team="Home", away_team="Away", selection="Home",
             sportsbook_key="book", spread="-3.5", edge_points="5.2",
             grading_status="settled", selection_result="win",
             one_unit_profit="0.909091")
    r.update(updates)
    return r

def quote(**updates):
    r = dict(pick(), capture_status="timestamped_live_quote",
             captured_at_utc="2026-11-14T19:40:00Z",
             market_last_update_utc="2026-11-14T19:39:00Z",
             bookmaker_last_update_utc="2026-11-14T19:39:00Z",
             american_odds="-110", spread="-4")
    r.update(updates)
    return r

class TestFivePartAudit(unittest.TestCase):
    def test_threshold_and_spread(self):
        r = run([pick()], [quote()])
        self.assertEqual(r["part_1_thresholds"]["5"]["wins"], 1)
        self.assertEqual(r["part_3_spread_buckets"]["3_to_under_7"]["wins"], 1)
    def test_quote_and_clv(self):
        r = run([pick()], [quote()])
        self.assertEqual(r["part_2_line_validation"]["status_counts"]["VERIFIED"], 1)
        self.assertEqual(r["part_5_closing_line_proxy"]["average_clv_points"], 0.5)
    def test_extreme_movement_requires_review(self):
        r = run([pick()], [quote(spread="-12")])
        self.assertEqual(r["part_2_line_validation"]["status_counts"]["REVIEW_EXTREME_MOVE"], 1)
    def test_future_and_wrong_book_excluded(self):
        r = run([pick()], [quote(sportsbook_key="other"),
                            quote(captured_at_utc="2026-11-14T20:01:00Z")])
        self.assertEqual(r["part_2_line_validation"]["status_counts"]["UNVERIFIED_NO_MATCHING_LIVE_SNAPSHOT"], 1)
        self.assertEqual(r["part_5_closing_line_proxy"]["sample_size"], 0)
    def test_missing_weighting_not_faked(self):
        r = run([pick()], [])
        self.assertTrue(r["official_v3_unchanged"])
        self.assertTrue(r["part_4_recent_weighting"]["status"].startswith("NOT_RUN"))

if __name__ == "__main__":
    unittest.main()
