"""Official, public college football availability report entry points.

These are discovery links, NOT a scraped or verified injury feed.
Conference coverage differs; absence from a report is not universal proof of health.
"""
from urllib.parse import urlparse

PUBLIC_AVAILABILITY_SOURCES = (
    {"conference": "Big Ten", "url": "https://bigten.org/", "coverage": "Conference games; locate the dated official player availability report", "automated": False},
    {"conference": "Pac-12", "url": "https://pac-12.com/news/2026/9/11/2026-football-reports.aspx", "coverage": "2026 conference matchups and certain participating nonconference matchups", "automated": False},
    {"conference": "Conference USA", "url": "https://conferenceusa.com/sports/2025/8/23/FB_0823254134.aspx", "coverage": "Official football availability reports; check the dated matchup", "automated": False},
    {"conference": "American", "url": "https://theamerican.org/sports/2026/8/6/football_player_availability.aspx", "coverage": "2026 football player availability reports", "automated": False},
    {"conference": "College Football Playoff", "url": "https://collegefootballplayoff.com/sports/2025/11/12/reports", "coverage": "Playoff participants; not a regular-season feed", "automated": False},
)

def public_source_directory():
    """Return independently reviewable source links, without fetching player status."""
    sources = [dict(item) for item in PUBLIC_AVAILABILITY_SOURCES]
    if len({item["conference"] for item in sources}) != len(sources):
        raise ValueError("duplicate source name")
    for item in sources:
        parsed = urlparse(item["url"])
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("invalid public source URL")
        if item["automated"]:
            raise ValueError("public source registry cannot imply automatic verification")
    return sources
