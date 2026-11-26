"""Blind solvability review: can each ticket be answered, and only one way, from what a perfect agent would know?

    python3 solvability_review.py --make DIR      # write DIR/batch*.json for the reviewers
    python3 solvability_review.py --compare DIR   # read DIR/answer*.json and diff them with the expected answers

A reviewer gets a ticket's opening, all its customer facts, the support API data the bot can read (the stage's seed;
for a follow-up, the state the first ticket left) and every rule of the stage (not the ticket's own rules, which would
hint), but never the expected answer. It says what a correct agent does: category, labels, payments, approval,
flight change, handoff, comment. --compare turns that into the end state the grader checks (payments add to what
the seed already holds) and lists every ticket whose answer differs, or that a reviewer found ambiguous.
Each ticket version is reviewed once: a copy with the same facts, answer and rules as an earlier stage is skipped.
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MONEY = ("refunds", "credits", "reimbursements", "approvals", "changes")
LABELS = {"agency-refund", "receipts-needed", "claim-late", "wear-and-tear", "change-denied", "not-authorized",
          "assistance-failure", "awaiting-receipts"}


def stage_dir(n):
    return ROOT / ("tests" if n == 0 else f"tests/stages/stage{n}")


def load(path):
    return json.loads(Path(path).read_text())


def entries():
    """Every ticket version worth a review, with its stage."""
    seen, out = {}, []
    for n in range(6):
        rules = load(stage_dir(n) / "rules.json")
        rule_text = {r["id"]: r["rule"] for r in rules}
        for c in load(stage_dir(n) / "cases.json"):
            key = json.dumps({"facts": c.get("facts"), "expect": c["expect"], "contains": c["contains"],
                              "required": c.get("required_calls"), "rules": {r: rule_text.get(r) for r in c["rules"]}},
                             sort_keys=True)
            if seen.get(c["id"]) == key:
                continue
            seen[c["id"]] = key
            out.append((n, c))
    return out


def api_data(n, case, cases):
    seed = {f: load(stage_dir(n) / "seed" / f"{f}.json") for f in
            ("customers", "bookings", "flights", "bag_reports", "tickets") + MONEY}
    if case.get("after"):  # a follow-up: the desk as the first ticket left it
        first = cases[case["after"]]
        for path, v in first["expect"].items():
            f, rid, field = path.split(".", 2)
            seed.setdefault(f, {}).setdefault(rid, {})[field] = v
    t = seed["tickets"][case["input"]["ticket_id"]]
    cid = t["customer_id"]
    looked = {g.split("/")[2] for g in case.get("lookups", []) if g.startswith("GET /bookings/")}
    bookings = {b: v for b, v in seed["bookings"].items() if v["customer_id"] == cid or b in looked}
    flights = {}
    for b in bookings.values():
        for s in b["segments"]:
            fl = seed["flights"].get(s["flight_id"])
            if fl:
                flights[s["flight_id"]] = fl
                rep = fl.get("replacement_flight")
                if rep and rep in seed["flights"]:
                    flights[rep] = seed["flights"][rep]
    tickets = {k: v for k, v in seed["tickets"].items() if v.get("customer_id") == cid}
    routes = {fl["route"] for fl in flights.values()}
    search = {k: v for k, v in seed["flights"].items() if v.get("route") in routes}  # what GET /flights?route= finds
    return {"ticket": {"id": case["input"]["ticket_id"], **t}, "customer": seed["customers"][cid],
            "other_tickets_of_this_customer": {k: v for k, v in tickets.items() if k != case["input"]["ticket_id"]},
            "bookings": bookings, "flights": flights,
            "bag_reports": {k: v for k, v in seed["bag_reports"].items() if v["booking_id"] in bookings},
            "flight_search_on_these_routes": search,
            "money_already_on_the_bookings": {f: {k: v for k, v in seed[f].items()
                                                  if k in bookings or k in tickets or v.get("booking_id") in bookings}
                                              for f in MONEY}}


def make(folder, batches=6, only=None):
    folder.mkdir(parents=True, exist_ok=True)
    items = []
    for n, c in entries():
        if only and f"{c['id']}@stage{n}" not in only:
            continue
        cases = {x["id"]: x for x in load(stage_dir(n) / "cases.json")}
        items.append({"id": f"{c['id']}@stage{n}", "stage": n, "handled_on": load(stage_dir(n) / "doc_plan.json")["date"],
                      "customer_opening": c["customer"], "customer_facts": c.get("facts") or [],
                      "requester_email": load(stage_dir(n) / "seed/tickets.json")[c["input"]["ticket_id"]]["requester_email"],
                      "api_data": api_data(n, c, cases)})
    size = -(-len(items) // batches)
    for i in range(batches):
        (folder / f"batch{i + 1}.json").write_text(json.dumps(items[i * size:(i + 1) * size], indent=1))
    for n in range(6):
        (folder / f"rules_stage{n}.json").write_text(json.dumps(
            [{"id": r["id"], "rule": r["rule"]} for r in load(stage_dir(n) / "rules.json")], indent=1))
    print(f"{len(items)} ticket versions in {batches} batches -> {folder}")


def predicted(answer, case, seed):
    """The end state the reviewer's actions give, in the grader's paths (payments add to the seed)."""
    sup = case["input"]["ticket_id"]
    out = {f"tickets.{sup}.category": answer.get("category")}
    totals = {}
    for p in answer.get("payments") or []:
        f, b = p["file"], p["booking"]
        if f == "refunds":
            key = (f, b, "amount")
            totals[key] = totals.get(key, (seed.get(f, {}).get(b) or {}).get("amount", 0)) + p["amount"]
            out[f"refunds.{b}.method"] = "original_payment"
        else:
            sub = p.get("reason") or p.get("kind")
            key = (f, b, sub)
            totals[key] = totals.get(key, (seed.get(f, {}).get(b) or {}).get(sub, 0)) + p["amount"]
    for (f, b, field), v in totals.items():
        out[f"{f}.{b}.{field}"] = round(v, 2)
    a = answer.get("approval")
    if a:
        out.update({f"approvals.{sup}.kind": a["kind"], f"approvals.{sup}.amount": a["amount"],
                    f"approvals.{sup}.booking_id": a["booking"]})
    ch = answer.get("change")
    if ch:
        out.update({f"changes.{ch['booking']}.to_flight": ch["to_flight"],
                    f"changes.{ch['booking']}.change_fee": ch["change_fee"],
                    f"changes.{ch['booking']}.fare_difference": ch["fare_difference"]})
    return out


def compare(folder):
    answers = {}
    for f in sorted(folder.glob("answer*.json")):
        answers.update(load(f))
    problems, ambiguous, checked = [], [], 0
    for n, c in entries():
        key = f"{c['id']}@stage{n}"
        a = answers.get(key)
        if a is None:
            problems.append((key, "no answer"))
            continue
        checked += 1
        seed = {f: load(stage_dir(n) / "seed" / f"{f}.json") for f in MONEY}
        if c.get("after"):
            first = {x["id"]: x for x in load(stage_dir(n) / "cases.json")}[c["after"]]
            for path, v in first["expect"].items():
                f, rid, field = path.split(".", 2)
                if f in seed:
                    seed[f].setdefault(rid, {})[field] = v
        got = predicted(a, c, seed)
        sup = c["input"]["ticket_id"]
        diffs = []
        for path, want in c["expect"].items():
            if got.get(path) != want:
                diffs.append(f"{path}: reviewer {got.get(path)!r}, expected {want!r}")
        for path, v in got.items():
            if path not in c["expect"] and path.split(".")[0] in MONEY:
                diffs.append(f"{path}: reviewer pays {v!r}, the ticket expects nothing there")
        want_labels = set(c["contains"].get(f"tickets.{sup}.labels", []))
        got_labels = set(a.get("labels") or []) & LABELS
        if want_labels != got_labels:
            diffs.append(f"labels: reviewer {sorted(got_labels)}, expected {sorted(want_labels)}")
        want_handoff = next((rc["body"].get("reason") for rc in c.get("required_calls", []) if "/handoffs" in rc["call"]), None)
        if (a.get("handoff") or None) != want_handoff:
            diffs.append(f"handoff: reviewer {a.get('handoff')!r}, expected {want_handoff!r}")
        want_comment = next((rc["call"].split("/")[2] for rc in c.get("required_calls", []) if "/comments" in rc["call"]),
                            sup if c.get("require_attempt") else None)
        if want_comment and not a.get("comment_on"):
            diffs.append(f"comment: reviewer posts none, expected one on {want_comment}")
        if diffs:
            problems.append((key, diffs))
        if a.get("ambiguous"):
            ambiguous.append((key, a["ambiguous"]))
    print(f"{checked} ticket versions answered blind; {len(problems)} differ from the expected answer; "
          f"{len(ambiguous)} flagged ambiguous")
    for key, d in problems:
        print(f"\n  {key}:")
        for x in (d if isinstance(d, list) else [d]):
            print(f"    {x}")
    if ambiguous:
        print("\nflagged ambiguous:")
        for key, why in ambiguous:
            print(f"  {key}: {why}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--make", type=Path)
    ap.add_argument("--compare", type=Path)
    ap.add_argument("--only", help="file listing the ticket versions to review again, one per line")
    ap.add_argument("--batches", type=int, default=6)
    args = ap.parse_args()
    if args.make:
        make(args.make, args.batches, set(Path(args.only).read_text().split()) if args.only else None)
    elif args.compare:
        compare(args.compare)
    else:
        ap.error("pass --make DIR or --compare DIR")


if __name__ == "__main__":
    main()
