"""Words that show a rule is in the bot's notes or prompt even when the builder rewrote it (diagnose.rule_found).

One statement (a sentence, list item or table cell, normalized: lowercase, no markdown, no underscores, so
not_covered is written notcovered) must hold one alternative from
every group in "all", or from every group of one set in "or". "re:" alternatives are regular expressions. A "not"
phrase anywhere means the bot kept an older version. BASE is stage 0 and is written to tests/rule_keywords.json; a
rule that changes gets its stage's keywords in that stage's rules.json ("keywords"), from STAGES.

    python3 rule_keywords.py   # self-check: each rule's text matches its keywords, an older version does not
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOURS = r"(?:hours?|hrs?|h)\b"


def hours(n, word):
    return rf"re:\b(?:{n}|{word})\+? ?(?:or more )?{HOURS}"


BASE = {
    "_about": "Words that show a rule is in the bot's notes or prompt even when the builder rewrote it (diagnose.rule_found). "
              "Each group in 'all' needs one alternative in one statement; 're:' alternatives are regular expressions. Any "
              "'not' phrase means the bot kept a wrong version of the rule. 'or' lists more sets of groups that also count; "
              "a rule in a stage's rules.json can carry its own 'keywords' for that stage. Written by scripts/rule_keywords.py.",
    # Rules most tickets touch (the category, what counts as Skyway's fault, what was already done): a ticket-specific
    # rule decides when there is one.
    "_general": ["R1", "R20", "R21"],
    # Process rules a check names for almost any field: they decide only when nothing else does.
    "_catch_all": ["R18", "R19", "R20", "R29"],
    # ...except on tickets that test them.
    "_specific_in_group": {"R18": ["bad-actor"]},
    # "control" alone would match "air traffic control"
    "R1": {"all": [["crew", "mechanical", "weather", "air traffic"],
                   ["skyway-controlled", "skyway controlled", "skyway's control", "our control", "on us", "our fault"]]},
    "R2": {"all": [["cancel"], ["delay"], ["refund"], [hours(3, "three")]]},
    "R3": {"all": [["credit"], ["110%", "110 %", "10% bonus", "10% more", "10% extra"]]},
    "R4": {"all": [["agency"], ["agency-refund"]]},
    "R5": {"all": [["24 hours", "24h", "one day", "a day"], ["7 days", "7+ days", "seven days", "a week", "one week"]],
           "or": [[["cancel"], ["standard"], ["$75", "75 dollars", "seventy-five"], ["credit"]]]},
    "R6": {"all": [["pet"], ["refund", "goes back", "comes back", "returned"]]},
    "R7": {"all": [["change"], ["flex"], ["$75"]], "or": [[["basic"], ["change-denied"]]]},
    "R8": {"all": [["silver", "gold"], ["change fee"]]},
    "R9": {"all": [["meal"], ["$15"]], "or": [[["meal"], ["$35"]]]},
    "R10": {"all": [["hotel", "room"], ["$175"]]},
    "R11": {"all": [["receipt"], ["receipts-needed"]]},
    "R12": {"all": [["compensation", "travel credit"], ["$150"]]},
    "R13": {"all": [["bag"], ["$75"]], "or": [[["bag"], ["$375"]]]},
    "R14": {"all": [["claim", "bag"], ["21 days"]], "or": [[["claim-late"], ["7 days"]]]},
    "R15": {"all": [["wear-and-tear"]], "or": [[["repair"], ["$250"]]]},
    "R16": {"all": [["goodwill", "service failure", "special meal", "broken screen", "rude"], ["$50"]],
            "or": [[["$100"], ["supervisor approval", "needs approval", "need approval", "needs supervisor"]]]},
    "R17": {"all": [["not-authorized"]], "or": [[["only"], ["contact"], ["booking"]]]},
    "R18": {"all": [["instruction"], ["text", "note", "message", "ticket"]]},
    "R19": {"all": [["hand", "person", "human"], ["injur", "medical", "legal", "lawyer", "discriminat"]]},
    "R20": {"all": [["twice", "again", "already"], ["refund", "credit", "reimburse", "approval"]]},
    "R21": {"all": [["disruption"], ["baggage"], ["refund"]]},
    # new in later stages (written to tests/rule_keywords.json too: a rule only one stage has keeps its own words)
    "R22": {"all": [["assistance", "wheelchair"], ["$100"]], "or": [[["assistance-failure"]]]},
    "R23": {"all": [[hours(2, "two")], ["move", "moved", "retime", "schedule change", "schedule"]]},
    "R24": {"all": [["travel manager"], ["listed", "company account", "authorizedagents", "authorized agents"]]},
    "R25": {"all": [["illness", "sick", "doctor"], ["no process", "not published", "hand", "notcovered", "not covered", "person"]]},
    "R26": {"all": [["taxi", "rideshare", "ground transport", "transport"], ["$40"]]},
    "R27": {"all": [["connect"], ["miss"]]},
    "R28": {"all": [["follow-up", "follow up", "earlier ticket", "previous ticket", "already handled"], ["comment"]]},
    "R29": {"all": [["fail", "error"], ["again", "retry", "once", "twice"]],
            "or": [[["hand", "notcovered"], ["notes", "cannot be read", "unreadable", "can't read"]]]},
    "R30": {"all": [["child", "under 12"], ["seat"]]},
    "R31": {"all": [["unaccompanied", "minor"], ["$150"]], "or": [[["5 to 14", "5-14"], ["15 to 17", "15-17"]]]},
    "R32": {"all": [["confirmation"]]},
}

# (rule, first stage) -> keywords from that stage on; "not" holds the older version's own wording.
STAGES = {
    ("R2", 5): {"all": [["cancel"], ["delay"], ["refund"], [hours(2, "two")]], "not": ["delays its departure 3 hours or more"]},
    ("R3", 1): {"all": [["credit"], ["equals the refund", "same as the refund", "equal to the refund", "bonus ended",
                                     "no bonus", "100%", "no longer 110%"]], "not": ["credit worth 110% of the refund"]},
    # the change sentence often says "it" for the pet fee, so "pet" is not required in it
    ("R6", 2): {"all": [["own booking", "customer cancels", "own cancellation", "cancels their own", "cancel their own"],
                        ["not refunded", "no refund", "not returned", "isn't refunded", "is not refunded", "does not come back",
                         "doesn't come back", "not come back", "not given back"]],
                "not": ["the pet fee goes back if the pet did not fly"]},
    ("R8", 3): {"all": [["silver"], ["$40", "40 dollars", "forty dollars", "$40.00"]],
                "not": ["silver and gold skyway miles members pay no change fee"]},
    ("R9", 4): {"all": [["meal"], ["$20"]], "or": [[["meal"], ["$35"]]], "not": ["up to $15 per passenger"]},
    # the approval threshold is part of the rule: a note with the new direct limit and the old threshold is a stale copy
    ("R10", 1): {"all": [["hotel", "room"], ["$200"]], "not": ["up to $175 per room", "above $175", "over $175"]},
    ("R10", 2): {"all": [["hotel", "room"], ["$225"]], "not": ["up to $175 per room", "up to $200 per room", "above $175",
                                                               "over $175", "above $200", "over $200"]},
    ("R11", 1): {"all": [["receipt"], ["awaiting-receipts"]], "not": ["label it receipts-needed", "label receipts-needed"]},
    ("R12", 2): {"all": [["compensation", "travel credit"], ["$175"]], "not": ["$150 travel credit per passenger"]},
    ("R12", 5): {"all": [["compensation", "travel credit", "late"], [hours(3, "three")]],
                 "or": [[["compensation", "travel credit"], ["$175"], [hours(3, "three")]]],
                 "not": ["$150 travel credit per passenger", "arrive 4 or more hours late"]},
    ("R13", 1): {"all": [["bag"], ["$90"]], "or": [[["bag"], ["$450"]]], "not": ["$75 for each full 24 hours"]},
    ("R14", 3): {"all": [["claim", "bag"], ["30 days"]], "not": ["within 21 days of getting the bag back"]},
    ("R16", 4): {"all": [["goodwill", "service failure", "special meal", "broken screen", "rude"], ["$60"]],
                 "or": [[["$120"], ["supervisor approval", "needs approval", "need approval", "needs supervisor"]]],
                 "not": ["$50 travel credit"]},
    ("R17", 1): {"all": [["only", "contact"], ["travel manager"]]},
}


def for_stage(rid, n):
    """The keywords of a rule at stage n: its latest override at or before n, else BASE."""
    found = [(s, spec) for (r, s), spec in STAGES.items() if r == rid and s <= n]
    return max(found, key=lambda x: x[0])[1] if found else BASE.get(rid)


def write_base():
    (ROOT / "tests/rule_keywords.json").write_text(json.dumps(BASE, indent=1) + "\n")


def self_check():
    """Each rule's own text matches its keywords at every stage; the version before a change does not."""
    sys.path.insert(0, str(ROOT / "tests"))
    import diagnose
    problems = []
    texts = {}
    for n in range(6):
        f = ROOT / ("tests/rules.json" if n == 0 else f"tests/stages/stage{n}/rules.json")
        for r in json.loads(f.read_text()):
            text = diagnose.normalize(r["rule"])
            if not diagnose.rule_keywords_found(r["id"], text, spec=for_stage(r["id"], n)):
                problems.append(f"stage {n} {r['id']}: its own text does not match its keywords")
            before = texts.get(r["id"])
            if before and before != text and (r["id"], n) in STAGES and \
                    diagnose.rule_keywords_found(r["id"], before, spec=for_stage(r["id"], n)):
                problems.append(f"stage {n} {r['id']}: the version before stage {n} still matches the new keywords")
            texts[r["id"]] = text
    return problems


if __name__ == "__main__":
    problems = self_check()
    for p in problems:
        print(" ", p)
    print(f"{len(problems)} keyword problems")
    sys.exit(1 if problems else 0)
