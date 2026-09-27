import unittest
from datetime import datetime, timezone
from backtest_v1_v2 import valid, v1_fit


def game(home='Alabama',away='Georgia',hc='fbs',ac='fbs'):
    return dict(completed=True,seasonType='regular',homeClassification=hc,
                awayClassification=ac,homePoints=24,awayPoints=17,
                homeTeam=home,awayTeam=away,startDate='2024-09-01T19:00:00Z')

class BacktestSafety(unittest.TestCase):
    def test_fbs(self): self.assertTrue(valid(game()))
    def test_fcs_excluded(self): self.assertFalse(valid(game(away='Howard',ac='fcs')))
    def test_future_excluded(self):
        g=game();g['completed']=False;self.assertFalse(valid(g))
    def test_missing_scores(self):
        g=game();g['homePoints']=None;self.assertFalse(valid(g))
    def test_v1_empty(self): self.assertEqual(v1_fit([]),{})
    def test_v1_projection(self):
        r=v1_fit([game()]);self.assertIn('alabama',r);self.assertIn('georgia',r)

if __name__=='__main__': unittest.main()
