"""Does a policy page still state, in other words, a rule part the split moved off the policy pages? Reads only.

    python3 judge_split.py [--top 10] [--workers 32]    # writes docs_build/split/judge.json

split_check.py finds a part only word for word. This asks a model. For every stage and every part its tickets need
that no policy page states word for word, the policy pages (confluence/customer-policies, confluence/support-playbooks;
not wrong versions, quick references or change notes) are ranked by the part's words (amounts, labels, other content
words) and the top ones are judged: "does this page state this part, in any wording? quote it". A yes counts when the
quote is really in the page and a second, independent read agrees.
"""
import argparse
import concurrent.futures as cf
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import blend_docs as bd  # noqa: E402
import check_docs as cd  # noqa: E402
import label_rule_parts as lp  # noqa: E402
import split_check as sc  # noqa: E402

OUT = bd.ROOT / "docs_build/split/judge.json"
STOP = set("a an the and or of to for on in at by is are be it its this that with as from any not no only when if "
           "their they them who what which".split())


def words(t):
    return {w for w in re.findall(r"\$?[a-z0-9_'-]+", cd.norm(t)) if w not in STOP and len(w) > 2}


def pages(n):
    plan = json.loads(((bd.ROOT / "tests") if n == 0 else bd.ROOT / f"tests/stages/stage{n}").joinpath("doc_plan.json").read_text())["docs"]
    skip = {d for d, x in plan.items() if x.get("trap") or x.get("role") in ("quick reference", "change log")}
    raw = {}
    roots = [bd.ENV] + [bd.ROOT / f"steps/stage{m}/workdir/stage{m}_update/new_docs" for m in range(1, n + 1)]
    for r in roots:
        for f in r.rglob("*.json"):
            rel = str(f.relative_to(r))
            if rel.startswith(sc.POLICY) and "docs/" + rel not in skip:
                doc = json.loads(f.read_text())
                raw["docs/" + rel] = cd.text_of({k: doc.get(k) for k in ["title"] + doc.get("content_field_names", [])})
    return raw


def ask_once(part, rule, text, tag):
    return bd.ask(bd.SYSTEM, f"""Rule {rule['id']}: {rule['rule'][:400]}
One part of this rule: "{part}"

Does the document below state this part, in any wording, as something support staff should apply? Mentioning the
topic is not enough: it must give the same condition, amount, limit, label or instruction. A sentence that only
quotes a customer, asks a question, or states something different does not count.
Document:
{text[:14000]}
Answer as {{"states": true or false, "quote": "the exact words from the document that state it, or empty"}}.""", tag)


def judge(item):
    part, rule, d, text = item
    a = ask_once(part, rule, text, "judge-split:a")
    quote = str(a.get("quote") or "").strip()
    if not a.get("states") or not quote or cd.norm(quote) not in cd.norm(text):
        return None
    b = ask_once(part, rule, text, "judge-split:b")
    if not b.get("states"):
        return None
    return {"part": part, "rule": rule["id"], "doc": d, "quote": quote, "second_quote": b.get("quote")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--workers", type=int, default=32)
    args = ap.parse_args()
    items, seen, per_step = [], set(), {}
    for step, folder in lp.steps():
        n = int(step[5:])
        rules = lp.rules_of(folder)
        raw = pages(n)
        flat = {d: cd.norm(t) for d, t in raw.items()}
        need = {(r, e) for c in lp.cases_of(folder) for r in c.get("rules", []) if r in rules
                for e in rules[r]["evidence"] if not e.startswith("This applies")}
        moved = [(r, e) for r, e in sorted(need) if not any(cd.norm(e).rstrip(".") in t for t in flat.values())]
        per_step[step] = len(moved)
        for r, e in moved:
            w = words(e)
            ranked = sorted(raw, key=lambda d: -len(w & words(raw[d])))[:args.top]
            for d in ranked:
                key = (e, d, hash(raw[d]))
                if key not in seen:
                    seen.add(key)
                    items.append((e, rules[r], d, raw[d]))
    print(f"parts off the policy pages per step: {per_step}; {len(items)} page and part pairs to judge", flush=True)

    def run(item):
        try:
            return judge(item)
        except Exception as ex:  # noqa: BLE001
            return {"error": str(ex)[:200], "part": item[0], "doc": item[2]}

    with cf.ThreadPoolExecutor(args.workers) as ex:
        found = [x for x in ex.map(run, items) if x]
    errors = [x for x in found if "error" in x]
    hits = [x for x in found if "error" not in x]
    OUT.write_text(json.dumps({"pairs_judged": len(items), "per_step": per_step, "hits": hits, "errors": errors},
                              indent=1) + "\n")
    print(f"{len(hits)} pages still state a moved part (both reads agree, quote found); {len(errors)} errors")
    for h in hits:
        print(f"  {h['rule']}: \"{h['part']}\" in {h['doc'][5:]}\n      \"{h['quote'][:200]}\"")


if __name__ == "__main__":
    main()
