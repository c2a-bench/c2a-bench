"""Solvability from the docs: can a model answer each ticket from the docs a builder would have to find?

    python3 solve_from_docs.py --docs expected [--limit N] [--stage 0]   # the ticket's expected_doc_ids
    python3 solve_from_docs.py --docs policy   [--limit N] [--stage 0]   # only the policy pages of its rules
    python3 solve_from_docs.py --docs rules --keys FILE                  # every source of its rules, customer agrees
    python3 solve_from_docs.py --compare expected                        # diff with the expected answers

solvability_review.py gives a reviewer the rule texts. This gives the docs instead, as they are at the ticket's
stage (stage updates and patches applied): with its expected docs a ticket should be solved (the split lost
nothing, and the part labels name every part it needs); with only the policy pages of its rules
(confluence/customer-policies, confluence/support-playbooks) most tickets should not be (the split is real).
The model also gets the ticket's opening, its customer facts, the API data the bot can read and the API doc, never
the answer. Answers go to docs_build/split/solve-<docs>/answer.json, in solvability_review.py's format, so
--compare reuses its diff.
"""
import argparse
import concurrent.futures as cf
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import blend_docs as bd  # noqa: E402
import check_docs as cd  # noqa: E402
import solvability_review as sr  # noqa: E402
import split_check as sc  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
API_DOC = (ROOT / "environment/app/api_docs/support-api.md").read_text()


def doc_text(n, d):
    """A doc as it reads at stage n: the newest copy (stage update or stage 0) with later patches applied."""
    rel = d.removeprefix("docs/")
    raw = None
    for m in range(n, -1, -1):
        f = (ROOT / "environment/app/docs" if m == 0 else ROOT / f"steps/stage{m}/workdir/stage{m}_update/new_docs") / rel
        if f.exists():
            raw = f.read_text()
            start = m
            break
    if raw is None:
        return None
    for m in range(start + 1, n + 1):
        for c in json.loads((ROOT / f"steps/stage{m}/workdir/stage{m}_update/changes.json").read_text())["changes"]:
            for p in c.get("patches", []):
                if p["doc"] == d:
                    raw = raw.replace(p["find"], p["replace"])
    doc = json.loads(raw)
    date = doc.get("last_updated") or doc.get("created_at") or ""
    return f"### {doc.get('title', '')} ({rel}, dated {str(date)[:10]})\n" + cd.text_of(
        {k: doc.get(k) for k in doc.get("content_field_names", [])})


def docs_for(n, case, mode):
    if mode == "expected":
        ids = case["expected_doc_ids"]
    elif mode == "rules":  # every doc stating a part of the ticket's rules: shows whether its part labels miss a part
        rules = {r["id"]: r for r in sr.load(sr.stage_dir(n) / "rules.json")}
        ids = sorted({d for r in case["rules"] for d in rules.get(r, {}).get("sources", [])})
    else:  # the policy pages of the ticket's rules: every source a builder reading only policy pages would read
        rules = {r["id"]: r for r in sr.load(sr.stage_dir(n) / "rules.json")}
        ids = sorted({d for r in case["rules"] for d in rules.get(r, {}).get("sources", [])
                      if d.removeprefix("docs/").startswith(sc.POLICY)})
    return [t for t in (doc_text(n, d) for d in ids) if t]


# A one-shot answer has no conversation: the customer's yes to a quote or a confirmation never comes.
AGREE = """
The customer has already told you everything they would tell you (below), and agrees to any option, quote or
confirmation you would ask them about: act on it now, as you would after their yes."""

ANSWER = """{"category": "refund|disruption|baggage|change|service|other",
 "labels": ["label", ...],
 "payments": [{"file": "refunds|credits|reimbursements", "booking": "booking id", "amount": number,
               "reason": "the reason or kind the API doc names, for credits and reimbursements"}],
 "approval": null or {"kind": "...", "amount": number, "booking": "booking id"},
 "change": null or {"booking": "...", "to_flight": "...", "change_fee": number, "fare_difference": number},
 "handoff": null or "reason",
 "comment_on": null or "ticket id",
 "ambiguous": null or "what you could not decide from these docs, and why",
 "used": ["the doc sentences your answer rests on"]}"""


def solve(n, case, mode, cases, agree=False):
    docs = docs_for(n, case, mode)
    res = bd.ask(bd.SYSTEM, f"""You are a careful Skyway Air support agent. Decide what to do on this ticket using ONLY the
documents below, the API data and the API doc. When documents disagree, the most recently dated statement wins. If the
documents do not say what to do, say so in "ambiguous" and act on what they do say; do not invent a rule.{AGREE if mode == "rules" or agree else ""}

Handled on: {sr.load(sr.stage_dir(n) / "doc_plan.json")["date"][:10]}
Customer's opening: {case["customer"]}
What the customer tells you when asked: {json.dumps(case.get("facts") or [])}
API data you can read: {json.dumps(sr.api_data(n, case, cases))}

API doc:
{API_DOC}

Documents ({len(docs)}):
{chr(10).join(docs)}

Answer as JSON: {ANSWER}""", f"solve:{mode}")
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", choices=["expected", "policy", "rules"])
    ap.add_argument("--compare", choices=["expected", "policy", "rules"])
    ap.add_argument("--keys", type=Path, help="only these ticket versions (one id@stageN per line)")
    ap.add_argument("--agree", action="store_true", help="the customer agrees to any confirmation (own folder)")
    ap.add_argument("--stage", type=int)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=32)
    args = ap.parse_args()
    mode = args.docs or args.compare
    folder = ROOT / f"docs_build/split/solve-{mode}{'-agree' if args.agree else ''}"
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / "answer.json"
    if args.compare:
        return sr.compare(folder)
    answers = json.loads(out.read_text()) if out.exists() else {}
    todo = [(n, c) for n, c in sr.entries() if f"{c['id']}@stage{n}" not in answers
            and (args.stage is None or n == args.stage)]
    if args.keys:
        keys = set(args.keys.read_text().split())
        todo = [(n, c) for n, c in todo if f"{c['id']}@stage{n}" in keys]
    if args.limit:
        todo = todo[:args.limit]

    def run(item):
        n, c = item
        cases = {x["id"]: x for x in sr.load(sr.stage_dir(n) / "cases.json")}
        try:
            return f"{c['id']}@stage{n}", solve(n, c, mode, cases, args.agree)
        except Exception as e:  # noqa: BLE001
            return f"{c['id']}@stage{n}", {"error": str(e)[:200]}

    with cf.ThreadPoolExecutor(args.workers) as ex:
        for key, a in ex.map(run, todo):
            if "error" not in a:
                answers[key] = a
            else:
                print("  FAILED", key, a["error"])
    out.write_text(json.dumps(answers, indent=1, sort_keys=True) + "\n")
    print(f"{len(todo)} solved now; {len(answers)} answers in {out}")


if __name__ == "__main__":
    main()
