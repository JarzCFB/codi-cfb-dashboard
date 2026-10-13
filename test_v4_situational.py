import unittest
import io
import pandas as pd
from cfb_v4_situational import review_games, standout_players, fetch_player_stats, evidence_coverage, parse_evidence_csv, player_availability
from unittest.mock import patch, Mock

class V4Tests(unittest.TestCase):
    def test_empty_game_list_has_stable_columns(self):
        frame = pd.DataFrame(columns=["Game ID", "Matchup", "Kickoff UTC", "V3/final margin"])
        result = review_games(frame, [])
        self.assertTrue(result.empty)
        self.assertIn("V4 verification", result.columns)
        self.assertIn("V4 adjusted margin", result.columns)

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

    def test_team_nickname_alias_matches(self):
        frame = pd.DataFrame([{"Game ID":"123","Matchup":"Nebraska Cornhuskers @ Ohio State Buckeyes",
                               "Kickoff UTC":"2026-10-17T19:00:00Z","V3/final margin":3.5}])
        evidence = [{"game_id":"123","team":"Nebraska","factor":"quarterback",
                     "source":"https://example.com/report",
                     "observed_at_utc":"2026-10-12T12:00:00Z"}]
        result = review_games(frame, evidence)
        self.assertIn("Source-linked report", result.iloc[0]["V4 verification"])

    def test_similar_team_names_do_not_cross_match(self):
        frame = pd.DataFrame([{"Game ID":"123","Matchup":"Texas Southern @ Texas State",
                               "Kickoff UTC":"2026-10-17T19:00:00Z","V3/final margin":3.5}])
        evidence = [{"game_id":"123","team":"Texas","factor":"quarterback",
                     "source":"https://example.com/report",
                     "observed_at_utc":"2026-10-12T12:00:00Z"}]
        result = review_games(frame, evidence)
        self.assertIn("Not verified", result.iloc[0]["V4 verification"])

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

    def test_csv_unknown_factor_rejected(self):
        header = "game_id,team,player,position,factor,status,source,observed_at_utc,notes,impact_points"
        row = "123,Nebraska,Example,QB,unlisted,questionable,https://example.com/report,2026-10-12T12:00:00Z,practice,"
        with self.assertRaises(ValueError):
            parse_evidence_csv(io.StringIO(header + "\n" + row + "\n"))

    def test_csv_schema_required(self):
        with self.assertRaises(ValueError):
            parse_evidence_csv(io.StringIO("team,factor\nNebraska,injury\n"))

    def test_csv_parses_source_linked_report(self):
        header = "game_id,team,player,position,factor,status,source,observed_at_utc,notes,impact_points"
        row = "123,Nebraska,Example,QB,quarterback,questionable,https://example.com/report,2026-10-12T12:00:00Z,practice,"
        records = parse_evidence_csv(io.StringIO(header + "\n" + row + "\n"))
        self.assertEqual(records[0]["team"], "Nebraska")

    def test_player_availability_never_inferred_from_stats(self):
        self.assertIn("Unknown", player_availability("Player A", "Nebraska", [], "123"))

    def test_conflicting_player_reports_require_review(self):
        reports = [
            {"game_id":"123", "team":"Nebraska", "player":"Player A", "factor":"injury",
             "status":status, "source":"https://example.com/report"}
            for status in ("out", "available")
        ]
        self.assertIn("Conflicting", player_availability("Player A", "Nebraska", reports, "123"))

    def test_evidence_coverage(self):
        frame = pd.DataFrame([{"Game ID":"123","Matchup":"Away @ Home","Kickoff UTC":"2026-10-17T19:00:00Z","V3/final margin":3.5}])
        self.assertEqual(evidence_coverage(review_games(frame, []))["unverified"], 1)

    def test_season_stat_leaders_are_metric_specific(self):
        stats = [{"player":"A","category":"passing","stat_type":"YDS","value":2100},
                 {"player":"B","category":"rushing","stat_type":"YDS","value":800}]
        self.assertEqual([x["player"] for x in standout_players(stats)], ["A", "B"])

if __name__ == "__main__":
    unittest.main()
