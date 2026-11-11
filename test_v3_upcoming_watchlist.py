import unittest
from datetime import datetime, timezone
from v3_upcoming_watchlist import watchlist

NOW=datetime(2026,11,11,16,tzinfo=timezone.utc)

def movement():
    return dict(kickoff_utc="2026-11-14T20:00:00Z",home_team="Ohio",
                away_team="Akron",sportsbook="Book",sportsbook_key="book",
                first_home_spread=-3,latest_home_spread=-6,
                movement_points=-3,severity="SIGNIFICANT_3_PLUS",
                crossed_key_numbers="7.0",latest_seen_utc="2026-11-11T15:00:00Z")

def locked():
    return dict(kickoff_utc="2026-11-14T20:00:00Z",home_team="Ohio",
                away_team="Akron",sportsbook_key="book",decision="PLAY",
                selection="Ohio",spread=-3,edge_points=4)

class WatchlistTests(unittest.TestCase):
    def test_locked_edge_drops_below_three(self):
        r=watchlist([movement()],[locked()],NOW)
        self.assertEqual(r[0]["current_edge_at_same_book"],1)
        self.assertEqual(r[0]["lock_status"],"EDGE_BELOW_3")
    def test_other_book_does_not_fake_current_edge(self):
        l=locked();l["sportsbook_key"]="other"
        r=watchlist([movement()],[l],NOW)
        self.assertEqual(r[0]["lock_status"],"OTHER_SPORTSBOOK")
        self.assertEqual(r[0]["current_edge_at_same_book"],"")
    def test_only_upcoming(self):
        m=movement();m["kickoff_utc"]="2026-11-10T20:00:00Z"
        self.assertEqual(watchlist([m],[],NOW),[])

if __name__=="__main__":
    unittest.main()
