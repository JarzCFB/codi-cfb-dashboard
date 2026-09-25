"""Conservative 2026 FBS eligibility gate for unvalidated cross-division predictions.
Unknown schools are suppressed, not assumed FCS. Review when FBS membership changes.
This does not improve or validate the underlying rating model.
"""
from cfb_team_matching import match_rating

FBS_SCHOOLS = frozenset('air force,akron,alabama,appalachian state,arizona,arizona state,arkansas,arkansas state,army,auburn,ball state,baylor,boise state,boston college,bowling green,buffalo,byu,california,central michigan,charlotte,cincinnati,clemson,coastal carolina,colorado,colorado state,duke,east carolina,eastern michigan,fiu,florida,florida atlantic,florida state,fresno state,georgia,georgia southern,georgia state,georgia tech,hawaii,houston,illinois,indiana,iowa,iowa state,jacksonville state,james madison,kansas,kansas state,kent state,kentucky,kennesaw state,liberty,louisiana,louisiana tech,louisville,lsu,marshall,maryland,memphis,miami,miami (oh),michigan,michigan state,middle tennessee,minnesota,mississippi state,missouri,navy,nc state,nebraska,nevada,new mexico,new mexico state,north carolina,north texas,northern illinois,northwestern,notre dame,ohio,ohio state,oklahoma,oklahoma state,old dominion,ole miss,oregon,oregon state,penn state,pittsburgh,purdue,rice,rutgers,sam houston,san diego state,san jose state,smu,south alabama,south carolina,south florida,southern miss,stanford,syracuse,temple,tennessee,texas,texas a&m,texas state,texas tech,toledo,troy,tulane,tulsa,uab,ucf,ucla,uconn,ul monroe,umass,unlv,usc,utah,utah state,utep,utsa,vanderbilt,virginia,virginia tech,wake forest,washington,washington state,west virginia,western kentucky,western michigan,wisconsin,wyoming,delaware,missouri state'.split(','))

def matchup_status(home, away):
    # Shared matcher resolves sportsbook mascot names and CFBD school aliases.
    dummy = {school: 0 for school in FBS_SCHOOLS}
    _, h, _ = match_rating(home, dummy)
    _, a, _ = match_rating(away, dummy)
    if h is not None and a is not None:
        return 'FBS vs FBS'
    return 'Unverified division / FCS: model suppressed'

def model_allowed(home, away):
    return matchup_status(home, away) == 'FBS vs FBS'
