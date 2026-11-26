"""Which parts of its rules each ticket needs (the split: a rule's parts sit in different docs).

    python3 label_rule_parts.py [--workers 32]    # writes tests/rule_parts.json

A part is one evidence sentence of a rule (rules.json "evidence"). A ticket needs a part when, without it, a careful
agent could end with a different checked value or make a forbidden call. Two model reads per ticket version, asked
differently; a part either read marks as needed is kept (missing a needed part would blame the builder unfairly, an
extra one only widens what is judged). Disagreements are recorded. Read by build_stage0_tickets.py and
build_stage_tickets.py (expected_doc_ids: the docs holding the needed parts) and scripts/build_facts.py (one fact per
needed part). A ticket version is labelled once: later stages reuse it while its rules' parts and pass conditions
stay the same.
"""
import argparse
import concurrent.futures as cf
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import blend_docs as bd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests/rule_parts.json"
PASS_KEYS = ("expect", "contains", "not_contains", "unchanged", "forbidden_calls", "required_calls", "must_not")


def steps():
    yield "stage0", ROOT / "tests"
    for n in range(1, 6):
        yield f"stage{n}", ROOT / f"tests/stages/stage{n}"


def rules_of(d):
    r = json.loads((d / "rules.json").read_text())
    r = r.get("rules", r) if isinstance(r, dict) else r
    return {x["id"]: x for x in (r.values() if isinstance(r, dict) else r)}


def cases_of(d):
    c = json.loads((d / "cases.json").read_text())
    return c.get("cases", c) if isinstance(c, dict) else c


def key(case, rules):
    parts = {r: rules[r]["evidence"] for r in case.get("rules", []) if r in rules}
    raw = json.dumps([parts, case["input"], case.get("facts"), [case.get(k) for k in PASS_KEYS]], sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def ticket_text(case, rules):
    listing = []
    for r in case.get("rules", []):
        if r in rules:
            listing.append(f"{r} ({rules[r]['rule'][:300]})")
            listing += [f"  - {e}" for e in rules[r]["evidence"]]
    return f"""Customer's first message: {case['input']['message']}
What the customer knows: {json.dumps(case.get('facts', []))}
What a correct agent ends with: {case.get('test', '')}
Why it is tricky: {case.get('matters', '')}
Checked end state: {json.dumps({k: case.get(k) for k in ('expect', 'contains', 'not_contains', 'unchanged') if case.get(k)})}
Calls it must not make: {json.dumps(case.get('forbidden_calls', []))}
Rules and their parts:
{chr(10).join(listing)}"""


def label(case, rules):
    text = ticket_text(case, rules)
    parts = {e for r in case.get("rules", []) if r in rules for e in rules[r]["evidence"]}
    a = bd.ask(bd.SYSTEM, f"""A support ticket and the rules it uses, each split into parts.
{text}
Which parts must the agent know to reach exactly this end state and avoid the forbidden calls? A part is needed if,
without it, a careful agent could set a different checked value, set or leave a different label, or make a forbidden
call. A part about a situation this ticket is not in is not needed.
Answer as {{"needed": ["the part, copied exactly", ...]}}.""", "parts:a")
    b = bd.ask(bd.SYSTEM, f"""{text}
For every part listed above, say whether this ticket's correct outcome depends on it: would an agent who did not know
that part risk getting a checked value, a label or a call wrong on THIS ticket?
Answer as {{"parts": [{{"part": "copied exactly", "depends": true or false}}]}}.""", "parts:b")
    na = {x for x in a.get("needed", []) if x in parts}
    nb = {x["part"] for x in b.get("parts", []) if x.get("depends") and x.get("part") in parts}
    return sorted(na | nb), sorted(na ^ nb)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=32)
    args = ap.parse_args()
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    cache = {v["key"]: v for step in old.get("steps", {}).values() for v in step.values()}
    todo, out = {}, {}
    for step, d in steps():
        rules = rules_of(d)
        for case in cases_of(d):
            k = key(case, rules)
            out.setdefault(step, {})[case["id"]] = k
            if k not in cache:
                todo[k] = (case, rules)

    def run(item):
        k, (case, rules) = item
        try:
            return k, *label(case, rules)
        except Exception as e:  # noqa: BLE001
            return k, None, str(e)[:200]

    with cf.ThreadPoolExecutor(args.workers) as ex:
        for k, needed, disagree in ex.map(run, todo.items()):
            if needed is None:
                print("  FAILED", k, disagree)
                continue
            cache[k] = {"key": k, "needed": needed, "disagree": disagree}
    steps_out = {s: {cid: cache[k] for cid, k in v.items() if k in cache} for s, v in out.items()}
    OUT.write_text(json.dumps({
        "_about": __doc__.strip().split("\n")[0] + " Generated by scripts/label_rule_parts.py; checked by "
                  "scripts/split_check.py.", "steps": steps_out}, indent=1, sort_keys=True) + "\n")
    n = sum(len(v) for v in steps_out.values())
    print(f"labelled {len(todo)} new ticket versions; {n} tickets over {len(steps_out)} steps; "
          f"{sum(1 for v in steps_out.values() for x in v.values() if x['disagree'])} with a disagreement")


if __name__ == "__main__":
    main()
