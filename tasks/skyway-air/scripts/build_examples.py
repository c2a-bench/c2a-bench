"""Build the practice examples the builder sees: environment/app/examples/cases.json and examples/seed/.

Run from tasks/skyway-air. Practice customers, bookings and flights are separate from the test tickets' records. Amounts
come from the stage-0 rule functions, and every example is rebuilt under each later stage's rule switches (read from
build_stage_tickets.py) and must come out the same, so an example never teaches an answer a later stage changes. Each
example is played through the server to check its end state.
"""
import copy
import importlib.util
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_stage0_tickets as b0  # noqa: E402

OUT = ROOT / "environment/app/examples"
MONEY_FILES = ["refunds", "credits", "reimbursements", "approvals", "changes"]

# a separate practice world
for name in ("CUSTOMERS", "BOOKINGS", "BAGS", "REFUNDS", "CREDITS", "REIMBURSEMENTS", "APPROVALS", "CHANGES"):
    setattr(b0, name, {})
b0.FLIGHTS = {
    "SX101": b0.flight("RDU-ORD", "2026-05-17T14:00:00Z", "cancelled", "crew", "2026-05-17T10:00:00Z", replacement="SX103"),
    "SX103": b0.flight("RDU-ORD", "2026-05-17T19:00:00Z", arrived="2026-05-17T21:05:00Z"),
    "SX201": b0.flight("BNA-MCO", "2026-05-16T15:00:00Z", "delayed", "weather", dep_delay=210, arr_delay=220,
                       arrived="2026-05-16T21:40:00Z"),
    "SX301": b0.flight("RDU-LGA", "2026-05-14T12:00:00Z", arrived="2026-05-14T13:40:00Z"),
    "SX401": b0.flight("BNA-ATL", "2026-06-12T13:00:00Z", fares={"Basic": 99, "Standard": 149, "Flex": 209}),
    "SX403": b0.flight("BNA-ATL", "2026-06-14T13:00:00Z", fares={"Basic": 109, "Standard": 169, "Flex": 229}),
    "SX501": b0.flight("RDU-MIA", "2026-06-20T15:00:00Z", fares={"Basic": 119, "Standard": 172, "Flex": 239}),
    "SX503": b0.flight("RDU-MIA", "2026-06-20T19:00:00Z", fares={"Basic": 129, "Standard": 182, "Flex": 249}),
}
b0.customer("cust_ex_wood", "Holly Wood", "holly.wood@example.com")
b0.booking("SKX101", "cust_ex_wood", ["SX101"], "Standard", 210, ["Holly Wood"], "2026-04-01T08:00:00Z",
           addons=[("checked_bag", 0, "SX101", 35)])
b0.customer("cust_ex_park", "Dae Park", "dae.park@example.com")
b0.booking("SKX102", "cust_ex_park", ["SX501"], "Standard", 172, ["Dae Park"], "2026-05-01T08:00:00Z")
b0.customer("cust_ex_lane", "Ivy Lane", "ivy.lane@example.com")
b0.booking("SKX103", "cust_ex_lane", ["SX501"], "Flex", 239, ["Ivy Lane"], "2026-05-02T08:00:00Z")
b0.customer("cust_ex_moss", "Rob Moss", "rob.moss@example.com")
b0.booking("SKX104", "cust_ex_moss", ["SX301"], "Standard", 160, ["Rob Moss"], "2026-04-05T08:00:00Z",
           addons=[("checked_bag", 0, "SX301", 35)])
b0.bag("BX-1001", "SKX104", "SX301", "damaged", "2026-05-14T14:10:00Z")
b0.customer("cust_ex_hale", "Uma Hale", "uma.hale@example.com")
b0.booking("SKX105", "cust_ex_hale", ["SX301"], "Standard", 160, ["Uma Hale"], "2026-04-06T08:00:00Z",
           addons=[("checked_bag", 0, "SX301", 35)])
b0.bag("BX-1002", "SKX105", "SX301", "damaged", "2026-05-14T14:20:00Z")
b0.customer("cust_ex_ford", "Ned Ford", "ned.ford@example.com")
b0.booking("SKX106", "cust_ex_ford", ["SX401"], "Standard", 149, ["Ned Ford"], "2026-05-03T08:00:00Z")
b0.customer("cust_ex_gray", "Lia Gray", "lia.gray@example.com")
b0.booking("SKX107", "cust_ex_gray", ["SX401"], "Basic", 99, ["Lia Gray"], "2026-05-04T08:00:00Z")
b0.customer("cust_ex_cole", "Abe Cole", "abe.cole@example.com")
b0.booking("SKX108", "cust_ex_cole", ["SX201"], "Standard", 130, ["Abe Cole"], "2026-04-07T08:00:00Z")
b0.customer("cust_ex_rios", "Tina Rios", "tina.rios@example.com")
b0.booking("SKX109", "cust_ex_rios", ["SX301"], "Standard", 160, ["Tina Rios"], "2026-04-08T08:00:00Z")
b0.customer("cust_ex_vale", "Omar Vale", "omar.vale@example.com")
b0.booking("SKX110", "cust_ex_vale", ["SX101"], "Standard", 210, ["Omar Vale"], "2026-04-09T08:00:00Z",
           channel="agency", agency="TripNest")
