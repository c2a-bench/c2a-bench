"""Check the support API doc against the server: fields, values, enums, routes and error codes, over HTTP.

    python3 api_doc_check.py

Starts environment/app/server.py on every seed (stage 0-5 and the practice examples) and:
- GETs every record and compares its fields with the doc's example for that endpoint (nested lists and objects too),
  and every enum value in the data with the values the doc lists;
- checks the doc's write enums equal the server's, by sending each documented value (must work) and an unknown one
  (must get 400);
- checks the documented error codes (400, 404, 409), the 500 of --fail-writes, and that writes answer as documented.
Exits 1 on any mismatch.
"""
import json
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "environment/app"
DOC = (APP / "api_docs/support-api.md").read_text()
SEEDS = [ROOT / "tests/seed"] + [ROOT / f"tests/stages/stage{n}/seed" for n in range(1, 6)] + [APP / "examples/seed"]
ERRORS = []


def fail(msg):
    if msg not in ERRORS:
        ERRORS.append(msg)


# ---------------------------------------------------------------- the doc

def doc_example(locator):
    """The JSON block that follows a heading, or the JSON block whose text contains `locator`."""
    blocks = [(m.start(), m.group(1)) for m in re.finditer(r"```json\n(.*?)```", DOC, re.S)]
    inside = [b for _, b in blocks if locator in b]
    if inside:
        return json.loads(inside[0])
    start = DOC.index(locator)
    return json.loads(next(b for pos, b in blocks if pos > start))


def section(heading):
    """The doc text under a heading, up to the next heading."""
    start = DOC.index(heading) + len(heading)
    nxt = re.search(r"^#{2,3} ", DOC[start:], re.M)
    return DOC[start:start + nxt.start()] if nxt else DOC[start:]


def doc_values(field, heading):
    """Backticked values the doc lists for a field under a heading: a table row `| `field` | ... |`, or a line
    "`field`: `a` | `b`" (up to the end of that sentence)."""
    out = set()
    for line in section(heading).splitlines():
        if re.match(rf"\|\s*`{re.escape(field)}`\s*\|", line):
            cell = re.split(r"(?<!\\)\|", line)[2]
        elif f"`{field}`: `" in line:
            cell = re.split(r"\.(\s|$)", line.split(f"`{field}`: ", 1)[1])[0]
        else:
            continue
        out |= {v.strip("`") for v in re.findall(r"`[^`]+`", cell) if "{" not in v}
    return {None if v == "null" else v for v in out}


# ---------------------------------------------------------------- the server

