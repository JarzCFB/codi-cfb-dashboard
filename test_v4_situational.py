import unittest
import pandas as pd
from cfb_v4_situational import review_games, standout_players, fetch_player_stats, evidence_coverage
from unittest.mock import patch, Mock

class V4Tests(unittest.TestCase):
    def test_unknown_player_status_not_mistaken_for_healthy(self):
        frame = pd.DataFrame([{"Game ID":"123","Matchup":"Away @ Home","Kickoff UTC":"2026-10-17","V3/final margin":3.5}])
        result = review_games(frame, [])
        self.assertIn("Not verified", result.iloc[0]["V4 verification"])
        self.assertEqual(result.iloc[0]["V3/final margin"], 3.5)

    def test_evidence_requires_source_and_timestamp(self):
        frame = pd.DataFrame([{"Game ID":"123","Matchup":"Away @ Home","Kickoff UTC":"2026-10-17","V3/final margin":3.5}])
        result = review_games(frame, [{"game_id":"123","team":"Home","factor":"star_player","player":"Example","position":"WR","status":"out","source":"","observed_at_utc":"2026-10-12T12:00:00Z"}])
        self.assertIn("Not verified", result.iloc[0]["V4 verification"])

    def test_unrelated_game_evidence_not_applied(self):
        frame = pd.DataFrame([{"Game ID":"123","Matchup":"Away @ Home","Kickoff UTC":"2026-10-17","V3/final margin":3.5}])
        evidence = [{"game_id":"other","team":"Home","factor":"quarterback","player":"Example",
                     "position":"QB","status":"out","source":"https://example.com/report",
                     "observed_at_utc":"2026-10-12T12:00:00Z"}]
        result = review_games(frame, evidence)
        self.assertIn("Not verified", result.iloc[0]["V4 verification"])

    def test_valid_game_specific_evidence(self):
        frame = pd.DataFrame([{"Game ID":"123","Matchup":"Nebraska @ Ohio State","Kickoff UTC":"2026-10-17T19:00:00Z","V3/final margin":3.5}])
        evidence = [{"game_id":"123","team":"Nebraska","factor":"quarterback",
                     "player":"Example","position":"QB","status":"questionable",
                     "source":"https://example.com/official",
                     "observed_at_utc":"2026-10-12T12:00:00Z"}]
        result = review_games(frame, evidence)
        self.assertIn("Source-linked report", result.iloc[0]["V4 verification"])
        self.assertEqual(result.iloc[0]["V3/final margin"], 3.5)

    def test_future_report_rejected(self):
        frame = pd.DataFrame([{"Game ID":"123","Matchup":"Away @ Home","Kickoff UTC":"2026-10-17T19:00:00Z","V3/final margin":3.5}])
        evidence = [{"game_id":"123","team":"Home","factor":"injury",
                     "source":"https://example.com/report",
                     "observed_at_utc":"2099-10-12T12:00:00Z"}]
        self.assertIn("Not verified", review_games(frame, evidence).iloc[0]["V4 verification"])

    def test_after_kickoff_evidence_is_rejected(self):
        frame = pd.DataFrame([{"Game ID":"123","Matchup":"Away @ Home","Kickoff UTC":"2026-10-17T19:00:00Z","V3/final margin":3.5}])
        evidence = [{"game_id":"123","team":"Home","factor":"injury","status":"out",
                     "source":"https://example.com/report",
                     "observed_at_utc":"2026-10-17T19:01:00Z"}]
        from datetime import datetime, timezone
        result = review_games(frame, evidence, asof=datetime(2026,10,18,tzinfo=timezone.utc))
        self.assertIn("Not verified", result.iloc[0]["V4 verification"])

    @patch("cfb_v4_situational.requests.get")
    def test_player_stats_provider_response(self, get):
        get.return_value = Mock()
        get.return_value.json.return_value = [
            {"player":"Test QB","category":"passing","statType":"YDS","stat":"2,350"}]
        stats, error = fetch_player_stats("test-key", 2026, "Nebraska")
        self.assertIsNone(error)
        self.assertEqual(stats[0]["value"], 2350)
        self.assertEqual(get.call_args.kwargs["params"]["team"], "Nebraska")

    def test_evidence_coverage(self):
        frame = pd.DataFrame([{"Game ID":"123","Matchup":"Away @ Home","Kickoff UTC":"2026-10-17T19:00:00Z","V3/final margin":3.5}])
        self.assertEqual(evidence_coverage(review_games(frame, []))["unverified"], 1)

    def test_season_stat_leaders_are_metric_specific(self):
        stats = [{"player":"A","category":"passing","stat_type":"YDS","value":2100},
                 {"player":"B","category":"rushing","stat_type":"YDS","value":800}]
        self.assertEqual([x["player"] for x in standout_players(stats)], ["A", "B"])

if __name__ == "__main__":
    unittest.main()
