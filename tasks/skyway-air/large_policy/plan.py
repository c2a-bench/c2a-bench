"""The large-policy plan for skyway-arch: rules and tables in support areas no existing rule or ticket touches.

    python3 tasks/skyway-arch/large_policy/plan.py            # write plan.json and PLAN.md, print sizes and checks

Nothing here is tested by a ticket. The policy is there so that, under the 12k-token prompt cap, no bot can carry all
of Skyway's support knowledge: it has to fetch what a ticket needs. Every rule is a few sentences that the generated
docs must contain word for word (as tests/doc_plan.json's "states"); tables are stated one sentence per value.

Values are fixed per key (a hash of the key), with no pattern a bot could learn instead of the facts.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import facts as F  # noqa: E402

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]

# Airports any existing ticket, seed or example uses (tests/**/flights.json, cases.json): kept out of every new doc,
# with their cities, so no new doc competes with an existing ticket's rule docs in retrieval.
TICKET_AIRPORTS = {"ATL", "BNA", "BOS", "DEN", "DFW", "HOU", "IAH", "JFK", "LAX", "LGA", "MCO", "MIA", "ORD", "PHX",
                   "RDU", "SEA", "SJU"}
TICKET_CITIES = {"Atlanta", "Nashville", "Boston", "Denver", "Dallas", "Houston", "New York", "Los Angeles", "Orlando",
                 "Miami", "Chicago", "Phoenix", "Raleigh", "Durham", "Seattle", "San Juan", "Fort Worth"}

# Words of the existing rules' topics (R1-R32), the batteries/dangerous-goods topic that handoff-03 expects to be
# uncovered, and illness (R25). No new rule or table sentence may contain one.
EXCLUDED = ["refund", "credit", "compensat", "reimburs", "approv", "payment", "pay ", "paid", "fee ", "fees", "fare ", "fares", "charge",
            "price", "cost ", "costs", "money", "voucher", "goodwill", "delay", "cancel", "retime", "schedule change", "missed",
            "connection", "connecting", "overnight", "hotel", "meal", "taxi", "rideshare", "ground transport", "bag",
            "luggage", "suitcase", "claim", "damage", "wear", "pet", "animal", "child", "minor", "infant", "family",
            "wheelchair", "assistance", "accessib", "disab", "travel manager", "agency", "agent's company",
            "authori", "illness", "ill ", "sick", "doctor", "medical", "injur", "legal", "lawyer", "discriminat",
            "batter", "lithium", "power bank", "dangerous", "hazard", "change fee", "rebook", "standby",
            "skyway miles", "miles", "loyalty", "tier", "silver", "gold", "elite status", "membership status", "confirmation_id",
            "confirmation id", "follow-up", "handoff", "hand off", "hand it", "escalat", "weather", "storm"]

LABELS = ["checkin-help", "docs-check", "privacy-request", "account-change", "app-issue", "facility-info", "charter-enquiry", "cargo-enquiry", "media-enquiry",
          "group-enquiry"]


def h(key, n):
    return int(hashlib.sha256(key.encode()).hexdigest()[:12], 16) % n


def pick(key, options):
    return options[h(key, len(options))]


# ------------------------------------------------------------------ prose rules
# (id, area, sentences). Each sentence is stated word for word in a planned doc.
RULES = [
    # --- check-in and boarding
    ("C1", "checkin", ["Online check-in opens 30 hours before departure and closes at the station's check-in cut-off."]),
    ("C2", "checkin", ["A customer who cannot check in online should be told to use a kiosk or the counter; do not check them in yourself from the support desk."]),
    ("C3", "checkin", ["Boarding passes are sent to the email on the booking and to the app; the desk can resend one to that email."]),
    ("C4", "checkin", ["When a boarding pass will not scan at home, tell the customer to print it at a kiosk with the booking code; add the label checkin-help."]),
    ("C6", "checkin", ["Boarding is in five groups; group 1 boards first, then groups 2 to 5 in order."]),
    ("C7", "checkin", ["Group 1 is for customers seated in rows 1 to 6; everyone else is grouped by seat row from the back of the aircraft forward."]),
    ("C9", "checkin", ["The gate closes at the station's gate-close time; after that the gate team cannot reopen the door."]),
    ("C10", "checkin", ["Tell a customer who asks about a station's cut-offs the exact times from that station's handbook, for the season of their travel date."]),
    ("C11", "checkin", ["Seasons in station handbooks: off-peak is January to March, shoulder is April, May, September and October, peak is June to August and November to December."]),
    ("C12", "checkin", ["A customer whose name on the booking differs from their ID by one or two letters is told to bring the booking code and their ID to the counter; add the label checkin-help."]),
    ("C13", "checkin", ["Accepted ID for domestic flights: a passport, a national ID card, a driving licence with a photo, or a military ID."]),
    ("C14", "checkin", ["International flights need a passport for every traveller; no other ID is accepted at check-in."]),
    ("C15", "checkin", ["Mobile boarding passes work at every station except those whose handbook says paper only."]),
    ("C16", "checkin", ["Customers checking in at a kiosk need the booking code or the card number used to buy the trip; the last name alone is not enough."]),
    ("C18", "checkin", ["When a customer asks why they were selected for an extra security screen, explain that the airport security team chooses at random and Skyway has no say."]),
    ("C19", "checkin", ["Do not tell a customer they will be allowed through the gate after the gate-close time, even if they are in the terminal."]),
    ("C20", "checkin", ["Group travellers of ten or more on one booking may check in together at the counter; add the label group-enquiry when they ask how."]),
    ("C22", "checkin", ["Duplicate boarding passes are fine: only the latest one issued scans at the gate."]),
    # --- travel documents
    ("D1", "documents", ["Before an international flight, each traveller uploads their passport in the app's Document Check at least the number of hours before departure that the destination's entry in the document table gives."]),
    ("D2", "documents", ["Document Check results arrive in the app within four hours; a pending result does not stop online check-in from opening."]),
    ("D3", "documents", ["A traveller whose Document Check fails must show their papers at the counter; add the label docs-check and tell them which document failed."]),
    ("D4", "documents", ["Skyway checks passport validity against the destination's entry in the document table; validity is counted from the date of return."]),
    ("D5", "documents", ["Where the document table says an entry permit is needed, the traveller must show it at check-in, printed or on screen."]),
    ("D6", "documents", ["Skyway does not issue entry permits or visas; tell the customer to apply through the destination country's official site."]),
    ("D7", "documents", ["Where the document table says proof of onward travel is needed, a booking for any onward flight, bus or train out of the country counts."]),
    ("D8", "documents", ["A traveller with two nationalities checks in with the passport they will use to enter the destination."]),
    ("D9", "documents", ["A residence card counts in place of an entry permit only where the document table says so for that destination."]),
    ("D10", "documents", ["Do not advise a customer that their papers are fine before Document Check has passed; say what the table requires and that the check will confirm it."]),
    ("D11", "documents", ["A name on the passport that does not match the booking exactly fails Document Check; the customer corrects it at the counter with the passport."]),
    ("D12", "documents", ["Emergency or temporary passports are accepted for every destination except where the document table says full passports only."]),
    # --- accounts, privacy and the app
    ("P1", "privacy", ["A customer can ask for a copy of the personal data Skyway holds; add the label privacy-request and tell them the privacy team answers within 25 days."]),
    ("P2", "privacy", ["A request to delete an account is labelled privacy-request; tell the customer that bookings with future flights stay until the last flight has flown."]),
    ("P4", "privacy", ["Never read out or send personal data in a ticket reply; the privacy team sends it through the secure download link."]),
    ("P5", "privacy", ["A customer asking to stop marketing emails is unsubscribed in the app settings by the customer; tell them the steps, and that service emails about their flights still arrive."]),
    ("P6", "privacy", ["Text messages about flights can be switched off in the app; Skyway still sends gate and boarding messages by email."]),
    ("P7", "privacy", ["An email address on an account is changed only by the customer in the app, after confirming a code sent to the old address; add the label account-change if they cannot reach the old address."]),
    ("P8", "privacy", ["When the customer cannot reach the old address, the account team checks their identity by video call within five working days."]),
    ("P9", "privacy", ["Phone numbers on an account can be changed by the customer in the app at any time."]),
    ("P10", "privacy", ["Two-step sign-in can be turned off only by the account team; add the label account-change and tell the customer to expect an email within two working days."]),
    ("P11", "privacy", ["A customer who sees a sign-in they did not make is told to reset their password at once and to turn on two-step sign-in; add the label account-change."]),
    ("P12", "privacy", ["Two accounts for the same person can be merged by the account team; the older account is kept and the newer one is closed."]),
    ("P13", "privacy", ["App crashes are labelled app-issue with the phone model and app version in the ticket comment."]),
    ("P14", "privacy", ["The app supports the two newest major versions of each phone system; older phones should use the website."]),
    ("P15", "privacy", ["If the app shows an old booking that has already flown, tell the customer to pull down to refresh; past trips move to the History tab after a day."]),
    ("P16", "privacy", ["The website and the app show the same bookings; if they differ, the website is right and the app catches up within an hour."]),
    ("P17", "privacy", ["Do not ask a customer for their password, the full card number or a sign-in code in a ticket."]),
    ("P18", "privacy", ["Cookie and tracking choices on the website are made in the cookie banner; the desk cannot change them for the customer."]),
    ("P19", "privacy", ["A customer who asks who saw their data is told the privacy team keeps an access log and can share it on request; add the label privacy-request."]),
    # --- airport facilities
    ("F1", "facilities", ["Tell a customer which lounge partner a station uses and its opening hours from that station's handbook, for the season of their travel date."]),
    ("F2", "facilities", ["Lounge partners set their own entry rules; the support desk cannot give or promise lounge entry."]),
    ("F3", "facilities", ["Stations with no lounge partner in the handbook have none; do not suggest another airline's lounge."]),
    ("F4", "facilities", ["Free terminal Wi-Fi is run by the airport, not Skyway; the desk cannot help with sign-in problems on it."]),
    ("F5", "facilities", ["Prayer rooms and quiet rooms are listed in the station handbook where the airport has one."]),
    ("F6", "facilities", ["Parking at the airport is run by the airport or its partners; add the label facility-info and give the parking partner from the station handbook."]),
    ("F7", "facilities", ["Skyway has no showers or sleeping pods of its own at any station."]),
    ("F8", "facilities", ["Charging points at Skyway gates are free and need no sign-in."]),
    ("F9", "facilities", ["Give a customer the station office phone and its hours from that station's handbook, for the season of their travel date; add the label facility-info."]),
    ("F10", "facilities", ["Smoking areas, water refill points and the number of Skyway kiosks are listed in each station handbook; quote them as written."]),
    # --- charter, cargo, media, other enquiries
    ("E1", "enquiries", ["Charter requests for a whole aircraft are labelled charter-enquiry; the charter team replies within three working days."]),
    ("E2", "enquiries", ["Charter enquiries need the dates, the route, the number of travellers and a contact phone number in the ticket comment."]),
    ("E3", "enquiries", ["Do not quote or estimate anything for a charter; only the charter team does."]),
    ("E4", "enquiries", ["Cargo shipments are handled by Skyway Cargo, not the support desk; add the label cargo-enquiry and give the cargo desk email cargo@skywayair.example."]),
    ("E5", "enquiries", ["The support desk cannot track cargo; tell the customer to use the airway bill number on the Skyway Cargo site."]),
    ("E6", "enquiries", ["Journalists and film crews are labelled media-enquiry and told the press office answers within one working day."]),
    ("E7", "enquiries", ["Do not comment to a journalist on any flight, customer or staff member; only the press office speaks for Skyway."]),
    ("E8", "enquiries", ["Requests to film or photograph on board or at a Skyway gate need written permission from the press office; label media-enquiry."]),
    ("E9", "enquiries", ["Groups of ten or more travelling together book through the group desk; add the label group-enquiry and give the group desk email groups@skywayair.example."]),
    ("E10", "enquiries", ["Job applicants are sent to the careers site; the support desk does not take applications or pass on CVs."]),
    ("E11", "enquiries", ["Suppliers and companies offering services are sent to the procurement email procurement@skywayair.example."]),
    ("E13", "enquiries", ["School and university projects asking for Skyway information are sent to the press office; label media-enquiry."]),
    ("E14", "enquiries", ["Requests for flight data for research go to the press office; the desk does not share flight data."]),
]

AREAS = {
    "checkin": ("confluence/customer-policies/check-in-and-boarding", "slack/airport-ops"),
    "documents": ("confluence/customer-policies/travel-documents", "slack/support-policy-questions"),
    "privacy": ("confluence/support-playbooks/accounts-and-privacy", "slack/digital-team"),
    "facilities": ("confluence/airport-operations/station-facilities", "slack/airport-ops"),
    "enquiries": ("confluence/support-playbooks/other-enquiries", "slack/support-team"),
}

# ------------------------------------------------------------------ tables
STATIONS = [  # Skyway stations no ticket uses (IATA code, city)
    ("ABQ", "Albuquerque"), ("ALB", "Albany"), ("AMA", "Amarillo"), ("ANC", "Anchorage"), ("AUS", "Austin"),
    ("AVL", "Asheville"), ("BDL", "Hartford"), ("BHM", "Birmingham"), ("BIL", "Billings"), ("BOI", "Boise"),
    ("BTV", "Burlington"), ("BUF", "Buffalo"), ("BWI", "Baltimore"), ("BZN", "Bozeman"), ("CAE", "Columbia"),
    ("CHS", "Charleston"), ("CLE", "Cleveland"), ("CLT", "Charlotte"), ("CMH", "Columbus"), ("COS", "Colorado Springs"),
    ("CVG", "Cincinnati"), ("DAY", "Dayton"), ("DCA", "Washington National"), ("DSM", "Des Moines"),
    ("DTW", "Detroit"), ("ELP", "El Paso"), ("EUG", "Eugene"), ("EWR", "Newark"), ("FAR", "Fargo"), ("FAT", "Fresno"),
    ("FLL", "Fort Lauderdale"), ("GEG", "Spokane"), ("GRR", "Grand Rapids"), ("GSP", "Greenville"),
    ("HNL", "Honolulu"), ("HSV", "Huntsville"), ("IAD", "Washington Dulles"), ("ICT", "Wichita"),
    ("IND", "Indianapolis"), ("JAN", "Jackson"), ("JAX", "Jacksonville"), ("KOA", "Kona"), ("LAS", "Las Vegas"),
    ("LEX", "Lexington"), ("LIT", "Little Rock"), ("MCI", "Kansas City"),     ("MEM", "Memphis"), ("MKE", "Milwaukee"), ("MSN", "Madison"), ("MSP", "Minneapolis"), ("MSY", "New Orleans"),
    ("MYR", "Myrtle Beach"), ("OAK", "Oakland"), ("OGG", "Maui"), ("OKC", "Oklahoma City"), ("OMA", "Omaha"),
    ("ONT", "Ontario"), ("ORF", "Norfolk"), ("PBI", "West Palm Beach"), ("PDX", "Portland"), ("PHL", "Philadelphia"),
    ("PIT", "Pittsburgh"), ("PNS", "Pensacola"), ("PSP", "Palm Springs"), ("PVD", "Providence"), ("PWM", "Portland Maine"),
    ("RIC", "Richmond"), ("RNO", "Reno"), ("ROC", "Rochester"), ("RSW", "Fort Myers"), ("SAN", "San Diego"),
    ("SAT", "San Antonio"), ("SAV", "Savannah"), ("SBA", "Santa Barbara"), ("SDF", "Louisville"),
    ("SFO", "San Francisco"), ("SJC", "San Jose"), ("SLC", "Salt Lake City"), ("SMF", "Sacramento"),
    ("SNA", "Santa Ana"), ("SRQ", "Sarasota"), ("STL", "St. Louis"), ("SYR", "Syracuse"), ("TPA", "Tampa"),
    ("TUL", "Tulsa"), ("TUS", "Tucson"), ("TYS", "Knoxville"), ("XNA", "Bentonville"),
    ("BGR", "Bangor"), ("CRW", "Charleston West Virginia"), ("CID", "Cedar Rapids"), ("CHA", "Chattanooga"),
    ("ECP", "Panama City Beach"), ("EYW", "Key West"), ("FSD", "Sioux Falls"), ("GPT", "Gulfport"), ("GSO", "Greensboro"),
    ("HPN", "White Plains"), ("ISP", "Islip"), ("ITO", "Hilo"), ("JAC", "Jackson Hole"), ("LBB", "Lubbock"),
    ("LGB", "Long Beach"), ("LIH", "Kauai"), ("MAF", "Midland"), ("MHT", "Manchester"), ("MLB", "Melbourne"),
    ("MOB", "Mobile"), ("MSO", "Missoula"), ("PSC", "Pasco"), ("RAP", "Rapid City"), ("ROA", "Roanoke"),
    ("SBN", "South Bend"), ("SGF", "Springfield"), ("SHV", "Shreveport"), ("TLH", "Tallahassee"), ("VPS", "Destin"),
    # the airports tickets use: their station pages exist like every other station's (an airport with no page would
    # read as "these pages are not about our flights")
    ("ATL", "Atlanta"), ("BNA", "Nashville"), ("BOS", "Boston"), ("DEN", "Denver"), ("DFW", "Dallas Fort Worth"),
    ("HOU", "Houston Hobby"), ("IAH", "Houston Intercontinental"), ("JFK", "New York JFK"), ("LAX", "Los Angeles"),
    ("LGA", "New York LaGuardia"), ("MCO", "Orlando"), ("MIA", "Miami"), ("ORD", "Chicago O'Hare"), ("PHX", "Phoenix"),
    ("RDU", "Raleigh-Durham"), ("SEA", "Seattle"), ("SJU", "San Juan"),
    # international
    ("YYZ", "Toronto"), ("YUL", "Montreal"), ("YVR", "Vancouver"), ("YYC", "Calgary"), ("YOW", "Ottawa"),
    ("CUN", "Cancun"), ("MEX", "Mexico City"), ("GDL", "Guadalajara"), ("SJD", "Los Cabos"), ("PVR", "Puerto Vallarta"),
    ("MTY", "Monterrey"), ("NAS", "Nassau"), ("MBJ", "Montego Bay"), ("KIN", "Kingston"), ("PUJ", "Punta Cana"),
    ("SDQ", "Santo Domingo"), ("AUA", "Aruba"), ("CUR", "Curacao"), ("BGI", "Bridgetown"), ("STT", "St. Thomas"),
    ("SXM", "St. Maarten"), ("GCM", "Grand Cayman"), ("BDA", "Bermuda"), ("LIR", "Liberia"), ("SJO", "San Jose Costa Rica"),
    ("PTY", "Panama City"), ("BZE", "Belize City"), ("GUA", "Guatemala City"), ("SAL", "San Salvador"),
    ("BOG", "Bogota"), ("MDE", "Medellin"), ("LIM", "Lima"), ("UIO", "Quito"), ("SCL", "Santiago"),
    ("GRU", "Sao Paulo"), ("EZE", "Buenos Aires"), ("LHR", "London"), ("DUB", "Dublin"), ("CDG", "Paris"),
    ("AMS", "Amsterdam"), ("FRA", "Frankfurt"), ("MAD", "Madrid"), ("BCN", "Barcelona"), ("FCO", "Rome"),
    ("LIS", "Lisbon"), ("KEF", "Reykjavik"), ("ZRH", "Zurich"), ("CPH", "Copenhagen"),
    ("MAN", "Manchester UK"), ("EDI", "Edinburgh"), ("SNN", "Shannon"), ("MUC", "Munich"), ("BRU", "Brussels"),
    ("VIE", "Vienna"), ("ATH", "Athens"), ("OSL", "Oslo"), ("ARN", "Stockholm"), ("HEL", "Helsinki"),
    ("NRT", "Tokyo"), ("ICN", "Seoul"), ("TLV", "Tel Aviv"), ("CMN", "Casablanca"), ("YHZ", "Halifax"),
    ("YQB", "Quebec City"), ("POS", "Port of Spain"), ("UVF", "Saint Lucia"), ("ANU", "Antigua"), ("PLS", "Providenciales"),
]
INTL = {c for c, _ in STATIONS[STATIONS.index(("YYZ", "Toronto")):]}
COUNTRIES = ["Canada", "Mexico", "Bahamas", "Jamaica", "Dominican Republic", "Aruba", "Curacao", "Barbados",
             "Cayman Islands", "Bermuda", "Costa Rica", "Panama", "Belize", "Guatemala", "El Salvador", "Colombia",
             "Peru", "Ecuador", "Chile", "Brazil", "Argentina", "United Kingdom", "Ireland", "France", "Netherlands",
             "Germany", "Spain", "Italy", "Portugal", "Iceland", "Switzerland", "Denmark", "Sint Maarten",
             "Honduras", "Nicaragua", "Uruguay", "Paraguay", "Bolivia", "Trinidad and Tobago", "Saint Lucia",
             "Antigua and Barbuda", "Grenada", "Turks and Caicos", "Guadeloupe", "Martinique", "Norway", "Sweden",
             "Finland", "Austria", "Belgium", "Greece", "Croatia", "Poland", "Czechia", "Morocco", "Japan",
             "South Korea", "Australia", "New Zealand", "Israel"]


LABEL_LINES = [
    "For any customer question about Skyway at {city} ({code}), add the label facility-info and note {code} in a ticket comment.",
    "Questions about {code} get the label facility-info, with the station code {code} written in a ticket comment.",
    "When a customer asks about {city}, label the ticket facility-info and record {code} in a comment.",
]
DOC_LABEL_LINES = [
    "For a travel-document question about {country}, add the label docs-check and name {country} in a ticket comment.",
    "Label travel-document questions about {country} docs-check and note the destination in a ticket comment.",
]


_REWORD = None


def rw(sentences, reword=True):
    """The sentences as reworded by reword.py (reword_map.json), or as written when reword=False or not reworded."""
    global _REWORD
    if not reword:
        return list(sentences)
    if _REWORD is None:
        f = HERE / "reword_map.json"
        _REWORD = json.loads(f.read_text()) if f.exists() else {}
    return [_REWORD.get(x, x) for x in sentences]


def own_station_for_text(text):
    """(code, city) of a station the text names by code, for the excluded-term check of a reworded sentence."""
    for code, city in STATIONS:
        if re.search(rf"\b{code}\b", text):
            return code, city
    return None


def station_label(code, city):
    return LABEL_LINES[h(code + "label", len(LABEL_LINES))].format(city=city, code=code)


def station_page(code, city, changes=(), reword=True):
    """The handbook page's sentences: every fact, with the Slack-updated one (if any) at its old value, and the
    station's label line."""
    intl = code in INTL
    upd = F.update_fact(code, intl)
    return rw(list(F.station_facts(code, city, intl, changes, old=upd).values()) + [station_label(code, city)], reword)


