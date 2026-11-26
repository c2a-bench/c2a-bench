"""The large-policy step of Skyway Air (skyway-arch), run once on the task built from ../scripts.

skyway-arch keeps skyway-air's tickets, answers and grader, and adds ~550 docs of Skyway support policy in areas no
ticket or existing rule touches (tasks/skyway-arch/large_policy, see DESIGN.md) and a 12,000-token cap on every bot
model call, so the bot cannot carry all of Skyway's knowledge next to the tested rules in one call.

On the freshly built task (in place):
- stage-0 docs (large_policy/docs/stage0) into environment/app/docs;
- stage N's new and changed docs (large_policy/docs/stageN) into steps/stageN/workdir/stageN_update/new_docs, listed
  in new_docs.txt (setup.sh copies new_docs over /app/docs, so a changed page replaces the old one);
- prompt_cap_tokens 12000 on every hidden case (a case with a stricter cap keeps it);
- one paragraph on the cap, and one line on the questions customers may ask, in every stage's instructions;
- four practice examples on the new policy (station, travel documents, privacy, charter).
The docs themselves come from large_policy/build_docs.py (and reword.py); the published task already has this step applied.
"""
import json
import pathlib
import shutil
import sys

REPO = pathlib.Path(__file__).resolve().parents[3]
CAP = 12000

CAP_ANCHOR = "Only `/app/bot` exists at test time, so any index, notes or prompts must be saved there."
ASK_TEXT = ("\n\nCustomers may also ask about Skyway's airports (check-in, boarding and gate times, lounges and other "
            "facilities), travel documents for international trips, their account and personal data, and charters, "
            "cargo or media requests.")
CAP_TEXT = (f"\n\nEvery model call the LLM agent makes may use at most {CAP:,} tokens, counted as characters / 4 over "
            "the messages, tool calls, tool results and tool definitions together. A call over the limit fails as if "
            "the model's context were too small. Skyway's docs hold far more than that, so the LLM agent cannot send "
            "all of its knowledge on every call: it has to bring in what each ticket needs.")


def replace_once(text, old, new, where):
    if text.count(old) != 1:
        raise SystemExit(f"{where}: expected the anchor once, found {text.count(old)}: {old[:60]!r}")
    return text.replace(old, new)


def copy_docs(src, dest):
    n = []
    for f in sorted(src.rglob("*.json")):
        rel = f.relative_to(src)  # docs/...
        to = dest / rel.relative_to("docs")
        to.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(f, to)
        n.append(rel.as_posix())
    return n


