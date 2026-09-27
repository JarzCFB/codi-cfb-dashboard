import unittest
from spread_audit import select_archived,side_result,historical_join
BASE=dict(season='2026',game_id='g1',kickoff_utc='2026-09-26T20:00:00Z',home_team='Home',away_team='Away',sportsbook_key='book',selection='Home',spread='-3.5',american_odds='-110',captured_at_utc='2026-09-26T12:00:00Z',market_last_update_utc='2026-09-26T11:59:00Z',projected_home_margin='10',actual_home_margin='7')
class TestAudit(unittest.TestCase):
 def test_one_pick_per_game(self):
  a=dict(BASE);b=dict(BASE,selection='Away',spread='3.5');self.assertEqual(len(select_archived([a,b])),1)
 def test_cutoff(self):self.assertEqual(select_archived([dict(BASE,captured_at_utc='2026-09-26T19:00:00Z')]),[])
 def test_stale_market_timestamp(self):self.assertEqual(select_archived([dict(BASE,market_last_update_utc='2026-09-26T13:00:00Z')]),[])
 def test_result(self):self.assertEqual(side_result(7,-3.5,True),'win')
 def test_no_outcome_in_selection(self):
  a=select_archived([BASE]);b=select_archived([dict(BASE,actual_home_margin='-100')]);self.assertEqual(a[0]['selection'],b[0]['selection'])
 def test_historical_requires_real_lines(self):
  g=[dict(game_id='1',season='2024',kickoff_utc='2024-09-07T20:00:00Z',home_team='A',away_team='B',actual_home_margin='7',v1_home_margin='10',v2_home_margin='12')]
  self.assertEqual(historical_join(g,[]),[])
  self.assertEqual(historical_join(g,[dict(game_id='1',captured_at_utc='2024-09-07T19:00:00Z',home_spread='-3',home_american_odds='-110',away_american_odds='-110')]),[])
if __name__=='__main__':unittest.main()
