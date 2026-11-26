"""Play every ticket's correct answer against the server and check the end state matches what the ticket expects.

    python3 server_selftest.py

For each stage and ticket: reset the stage's seed, make the calls the expected state implies (PATCH the ticket,
POST refunds/credits/reimbursements/approvals/changes, handoffs and comments), and compare the records with expect,
contains, not_contains and unchanged. Ticket pairs ("after") run in order on the same records; the second is
compared with the records as the first left them, as verify.py does. Catches tickets whose
expectations the server cannot produce, or produces differently.
"""
import copy
import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("server", ROOT / "environment/app/server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


def call(method, path, body=None):
    result = server.route(method, path, copy.deepcopy(body) if body is not None else ({} if method != "GET" else None))
    return server.with_confirmation(path, result) if method == "POST" else result


def booking_for(case):
    for g in case.get("lookups", []):
        if g.startswith("GET /bookings/"):
            return g.split("/")[2]
    for p in case["expect"]:
        if p.split(".")[0] in ("refunds", "credits", "reimbursements", "changes"):
            return p.split(".")[1]
    return None


def play(case, responses):
    """Make the calls this ticket's expected end state implies; remember write responses for confirmation ids."""
    sup = case["input"]["ticket_id"]
    patch = {}
    groups = {}
    for path, want in case["expect"].items():
        file, rid, field = path.split(".", 2)
        if file == "tickets":
            patch[field] = want
        else:
            groups.setdefault((file, rid), {})[field] = want
    labels = case["contains"].get(f"tickets.{sup}.labels")
    if labels:
        patch["labels"] = labels
    if patch:
        call("PATCH", f"/tickets/{sup}", patch)
    for (file, rid), fields in groups.items():
        if file == "refunds":
            responses.append(call("POST", "/refunds", {"booking_id": rid, "amount": fields["amount"], "method": fields["method"]}))
        elif file == "credits":
            for reason, amount in fields.items():
                responses.append(call("POST", "/credits", {"booking_id": rid, "amount": amount, "reason": reason}))
        elif file == "reimbursements":
            for kind, amount in fields.items():
                responses.append(call("POST", "/reimbursements", {"booking_id": rid, "amount": amount, "kind": kind}))
        elif file == "approvals":
            responses.append(call("POST", "/approvals", {"ticket_id": rid, "booking_id": booking_for(case),
                                                         "kind": fields["kind"], "amount": fields["amount"]}))
        elif file == "changes":
            responses.append(call("POST", f"/bookings/{rid}/change", fields))
        else:
            raise AssertionError(f"no call writes {file}")
    for rc in case.get("required_calls", []):
        method, path = rc["call"].split()
        if path == "/handoffs":
            call("POST", path, {**rc["body"], "summary": "Handing over."})
        elif path.endswith("/comments"):
            call("POST", path, {"body": "Status: done on your earlier ticket.", "public": True})
    if case.get("require_attempt"):
        cid = next(r["confirmation_id"] for r in responses if isinstance(r, dict) and "confirmation_id" in r)
        call("POST", f"/tickets/{sup}/comments", {"body": f"Your confirmation number is {cid}.", "public": True})
        sup_comments = [c["body"] for c in server.load("tickets")[sup]["comments"]]
        assert any(cid in b for b in sup_comments)


def lookup(state, path):
    file, rid, field = path.split(".", 2)
    return state.get(file, {}).get(rid, {}).get(field)


def check(case, seed, n):
    state = {name: server.load(name) for name in server.FILES}
    errors = []
    for path, want in case["expect"].items():
        if lookup(state, path) != want:
            errors.append(f"{path}: got {lookup(state, path)!r}, want {want!r}")
    for path, values in case["contains"].items():
        got = lookup(state, path) or []
        errors += [f"{path}: missing {v}" for v in values if v not in got]
    for path, values in case.get("not_contains", {}).items():
        got = lookup(state, path) or []
        errors += [f"{path}: has {v}" for v in values if v in got]
    for file in case.get("unchanged", []):
        if state.get(file) != seed.get(file):
            errors.append(f"{file} changed")
    return errors


def main():
    total, failed = 0, []
    for n in range(6):
        base = ROOT / ("tests" if n == 0 else f"tests/stages/stage{n}")
        cases = json.loads((base / "cases.json").read_text())
        by_id = {c["id"]: c for c in cases}
        seed = {name: json.loads((base / "seed" / f"{name}.json").read_text()) if (base / "seed" / f"{name}.json").exists() else {}
                for name in server.FILES}
        for c in cases:
            if any(x.get("after") == c["id"] for x in cases):
                continue  # the first ticket of a pair runs with its partner
            data = Path(tempfile.mkdtemp())
            server.DATA_DIR, server.FAIL_WRITES = data, 0
            server.reset(data, base / "seed")
            chain = ([by_id[c["after"]]] if c.get("after") else []) + [c]
            responses, errors = [], []
            try:
                start = seed
                for i, x in enumerate(chain):
                    play(x, responses)
                    errors += [f"({x['id']}) {e}" for e in check(x, start, n)]
                    # verify.run_case grades a follow-up against the desk as the first ticket left it
                    start = {name: server.load(name) for name in server.FILES}
            except Exception as e:  # a call the server refuses
                errors.append(f"server refused: {e}")
            total += len(chain)
            if errors:
                failed.append((n, c["id"], errors))
            shutil.rmtree(data)
    for n, cid, errors in failed:
        print(f"stage {n} {cid}: {errors[:3]}")
    print(f"{total - len(failed)}/{total} tickets reach their expected end state through the server")


if __name__ == "__main__":
    main()