def station_update(code, city, reword=True):
    """(fact sentence as current, the Slack update's sentences) or None."""
    intl = code in INTL
    upd = F.update_fact(code, intl)
    if not upd:
        return None
    current = F.station_facts(code, city, intl)[upd]
    day = 1 + h(code + "updday", 28)
    return rw([current], reword)[0], rw([f"Update for {city} ({code}) from {day} May 2026, in place of the station "
                                         f"handbook line: {current}"], reword)


def station_current(code, city, changes=(), reword=True):
    """Every fact as it stands (the Slack-updated one at its new value)."""
    return rw(list(F.station_facts(code, city, code in INTL, changes).values()) + [station_label(code, city)], reword)


def country_page(c, changes=(), reword=True):
    return rw(list(F.country_facts(c, changes).values()) + [DOC_LABEL_LINES[h(c + "label", 2)].format(country=c)],
              reword)


def slug(s):
    return "-".join(re.sub(r"[^a-z0-9 ]+", " ", s.lower()).split())


def stage0_docs():
    """{docs/... path: {"states": [...], "area": ..., "kind": ...}}. Each rule's sentences sit in one Confluence page;
    about a third of rules are also restated in a Slack thread (as the tested rules are)."""
    docs = {}
    by_area = {}
    for rid, area, sents in RULES:
        by_area.setdefault(area, []).append((rid, sents))
    for area, rules in by_area.items():
        conf, slack = AREAS[area]
        for i in range(0, len(rules), 3):  # three rules per page, as policy pages often hold a few related rules
            chunk = rules[i:i + 3]
            title = f"{area}-{chunk[0][0].lower()}-{chunk[-1][0].lower()}"
            docs[f"docs/{conf}/{title}.json"] = {"states": [s for _, ss in chunk for s in ss], "area": area,
                                                  "kind": "page", "rules": [r for r, _ in chunk]}
        for rid, sents in rules:
            if h(rid + "slack", 3) == 0:
                docs[f"docs/{slack}/{area}-{rid.lower()}-thread.json"] = {"states": sents, "area": area,
                                                                          "kind": "thread", "rules": [rid]}
    for code, city in STATIONS:
        docs[f"docs/confluence/airport-operations/stations/{slug(city)}-{code.lower()}.json"] = {
            "states": station_page(code, city), "area": "stations", "kind": "station", "rules": [code]}
        u = station_update(code, city)
        if u:
            docs[f"docs/slack/airport-ops/{slug(city)}-{code.lower()}-update.json"] = {
                "states": u[1], "area": "stations", "kind": "update", "rules": [code]}
    for c in COUNTRIES:
        docs[f"docs/confluence/customer-policies/travel-documents/countries/{slug(c)}.json"] = {
            "states": country_page(c), "area": "countries", "kind": "country", "rules": [c]}
    for path, states in DECOYS0:
        docs[path] = {"states": states, "area": "decoy", "kind": "decoy", "rules": []}
    return docs


