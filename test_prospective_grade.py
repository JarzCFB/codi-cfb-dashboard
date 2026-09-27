import unittest
from prospective_grade import grade_selections, summarize

BASE={'rule_version':'test','model_version':'v1','season':'2026','game_id':'abc','kickoff_utc':'2026-10-03T16:00:00Z','captured_at_utc':'2026-09-27T03:51:32Z','home_team':'Home','away_team':'Away','division_status':'FBS vs FBS','selection':'Away','sportsbook_key':'book','sportsbook':'Book','spread':'5.5','american_odds':'-110','projected_home_margin':'-1','edge_points':'4','market_last_update_utc':'2026-09-27T03:51:04Z'}
GAME={'homeTeam':'Home','awayTeam':'Away','startDate':'2026-10-03T16:00:00Z','completed':True,'homePoints':21,'awayPoints':17,'id':123}
class Tests(unittest.TestCase):
 def test_win_and_profit(self):
  r=grade_selections([BASE],[GAME])[0];self.assertEqual(r['selection_result'],'win');self.assertAlmostEqual(r['one_unit_profit'],.909091)
 def test_loss(self):
  r=grade_selections([{**BASE,'spread':'3.5'}],[GAME])[0];self.assertEqual(r['selection_result'],'loss')
 def test_push(self):
  r=grade_selections([{**BASE,'spread':'4'}],[GAME])[0];self.assertEqual(r['selection_result'],'push')
 def test_pending(self):
  self.assertEqual(grade_selections([BASE],[])[0]['grading_status'],'pending')
 def test_post_cutoff(self):
  self.assertEqual(grade_selections([{**BASE,'captured_at_utc':'2026-10-03T15:00:00Z'}],[GAME])[0]['grading_status'],'invalid_selection')
 def test_duplicate_model_game(self):
  rows=grade_selections([BASE,BASE],[GAME]);self.assertEqual(rows[1]['grading_status'],'invalid_selection')
 def test_separate_models(self):
  rows=grade_selections([BASE,{**BASE,'model_version':'v2'}],[GAME]);self.assertEqual(summarize(rows)['models']['v2']['wins'],1)
 def test_fcs(self):
  self.assertEqual(grade_selections([{**BASE,'division_status':'unverified'}],[GAME])[0]['grading_status'],'invalid_selection')
 def test_future_market(self):
  self.assertEqual(grade_selections([{**BASE,'market_last_update_utc':'2026-09-27T04:00:00Z'}],[GAME])[0]['grading_status'],'invalid_selection')
if __name__=='__main__':unittest.main()
