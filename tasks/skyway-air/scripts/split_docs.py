"""The split, in the docs: each part of a rule is stated as the rule in one doc only (docs_build/split/plan.json).

    python3 split_docs.py [--limit N] [--workers 32]   # stage the edited docs in docs_build/split/staged/
    python3 split_docs.py --apply                      # write them into the env, the generator's sources, the stages

docs_build/split/rewrites.json lists, per planned doc, the sentences it no longer states (remove) and the ones it now
states (add): the difference between the manifests before and after the builders read the split plan. A doc changes
as little as possible: a removed part goes with every rewording of it, its amounts and labels; an added part goes in
word for word where it fits. Checks on every result: the doc's planned sentences (check_docs), no removed sentence,
amount or label left, the stage patches still find their text, and a second model call that reads the doc and says
whether it still states a removed part in other words.
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

OUT = bd.ROOT / "docs_build/split"
STAGED = OUT / "staged"
RESULTS = OUT / "results.json"  # per list: results.json for rewrites.json, results-<name>.json for another


def manifest(n, rel):
    return json.loads((bd.ROOT / f"docs_build/stage{n}/manifest.json").read_text())["docs"]["sources/" + rel]


def patch_finds(rel):
    """Text a later stage's patch must still find in this doc."""
    out = []
    for n in range(1, 6):
        f = bd.ROOT / f"steps/stage{n}/workdir/stage{n}_update/changes.json"
        out += [p["find"] for c in json.loads(f.read_text())["changes"] for p in c.get("patches", [])
                if p["doc"].removeprefix("docs/") == rel]
    return out


def units(doc):
    """[(field, index or None, text)]: a Slack message, a list item, or a whole text field."""
    out = []
    for f in doc["content_field_names"]:
        v = doc.get(f)
        if isinstance(v, list):
            out += [(f, i, x) for i, x in enumerate(v) if isinstance(x, str)]
        elif isinstance(v, str):
            out.append((f, None, v))
    return out


def gone_problems(doc, item, m):
    body = cd.text_of(doc)
    flat = cd.norm(body)
    keep = cd.norm(" ".join(m["must_contain"]))
    out = [f"still states: {s}" for s in item["remove"] if cd.norm(s).rstrip(".") in flat]
    for s in item["remove"]:
        for x in cd.figures(s):
            if x not in keep and x in {cd.norm(y).rstrip(",.;:") for y in cd.figures(body)}:
                out.append(f"still has {x} from: {s}")
        for lab in re.findall(r"\b[a-z]+(?:-[a-z]+)+\b|\bnot_covered\b", s):
            if lab in flat and lab not in keep:
                out.append(f"still has the label {lab}")
    out += [f"a later stage's patch no longer finds {f!r}" for f in patch_finds(item["rel"]) if f not in json.dumps(doc)
            and f not in cd.text_of(doc)]
    return out