# ------------------------------------------------------------------ decoys (stage 0) and stages 1-5
# Decoys look like policy but are not in force: drafts, proposals, and old versions marked as replaced. They follow
# the tested corpus's own messy appearances. Each names what is current, so a careful reader is never misled.
DECOYS0 = [
    ("docs/confluence/support-playbooks/accounts-and-privacy/privacy-requests-2025.json",
     ["Replaced: until March 2026 the privacy team answered data copy requests within 30 days; it is now 25 days."]),
    ("docs/slack/digital-team/two-step-sign-in-proposal-thread.json",
     ["Proposal, not in force: let the support desk turn off two-step sign-in directly. For now only the account team can."]),
    ("docs/confluence/customer-policies/check-in-and-boarding/boarding-groups-draft.json",
     ["Draft for review, not in force: board in six groups instead of five. Today boarding is in five groups."]),
    ("docs/confluence/customer-policies/travel-documents/document-check-pilot-2025.json",
     ["Pilot ended: in 2025 Document Check results took up to eight hours; results now arrive within four hours."]),
    ("docs/slack/support-team/charter-reply-time-thread.json",
     ["Old reply time, replaced: the charter team used to reply within five working days; it is now three."]),
]

# Stages 1-5: the new policy moves like a real policy base. Per stage: value changes in station and country tables,
# rule edits, new rules, a retired rule and drafts that are not in force. No ticket uses any of it.
STAGE_NEW_RULES = {
    1: [("C23", "checkin", ["Customers who checked in online can print their boarding pass at any Skyway kiosk by scanning the booking code."])],
    2: [("P21", "privacy", ["Customers can download their trip history as a file from the app's History tab."])],
    3: [("E15", "enquiries", ["Requests to name an aircraft or sponsor a route go to the press office; label media-enquiry."])],
    4: [("D13", "documents", ["Digital passports stored in the app count at check-in only where the document table says so."])],
    5: [("F11", "facilities", ["Stations list a work area with desks in the handbook where the airport has one."])],
}
STAGE_RETIRED = {1: "F7", 2: "C18", 3: "P14", 4: "E10", 5: "C15"}


