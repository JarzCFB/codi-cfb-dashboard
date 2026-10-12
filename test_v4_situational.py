import unittest
import pandas as pd
from cfb_v4_situational import review_games

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

if __name__ == "__main__":
    unittest.main()
