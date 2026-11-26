"""Can a cheap test tell the planned rule docs from the background? One table per signal, rule docs vs background.

    python3 giveaway_audit.py            # stage 0 corpus (environment/app/docs) and the stage update folders
    python3 giveaway_audit.py --json     # the same numbers as JSON

Signals (a review and our own audit): length per folder, page and thread shape (field-per-section pages,
message format, created_at style), dollar amounts and "travel credit", document types the folder's background never
uses, file names, each folder's share of rule docs, file times, lookalikes per rule, and the stage update folders.
A signal gives the rule docs away when its rate among rule docs is far from its rate in the background. Reads only.
"""
import argparse
import collections
import json
import os
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_docs as cd  # noqa: E402
from blend_docs import msg_format  # noqa: E402
from rename_rule_docs import TELL  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / "environment/app/docs"


def load(p):
    return json.loads(Path(p).read_text())


def body(doc):
    return cd.text_of({k: doc.get(k) for k in doc.get("content_field_names", [])})


def folder(rel):
    return "/".join(rel.split("/")[:2])


def pct(a, b):
    return f"{100 * a / b:.0f}%" if b else "-"


def stage0():
    planned = {p[len("sources/"):] for p in load(ROOT / "docs_build/stage0/manifest.json")["docs"]}
    rule, bg = {}, {}
    for f in ENV.rglob("*.json"):
        rel = str(f.relative_to(ENV))
        (rule if rel in planned else bg)[rel] = load(f)
    return rule, bg


def rates(rule, bg, test):
    r = sum(1 for d in rule.values() if test(d))
    b = sum(1 for d in bg.values() if test(d))
    return {"rule": f"{r}/{len(rule)} ({pct(r, len(rule))})", "background": f"{b}/{len(bg)} ({pct(b, len(bg))})",
            "share of hits that are rule docs": pct(r, r + b)}