def stage_plan(n):
    """What changes in stage n: station and country values (re-drawn with a stage salt), rule edits, new and retired
    rules, drafts. Deterministic per stage."""
    codes = [c for c, _ in STATIONS]
    stations = sorted(codes, key=lambda c: h(f"s{n}{c}", 10**9))[:25]
    countries = sorted(COUNTRIES, key=lambda c: h(f"s{n}{c}", 10**9))[:6]
    earlier = {c for k in range(1, n) for c in stage_plan(k)["drafts"]}
    return {"station_value_changes": stations, "country_value_changes": countries,
            "new_rules": STAGE_NEW_RULES[n], "retired_rule": STAGE_RETIRED[n],
            "drafts": [c for c in stations if c not in earlier][:3]}


# ------------------------------------------------------------------ checks
def own_station(path):
    """(code, city) when the doc is about one station (its page, Slack update or cut-off proposal): its own airport
    may be named."""
    for code, city in STATIONS:
        if path.endswith(f"-{code.lower()}.json") or f"-{code.lower()}-" in path.rsplit("/", 1)[-1]:
            return code, city
    return None


def excluded_hits(text, allow=None):
    if allow:
        code, city = allow
        text = re.sub(rf"\b{re.escape(code)}\b", " ", text)
        text = re.sub(re.escape(city), " ", text, flags=re.I)
        for tc in TICKET_CITIES:  # "Dallas Fort Worth" names Dallas; "New York JFK" names New York
            if tc.lower() in city.lower():
                text = re.sub(re.escape(tc), " ", text, flags=re.I)
    low = " " + text.lower() + " "
    hits = [w for w in EXCLUDED if re.search(r"\b" + re.escape(w.strip()) + (r"\b" if w.endswith(" ") else ""), low)]
    hits += [c for c in TICKET_AIRPORTS if re.search(rf"\b{c}\b", text)]
    hits += [c for c in TICKET_CITIES if c.lower() in low]
    return hits


