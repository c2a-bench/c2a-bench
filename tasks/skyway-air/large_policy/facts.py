"""Irregular station and country facts for skyway-arch, written as prose sentences.

The first version stated every station in the same 25 one-line fields; a builder parsed all 245 pages with a script and
packed them into ~5.6k tokens of coded rows. Here each station and country gets its own subset of fact types, each
fact carries its own condition or exception, and each is phrased one of several ways, so there are no shared columns
to encode: a builder has to read the pages (or have a model read them) and keep entity + condition + value per fact.

Everything is fixed per key (a hash), so a rerun gives the same facts. Stage changes re-draw a few facts of an entity
with a stage salt (changed_facts).
"""
import hashlib

REGIONS = ["Canada", "Mexico", "the Caribbean", "Central America", "South America", "Europe"]
DAYS = ["Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays", "Sundays"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]
LOUNGES = ["Harbor Lounge", "Cedar Club", "Meridian Rooms", "Northlight Lounge", "Atlas Lounge", "Saltwater Club",
           "Kestrel Lounge", "Juniper Room", "Bluepoint Lounge", "Tidewater Club"]
PARKING = ["ParkWell", "Lotline", "Kerbside Parking", "SkyPark Partners", "Gatepark", "Northgate Parking",
           "Runway Park", "the airport's own car parks"]
TERMINALS = ["Terminal 1", "Terminal 2", "Terminal 3", "Terminal A", "Terminal B", "Terminal C", "Main Terminal",
             "North Terminal", "South Terminal", "East Concourse", "West Concourse"]
WIFI = ["{c}-Free", "{c} Airport Guest", "Fly{c}", "{c}-Public", "Connect{c}", "{c}Open"]


def h(key, n):
    return int(hashlib.sha256(key.encode()).hexdigest()[:12], 16) % n


def pick(key, options):
    return options[h(key, len(options))]


def hhmm(m):
    return f"{m // 60:02d}:{m % 60:02d}"