class Desk:
    def __init__(self, seed, fail_writes=0):
        self.data = Path(tempfile.mkdtemp())
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.proc = subprocess.Popen([sys.executable, "-I", str(APP / "server.py"), "--data", str(self.data),
                                      "--reset-from", str(seed), "--port", str(self.port),
                                      "--fail-writes", str(fail_writes)])
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", self.port), 0.1).close()
                return
            except OSError:
                time.sleep(0.05)
        raise SystemExit("server did not start")

    def call(self, method, path, body=None, raw=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def close(self):
        self.proc.terminate()
        self.proc.wait()
        shutil.rmtree(self.data)


# ---------------------------------------------------------------- reads

OPTIONAL = {"bookings.passengers": {"age"}, "refunds": {"issued_at"}, "credits": {"issued_at"},
            "reimbursements": {"paid_at"}, "approvals": {"requested_at"}}  # the doc says when these appear


def same_fields(where, got, want):
    if isinstance(want, dict) and isinstance(got, dict):
        optional = OPTIONAL.get(where, set())
        if set(got) - set(want) or set(want) - set(got) - optional:
            fail(f"{where}: server has {sorted(set(got) - set(want))} not in the doc; doc has "
                 f"{sorted(set(want) - set(got) - optional)} not on the record")
        for k in set(got) & set(want):
            if isinstance(want[k], (dict, list)) and want[k] and k != "fares":
                same_fields(f"{where}.{k}", got[k], want[k])
    elif isinstance(want, list) and isinstance(got, list):
        for x in got:
            same_fields(where, x, want[0])


HEAD = {"customers": "### `GET /customers/{customer_id}`", "bookings": "### `GET /bookings/{booking_id}`",
        "flights": "### `GET /flights/{flight_id}`", "bag_reports": "### `GET /bag_reports/{report_id}`",
        "tickets": "### `PATCH /tickets/{ticket_id}`"}
VALUES = {"customers": ["skyway_miles_tier"], "bookings": ["channel", "fare_type"], "flights": ["status", "cause"],
          "bag_reports": ["type", "status"], "tickets": ["category", "status"]}


def check_reads(desk, seed):
    examples = {"customers": doc_example("### `GET /customers/{customer_id}`"),
                "bookings": doc_example("### `GET /bookings/{booking_id}`"),
                "flights": doc_example("### `GET /flights/{flight_id}`"),
                "bag_reports": doc_example("### `GET /bag_reports/{report_id}`"),
                "tickets": doc_example("### `GET /tickets/{ticket_id}`")}
    for name, want in examples.items():
        ids = list(json.loads((seed / f"{name}.json").read_text()))
        for rid in ids:
            status, rec = desk.call("GET", f"/{name}/{rid}")
            if status != 200:
                fail(f"GET /{name}/{rid}: {status}")
                continue
            same_fields(name, rec, want)
            for field in VALUES[name]:
                allowed = doc_values(field, HEAD[name]) | ({None} if name == "tickets" and field == "category" else set())
                if rec[field] not in allowed:  # a new ticket has no category yet
                    fail(f"{name}.{field} = {rec[field]!r} is not a value the doc lists {sorted(map(str, allowed))}")
            if name == "bookings":
                for a in rec["addons"]:
                    if a["type"] not in doc_values("addons[].type", HEAD[name]):
                        fail(f"addon type {a['type']!r} not in the doc")
                for a in rec.get("assistance", []):
                    same_fields("bookings.assistance", a, {"passenger": 0, "type": 0, "requested_at": 0})
        if name == "customers":
            for rid in ids:
                for sub in ("bookings", "tickets"):
                    status, recs = desk.call("GET", f"/customers/{rid}/{sub}")
                    if status != 200 or [r["id"] for r in recs] != sorted(r["id"] for r in recs):
                        fail(f"GET /customers/{rid}/{sub}: {status} or not oldest id first")
                    for r in recs:
                        same_fields(sub, r, examples[sub])
    for r in json.loads((seed / "bag_reports.json").read_text()).values():
        status, recs = desk.call("GET", f"/bag_reports?tag_number={r['tag_number']}")
        if status != 200 or not recs:
            fail(f"GET /bag_reports?tag_number={r['tag_number']}: {status}, {len(recs)} found")
    money = {"refunds": doc_example('{ "amount": 238, "method"'),
             "credits": doc_example('{ "goodwill": 50'), "reimbursements": doc_example('{ "hotel": 160')}
    for name in ("refunds", "credits", "reimbursements", "changes"):
        for bid, rec in json.loads((seed / f"{name}.json").read_text()).items():
            status, got = desk.call("GET", f"/{name}/{bid}")
            if status != 200 or got != rec:
                fail(f"GET /{name}/{bid}: {status}")
            if name == "refunds":
                same_fields(name, got, money[name])
            elif name == "credits":
                extra = set(got) - doc_values("reason", "### `POST /credits`") - {"issued_at"}
                extra and fail(f"credits on {bid} have keys the doc does not explain: {sorted(extra)}")
            elif name == "reimbursements":
                extra = set(got) - doc_values("kind", "### `POST /reimbursements`") - {"paid_at"}
                extra and fail(f"reimbursements on {bid} have keys the doc does not explain: {sorted(extra)}")
    for rec in json.loads((seed / "approvals.json").read_text()).values():
        status, got = desk.call("GET", f"/approvals?booking_id={rec['booking_id']}")
        for x in got:
            same_fields("approvals", x, doc_example("`GET /approvals?booking_id=SK1234` lists")[0])


# ---------------------------------------------------------------- writes

def check_prose():
    """The doc's statements a test can hold to: the error codes it lists, and the label limits."""
    src = (APP / "server.py").read_text()
    server_codes = {int(c) for c in re.findall(r"ApiError\((\d{3})", src)}
    line = next(l for l in DOC.splitlines() if l.startswith("All bodies are JSON."))
    doc_codes = {int(c) for c in re.findall(r"`(\d{3})`", line)}
    if doc_codes != server_codes:
        fail(f"error codes: the doc lists {sorted(doc_codes)}, the server returns {sorted(server_codes)}")
    row = next(l for l in DOC.splitlines() if l.startswith("| `labels` |"))
    limit = re.search(r"\{0,(\d+)\}", re.search(r"LABEL_RE = .*", src).group(0)).group(1)
    if f"at most {int(limit) + 1} characters" not in row or "starts with a letter or digit" not in row:
        fail(f"labels row does not state the server's limits (first character a letter or digit, {int(limit) + 1} max)")


def check_writes(seed):
    tickets = json.loads((seed / "tickets.json").read_text())
    bookings = json.loads((seed / "bookings.json").read_text())
    flights = json.loads((seed / "flights.json").read_text())
    sup, bid, fid = next(iter(tickets)), next(iter(bookings)), next(iter(flights))
    server_sets = {}
    src = (APP / "server.py").read_text()
    for name in ("CATEGORIES", "STATUSES", "REFUND_METHODS", "CREDIT_REASONS", "REIMBURSEMENT_KINDS", "APPROVAL_KINDS",
                 "HANDOFF_REASONS"):
        server_sets[name] = set(eval(re.search(rf"^{name} = (.*)$", src, re.M).group(1)))
    enums = {"CATEGORIES": ("category", "### `PATCH /tickets"), "STATUSES": ("status", "### `PATCH /tickets"),
             "REFUND_METHODS": ("method", "### `POST /refunds`"), "CREDIT_REASONS": ("reason", "### `POST /credits`"),
             "REIMBURSEMENT_KINDS": ("kind", "### `POST /reimbursements`"),
             "APPROVAL_KINDS": ("kind", "### `POST /approvals`"), "HANDOFF_REASONS": ("reason", "### `POST /handoffs`")}
    doc_sets = {name: doc_values(field, heading) for name, (field, heading) in enums.items()}
    for name in enums:
        if doc_sets[name] != server_sets[name]:
            fail(f"{name}: doc lists {sorted(doc_sets[name])}, server accepts {sorted(server_sets[name])}")

    desk = Desk(seed)
    try:
        def expect(status_want, method, path, body=None, raw=None, keys=None):
            status, got = desk.call(method, path, body, raw)
            if status != status_want:
                fail(f"{method} {path} {body}: {status} (want {status_want}) {got}")
            if keys is not None and status == 200 and set(got) != set(keys):
                fail(f"{method} {path}: returns {sorted(got)}, want {sorted(keys)}")
            return got

        ticket_keys = set(doc_example("### `GET /tickets/{ticket_id}`"))
        for c in doc_sets["CATEGORIES"]:
            expect(200, "PATCH", f"/tickets/{sup}", {"category": c}, keys=ticket_keys)
        for s in doc_sets["STATUSES"]:
            expect(200, "PATCH", f"/tickets/{sup}", {"status": s})
        expect(200, "PATCH", f"/tickets/{sup}", {"labels": ["agency-refund"], "booking_id": bid})
        expect(400, "PATCH", f"/tickets/{sup}", {"category": "bogus"})
        expect(400, "PATCH", f"/tickets/{sup}", {"labels": ["Not Valid"]})
        expect(400, "PATCH", f"/tickets/{sup}", {"labels": ["-starts-with-dash"]})
        expect(400, "PATCH", f"/tickets/{sup}", {"labels": ["a" * 65]})
        expect(200, "PATCH", f"/tickets/{sup}", {"labels": ["a" * 64]})
        expect(400, "PATCH", f"/tickets/{sup}", {"priority": "high"})
        expect(404, "PATCH", "/tickets/SKY-0000", {"status": "open"})
        expect(200, "POST", f"/tickets/{sup}/comments", {"body": "Noted.", "public": False}, keys={"body", "public"})
        expect(400, "POST", f"/tickets/{sup}/comments", {"body": "Noted."})
        paid = {"booking_id", "amount", "confirmation_id"}
        for m in doc_sets["REFUND_METHODS"]:
            expect(200, "POST", "/refunds", {"booking_id": bid, "amount": 10, "method": m}, keys=paid | {"method"})
        for r in doc_sets["CREDIT_REASONS"]:
            expect(200, "POST", "/credits", {"booking_id": bid, "amount": 10, "reason": r}, keys=paid | {"reason"})
        for k in doc_sets["REIMBURSEMENT_KINDS"]:
            expect(200, "POST", "/reimbursements", {"booking_id": bid, "amount": 10, "kind": k}, keys=paid | {"kind"})
        expect(400, "POST", "/refunds", {"booking_id": bid, "amount": 10, "method": "cash"})
        expect(400, "POST", "/credits", {"booking_id": bid, "amount": 10, "reason": "bogus"})
        expect(400, "POST", "/reimbursements", {"booking_id": bid, "amount": 10, "kind": "bogus"})
        expect(400, "POST", "/refunds", {"booking_id": bid, "amount": 0, "method": "original_payment"})
        expect(404, "POST", "/refunds", {"booking_id": "SK0000", "amount": 10, "method": "original_payment"})
        expect(400, "POST", "/approvals", {"ticket_id": sup, "booking_id": bid, "kind": "bogus", "amount": 300})
        kinds = sorted(doc_sets["APPROVAL_KINDS"])
        others = [t for t in tickets if t != sup]
        for k, t in zip(kinds, [sup] + others):
            expect(200, "POST", "/approvals", {"ticket_id": t, "booking_id": bid, "kind": k, "amount": 300},
                   keys={"ticket_id", "booking_id", "kind", "amount", "status"})
        expect(409, "POST", "/approvals", {"ticket_id": sup, "booking_id": bid, "kind": kinds[0], "amount": 300})
        got = expect(200, "POST", f"/bookings/{bid}/change", {"to_flight": fid, "change_fee": 0, "fare_difference": 0},
                     keys={"booking_id", "to_flight", "change_fee", "fare_difference"})
        if desk.call("GET", f"/changes/{bid}")[1] != {k: v for k, v in got.items() if k != "booking_id"}:
            fail("GET /changes does not show the change just made")
        expect(404, "POST", f"/bookings/{bid}/change", {"to_flight": "SX000", "change_fee": 0, "fare_difference": 0})
        for r in doc_sets["HANDOFF_REASONS"]:
            h = expect(200, "POST", "/handoffs", {"ticket_id": sup, "reason": r, "summary": "Over to you."},
                       keys={"id", "ticket_id", "reason", "summary"})
            if not re.fullmatch(r"H-\d{4}", h.get("id", "")):
                fail(f"handoff id {h.get('id')!r} is not like H-0001")
        expect(400, "POST", "/handoffs", {"ticket_id": sup, "reason": "safety"})
        expect(400, "POST", "/handoffs", {"ticket_id": sup, "reason": "bogus", "summary": "x"})
        expect(404, "GET", "/flights/SX000")
        f0 = next(iter(flights.values()))
        found = expect(200, "GET", f"/flights?route={f0['route']}&date={f0['scheduled_departure'][:10]}")
        if fid not in [x["id"] for x in found] or any(x["route"] != f0["route"] for x in found):
            fail("GET /flights?route=&date= does not find the flight it should")
        expect(400, "GET", "/flights?date=2026-06-07")
        expect(404, "GET", "/nowhere")
        expect(400, "POST", "/refunds", raw=b"{not json")
        log = (desk.data / "requests.jsonl").read_text().splitlines()
        if not log or any(set(json.loads(l)) != {"method", "path", "body", "status", "response", "error"} for l in log):
            fail("requests.jsonl lines are missing or malformed")
    finally:
        desk.close()

    desk = Desk(seed, fail_writes=1)
    try:
        if desk.call("POST", "/refunds", {"booking_id": bid, "amount": 10, "method": "original_payment"})[0] != 500 or \
           desk.call("POST", "/refunds", {"booking_id": bid, "amount": 10, "method": "original_payment"})[0] != 200:
            fail("--fail-writes 1: the first write must get 500 and the next one work")
    finally:
        desk.close()


def main():
    for seed in SEEDS:
        desk = Desk(seed)
        try:
            check_reads(desk, seed)
        finally:
            desk.close()
    check_prose()
    check_writes(SEEDS[0])
    check_writes(SEEDS[-1])
    for e in ERRORS:
        print(" ", e)
    print(f"{len(SEEDS)} seeds read over HTTP; writes checked on 2; {len(ERRORS)} mismatches between the API doc and the server")
    sys.exit(1 if ERRORS else 0)


if __name__ == "__main__":
    main()
