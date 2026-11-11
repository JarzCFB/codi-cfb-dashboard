import unittest
from v3_line_movement import home_spread, summarize, crossed_keys


def quote(at, side, spread, book="book_a", home="Ohio", away="Akron"):
    return dict(season="2026", home_team=home, away_team=away,
                kickoff_utc="2026-11-14T20:00:00Z",
                captured_at_utc=at, sportsbook_key=book, sportsbook=book,
                selection=side, spread=str(spread), capture_status="timestamped_live_quote")


class MovementTests(unittest.TestCase):
    def test_away_side_converts_to_home_spread(self):
        self.assertEqual(home_spread(quote("2026-11-12T12:00:00Z", "Akron", 7)), -7)

    def test_same_book_and_first_observed(self):
        rows = [quote("2026-11-12T12:00:00Z", "Ohio", -2.5),
                quote("2026-11-13T12:00:00Z", "Ohio", -5.5),
                quote("2026-11-13T12:00:00Z", "Ohio", -9.5, "book_b")]
        result = summarize(rows)
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0]["is_major"])
        self.assertEqual(result[0]["absolute_movement_points"], 3)
        self.assertEqual(result[0]["direction"], "TOWARD_HOME")
        self.assertEqual(result[0]["crossed_key_numbers"], "3.0")

    def test_no_cross_book_false_movement(self):
        rows = [quote("2026-11-12T12:00:00Z", "Ohio", -2, "book_a"),
                quote("2026-11-13T12:00:00Z", "Ohio", -7, "book_b")]
        self.assertEqual(summarize(rows), [])

    def test_no_future_quotes(self):
        rows = [quote("2026-11-12T12:00:00Z", "Ohio", -2),
                quote("2026-11-15T12:00:00Z", "Ohio", -8)]
        self.assertEqual(summarize(rows), [])

    def test_cross_key(self):
        self.assertEqual(crossed_keys(-2.5, -7.5), "3.0,7.0")


if __name__ == "__main__":
    unittest.main()
