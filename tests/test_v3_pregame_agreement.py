"""Regression checks for new, same-capture V3 research evidence."""
import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from prospective_capture import record_v3_agreement


class AgreementCaptureTests(unittest.TestCase):
    def test_nonqualifying_v1_v2_still_recorded_for_new_v3(self):
        pick = dict(model_version='v3', season='2026', game_id='game-1',
                    kickoff_utc='2026-10-24T18:00:00Z',
                    captured_at_utc='2026-10-20T13:00:00Z',
                    home_team='Home', away_team='Away', selection='Home',
                    sportsbook_key='book', spread=-3.5, american_odds=-110,
                    projected_home_margin=8.1)
        quote = dict(season='2026', game_id='game-1',
                     captured_at_utc=pick['captured_at_utc'],
                     selection='Home', sportsbook_key='book',
                     home_team='Home', away_team='Away', american_odds=-110,
                     spread=-3.5, projected_home_margin=7.0)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'v3_pregame_agreement.csv'
            with patch('prospective_capture.projected_margin', return_value=5.0):
                self.assertEqual(record_v3_agreement([pick], [quote], {}, {}, path), 1)
                self.assertEqual(record_v3_agreement([pick], [quote], {}, {}, path), 0)
            with path.open(newline='', encoding='utf-8') as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['investigation_status'], 'PASS')
            self.assertEqual(rows[0]['v1_margin'], '7.0')
            self.assertEqual(rows[0]['v2_margin'], '5.0')

    def test_no_new_v3_never_writes_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'evidence.csv'
            self.assertEqual(record_v3_agreement([], [], {}, {}, path), 0)
            self.assertFalse(path.exists())

    def test_mismatched_source_quote_rejected(self):
        pick = dict(model_version='v3', season='2026', game_id='g',
                    kickoff_utc='2026-10-24T18:00:00Z',
                    captured_at_utc='2026-10-20T13:00:00Z',
                    home_team='Home', away_team='Away', selection='Home',
                    sportsbook_key='book', spread=-3.5,
                    projected_home_margin=8.1)
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                record_v3_agreement([pick], [], {}, {}, Path(folder) / 'evidence.csv')


if __name__ == '__main__':
    unittest.main()