def edit(item):
    n, rel = item["stage"], item["rel"]
    path = bd.stage_path(n, rel)[0]
    doc = bd.load(path)
    m = manifest(n, rel)
    us = units(doc)
    listing = "\n".join(f"[{k}] {t}" for k, (_, _, t) in enumerate(us))
    asks = []
    if item["remove"]:
        asks.append("Remove these points, and every rewording or hint of them, with their amounts, numbers and labels: "
                    + "; ".join(f'"{s}"' for s in item["remove"]) + ". Where a reply only made sense with a removed "
                    "point, reword it so the conversation still reads naturally, or drop it.")
    if item["add"]:
        asks.append("Add these sentences word for word, where they fit naturally (inside an existing part, or as one "
                    "new part right after the part it follows from): " + "; ".join(f'"{s}"' for s in item["add"]) + ".")
    feedback, probs = "", []
    for _ in range(5):
        res = bd.ask(bd.SYSTEM, f"""Below are the parts of an internal Skyway Air document "{doc.get('title', '')}" ({doc.get('source_system')}), numbered.
{chr(10).join(asks)}
Change as little as possible. Keep these sentences exactly as they are: {json.dumps(m['must_contain'])}.
Keep every Slack message's speaker and time prefix exactly. Do not add any other policy, amount, limit or label.
{bd.NO_DECIDING if not m['must_contain'] else ''}
Parts:
{listing}
Answer as {{"edits": [{{"part": <number>, "text": "the whole new text of that part, or empty to delete it"}}],
"insert": [{{"after": <number>, "text": "a new part"}}]}}.{feedback}""", f"split:{rel}")
        new = json.loads(json.dumps(doc))
        changed = {int(e["part"]): e.get("text", "") for e in res.get("edits", []) if str(e.get("part", "")).isdigit()}
        inserts = {}
        for e in res.get("insert", []):
            if str(e.get("after", "")).isdigit() and e.get("text"):
                inserts.setdefault(int(e["after"]), []).append(e["text"])
        lists = {}
        for k, (f, i, t) in enumerate(us):
            t2 = changed.get(k, t)
            if i is None:
                new[f] = t2 + "".join("\n\n" + x for x in inserts.get(k, []))
                continue
            lst = lists.setdefault(f, [])
            if t2:
                lst.append(t2)
            for x in inserts.get(k, []):
                if doc.get("source_system") == "slack" and bd.stamp_of(t):
                    st = bd.stamp_of(t)
                    g = bd.FORMAT_RE[st[0]].match(t)
                    name = g.group(2) if st[0] == "datefirst" else g.group(1)
                    x = bd.FORMATS[st[0]][1](name, st[1] + bd.timedelta(minutes=1)) + bd.clean(x)
                lst.append(x)
        for f, lst in lists.items():
            new[f] = lst
        probs = bd.planned_problems(new, m, bd.banned_words()) + gone_problems(new, item, m)
        if doc.get("source_system") == "slack":
            if any(bd.stamp_of(x) is None for x in new["messages"]) and all(bd.stamp_of(x) for x in doc["messages"]):
                probs.append("a message lost its speaker and time prefix")
        if not probs and item["remove"]:
            v = bd.ask(bd.SYSTEM, f"""Does this document state, imply or hint at any of these points, even in other words?
{json.dumps(item['remove'])}
These sentences are meant to stay and do not count, unless the document goes on to state a point above:
{json.dumps(m['must_contain'])}
Document:
{cd.text_of({k: new[k] for k in new['content_field_names']})[:12000]}
Answer as {{"states_any": true or false, "quote": "the words that state it, if any"}}.""", f"split-check:{rel}")
            if v.get("states_any"):
                probs.append(f"still says it in other words: {str(v.get('quote'))[:200]}")
        if not probs:
            return new, "ok"
        feedback = "\nA first try had these problems; fix them: " + "; ".join(probs)
    return None, "; ".join(probs)


def apply():
    done = json.loads(RESULTS.read_text())
    for key, e in sorted(done.items()):
        text = (STAGED / str(e["stage"]) / e["rel"]).read_text()
        for p in bd.stage_path(e["stage"], e["rel"]):
            p.write_text(text)
    print(f"applied {len(done)} docs")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=32)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--list", default="rewrites.json", help="a follow-up list after the plan changed")
    args = ap.parse_args()
    global RESULTS
    if args.list != "rewrites.json":
        RESULTS = OUT / f"results-{Path(args.list).stem}.json"
    if args.apply:
        return apply()
    items = json.loads((OUT / args.list).read_text())
    done = json.loads(RESULTS.read_text()) if RESULTS.exists() else {}
    todo = [i for i in items if f"{i['stage']}/{i['rel']}" not in done]
    if args.limit:
        todo = todo[:args.limit]

    def run(item):
        try:
            return item, *edit(item)
        except Exception as e:  # noqa: BLE001 - one bad answer must not stop the run
            return item, None, f"error: {type(e).__name__}: {e}"[:300]

    failed = []
    with cf.ThreadPoolExecutor(args.workers) as ex:
        for item, doc, note in ex.map(run, todo):
            if doc is None:
                failed.append((item, note))
                continue
            bd.write_doc(STAGED / str(item["stage"]) / item["rel"], doc)
            done[f"{item['stage']}/{item['rel']}"] = {"stage": item["stage"], "rel": item["rel"], "note": note}
    RESULTS.write_text(json.dumps(done, indent=1, sort_keys=True) + "\n")
    print(f"staged {len(todo) - len(failed)}/{len(todo)}; all staged: {len(done)}/{len(items)}")
    for item, note in failed:
        print("  FAILED", item["stage"], item["rel"], "-", note[:300])


if __name__ == "__main__":
    main()
