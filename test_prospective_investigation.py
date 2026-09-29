import unittest
from prospective_investigation import classify, build_new_cohorts, summarize

class TestInvestigation(unittest.TestCase):
    def test_thresholds_and_winner_cross(self):
        self.assertEqual(classify(10,12)[2],'PASS')
        self.assertEqual(classify(10,16)[2],'CAUTION')
        self.assertEqual(classify(10,21)[2],'UNSTABLE')
        self.assertEqual(classify(-1,1)[2],'UNSTABLE')

    def test_freezes_existing(self):
        existing=[{'season':'2026','game_id':'1','investigation_status':'PASS'}]
        selections=[
            {'season':'2026','game_id':'1','model_version':'v1','projected_home_margin':'1'},
            {'season':'2026','game_id':'1','model_version':'v2','projected_home_margin':'20'},
        ]
        out=build_new_cohorts(selections,existing)
        self.assertEqual(out[0]['investigation_status'],'PASS')

    def test_summary_uses_v3(self):
        cohort=[{'season':'2026','game_id':'2','investigation_status':'PASS','v3_margin':'7'}]
        graded=[{'season':'2026','game_id':'2','model_version':'v3','grading_status':'settled','actual_home_margin':'10'}]
        s=summarize(cohort,graded)['groups']['PASS']
        self.assertEqual(s['settled_games'],1)
        self.assertEqual(s['winner_accuracy'],1.0)
        self.assertEqual(s['margin_mae'],3.0)

if __name__=='__main__': unittest.main()