def audit():
    rule, bg = stage0()
    out = {}
    # length per folder
    by = collections.defaultdict(lambda: ([], []))
    for i, docs in enumerate((rule, bg)):
        for rel, d in docs.items():
            by[folder(rel)][i].append(len(body(d)))
    out["median length per folder (rule / background)"] = {
        f: f"{int(statistics.median(r))} / {int(statistics.median(b))}" for f, (r, b) in sorted(by.items()) if r and b}
    # shape
    conf = lambda d: d.get("source_system") == "confluence"  # noqa: E731
    slack = lambda d: d.get("source_system") == "slack"  # noqa: E731
    cr = {k: d for k, d in rule.items() if conf(d)}
    cb = {k: d for k, d in bg.items() if conf(d)}
    out["confluence pages with a field per section"] = rates(cr, cb, lambda d: len(d.get("content_field_names", [])) > 1)
    sr = {k: d for k, d in rule.items() if slack(d)}
    sb = {k: d for k, d in bg.items() if slack(d)}
    fmts = lambda docs: collections.Counter(  # noqa: E731
        msg_format(d["messages"][0]) if isinstance(d.get("messages"), list) and d["messages"] else None
        for d in docs.values())
    fr, fb = fmts(sr), fmts(sb)
    out["slack message format (rule / background)"] = {
        str(k): f"{pct(fr[k], len(sr))} / {pct(fb[k], len(sb))}" for k in sorted(set(fr) | set(fb), key=str)}
    style = lambda d: re.sub(r"\d", "9", str(d.get("created_at", "")))[19:] or "date only"  # noqa: E731
    out["slack created_at ending in Z"] = rates(sr, sb, lambda d: style(d) == "Z")
    out["slack median messages (rule / background)"] = (
        f"{statistics.median(len(d.get('messages') or []) for d in sr.values())} / "
        f"{statistics.median(len(d.get('messages') or []) for d in sb.values())}")
    # words
    out['docs with a "$" amount'] = rates(rule, bg, lambda d: bool(cd.MONEY.search(body(d))))
    out['docs saying "travel credit"'] = rates(rule, bg, lambda d: "travel credit" in body(d).lower())
    out['"$" in a sentence that grants or limits'] = rates(rule, bg, lambda d: any(
        cd.DECIDES.search(cd.sentence_at(body(d), m.start())) for m in cd.MONEY.finditer(body(d))))
    # the same search, split: does it find only the current rules, or wrong and old versions too?
    man = load(ROOT / "docs_build/stage0/manifest.json")["docs"]
    roles = load(ROOT / "tests/doc_plan.json")["docs"]
    split = collections.Counter()
    for rel, d in rule.items():
        b = body(d)
        if any(cd.DECIDES.search(cd.sentence_at(b, m.start())) for m in cd.MONEY.finditer(b)):
            split["wrong version" if man["sources/" + rel].get("trap") else
                  "quick reference (old value after a change)" if roles.get("docs/" + rel, {}).get("role") == "quick reference"
                  else "current rule"] += 1
    out['"$" in a sentence that grants or limits: which docs'] = dict(split)
    # document types
    types = collections.defaultdict(collections.Counter)
    for rel, d in bg.items():
        types[folder(rel)][d.get("document_type")] += 1
    out["rule docs whose document type the folder's background uses under 5 times"] = sum(
        1 for rel, d in rule.items() if types[folder(rel)][d.get("document_type")] < 5)
    # names
    name = lambda rel: rel.rsplit("/", 1)[-1]  # noqa: E731
    r = sum(1 for rel in rule if TELL.search(name(rel)))
    b = sum(1 for rel in bg if TELL.search(name(rel)))
    out["file names that give a doc away (number, date, thread, draft, old)"] = {
        "rule": f"{r}/{len(rule)}", "background": f"{b}/{len(bg)}"}
    # folders
    fc = collections.Counter(folder(x) for x in rule)
    ft = collections.Counter(folder(x) for x in list(rule) + list(bg))
    out["folders where rule docs are over 5% of the docs"] = {
        f: f"{fc[f]}/{ft[f]} ({pct(fc[f], ft[f])})" for f in sorted(fc) if fc[f] / ft[f] > 0.05}
    total = len(rule) + len(bg)
    out["biggest folders (share of the corpus)"] = {f: pct(n, total) for f, n in ft.most_common(6)}
    out["stage 0 docs"] = total
    # file times
    times = collections.Counter(int(os.stat(ENV / rel).st_mtime) for rel in list(rule) + list(bg))
    out["distinct file times in environment/app/docs (the Dockerfile and setup.sh set one time)"] = len(times)
    # lookalikes
    looks = ROOT / "docs_build/blend/lookalikes.json"
    if looks.exists():
        per = collections.Counter(v["rule"] for v in load(looks).values())
        out["lookalikes per rule (min / max, rules)"] = f"{min(per.values())} / {max(per.values())}, {len(per)} rules"
    else:
        out["lookalikes per rule (min / max, rules)"] = "none installed"
    # stage update folders
    stages = {}
    for n in range(1, 6):
        u = ROOT / f"steps/stage{n}/workdir/stage{n}_update/new_docs"
        planned = {p[len("sources/"):] for p in load(ROOT / f"docs_build/stage{n}/manifest.json")["docs"]}
        files = [str(f.relative_to(u)) for f in u.rglob("*.json")]
        stages[n] = (f"{len(files)} new docs, {sum(f in planned for f in files)} of them rule docs, "
                     f"{sum(1 for f in files if TELL.search(name(f)))} names that give it away")
    out["stage update folders"] = stages
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    out = audit()
    if args.json:
        print(json.dumps(out, indent=1))
        return
    for k, v in out.items():
        if isinstance(v, dict):
            print(f"{k}:")
            for a, b in v.items():
                print(f"    {a}: {b}")
        else:
            print(f"{k}: {v}")


if __name__ == "__main__":
    main()