b0.customer("cust_ex_burr", "Kim Burr", "kim.burr@example.com")
b0.booking("SKX111", "cust_ex_wood", ["SX101"], "Standard", 210, ["Sam Wood"], "2026-04-10T08:00:00Z")
b0.customer("cust_ex_shaw", "Lee Shaw", "lee.shaw@example.com")
b0.booking("SKX112", "cust_ex_shaw", ["SX101"], "Standard", 210, ["Lee Shaw"], "2026-04-11T08:00:00Z")

EX = []


def example(n, test, customer_id, message, category, money=None, labels=(), handoff=None, rules=(), requester=None):
    sup = f"SKY-09{n:02d}"
    expect = {f"tickets.{sup}.category": category}
    expect.update({p.replace("{T}", sup): v for p, v in b0.norm_money(money or {}).items()})
    touched = {p.split(".")[0] for p in expect}
    case = {"id": f"example-{n:02d}", "test": test, "input": {"ticket_id": sup, "customer_id": customer_id, "message": message},
            "expect": expect, "contains": {f"tickets.{sup}.labels": list(labels)} if labels else {},
            "unchanged": [f for f in MONEY_FILES if f not in touched],
            "forbidden_calls": [b0.MONEY[f] for f in MONEY_FILES if f not in touched] + ([] if handoff else ["POST /handoffs"])}
    if handoff:
        case["required_calls"] = [{"call": "POST /handoffs", "body": {"ticket_id": sup, "reason": handoff}}]
    EX.append((case, requester or b0.CUSTOMERS[customer_id]["email"]))



def build():
    EX.clear()
    r = b0.refund_for("SKX101")
    example(1, f"Crew cancellation, the customer did not fly: refund {r} to the original payment.", "cust_ex_wood",
            "Skyway cancelled my May 17 Chicago flight (SKX101) and I didn't take the replacement. Please refund me, bag fee too.",
            "refund", {"refunds.SKX101.amount": r, "refunds.SKX101.method": "original_payment"}, rules=["R2", "R21"])
    ref, cred = b0.voluntary("SKX102")
    example(2, f"Customer cancels their own Standard booking: travel credit {cred}, no refund.", "cust_ex_park",
            "Please cancel my June 20 Miami flight (SKX102). I booked it weeks ago and can't go now.",
            "refund", {"credits.SKX102.amount": cred, "credits.SKX102.reason": "voluntary_cancellation"}, rules=["R5", "R21"])
    ref, cred = b0.voluntary("SKX103")
    example(3, f"Customer cancels their own Flex booking: refund {ref} to the original payment.", "cust_ex_lane",
            "Please cancel my June 20 Miami flight (SKX103) and refund me.",
            "refund", {"refunds.SKX103.amount": ref, "refunds.SKX103.method": "original_payment"}, rules=["R5", "R21"])
    p = b0.repair_pay("shell", 180)
    example(4, f"Bag shell cracked, reported the same day, $180 quote: reimburse {p}.", "cust_ex_moss",
            "My suitcase came off the May 14 New York flight (SKX104, report BX-1001) with the shell cracked. Repair quote $180.",
            "baggage", {"reimbursements.SKX104.bag_repair": p}, rules=["R14", "R15", "R21"])
    example(5, "Bag wheel broke off: label wear-and-tear, nothing paid.", "cust_ex_hale",
            "A wheel came off my suitcase on the May 14 New York flight (SKX105, report BX-1002). Quote $45 to fix.",
            "baggage", labels=["wear-and-tear"], rules=["R15", "R21"])
    ok, fee, diff, back = b0.change("SKX106", "SX403", None)
    example(6, f"Standard fare, not a member, moves to a dearer flight: change fee {fee}, fare difference {diff}.", "cust_ex_ford",
            "Please move my June 12 Atlanta flight (SKX106) to June 14. I'll pay what it costs.",
            "change", {"changes.SKX106.to_flight": "SX403", "changes.SKX106.change_fee": fee, "changes.SKX106.fare_difference": diff},
            rules=["R7", "R21"])
    example(7, "Basic fare, the customer asks to move the flight: label change-denied, nothing changed.", "cust_ex_gray",
            "Can I move my June 12 Atlanta flight (SKX107) to June 14?", "change", labels=["change-denied"], rules=["R7", "R21"])
    example(8, "Weather delay of 3.5 hours, $24 lunch: nothing paid.", "cust_ex_cole",
            "My May 16 Orlando flight (SKX108) was over 3 hours late because of storms. I bought lunch, $24. Can I get it back?",
            "disruption", rules=["R1", "R21"])
    example(9, "The customer was hurt boarding: hand off with reason safety, nothing paid.", "cust_ex_rios",
            "I tripped on the boarding stairs for my May 14 New York flight (SKX109) and hurt my ankle. What now?",
            "other", handoff="safety", rules=["R19", "R21"])
    example(10, "Cancelled flight booked through a travel agency: label agency-refund, no refund.", "cust_ex_vale",
            "My May 17 Chicago flight (SKX110) was cancelled; I didn't fly. I booked through TripNest. Refund please.",
            "refund", labels=["agency-refund"], rules=["R2", "R4", "R21"])
    example(11, "Someone who is not the booking contact asks for a refund: label not-authorized, nothing changed.", "cust_ex_burr",
            "Please refund booking SKX111, Sam's cancelled May 17 Chicago flight. I'm a friend sorting it out for him.",
            "refund", labels=["not-authorized"], rules=["R17", "R21"])
    r = b0.refund_for("SKX112")
    example(12, f"Like example-01, on a desk whose first write fails (run it with --fail-writes 1): retry, refund {r} once.",
            "cust_ex_shaw", "Skyway cancelled my May 17 Chicago flight (SKX112) and I didn't fly. Refund please.",
            "refund", {"refunds.SKX112.amount": r, "refunds.SKX112.method": "original_payment"}, rules=["R2", "R21"])



