"""Regression checks for 2026 FBS safety classification."""
import unittest
from cfb_division_safety import matchup_status
from cfb_team_matching import match_rating

class DivisionSafetyTests(unittest.TestCase):
    def test_legitimate_fbs_matchups(self):
        for home, away in [
            ('UCF Knights', 'TCU Horned Frogs'),
            ('BYU Cougars', 'TCU Horned Frogs'),
            ('Tulane Green Wave', 'Southern Mississippi Golden Eagles'),
            ('Miami Hurricanes', 'Central Michigan Chippewas'),
            ('Miami (OH) RedHawks', 'UConn Huskies'),
            ('UMass Minutemen', 'Sacramento State Hornets'),
            ('Sacramento State Hornets', 'North Dakota State Bison'),
        ]:
            with self.subTest(home=home, away=away):
                self.assertEqual(matchup_status(home, away), 'FBS vs FBS')

    def test_fcs_suppression(self):
        for home, away in [
            ('Rutgers Scarlet Knights', 'Howard Bison'),
            ('Eastern Michigan Eagles', 'Lindenwood Lions'),
            ('East Carolina Pirates','North Carolina Central Eagles'),
            ('North Texas Mean Green','Houston Baptist Huskies'),
            ('North Texas Mean Green','Houston Christian Huskies'),
        ]:
            with self.subTest(home=home, away=away):
                self.assertNotEqual(matchup_status(home, away), 'FBS vs FBS')

    def test_known_fcs_cannot_be_matched_as_fbs_prefix(self):
        from cfb_division_safety import model_allowed
        self.assertFalse(model_allowed('East Carolina Pirates','North Carolina Central Eagles'))
        self.assertFalse(model_allowed('North Texas Mean Green','Houston Baptist Huskies'))

    def test_southern_miss_rating_alias(self):
        self.assertEqual(match_rating('Southern Mississippi Golden Eagles', {'southern miss': 3.0})[0], 3.0)

if __name__ == '__main__':
    unittest.main()
