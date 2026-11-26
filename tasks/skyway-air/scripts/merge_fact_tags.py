"""Merge the reviewers' customer-fact tags into tests/fact_tags.json, after checking them.

    python3 merge_fact_tags.py <tags dir>   # reads <dir>/batch*.json (what reviewers got) and <dir>/out*.json (their tags)

Refuses to write unless every ticket version and every fact of its batch is tagged with the fact's exact text, every
"decides" is one of that ticket's check groups, and a fact is decisive exactly when it decides something. The format is
redwood-inference's: {case: {stage: {fact: {decisive, why, decides}}}}; read by scripts/build_facts.py.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ABOUT = ("Customer facts (cases.json \"facts\") that decide a ticket: without the fact, or with another value, a correct "
         "bot would set a different checked value or take a different checked action. Per ticket, per stage where its "
         "facts or pass conditions changed (a later stage uses the latest earlier entry). Drafted by model reviewers from "
         "each ticket's pass conditions, test, rules and the support API data it can read; \"decides\" lists the checks a "
         "decisive fact decides (check groups: category, labels:<name>, refunds, credits, reimbursements, approvals, "
         "changes, handoff, comment); read by scripts/build_facts.py.")


# Applied after the reviewers, so the same kind of fact gets the same tag everywhere (redwood-inference's convention).
# A preference that only confirms what a correct bot does anyway is not decisive; one that changes it is.
DEFAULT_CONFIRMING = re.compile(r"(?i)^(you want (the |your )?money (back )?(on|to) your card|refund his part to the card|"
                                r"you want (the )?money on your card, not travel credit|you are fine paying (a|any) difference|"
                                r"you'll pay if you must|you did not buy food)\.?$")
# Reviewers disagreed across stages on these while the ticket's answer stayed the same: one value for every stage.
OVERRIDES = {
    # the opening already asks to cancel and the booking has one passenger: repeating it changes nothing
    ("cancel-own-01", "Nobody needs to fly; cancel the whole booking."): False,
    ("cancel-own-02", "Cancel the whole booking."): False,
    # the "Denver trip" fact names the booking; the slip and correction are noise
    ("cancel-06", "At first you say it was the Boston trip, then correct yourself: Denver."): False,
    # only one cancelled company booking fits the opening
    ("mgr-01", "It is Priya Rao's work trip, booking SK8160."): False,
    # the wheelchair is what makes the mockery disability discrimination (handoff, credit)
    ("gate-01", "You use a wheelchair."): True,
    # the customer asks about a hotel or dinner, not a refund: whether they flew does not change that answer
    ("done-03", "You flew the next morning."): False,
    ("weather-03", "You flew the next day."): False,
    # the opening already says they flew on the replacement
    ("notice-01", "You flew on the replacement flight the same day."): False,
}


def label_problems():
    """A ticket labelled API only (info_type 1) has no decisive customer fact, and one labelled as needing the
    customer (2, 4) has at least one: the label and the tags must agree (what the silent-customer audit tests)."""
    tags = json.loads((ROOT / "tests/fact_tags.json").read_text())
    out = []
    for n in range(6):
        base = ROOT / ("tests" if n == 0 else f"tests/stages/stage{n}")
        for c in json.loads((base / "cases.json").read_text()):
            st = tags.get(c["id"], {})
            keys = [k for k in st if int(k[5:]) <= n]
            facts = st[max(keys, key=lambda k: int(k[5:]))] if keys else {}
            decisive = [f for f, t in facts.items() if t["decisive"]]
            if c["info_type"] == 1 and decisive:
                out.append(f"stage {n} {c['id']}: API only, but decisive customer facts {decisive[:2]}")
            if c["info_type"] in (2, 4) and not decisive:
                out.append(f"stage {n} {c['id']}: info_type {c['info_type']} needs the customer, but no fact is decisive")
    return out


def settle(case, fact, tag, by_fact):
    """The convention and the overrides; a fact forced decisive takes the checks it decides in another stage."""
    want = OVERRIDES.get((case, fact), False if DEFAULT_CONFIRMING.match(fact) else None)
    if want is None or want == tag["decisive"]:
        return tag
    if not want:
        return {"decisive": False, "why": "Confirms what a correct bot does anyway, or repeats the opening; changes no "
                                         "checked outcome.", "decides": []}
    other = next((t for t in by_fact.get((case, fact), []) if t["decisive"]), None)
    return other or tag


def main(folder):
    folder = Path(folder)
    entries = [e for f in sorted(folder.glob("batch*.json")) for e in json.loads(f.read_text())]
    tags = {}
    for f in sorted(folder.glob("out*.json")):
        for case, stages in json.loads(f.read_text()).items():
            for stage, facts in stages.items():
                if stage in tags.get(case, {}):
                    raise SystemExit(f"{case} {stage} is tagged twice ({f.name})")
                tags.setdefault(case, {})[stage] = facts
    problems = []
    for e in entries:
        got = tags.get(e["case"], {}).get(e["stage"])
        if got is None:
            problems.append(f"{e['case']} {e['stage']}: not tagged")
            continue
        if set(got) != set(e["facts"]):
            problems.append(f"{e['case']} {e['stage']}: facts differ: missing {sorted(set(e['facts']) - set(got))[:2]}, "
                            f"extra {sorted(set(got) - set(e['facts']))[:2]}")
        for fact, t in got.items():
            if set(t) != {"decisive", "why", "decides"} or not isinstance(t["decisive"], bool):
                problems.append(f"{e['case']} {e['stage']}: bad tag for {fact[:40]!r}: {t}")
                continue
            if t["decisive"] != bool(t["decides"]):
                problems.append(f"{e['case']} {e['stage']}: {fact[:40]!r} decisive={t['decisive']} but decides {t['decides']}")
            bad = [d for d in t["decides"] if d not in e["check_groups"]]
            if bad:
                problems.append(f"{e['case']} {e['stage']}: {fact[:40]!r} decides {bad}, not a check of this ticket")
    extra = {(c, s) for c, st in tags.items() for s in st} - {(e["case"], e["stage"]) for e in entries}
    problems += [f"{c} {s}: tagged but not asked for" for c, s in sorted(extra)]
    if problems:
        print("\n".join(["NOT WRITTEN:"] + problems))
        raise SystemExit(1)
    by_fact = {}
    for case, stages in tags.items():
        for facts in stages.values():
            for fact, tag in facts.items():
                by_fact.setdefault((case, fact), []).append(tag)
    settled = 0
    for case, stages in tags.items():
        for facts in stages.values():
            for fact, tag in list(facts.items()):
                new = settle(case, fact, tag, by_fact)
                settled += new is not tag
                facts[fact] = new
    print(f"{settled} tags set by the convention and overrides")
    out = {"_about": ABOUT}
    for case in sorted(tags):
        out[case] = {s: tags[case][s] for s in sorted(tags[case], key=lambda s: int(s[5:]))}
    (ROOT / "tests/fact_tags.json").write_text(json.dumps(out, indent=1) + "\n")
    facts = [t for st in tags.values() for fs in st.values() for t in fs.values()]
    print(f"tests/fact_tags.json: {len(tags)} tickets, {len(entries)} ticket versions, {len(facts)} facts, "
          f"{sum(t['decisive'] for t in facts)} decisive")
    problems = label_problems()
    if problems:
        print("\n".join(["LABELS AND TAGS DISAGREE (fix the ticket's info_type or the tag):"] + problems))
        raise SystemExit(1)
    print("every ticket's info_type agrees with its decisive customer facts")


if __name__ == "__main__":
    main(sys.argv[1])
