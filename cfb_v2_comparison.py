"""Fail-closed, display-only V1/V2 comparison; never changes stored snapshots."""
from cfb_division_safety import matchup_status, model_allowed
from cfb_team_matching import match_rating
from cfb_v2_experimental import projected_margin


def comparison_rows(events, v1_ratings, v2_ratings, home_adv=2.5):
    """Return (eligible comparison rows, suppressed matchup rows)."""
    rows, suppressed = [], []
    for event in events:
        if not isinstance(event, dict):
            continue
        home, away = event.get('home_team'), event.get('away_team')
        if not home or not away:
            continue
        matchup = f'{away} @ {home}'
        status = matchup_status(home, away)
        if not model_allowed(home, away):
            suppressed.append({'Matchup': matchup, 'Division status': status})
            continue
        h, _, _ = match_rating(home, v1_ratings)
        a, _, _ = match_rating(away, v1_ratings)
        v1 = h - a + home_adv if h is not None and a is not None else None
        v2 = projected_margin(home, away, v2_ratings, home_adv)
        rows.append({'Matchup': matchup,
                     'V1 home margin': round(v1, 1) if v1 is not None else None,
                     'V2 home margin': round(v2, 1) if v2 is not None else None})
    return rows, suppressed