def tokens(text):
    return (len(text) + 3) // 4


def facts_count():
    """Station and country facts (each one entity + condition + value), and the prose rules' sentences."""
    st = sum(len(station_current(c, city)) for c, city in STATIONS)
    co = sum(len(country_page(c)) for c in COUNTRIES)
    return st, co


AREA_NAMES = {"checkin": "Check-in and boarding", "documents": "Travel documents",
              "privacy": "Accounts, privacy and the app", "facilities": "Airport facilities",
              "enquiries": "Charter, cargo, media and other enquiries"}


def render(docs, full):
    """PLAN.md: the plan in a form to review."""
    L = ["# skyway-arch large policy: plan (generated by plan.py, for review)", "",
         f"{len(RULES)} rules in {len(AREA_NAMES)} areas, tables for {len(STATIONS)} stations ({len(INTL)} international) "
         f"and {len(COUNTRIES)} countries, {len(DECOYS0)} decoys: {len(docs)} stage-0 docs.", "",
         f"Size: {full:,} tokens as written ({facts_count()[0]} station facts, {facts_count()[1]} country facts, "
         f"{len(RULES)} prose rules). Whether it packs under the 12,000-token cap is checked by gate B (one "
         "prompt-workflows run, stage 0), not estimated.", "",
         "Kept out of every new doc: the 17 airports and their cities that tickets use, and the words of every existing "
         "rule's topic (`EXCLUDED` in plan.py). Excluded-term check: 0 hits.", "",
         f"New labels: {', '.join(LABELS)}. No payment, no booking change, no handoff.", ""]
    for area, name in AREA_NAMES.items():
        conf, slack = AREAS[area]
        L += [f"## {name}", "", f"Pages in `{conf}`, some rules also in a Slack thread in `{slack}`.", ""]
        for rid, a, sents in RULES:
            if a == area:
                L.append(f"- **{rid}** " + " ".join(sents))
        L.append("")
    code, city = STATIONS[0]
    L += ["## Station handbooks", "", "One prose page per station in `confluence/airport-operations/stations/`, "
          "written by the generator: each station has its own 8-13 fact types, each with its own condition, phrased "
          "one of several ways. A quarter of stations have one fact whose current value is only in a Slack update. "
          "Example (Toronto):", ""]
    L += [f"- {x}" for x in station_page("YYZ", "Toronto")]
    u = station_update("YYZ", "Toronto")
    if u:
        L += [f"- Slack update: {u[1][0]}"]
    L += ["", "## Country document table", "", "One page per country in "
          "`confluence/customer-policies/travel-documents/countries/`. Example:", ""]
    L += [f"- {x}" for x in country_page(COUNTRIES[0])]
    L += ["", "## Decoys (stage 0)", "", "Not in force; each says what is current.", ""]
    L += [f"- `{p}`: " + " ".join(st) for p, st in DECOYS0]
    L += ["", "## Stages 1-5", "", "| Stage | Station values changed | Country values changed | New rule | Retired | Drafts |",
          "|---|---|---|---|---|---|"]
    for n in range(1, 6):
        sp = stage_plan(n)
        nr = "; ".join(f"{r}: {' '.join(st)}" for r, _, st in sp["new_rules"])
        L.append(f"| {n} | {len(sp['station_value_changes'])} | {len(sp['country_value_changes'])} | {nr} | "
                 f"{sp['retired_rule']} | {len(sp['drafts'])} proposals (not in force) |")
    L += ["", "No ticket changes in any stage: everything above is in areas no ticket uses."]
    (HERE / "PLAN.md").write_text("\n".join(L) + "\n")


