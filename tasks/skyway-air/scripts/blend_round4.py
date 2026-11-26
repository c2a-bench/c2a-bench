"""Round 4 of blending (external review): ordinary stage-update docs that look like the rule changes, more lookalikes.

    python3 blend_round4.py --job lookalike|changelog|applies|all [--workers 16]   # stage to docs_build/blend/round4/
    python3 blend_round4.py --apply                                                  # write the staged docs into the stages

lookalike  three more lookalikes each for R22-R25 (stage 1 had room for one each), as blend_docs.py makes them
changelog  new ordinary notes in confluence/policy-and-compliance/change-log/ about a process change (a case-note
           field, a queue, a template), each with the stage's "This applies to every request handled from ..." line,
           so the change-log folder and that line are no longer rule-only
applies    the same kind of process-change line, plus the stage's applicability sentence, added to existing ordinary
           stage-update docs
money      a dollar amount (an invoice, a fare paid, a team budget) or a travel-credit mention added to ordinary
           stage-update docs, as blend_docs.py's money job did for stage 0: until then no ordinary stage-update doc
           had a "$" or "travel credit", so a search for either found only rule docs
Per stage, changelog + applies match the rule docs that carry the applicability sentence (17/11/6/5/4). The docs are
checked like background (bd.bg_problems, strict figures) before the applicability sentence goes in, since that
sentence is also a rule part. Results in docs_build/blend/round4.json; --apply writes the staged docs, lists new docs in
new_docs.txt and adds the lookalikes to lookalikes.json.
"""
import argparse
import concurrent.futures as cf
import hashlib
import json
import random
import re
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import blend_docs as bd  # noqa: E402
import check_docs as cd  # noqa: E402

OUT = bd.OUT / "round4"
RESULTS = bd.OUT / "round4.json"
APPLIES = "This applies to every request handled from {}, whatever the date of the flight."
TARGET = {1: 17, 2: 11, 3: 6, 4: 5, 5: 4}  # rule docs with the applicability sentence per stage
CHANGELOGS = {1: 6, 2: 4, 3: 2, 4: 2, 5: 1}
CHANGELOG_DIR = "confluence/policy-and-compliance/change-log"
NEW_LOOKS = {"R22": 3, "R23": 3, "R24": 3, "R25": 3}
DOLLAR, CREDIT = 0.22, 0.05  # share of a stage's ordinary docs (rule docs in stage updates: 24% "$", 5% "travel credit")
PROCESS = ("a process change for staff, not a customer policy: a new or renamed field in the case tool, a queue or "
           "inbox that moves or is renamed, a reply template or macro that changes, a new tag for reporting, a "
           "checklist step added to case notes, a handover or shift-briefing change")
# One topic per change note, so the notes are not near-copies of each other (external review of #90)
CHANGELOG_TOPICS = [
    "the shared support inbox moves to a new queue name and its auto-reply text changes",
    "a new mandatory 'contact channel' field in the case form",
    "the shift-handover checklist gains a step for open callbacks",
    "the case-notes template is shortened and its section order changes",
    "a new reporting tag for contacts that mention accessibility needs",
    "the airport desk escalation form moves from email to the case tool",
    "screen-sharing sessions now need a note of the customer's consent in the case",
    "a renamed status for cases waiting on another team",
    "the macro library is reorganised and three old macros are retired",
    "a new weekly quality-review sample and how agents tag cases for it",
    "the after-hours on-call rota moves to a new scheduling tool",
    "chat transcripts are now attached to cases automatically and agents stop pasting them",
    "a new field to record the customer's preferred language",
    "the duplicate-case merge button moves and merged cases keep both reference numbers",
    "training-mode cases get a prefix so they are left out of reporting",
]
NO_POLICY = ("Nothing about refunds, credits, compensation, fees, fares, reimbursements, approvals, limits, deadlines, "
             "who is eligible or what a customer gets; no money amounts and no numbers of hours or days.")


def stage_dates():
    """The handling date a stage's changed rules apply from: the "This applies ..." date that first appears there."""
    seen, out = set(), {}
    for n in range(0, 6):
        folder = bd.ROOT / ("tests" if n == 0 else f"tests/stages/stage{n}")
        dates = {m.group(1) for r in json.loads((folder / "rules.json").read_text()) for e in r["evidence"]
                 for m in [re.match(r"This applies to every request handled from (.+?), whatever", e)] if m}
        new = sorted(dates - seen)
        if n:
            assert len(new) == 1, (n, new)
            out[n] = new[0]
        seen |= dates
    return out


def ordinary(n):
    """Existing ordinary docs of a stage's update (not planned, not a lookalike), by path."""
    plan = json.loads((bd.ROOT / f"tests/stages/stage{n}/doc_plan.json").read_text())["docs"]
    looks = set(bd.load(bd.OUT / "lookalikes.json"))
    root = bd.ROOT / f"steps/stage{n}/workdir/stage{n}_update/new_docs"
    return sorted(str(f.relative_to(root)) for f in root.rglob("*.json")
                  if "docs/" + str(f.relative_to(root)) not in plan and str(f.relative_to(root)) not in looks)


