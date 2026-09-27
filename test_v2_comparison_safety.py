import unittest
from cfb_v2_comparison import comparison_rows

class ComparisonSafetyTests(unittest.TestCase):
    def test_known_fcs_and_prefix_collision_excluded_from_both_models(self):
        events=[
            {'home_team':'North Texas Mean Green','away_team':'Houston Baptist Huskies'},
            {'home_team':'East Carolina Pirates','away_team':'North Carolina Central Eagles'},
            {'home_team':'Rutgers Scarlet Knights','away_team':'Howard Bison'},
            {'home_team':'Indiana Hoosiers','away_team':'Purdue Boilermakers'},
        ]
        ratings={'north texas':2,'houston':10,'east carolina':3,'north carolina':4,'rutgers':5,'indiana':6,'purdue':-2}
        rows, excluded=comparison_rows(events,ratings,ratings)
        self.assertEqual(len(rows),1)
        self.assertEqual(len(excluded),3)
        self.assertEqual(rows[0]['Matchup'],'Purdue Boilermakers @ Indiana Hoosiers')
        self.assertEqual(rows[0]['V1 home margin'],10.5)
    def test_unknown_team_suppressed_even_if_rating_exists(self):
        rows, excluded=comparison_rows([{'home_team':'North Texas','away_team':'Imaginary College'}],{'north texas':1,'imaginary college':2},{'north texas':1,'imaginary college':2})
        self.assertFalse(rows)
        self.assertEqual(len(excluded),1)
    def test_missing_ratings_not_invented(self):
        rows,excluded=comparison_rows([{'home_team':'Indiana Hoosiers','away_team':'Purdue Boilermakers'}],{}, {})
        self.assertEqual(len(rows),1)
        self.assertIsNone(rows[0]['V1 home margin'])
        self.assertIsNone(rows[0]['V2 home margin'])
        self.assertFalse(excluded)

if __name__=='__main__': unittest.main()
