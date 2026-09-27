import unittest
from datetime import datetime, timezone, timedelta
from grade_snapshots import grade
from snapshot_capture import iso

class GradingDiagnosticsTests(unittest.TestCase):
    def quote(self,kick):
        return dict(season='2026',game_id='fixture',home_team='Alabama Crimson Tide',away_team='Auburn Tigers',kickoff_utc=iso(kick),captured_at_utc=iso(kick-timedelta(days=1)),market_last_update_utc=iso(kick-timedelta(days=1,minutes=1)),spread='-3.5',american_odds='-110',projected_home_margin='5',sportsbook_key='test',selection='Alabama Crimson Tide')
    def test_upcoming_not_mislabeled_missing(self):
        r=self.quote(datetime.now(timezone.utc)+timedelta(days=2))
        _,stats,diag=grade([r],[])
        self.assertEqual(stats.get('upcoming_game'),1)
        self.assertEqual(diag[0]['reason'],'upcoming_game')
    def test_missing_past_game_is_flagged(self):
        r=self.quote(datetime.now(timezone.utc)-timedelta(days=3))
        _,stats,diag=grade([r],[])
        self.assertEqual(stats.get('no_matching_cfbd_game'),1)
    def test_completed_game_grades(self):
        k=datetime.now(timezone.utc)-timedelta(days=3)
        r=self.quote(k)
        g=dict(homeTeam='Alabama',awayTeam='Auburn',startDate=iso(k),completed=True,homePoints=24,awayPoints=17,id=1)
        rows,stats,_=grade([r],[g])
        self.assertEqual(stats['graded_games'],1)
        self.assertEqual(rows[0]['selection_result'],'win')

if __name__=='__main__':unittest.main()

class CanonicalScoreMatchingTests(unittest.TestCase):
    def test_mascot_and_cfbd_names_agree(self):
        from grade_snapshots import school
        for sportsbook,cfbd in [('Indiana Hoosiers','Indiana'),('Northwestern Wildcats','Northwestern'),('California Golden Bears','California'),('Clemson Tigers','Clemson'),('Purdue Boilermakers','Purdue'),('Notre Dame Fighting Irish','Notre Dame'),('Ohio State Buckeyes','Ohio State'),('Illinois Fighting Illini','Illinois')]:
            with self.subTest(sportsbook=sportsbook):
                self.assertEqual(school(sportsbook),school(cfbd))
    def test_fcs_not_misidentified_as_fbs(self):
        from grade_snapshots import school
        self.assertEqual(school('North Carolina Central Eagles'),'north carolina central')
        self.assertEqual(school('Houston Baptist Huskies'),'houston christian')
