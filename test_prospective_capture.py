import tempfile
import unittest
from pathlib import Path
from prospective_capture import freeze, pick_rows

class ProspectiveTests(unittest.TestCase):
    def row(self,**changes):
        r=dict(season='2026',game_id='g1',kickoff_utc='2026-10-03T18:00:00Z',
               captured_at_utc='2026-10-03T10:00:00Z',home_team='Alabama Crimson Tide',
               away_team='Georgia Bulldogs',selection='Georgia Bulldogs',spread=10,
               american_odds=-110,projected_home_margin=3,division_status='FBS vs FBS',
               sportsbook_key='book1',sportsbook='Book 1',market_last_update_utc='2026-10-03T09:00:00Z',
               bookmaker_last_update_utc='2026-10-03T09:00:00Z')
        r.update(changes);return r
    def test_one_per_game_per_version(self):
        with tempfile.TemporaryDirectory() as d:
            ledger=Path(d)/'picks.csv'
            r=self.row();first=freeze([r,r],{'alabama':4,'georgia':0},ledger,{'previous_games':1,'current_games':2})
            self.assertEqual(len(first),2)
            self.assertEqual(freeze([r],{'alabama':4,'georgia':0},ledger,{}),[])
            self.assertEqual(len(ledger.read_text().splitlines()),3)
    def test_kickoff_cutoff(self):
        self.assertEqual(pick_rows([self.row(captured_at_utc='2026-10-03T13:00:00Z')],{}),{})
    def test_future_market_quote_rejected(self):
        self.assertEqual(pick_rows([self.row(market_last_update_utc='2026-10-03T11:00:00Z')],{}),{})
    def test_fcs_rejected(self):
        self.assertEqual(pick_rows([self.row(away_team='Houston Baptist Huskies',selection='Houston Baptist Huskies')],{}),{})
    def test_missing_v2_no_fake_projection(self):
        self.assertEqual(set(k[2] for k in pick_rows([self.row()],{})),{'v1'})
    def test_no_final_score_used(self):
        r=self.row(actual_home_margin=-50)
        self.assertEqual(len(pick_rows([r],{'alabama':4,'georgia':0})),2)

if __name__=='__main__':unittest.main()
