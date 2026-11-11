import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from v3_weekly_lock import asof_rows, lock_window, save_lock

TUES = datetime(2026, 11, 17, 14, 0, tzinfo=timezone.utc)
SAT = datetime(2026, 11, 14, 14, 0, tzinfo=timezone.utc)


class WeeklyLockTests(unittest.TestCase):
    def test_central_schedule(self):
        self.assertEqual(lock_window(TUES)[0], "weekday")
        self.assertEqual(lock_window(SAT)[0], "saturday")
        with self.assertRaises(ValueError):
            lock_window(datetime(2026, 11, 17, 13, 0, tzinfo=timezone.utc))

    def test_every_game_including_missing_quotes(self):
        games = [{"id": 1, "startDate": "2026-11-18T01:00:00Z",
                  "homeTeam": "Toledo", "awayTeam": "Akron", "seasonType": "regular"},
                 {"id": 2, "startDate": "2026-11-19T01:00:00Z",
                  "homeTeam": "Ohio", "awayTeam": "Miami (OH)", "seasonType": "regular"},
                 {"id": 3, "startDate": "2026-11-21T18:00:00Z",
                  "homeTeam": "Nebraska", "awayTeam": "Iowa", "seasonType": "regular"}]
        rows = asof_rows(TUES, games, [], {})
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["decision"] == "PASS" for r in rows))
        self.assertTrue(all(r["reason"] == "no_live_spread_quote" for r in rows))

    def test_append_only_lock(self):
        rows = [dict(game_id="1", kickoff_utc="2026-11-18T01:00:00Z",
                     decision="PASS")]
        with tempfile.TemporaryDirectory() as d:
            target, digest = save_lock(TUES, rows, root=Path(d))
            self.assertTrue(target.exists())
            self.assertEqual(len(digest), 64)
            with self.assertRaises(FileExistsError):
                save_lock(TUES, rows, root=Path(d))


if __name__ == "__main__":
    unittest.main()
