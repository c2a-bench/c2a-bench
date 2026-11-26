"""Break every ticket's right answer in every way the grader checks, and confirm the grader fails each one.

    python3 grader_mutation_check.py

The hand-written wrong-answer fixtures cover the likely mistakes. This covers the rest mechanically: from each
ticket's passing fixture it makes one wrong answer per checked thing (each expected value changed or missing, each
required label dropped, each forbidden label added, money paid into each file that must stay unchanged, an extra
payment in each file it may write (another record, or another reason or kind on the same booking), each
forbidden call made, each required call left out, the confirmation id not quoted) and runs verify.evaluate on it.
Every mutant must fail and the untouched answer must pass.
"""
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import verify  # noqa: E402

PAY = {"refunds": ("POST", "/refunds", {"amount": 10, "method": "original_payment"}),
       "credits": ("POST", "/credits", {"amount": 10, "reason": "goodwill"}),
       "reimbursements": ("POST", "/reimbursements", {"amount": 10, "kind": "meals"}),
       "approvals": ("POST", "/approvals", {"kind": "goodwill", "amount": 10}),
       "changes": ("POST", "/bookings/{b}/change", {"to_flight": "X", "change_fee": 0, "fare_difference": 0})}


def other(value):
    if isinstance(value, bool):
        return not value
    if isinstance(value, (int, float)):
        return value + 5
    return f"{value}-wrong"


def grade(case, seed, fixture):
    this, requests = verify.grade_requests(case, fixture.get("requests", []), fixture.get("already", 0))
    return verify.evaluate(case, verify.apply_fixture(seed, fixture), requests, seed, model_requests=this,
                           all_requests=fixture.get("requests", []))


def mutants(case, seed, good):
    sup = case["input"]["ticket_id"]
    booking = next((p.split(".")[1] for p in case["expect"] if p.split(".")[0] in ("refunds", "credits", "changes")),
                   next(iter(seed["bookings"])))
    for path, want in case["expect"].items():
        file, rid, field = path.split(".", 2)
        m = copy.deepcopy(good)
        m["data"].setdefault(file, {}).setdefault(rid, {})[field] = other(want)
        yield f"wrong {path}", m
        m = copy.deepcopy(good)
        m["data"].get(file, {}).get(rid, {}).pop(field, None)
        if verify.lookup(seed, path)[1] != want:
            yield f"missing {path}", m
    for path, labels in case.get("contains", {}).items():
        for label in labels:
            m = copy.deepcopy(good)
            file, rid, field = path.split(".", 2)
            m["data"][file][rid][field] = [x for x in m["data"][file][rid][field] if x != label]
            yield f"drops {label}", m
    for path, labels in case.get("not_contains", {}).items():
        for label in labels:
            m = copy.deepcopy(good)
            file, rid, field = path.split(".", 2)
            row = m["data"].setdefault(file, {}).setdefault(rid, {})
            row[field] = list(row.get(field) or seed[file][rid].get(field) or []) + [label]
            yield f"adds {label}", m
    for path, banned in case.get("must_not", {}).items():
        for value in banned:
            m = copy.deepcopy(good)
            file, rid, field = path.split(".", 2)
            m["data"].setdefault(file, {}).setdefault(rid, {})[field] = value
            yield f"must_not {path}={value}", m
    for file in case.get("unchanged", []):
        if file in PAY:
            m = copy.deepcopy(good)
            m["data"].setdefault(file, {}).setdefault(booking if file != "approvals" else sup, {})["mutant"] = 10
            yield f"changes {file}", m
    # an extra payment in a file the ticket may write: another record, or another reason/kind on the same booking
    touched = {p.split(".")[0] for p in case["expect"]} - {"tickets"}
    for file in sorted(touched):
        rid = next(p.split(".")[1] for p in case["expect"] if p.startswith(file + "."))
        m = copy.deepcopy(good)
        elsewhere = sup + "-X" if file == "approvals" else booking + "X"
        m["data"].setdefault(file, {})[elsewhere] = {"amount": 10, "method": "original_payment"} if file == "refunds" else \
            {"goodwill": 10} if file == "credits" else {"meals": 10} if file == "reimbursements" else \
            {"booking_id": booking, "kind": "goodwill", "amount": 10, "status": "pending"} if file == "approvals" else \
            {"to_flight": "X", "change_fee": 0, "fare_difference": 0}
        yield f"also pays {file} on another record", m
        if file in ("credits", "reimbursements"):
            extra = next(k for k in (("goodwill", "assistance", "fare_difference") if file == "credits" else ("meals", "transport", "hotel"))
                         if f"{file}.{rid}.{k}" not in case["expect"])
            m = copy.deepcopy(good)
            row = m["data"].setdefault(file, {}).setdefault(rid, {})
            row[extra] = (row.get(extra) or seed[file].get(rid, {}).get(extra) or 0) + 10
            yield f"also pays {file} {extra} on {rid}", m
    for pattern in case.get("forbidden_calls", []):
        method, path = pattern.split(" ", 1)
        m = copy.deepcopy(good)
        m.setdefault("requests", []).append({"method": method, "path": path.replace("*", booking), "status": 200,
                                             "body": {"booking_id": booking, "ticket_id": sup}})
        yield f"calls {pattern}", m
    for spec in case.get("required_calls", []):
        m = copy.deepcopy(good)
        m["requests"] = [r for i, r in enumerate(m.get("requests", []))
                         if i < m.get("already", 0) or not verify.diagnose.call_matches(r, spec)]
        yield f"skips {spec['call']}", m
    if case.get("require_attempt"):
        m = copy.deepcopy(good)
        for r in m.get("requests", [])[m.get("already", 0):]:
            if r["path"].endswith("/comments"):
                r["body"]["body"] = "Done."
        for t in m["data"].get("tickets", {}).values():
            for c in t.get("comments", []):
                c["body"] = "Done."
        yield "id not quoted", m


def main():
    total, rights, problems = 0, 0, []
    for n in range(6):
        base = ROOT / ("tests" if n == 0 else f"tests/stages/stage{n}")
        cases = {c["id"]: c for c in json.loads((base / "cases.json").read_text())}
        seed = verify.load_state(base / "seed")
        for case in cases.values():
            rights += 1
            good = next(f for f in json.loads((base / "fixtures" / f"{case['id']}.json").read_text()) if f["should"] == "pass")
            if grade(case, seed, good):
                problems.append(f"stage {n} {case['id']}: the right answer fails")
            for name, m in mutants(case, seed, good):
                total += 1
                if not grade(case, seed, m):
                    problems.append(f"stage {n} {case['id']}: passes although it {name}")
    for p in problems:
        print(" ", p)
    print(f"{total} wrong answers made from {rights} right ones; {len(problems)} problems")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
