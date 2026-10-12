"""Shared, conservative Odds API -> CFBD school matching for dashboard and snapshots."""
import re
import unicodedata

# Map known sportsbook full names to CFBD's common school names.
ALIASES = {
 'appalachian state mountaineers':'appalachian state',
 'iowa hawkeyes':'iowa','michigan wolverines':'michigan',
 'liu sharks':'liu','florida international panthers':'fiu',
 'navy midshipmen':'navy','uab blazers':'uab',
 'ohio state buckeyes':'ohio state','oregon state beavers':'oregon state',
 'utep miners':'utep','rice owls':'rice','fresno state bulldogs':'fresno state',
 'stonehill skyhawks':'stonehill','ohio bobcats':'ohio',
 'troy trojans':'troy','utah state aggies':'utah state',
 'ucla bruins':'ucla','maryland terrapins':'maryland',
 'utah utes':'utah','iowa state cyclones':'iowa state',
 'william and mary tribe':'william & mary','duke blue devils':'duke',
 'hawaii rainbow warriors':'hawaii','army black knights':'army',
 'temple owls':'temple','nebraska cornhuskers':'nebraska',
 'michigan state spartans':'michigan state','san jose state spartans':'san jose state',
 'air force falcons':'air force',
 'nevada wolf pack':'nevada','nc state wolfpack':'nc state',
 'miami hurricanes':'miami','miami (fl) hurricanes':'miami',
 'miami (oh) redhawks':'miami (oh)','ole miss rebels':'ole miss',
 'lsu tigers':'lsu','ucf knights':'ucf','utsa roadrunners':'utsa',
 'unlv rebels':'unlv','usc trojans':'usc','smu mustangs':'smu',
 'uconn huskies':'uconn','umass minutemen':'umass',
 'louisiana ragin cajuns':'louisiana','florida atlantic owls':'florida atlantic',
 'middle tennessee blue raiders':'middle tennessee',
 'southern mississippi golden eagles':'southern miss',
 'southern miss golden eagles':'southern miss',
 'alabama crimson tide':'alabama','auburn tigers':'auburn',
 'georgia bulldogs':'georgia','tennessee volunteers':'tennessee',
 'texas longhorns':'texas','penn state nittany lions':'penn state',
 'notre dame fighting irish':'notre dame','mississippi state bulldogs':'mississippi state',
 'arizona wildcats':'arizona','washington state cougars':'washington state',
 'byu cougars':'byu','tcu horned frogs':'tcu',
 'ball state cardinals':'ball state','kent state golden flashes':'kent state',
 'texas a&m aggies':'texas a&m',
 'north carolina central eagles':'north carolina central',
 'houston baptist huskies':'houston christian',
'houston christian huskies':'houston christian',
'north dakota state bison':'north dakota state',
'sacramento state hornets':'sacramento state',
}
EQUIVALENTS = {
 'houston baptist':'houston christian',
 'north carolina central':'north carolina central',
 'florida international':'fiu','long island':'liu','long island university':'liu',
 'app state':'appalachian state','appalachian st':'appalachian state',
 'hawaii manoa':'hawaii','hawai i':'hawaii',
 'mississippi':'ole miss','southern california':'usc','central florida':'ucf',
 'texas san antonio':'utsa','nevada las vegas':'unlv',
 'connecticut':'uconn','massachusetts':'umass',
 'brigham young':'byu','southern methodist':'smu',
 'louisiana lafayette':'louisiana','ul lafayette':'louisiana',
 'miami florida':'miami','miami fl':'miami',
 'miami ohio':'miami (oh)','miami oh':'miami (oh)',
 'william and mary':'william & mary','w m':'william & mary',
 'penn st':'penn state','ohio st':'ohio state','iowa st':'iowa state',
 'michigan st':'michigan state','kansas st':'kansas state',
 'florida st':'florida state','colorado st':'colorado state',
 'georgia st':'georgia state','utah st':'utah state',
 'oregon st':'oregon state','fresno st':'fresno state',
}