def t(key, lo, hi, step=15):
    """A time between lo and hi minutes after midnight, on a step."""
    return hhmm(lo + step * h(key, (hi - lo) // step + 1))


def n(key, lo, hi, step=1):
    return lo + step * h(key, (hi - lo) // step + 1)


# Each fact type: (name, applies to "all" / "intl" / "dom", list of phrasings). A phrasing is a function of
# (key, city, code) returning one sentence. Several phrasings per type, chosen per station, so no two pages read alike.
def _f(fn):
    return fn


STATION_TYPES = [
    ("checkin-close", "dom", [
        lambda k, c, x: f"At {c} ({x}), domestic check-in closes {n(k + 'a', 30, 60, 5)} minutes before departure, "
                        f"but {n(k + 'b', 60, 90, 5)} minutes for the first departure of the day.",
        lambda k, c, x: f"{c} closes domestic check-in {n(k + 'a', 30, 60, 5)} minutes ahead of departure; on "
                        f"{pick(k + 'd', DAYS)} it closes {n(k + 'b', 45, 75, 5)} minutes ahead.",
        lambda k, c, x: f"For domestic flights from {x}, the check-in cut-off is {n(k + 'a', 30, 60, 5)} minutes, "
                        f"except from {pick(k + 'm', MONTHS[:6])} to {pick(k + 'm2', MONTHS[6:])}, when it is "
                        f"{n(k + 'b', 45, 75, 5)} minutes.",
    ]),
    ("checkin-close-intl", "intl", [
        lambda k, c, x: f"At {c} ({x}), check-in closes {n(k + 'a', 60, 120, 15)} minutes before departure, and "
                        f"{n(k + 'b', 75, 150, 15)} minutes for flights to {pick(k + 'r', REGIONS)}.",
        lambda k, c, x: f"International check-in at {x} closes {n(k + 'a', 60, 120, 15)} minutes before departure; "
                        f"on {pick(k + 'd', DAYS)} it closes {n(k + 'b', 75, 135, 15)} minutes before.",
    ]),
    ("counters-open", "all", [
        lambda k, c, x: f"Skyway counters at {c} open at {t(k + 'a', 210, 360)} on weekdays and {t(k + 'b', 240, 420)} "
                        f"at weekends.",
        lambda k, c, x: f"The {x} check-in counters open at {t(k + 'a', 210, 360)}, except on {pick(k + 'd', DAYS)}, "
                        f"when they open at {t(k + 'b', 240, 420)}.",
        lambda k, c, x: f"At {c}, counters open {n(k + 'a', 90, 180, 15)} minutes before the first Skyway departure "
                        f"of the day.",
    ]),
    ("gate-close", "all", [
        lambda k, c, x: f"Gates at {c} close {n(k + 'a', 10, 20, 1)} minutes before departure for narrow-body aircraft "
                        f"and {n(k + 'b', 20, 35, 1)} minutes for wide-body aircraft.",
        lambda k, c, x: f"At {x} the gate closes {n(k + 'a', 10, 25, 1)} minutes before departure; at gates "
                        f"{n(k + 'g', 1, 9)} to {n(k + 'g2', 10, 30)} it closes {n(k + 'b', 15, 30, 1)} minutes before.",
    ]),
    ("terminal", "all", [
        lambda k, c, x: f"Skyway flies from {pick(k + 't', TERMINALS)} at {c}, check-in zone {pick(k + 'z', list('ABCDEFGHJK'))}.",
        lambda k, c, x: f"At {x}, Skyway check-in is in {pick(k + 't', TERMINALS)}; arrivals use "
                        f"{pick(k + 't2', TERMINALS)}.",
    ]),
    ("kiosks", "all", [
        lambda k, c, x: f"{c} has {n(k + 'a', 2, 14)} Skyway kiosks, {n(k + 'b', 1, 4)} of them airside.",
        lambda k, c, x: f"There are {n(k + 'a', 2, 14)} Skyway check-in kiosks at {x}; the ones near zone "
                        f"{pick(k + 'z', list('ABCDEF'))} print boarding passes only.",
    ]),
    ("lounge", "all", [
        lambda k, c, x: f"The lounge partner at {c} is {pick(k + 'l', LOUNGES)}, open {t(k + 'a', 270, 390)}-"
                        f"{t(k + 'b', 1140, 1410)}, and until {t(k + 'c', 1200, 1425)} on {pick(k + 'd', DAYS)}.",
        lambda k, c, x: f"At {x}, Skyway customers use {pick(k + 'l', LOUNGES)} in {pick(k + 't', TERMINALS)}; it "
                        f"opens at {t(k + 'a', 270, 390)} and closes at {t(k + 'b', 1140, 1410)}.",
        lambda k, c, x: f"{c} has no Skyway lounge partner from {pick(k + 'm', MONTHS)} to {pick(k + 'm2', MONTHS)}; "
                        f"the rest of the year it is {pick(k + 'l', LOUNGES)}.",
    ]),
    ("parking", "all", [
        lambda k, c, x: f"Parking at {c} is run by {pick(k + 'p', PARKING)}; its shuttle runs every "
                        f"{n(k + 'a', 5, 30, 5)} minutes.",
        lambda k, c, x: f"The {x} parking partner is {pick(k + 'p', PARKING)}, with its desk in "
                        f"{pick(k + 't', TERMINALS)}.",
    ]),
    ("office", "all", [
        lambda k, c, x: f"The Skyway station office at {c} is open {t(k + 'a', 360, 540)}-{t(k + 'b', 990, 1320)} on "
                        f"weekdays and {t(k + 'c', 420, 600)}-{t(k + 'd', 900, 1200)} at weekends; phone "
                        f"+1 {200 + h(k + 'p1', 700)} {100 + h(k + 'p2', 900)} {1000 + h(k + 'p3', 9000)}.",
        lambda k, c, x: f"Call the {x} station office on +1 {200 + h(k + 'p1', 700)} {100 + h(k + 'p2', 900)} "
                        f"{1000 + h(k + 'p3', 9000)}, {t(k + 'a', 360, 540)} to {t(k + 'b', 990, 1320)}, closed on "
                        f"{pick(k + 'd', DAYS)}.",
    ]),
    ("quiet-room", "all", [
        lambda k, c, x: f"{c} has a quiet room airside near gate {n(k + 'g', 1, 40)}, open {t(k + 'a', 300, 480)}-"
                        f"{t(k + 'b', 1080, 1380)}.",
        lambda k, c, x: f"The quiet room at {x} is landside, beside check-in zone {pick(k + 'z', list('ABCDEF'))}.",
        lambda k, c, x: f"There is no quiet room at {c}; the multi-faith room is next to gate {n(k + 'g', 1, 40)}.",
    ]),
    ("smoking", "all", [
        lambda k, c, x: f"Smoking at {c} is only outside door {n(k + 'a', 1, 12)} of {pick(k + 't', TERMINALS)}.",
        lambda k, c, x: f"{x} has an airside smoking room near gate {n(k + 'g', 1, 40)}.",
        lambda k, c, x: f"{c} has no smoking area airside.",
    ]),
    ("water", "all", [
        lambda k, c, x: f"Water refill points at {c} are at gates {n(k + 'a', 1, 9)}, {n(k + 'b', 10, 19)} and "
                        f"{n(k + 'c', 20, 35)}.",
        lambda k, c, x: f"At {x} the only water refill point is just after security.",
    ]),
    ("wifi", "all", [
        lambda k, c, x: f"The airport Wi-Fi at {c} is called {pick(k + 'w', WIFI).format(c=x)} and gives "
                        f"{n(k + 'a', 30, 240, 30)} minutes per day.",
        lambda k, c, x: f"Free Wi-Fi at {x} is {pick(k + 'w', WIFI).format(c=x)}, unlimited in "
                        f"{pick(k + 't', TERMINALS)}.",
    ]),
    ("boarding-pass", "all", [
        lambda k, c, x: f"At {c}, mobile boarding passes do not scan at gates {n(k + 'a', 1, 9)} to "
                        f"{n(k + 'b', 10, 20)}; customers there need a printed pass.",
        lambda k, c, x: f"{x} accepts mobile boarding passes everywhere except the {pick(k + 't', TERMINALS)} "
                        f"bus gates.",
    ]),
    ("document-desk", "intl", [
        lambda k, c, x: f"The Document Check desk at {c} is {pick(k + 'p', ['beside the check-in counters', 'at the transfer desk', 'airside at gate level', 'in the arrivals hall'])}, "
                        f"open {t(k + 'a', 300, 480)}-{t(k + 'b', 1080, 1260)}.",
        lambda k, c, x: f"At {x}, Document Check is done at counter {n(k + 'a', 1, 40)} until {t(k + 'b', 900, 1200)}, "
                        f"then at the gate.",
    ]),
    ("walk", "all", [
        lambda k, c, x: f"Allow {n(k + 'a', 5, 25)} minutes to walk from check-in to the furthest Skyway gate at {c}.",
        lambda k, c, x: f"The walk from security to gate {n(k + 'g', 20, 60)} at {x} takes about {n(k + 'a', 8, 25)} "
                        f"minutes.",
    ]),
    ("charging", "all", [
        lambda k, c, x: f"Every Skyway gate at {c} has charging points except gates {n(k + 'a', 1, 9)} and "
                        f"{n(k + 'b', 10, 30)}.",
    ]),
    ("holiday", "all", [
        lambda k, c, x: f"On {n(k + 'd', 1, 28)} {pick(k + 'm', MONTHS)}, the {x} counters open at "
                        f"{t(k + 'a', 180, 300)} instead of the usual time.",
        lambda k, c, x: f"During the {pick(k + 'm', MONTHS)} school holidays the {c} station office opens at "
                        f"{t(k + 'a', 300, 420)}.",
    ]),
]


def update_fact(code, intl):
    """A quarter of stations have one fact whose current value is only in a Slack update; None for the rest."""
    if h(code + "upd", 4):
        return None
    types = [ty[0] for ty in STATION_TYPES if ty[1] == "all" or (ty[1] == "intl") == intl]
    keep = sorted(types, key=lambda name: h(code + name, 10**9))[:8 + h(code + "count", 6)]
    return keep[h(code + "updpick", len(keep))]


def station_facts(code, city, intl, changes=(), old=None):
    """{fact type: sentence} for a station: its own subset of types (8-13 of them), each with a phrasing chosen per
    station. changes: stages that re-drew this station's facts; each re-draws 2 of its facts with its own salt."""
    types = [ty for ty in STATION_TYPES if ty[1] == "all" or (ty[1] == "intl") == intl]
    keep = sorted(types, key=lambda ty: h(code + ty[0], 10**9))[:8 + h(code + "count", 6)]
    salt = {}
    upd = update_fact(code, intl)
    for st in changes:  # a stage never moves the fact a Slack update carries
        for ty in sorted([ty for ty in keep if ty[0] != upd], key=lambda ty: h(f"{code}{st}{ty[0]}", 10**9))[:2]:
            salt[ty[0]] = f"#s{st}"
    if old:
        salt[old] = "#old"  # the value the handbook page still shows before the Slack update
    out = {}
    for name, _, phrasings in sorted(keep, key=lambda ty: ty[0]):
        key = f"{code}|{name}" + salt.get(name, "")
        phrase = phrasings[h(code + name + "phrase", len(phrasings))]  # the phrasing stays; values move
        out[name] = phrase(key, city, code)
    return out


COUNTRY_TYPES = [
    ("validity", [
        lambda k, c: f"For {c}, the passport must be valid for {pick(k, ['the whole stay', '3 months beyond the stay', '6 months beyond the stay'])}, "
                     f"counted from the date of return.",
        lambda k, c: f"Travellers to {c} need {pick(k, ['3', '6'])} months of passport validity after they leave, unless they "
                     f"stay under {n(k + 'd', 3, 14)} days.",
    ]),
    ("permit", [
        lambda k, c: f"{c} requires {pick(k, ['an electronic entry permit', 'a visa', 'no entry permit'])} for most "
                     f"travellers; holders of a {pick(k + 'r', ['Canadian', 'Mexican', 'British', 'Irish'])} passport need "
                     f"{pick(k + 'x', ['none', 'a visa', 'an electronic entry permit'])}.",
        lambda k, c: f"An electronic entry permit for {c} must be granted at least {n(k + 'h', 24, 96, 24)} hours "
                     f"before departure.",
    ]),
    ("upload", [
        lambda k, c: f"Document Check uploads for {c} close {n(k, 12, 72, 12)} hours before departure.",
        lambda k, c: f"Flights to {c}: upload passports to Document Check at least {n(k, 12, 72, 12)} hours ahead, "
                     f"{n(k + 'b', 24, 96, 24)} hours for groups.",
    ]),
    ("onward", [
        lambda k, c: f"{c} asks for proof of onward travel within {n(k, 30, 180, 30)} days.",
        lambda k, c: f"No proof of onward travel is needed for {c}.",
    ]),
    ("residence", [
        lambda k, c: f"A residence card replaces the entry permit for {c} only if it is valid for "
                     f"{n(k, 1, 6)} more months.",
        lambda k, c: f"For {c}, a residence card never replaces the entry permit.",
    ]),
    ("temporary", [
        lambda k, c: f"Temporary passports are accepted for {c} only on direct flights.",
        lambda k, c: f"{c} accepts temporary passports; emergency passports are not accepted.",
        lambda k, c: f"Only full passports are accepted for {c}.",
    ]),
    ("transit", [
        lambda k, c: f"Travellers changing planes in {c} for under {n(k, 6, 24, 6)} hours need no entry permit.",
        lambda k, c: f"Every traveller passing through {c}, even airside, needs the entry permit.",
    ]),
    ("arrival-card", [
        lambda k, c: f"{c} uses an online arrival card, to be filled in within {n(k, 24, 72, 24)} hours of arrival.",
        lambda k, c: f"A paper arrival card for {c} is handed out on board.",
    ]),
]


def country_facts(country, changes=()):
    keep = sorted(COUNTRY_TYPES, key=lambda ty: h(country + ty[0], 10**9))[:5 + h(country + "count", 4)]
    salt = {}
    for st in changes:
        for ty in sorted(keep, key=lambda ty: h(f"{country}{st}{ty[0]}", 10**9))[:2]:
            salt[ty[0]] = f"#s{st}"
    out = {}
    for name, phrasings in sorted(keep, key=lambda ty: ty[0]):
        key = f"{country}|{name}" + salt.get(name, "")
        out[name] = phrasings[h(country + name + "phrase", len(phrasings))](key, country)
    return out