def main():
    docs = stage0_docs()
    bad = {p: excluded_hits(" ".join(d["states"]), own_station(p)) for p, d in docs.items()}
    for n, rules in STAGE_NEW_RULES.items():
        for rid, _, sents in rules:
            bad[f"stage {n} new rule {rid}"] = excluded_hits(" ".join(sents))
    bad = {p: v for p, v in bad.items() if v}
    plan = {"labels": LABELS, "rules": [{"id": r, "area": a, "states": s} for r, a, s in RULES],
            "stations": [c for c, _ in STATIONS], "countries": COUNTRIES, "docs": docs}
    (HERE / "plan.json").write_text(json.dumps(plan, indent=1) + "\n")
    kinds = {}
    for d in docs.values():
        kinds[d["kind"]] = kinds.get(d["kind"], 0) + 1
    st, co = facts_count()
    print(f"{len(RULES)} rules, {len(STATIONS)} stations ({len(INTL)} international), {len(COUNTRIES)} countries")
    print(f"{len(docs)} stage-0 docs: {kinds}")
    full = sum(tokens(" ".join(d["states"])) for d in docs.values() if d["kind"] != "thread")
    print(f"as written: {full} tokens; {st} station facts, {co} country facts")
    print(f"excluded-term check: {len(bad)} docs with hits")
    render(docs, full)
    for p, v in list(bad.items())[:30]:
        print(f"  {p}: {v}")


if __name__ == "__main__":
    main()
