import unittest
from datetime import datetime,timezone,timedelta
from cfb_v2_experimental import build_v2,projected_margin

NOW=datetime(2026,9,26,22,tzinfo=timezone.utc)
def game(h,a,hp,ap,kick='2026-09-20T12:00:00Z',completed=True):
    return dict(homeTeam=h,awayTeam=a,homePoints=hp,awayPoints=ap,startDate=kick,completed=completed,seasonType='regular')

class V2Tests(unittest.TestCase):
    def test_prior_affects_early_season(self):
        prev=[game('Indiana','Purdue',40,10)]
        ratings,meta=build_v2(prev,[],NOW)
        self.assertGreater(ratings['indiana'],ratings['purdue'])
        self.assertEqual(meta['current_games'],0)
    def test_future_and_live_games_excluded(self):
        prev=[game('Indiana','Purdue',40,10)]
        live=[game('Purdue','Indiana',90,0,'2026-09-26T21:00:00Z'),game('Purdue','Indiana',90,0,'2026-09-26T12:00:00Z',False)]
        base,_=build_v2(prev,[],NOW)
        actual,meta=build_v2(prev,live,NOW)
        self.assertEqual(base,actual)
        self.assertEqual(meta['current_games'],0)
    def test_completed_old_game_updates(self):
        prev=[game('Indiana','Purdue',40,10)]
        current=[game('Purdue','Indiana',30,10,'2026-09-20T12:00:00Z')]
        before,_=build_v2(prev,[],NOW)
        after,meta=build_v2(prev,current,NOW)
        self.assertLess(after['indiana']-after['purdue'],before['indiana']-before['purdue'])
        self.assertEqual(meta['current_games'],1)
    def test_fcs_never_enters_model(self):
        prev=[game('Indiana','Purdue',40,10),game('East Carolina','North Carolina Central',100,0)]
        ratings,meta=build_v2(prev,[],NOW)
        self.assertNotIn('north carolina central',ratings)
        self.assertEqual(meta['previous_games'],1)
        self.assertIsNone(projected_margin('East Carolina Pirates','North Carolina Central Eagles',ratings))
    def test_unrated_and_ambiguous_suppressed(self):
        ratings,_=build_v2([],[],NOW)
        self.assertIsNone(projected_margin('Indiana Hoosiers','Purdue Boilermakers',ratings))
        self.assertIsNone(projected_margin('Howard Bison','Rutgers Scarlet Knights',{'rutgers':1}))
    def test_no_naive_asof(self):
        with self.assertRaises(ValueError):build_v2([],[],datetime(2026,9,26))

if __name__=='__main__':unittest.main()
