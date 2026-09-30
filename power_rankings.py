"""Build predictive FBS power rankings from the existing V2 ratings.

The power rating is neutral-field team strength in points.
This module does not change V1, V2, V3, prospective selections,
or any frozen game projections.
"""

from cfb_division_safety import FBS_SCHOOLS
from cfb_team_matching import canonical_school


def build_power_rankings(v2_ratings):
    """Return all FBS teams ranked by neutral-field V2 strength."""

    rows = []

    for school in FBS_SCHOOLS:
        team = canonical_school(school)

        rating = v2_ratings.get(team)

        rows.append(
            {
                "team": team,
                "power_rating": float(rating) if rating is not None else None,
            }
        )

    # Teams with ratings first, strongest to weakest.
    # Any FBS team without a rating goes to the bottom rather than
    # being silently removed from the rankings.
    rows.sort(
        key=lambda row: (
            row["power_rating"] is not None,
            row["power_rating"] if row["power_rating"] is not None else float("-inf"),
        ),
        reverse=True,
    )

    rank = 0
    for row in rows:
        if row["power_rating"] is not None:
            rank += 1
            row["rank"] = rank
        else:
            row["rank"] = None

    return rows