def plan(corpus, rng):
    items, dates = [], stage_dates()
    looks = bd.load(bd.OUT / "lookalikes.json")
    rules = json.loads((bd.ROOT / "tests/stages/stage1/rules.json").read_text())
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from build_doc_projects import TOPIC
    for r in rules:
        if r["id"] not in NEW_LOOKS:
            continue
        have = {folder_dir for rel, x in looks.items() if x["rule"] == r["id"] for folder_dir in [rel.rsplit("/", 1)[0]]}
        dirs = list(dict.fromkeys([s[5:].rsplit("/", 1)[0] for s in r["sources"]] + [x[5:].rsplit("/", 1)[0] for x in r.get("decoys", [])]
                                  + ["slack/support-policy-questions", "slack/support-team", "slack/support-escalations"]))
        dirs = [d for d in dirs if d not in have] + [d for d in dirs if d in have]
        for i in range(NEW_LOOKS[r["id"]]):
            items.append({"job": "lookalike", "key": f"lookalike/{r['id']}/{i}", "stage": 1, "rule": r["id"],
                          "dir": dirs[i % len(dirs)], "topic": TOPIC.get(r["id"], r["rule"][:80]), "words": TOPIC.get(r["id"], "")})
    for n in range(1, 6):
        for i in range(CHANGELOGS[n]):
            items.append({"job": "changelog", "key": f"changelog/{n}/{i}", "stage": n, "date": dates[n]})
        pool = [rel for rel in ordinary(n) if "change-log/" not in rel]
        for rel in rng.sample(pool, TARGET[n] - CHANGELOGS[n]):
            items.append({"job": "applies", "key": f"applies/{n}/{rel}", "stage": n, "rel": rel, "date": dates[n]})
    for n in range(1, 6):  # after the jobs above are applied: every ordinary doc of the stage, new ones included
        pool = ordinary(n)
        picks = rng.sample(pool, round((DOLLAR + CREDIT) * len(pool)))
        for i, rel in enumerate(picks):
            items.append({"job": "money", "key": f"money/{n}/{rel}", "stage": n, "rel": rel,
                          "kind": "dollar" if i < round(DOLLAR * len(pool)) else "credit"})
    return items


def with_applies(doc, sentence):
    """The doc with a process-change line and the applicability sentence: a new last message, or a closing paragraph."""
    doc = json.loads(json.dumps(doc))
    if isinstance(doc.get("messages"), list) and doc["messages"]:
        msgs = doc["messages"]
        last = msgs[-1]
        k = bd.msg_format(last)
        if not k:
            return None
        g = bd.FORMAT_RE[k].match(last)
        name = g.group(2) if k == "datefirst" else g.group(1)
        st = bd.stamp_of(last)
        t = st[1] + timedelta(minutes=2) if st else None
        msgs.append(bd.FORMATS[k][1](name, t) + sentence)
        return doc
    fields = [f for f in doc.get("content_field_names", []) if isinstance(doc.get(f), str) and doc.get(f).strip()]
    if not fields:
        return None
    doc[fields[-1]] = doc[fields[-1]].rstrip() + "\n\n" + sentence
    return doc


def changelog(item, corpus, phrases, banned, rng):
    n = item["stage"]
    folder = bd.folder_of(CHANGELOG_DIR)
    topic = CHANGELOG_TOPICS[(sum(CHANGELOGS[m] for m in range(1, n)) + int(item["key"].rsplit("/", 1)[1])) % len(CHANGELOG_TOPICS)]
    brief = (f"It is a short change note about one process change for staff: {topic}. Say what changed and what staff "
             f"do now. Plain text, no HTML tags. {NO_POLICY}")
    feedback = ""
    for _ in range(3):
        day = bd.random_day(n, rng)
        title, content = bd.make_page(folder, day, rng, corpus, brief, 220, feedback)
        doc = bd.new_doc(folder, day, rng, corpus, content, title)
        probs = bd.bg_problems(doc, phrases, banned, strict_figures=True)
        if not probs:
            doc = with_applies(doc, APPLIES.format(item["date"]))
            rel = bd.free_name(CHANGELOG_DIR, title, corpus) if doc else None
            if rel:
                return (rel, doc), f"change note, stage {n}"
            probs = ["no field or name for it"]
        feedback = "\nA first try had these problems; avoid them: " + "; ".join(probs)
    return None, "; ".join(probs)