def large_examples(DST):
    """Four practice examples on the large policy (the builder sees them; no hidden ticket changes): a station
    question, a travel-document question, a privacy request and a charter enquiry, with their practice data."""
    import sys
    sys.path.insert(0, str(DST / "large_policy"))
    import plan as P
    import facts as F
    hidden = P.TICKET_AIRPORTS
    station = next((c, city) for c, city in P.STATIONS
                   if c not in hidden and "counters-open" in F.station_facts(c, city, c in P.INTL))
    code, city = station
    counters = F.station_facts(code, city, code in P.INTL)["counters-open"]
    country = next(c for c in P.COUNTRIES if "permit" in F.country_facts(c))
    permit = F.country_facts(country)["permit"]
    money = ["refunds", "credits", "reimbursements", "approvals", "changes"]
    forbidden = ["POST /refunds", "POST /credits", "POST /reimbursements", "POST /approvals",
                 "POST /bookings/*/change", "POST /handoffs"]
    rows = [
        ("SKY-0913", "cust_ex_park", "Mina Park", "mina.park@example.com",
         f"What time do the Skyway check-in counters open at {city} ({code})?",
         f"Station question: reply with the counter times from the {city} station handbook ({counters}); "
         f"label facility-info, {code} noted in a comment.", ["facility-info"]),
        ("SKY-0914", "cust_ex_ruiz", "Tomas Ruiz", "tomas.ruiz@example.com",
         f"I'm flying to {country} next month. What documents do I need?",
         f"Travel-document question: reply from the {country} document page ({permit}); label docs-check, "
         f"{country} noted in a comment.", ["docs-check"]),
        ("SKY-0915", "cust_ex_berg", "Lena Berg", "lena.berg@example.com",
         "Please send me a copy of all the personal data Skyway holds about me.",
         "Data copy request: label privacy-request; tell the customer the privacy team answers within 25 days; "
         "send no personal data in the reply.", ["privacy-request"]),
        ("SKY-0916", "cust_ex_okafor", "Chidi Okafor", "chidi.okafor@example.com",
         "Our company wants to charter a whole aircraft for about 120 people this September. Who do we talk to?",
         "Charter request: label charter-enquiry; the charter team replies within three working days; no quote.",
         ["charter-enquiry"]),
    ]
    ex = DST / "environment" / "app" / "examples"
    cases = json.loads((ex / "cases.json").read_text())
    tickets = json.loads((ex / "seed" / "tickets.json").read_text())
    customers = json.loads((ex / "seed" / "customers.json").read_text())
    for i, (tid, cid, name, email, message, test, labels) in enumerate(rows, start=13):
        cases.append({"id": f"example-{i}", "test": test,
                      "input": {"ticket_id": tid, "customer_id": cid, "message": message},
                      "expect": {f"tickets.{tid}.category": "other"},
                      "contains": {f"tickets.{tid}.labels": labels},
                      "unchanged": money, "forbidden_calls": forbidden})
        tickets[tid] = {"customer_id": cid, "requester_email": email, "booking_id": None, "category": None,
                        "labels": [], "status": "open", "created_at": "2026-05-20T10:00:00Z", "comments": []}
        customers[cid] = {"name": name, "email": email, "skyway_miles_tier": None, "bookings": [],
                          "authorized_agents": []}
    (ex / "cases.json").write_text(json.dumps(cases, indent=2) + "\n")
    (ex / "seed" / "tickets.json").write_text(json.dumps(tickets, indent=2) + "\n")
    (ex / "seed" / "customers.json").write_text(json.dumps(customers, indent=2) + "\n")
    return len(rows)


def add_large(DST):
    """Add the large policy, the cap, the instruction lines and the examples to the task at DST, in place."""
    large = DST / "large_policy" / "docs"
    if not large.is_dir():
        sys.exit(f"{large} missing: run large_policy/build_docs.py first")
    toml = (DST / "task.toml").read_text()
    toml = replace_once(toml, 'description = "Skyway Air with the architecture fixed per run',
                        'description = "Skyway Air with a large policy base and a 12k-token cap per model call; '
                        'the architecture is fixed per run', "task.toml")
    (DST / "task.toml").write_text(toml)

    added = {0: copy_docs(large / "stage0", DST / "environment" / "app" / "docs")}
    for n in range(1, 6):
        upd = DST / "steps" / f"stage{n}" / "workdir" / f"stage{n}_update"
        added[n] = copy_docs(large / f"stage{n}", upd / "new_docs")
        listing = upd / "new_docs.txt"
        lines = listing.read_text().splitlines() if listing.exists() else []
        lines += ["sources/" + p[len("docs/"):] for p in added[n] if "sources/" + p[len("docs/"):] not in lines]
        listing.write_text("\n".join(lines) + "\n")

    capped = kept = 0
    for f in [DST / "tests" / "cases.json", *sorted((DST / "tests" / "stages").glob("stage*/cases.json"))]:
        cases = json.loads(f.read_text())
        for c in cases:
            if c.get("prompt_cap_tokens") and c["prompt_cap_tokens"] <= CAP:
                kept += 1
            else:
                c["prompt_cap_tokens"] = CAP
                capped += 1
        f.write_text(json.dumps(cases, indent=2) + "\n")

    steps = sorted((DST / "steps").glob("*/instruction.md"))
    for f in steps:
        f.write_text(replace_once(f.read_text(), CAP_ANCHOR, CAP_ANCHOR + CAP_TEXT + ASK_TEXT, f.relative_to(REPO)))

    n_examples = large_examples(DST)
    print(f"large policy: {len(added[0])} stage-0 docs, "
          + ", ".join(f"stage {n}: {len(added[n])}" for n in range(1, 6))
          + f"; cap {CAP} on {capped} cases ({kept} keep a stricter cap); {n_examples} practice examples")