def normalize(name):
    value=str(name or '').lower().replace('&',' and ')
    value=unicodedata.normalize('NFKD',value).encode('ascii','ignore').decode('ascii')
    return ' '.join(re.sub(r'[^a-z0-9]+',' ',value).split())

_NORMALIZED_EQUIVALENTS={normalize(k):normalize(v) for k,v in EQUIVALENTS.items()}
_NORMALIZED_ALIASES={normalize(k):normalize(v) for k,v in ALIASES.items()}

def canonical_school(name):
    n=normalize(name)
    return _NORMALIZED_EQUIVALENTS.get(n,n)

# A school-name prefix is permitted only when the remaining words are a
# recognized team nickname. Never infer a school from an arbitrary suffix:
# "Texas Southern" is NOT "Texas", and "Florida Atlantic" is NOT "Florida".
# Unknown nicknames fail closed until added as explicit ALIASES above.
KNOWN_NICKNAMES = frozenset({
    'aggies', 'anteaters', 'aztecs', 'badgers', 'bearcats', 'bears', 'beavers',
    'big green', 'bison', 'black bears', 'black knights', 'blazers', 'blue devils',
    'blue hens', 'blue raiders', 'bobcats', 'boilermakers', 'broncos', 'bruin',
    'bruins', 'buckeyes', 'buffaloes', 'bulldogs', 'bulls', 'cardinals',
    'cavaliers', 'chanticleers', 'chippewas', 'commodores', 'cougars', 'cowboys',
    'cyclones', 'demon deacons', 'ducks', 'eagles', 'falcons', 'fighting hawks',
    'fighting illini', 'fighting irish', 'flames', 'flyers', 'friars', 'gamecocks',
    'golden eagles', 'golden flashes', 'golden gophers', 'golden hurricane',
    'governors', 'green wave', 'greyhounds', 'grizzlies', 'hawkeyes', 'hilltoppers',
    'hokies', 'horned frogs', 'hornets', 'hurricanes', 'huskies', 'jaguars',
    'jayhawks', 'knights', 'lobos', 'longhorns', 'lumberjacks', 'mean green',
    'minutemen', 'monarchs', 'mountaineers', 'musketeers', 'mustangs', 'nittany lions',
    'owls', 'panthers', 'pirates', 'rainbow warriors', 'ragin cajuns', 'rams',
    'rattlers', 'razorbacks', 'red raiders', 'redhawks', 'rebels', 'roadrunners',
    'rockets', 'scarlet knights', 'seawolves', 'shockers', 'skyhawks', 'sooners',
    'spartans', 'sun devils', 'tar heels', 'terrapins', 'thundering herd',
    'tigers', 'trojans', 'tulane green wave', 'utes', 'vandals', 'vikings',
    'volunteers', 'warhawks', 'warriors', 'wildcats', 'wolf pack', 'wolfpack',
    'wolverines', 'yellow jackets', 'zips',
})
_NORMALIZED_NICKNAMES = frozenset(normalize(x) for x in KNOWN_NICKNAMES)


def match_rating(name, ratings):
    """Return (value, canonical school, method), rejecting uncertain matches."""
    n = normalize(name)
    target = canonical_school(_NORMALIZED_ALIASES.get(n, n))
    if target in ratings:
        return ratings[target], target, 'alias' if n in _NORMALIZED_ALIASES else 'exact'

    # Match an approved school followed by an approved *complete* nickname.
    # Longest-match selection prevents e.g. Georgia Southern Eagles -> Georgia.
    candidates = []
    for raw_school in ratings:
        school = normalize(raw_school)
        if len(school) < 5 or not n.startswith(school + ' '):
            continue
        suffix = n[len(school) + 1:]
        if suffix in _NORMALIZED_NICKNAMES:
            candidates.append(raw_school)
    if candidates:
        longest = max(len(normalize(s)) for s in candidates)
        matches = [s for s in candidates if len(normalize(s)) == longest]
        if len(matches) == 1:
            return ratings[matches[0]], matches[0], 'verified_nickname'
        return None, None, 'ambiguous'
    return None, None, 'missing_rating_or_alias'