def applies(item, corpus, phrases, banned, rng):
    n, rel = item["stage"], item["rel"]
    path = bd.stage_path(n, rel)[0]
    doc = bd.load(path)
    text = cd.text_of({k: doc.get(k) for k in doc.get("content_field_names", [])})[:2500]
    feedback = ""
    for _ in range(3):
        res = bd.ask(bd.SYSTEM, f"""Here is an internal Skyway Air document ("{doc.get('title', '')}"):
---
{text}
---
Write ONE short sentence, in the voice of this document, announcing {PROCESS} that fits its topic. {NO_POLICY}
Answer as {{"sentence": "..."}}.{feedback}""", f"round4:applies:{rel}")
        line = bd.clean(str(res.get("sentence", "")).strip())
        new = with_applies(doc, line) if line else None
        probs = [] if new else ["empty sentence or a doc with nowhere to put it"]
        if new:
            probs = bd.bg_problems(new, phrases, banned, strict_figures=True)
        if not probs:
            new = with_applies(doc, line + " " + APPLIES.format(item["date"]))
            return new, f"process line: {line}"
        feedback = "\nA first try had these problems; avoid them: " + "; ".join(probs)
    return None, "; ".join(probs)


def money(item, corpus, phrases, banned, rng):
    """blend_docs.money on a stage-update doc: it reads SOURCES / rel, and an absolute rel points at the stage copy."""
    import blend_round3 as b3
    path = bd.stage_path(item["stage"], item["rel"])[0]
    doc, note = bd.money({**item, "rel": str(path.resolve())}, corpus, phrases, banned, rng)
    if doc and isinstance(doc.get("messages"), list):
        doc["messages"] = b3.in_order(doc["messages"])
    return doc, note


def lookalike(item, corpus, phrases, banned, rng):
    return bd.lookalike(item, corpus, phrases, banned, rng)


def apply():
    done = bd.load(RESULTS)
    looks = bd.load(bd.OUT / "lookalikes.json")
    added = {n: [] for n in range(1, 6)}
    for key, e in sorted(done.items()):
        n, rel = e["stage"], e["rel"]
        text = (OUT / str(n) / rel).read_text()
        for p in bd.stage_path(n, rel):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        if e["new"]:
            added[n].append("sources/" + rel)
        if e.get("rule"):
            looks[rel] = {"stage": n, "rule": e["rule"]}
    for n in range(1, 6):
        f = bd.ROOT / f"steps/stage{n}/workdir/stage{n}_update/new_docs.txt"
        lines = f.read_text().splitlines()
        f.write_text("".join(x + "\n" for x in lines + [a for a in added[n] if a not in lines]))
    (bd.OUT / "lookalikes.json").write_text(json.dumps(looks, indent=1, sort_keys=True) + "\n")
    print(f"applied {len(done)} docs; new per stage: { {n: len(v) for n, v in added.items()} }")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", choices=["lookalike", "changelog", "applies", "money", "all"])
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if args.apply:
        return apply()
    corpus = bd.Corpus()
    for n in range(1, 6):  # names already used in the stage updates
        root = bd.ROOT / f"steps/stage{n}/workdir/stage{n}_update/new_docs"
        corpus.taken |= {str(f.relative_to(root)) for f in root.rglob("*.json")}
    items = plan(corpus, random.Random(2029))
    if args.plan:
        import collections
        print(dict(collections.Counter((i["job"], i["stage"]) for i in items)), stage_dates())
        return
    done = bd.load(RESULTS) if RESULTS.exists() else {}
    todo = [i for i in items if args.job in ("all", i["job"]) and i["key"] not in done]
    phrases, banned = cd.rule_phrases(), bd.banned_words()
    fns = {"lookalike": lookalike, "changelog": changelog, "applies": applies, "money": money}

    def run(item):
        rng = random.Random(int(hashlib.md5(item["key"].encode()).hexdigest()[:8], 16))
        try:
            return item, *fns[item["job"]](item, corpus, phrases, banned, rng)
        except Exception as e:  # noqa: BLE001 - one bad answer must not stop the run
            return item, None, f"error: {type(e).__name__}: {e}"[:300]

    failed = []
    with cf.ThreadPoolExecutor(args.workers) as ex:
        for item, res, note in ex.map(run, todo):
            if res is None:
                failed.append((item["key"], note))
                continue
            if item["job"] in ("applies", "money"):
                rel, doc, new = item["rel"], res, False
            else:
                (rel, doc), new = res, True
            bd.write_doc(OUT / str(item["stage"]) / rel, doc)
            done[item["key"]] = {"stage": item["stage"], "rel": rel, "new": new, "rule": item.get("rule"), "note": note}
    RESULTS.write_text(json.dumps(done, indent=1, sort_keys=True) + "\n")
    print(f"staged {len(todo) - len(failed)}/{len(todo)}; all staged: {len(done)}/{len(items)}")
    for key, note in failed:
        print("  FAILED", key, "-", note[:200])


if __name__ == "__main__":
    main()