def stage_switches():
    """The rule switches each later stage sets, as written at the top level of build_stage_tickets.py."""
    out, n = {}, 0
    for line in (ROOT / "scripts/build_stage_tickets.py").read_text().splitlines():
        m = re.match(r"s(\d) = Stage\(", line)
        if m:
            n = int(m.group(1))
        elif n and re.match(r"b0\.[A-Z_]+(, b0\.[A-Z_]+)* = ", line):
            out.setdefault(n, []).append(line)
    return out


def main():
    build()
    answers = [c for c, _ in EX]
    for n, lines in sorted(stage_switches().items()):
        for line in lines:
            exec(line, {"b0": b0})
        build()
        moved = [a["id"] for a, (c, _) in zip(answers, EX) if a != c]
        if moved:
            raise SystemExit(f"stage {n} changes the answer of {moved}; pick examples no stage changes")
    seed = {"customers": copy.deepcopy(b0.CUSTOMERS), "bookings": b0.BOOKINGS, "flights": b0.FLIGHTS, "bag_reports": b0.BAGS,
            "refunds": {}, "credits": {}, "reimbursements": {}, "approvals": {}, "changes": {}, "handoffs": {},
            "tickets": {c["input"]["ticket_id"]: {"customer_id": c["input"]["customer_id"], "requester_email": req,
                                                  "booking_id": None, "category": None, "labels": [], "status": "open",
                                                  "created_at": b0.NOW, "comments": []} for c, req in EX}}
    for cid, c in seed["customers"].items():
        c["bookings"] = [b for b, bk in b0.BOOKINGS.items() if bk["customer_id"] == cid]
        c.setdefault("authorized_agents", [])
    if (OUT / "seed").exists():
        shutil.rmtree(OUT / "seed")
    for name, data in seed.items():
        b0.save(OUT / "seed" / f"{name}.json", data)
    b0.save(OUT / "cases.json", [c for c, _ in EX])

    # each example's end state through the server
    spec = importlib.util.spec_from_file_location("server", ROOT / "environment/app/server.py")
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)
    sys.path.insert(0, str(ROOT / "scripts"))
    import server_selftest as st
    st.server = server
    bad = []
    for c, _ in EX:
        data = Path(tempfile.mkdtemp())
        server.DATA_DIR, server.FAIL_WRITES = data, 0
        server.reset(data, OUT / "seed")
        st.play(c, [])
        errors = st.check(c, seed, 0)
        if errors:
            bad.append((c["id"], errors))
        shutil.rmtree(data)
    test_ids = {x["input"]["ticket_id"] for f in [ROOT / "tests/cases.json", *ROOT.glob("tests/stages/*/cases.json")]
                for x in json.loads(f.read_text())}
    clash = test_ids & {c["input"]["ticket_id"] for c, _ in EX}
    print(f"{len(EX)} examples written; {len(EX) - len(bad)} reach their end state through the server; "
          f"ticket ids shared with test tickets: {sorted(clash) or 'none'}")
    for cid, e in bad:
        print(" ", cid, e)


if __name__ == "__main__":
    main()
