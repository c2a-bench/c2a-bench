"""Give part of the stage-0 background docs short file names, so a short name no longer marks a rule page.

    python3 scripts/shorten_background_names.py                 # report: how many renames, the leak check's lift
    python3 scripts/shorten_background_names.py --apply         # move the files, write the map
    python3 scripts/shorten_background_names.py --share 0.35    # the share of background docs renamed

The rule pages are policy pages named after their short titles (delayed-bags, compensation, refund-timing), while
EnterpriseRAG named the background after long descriptive titles: almost no background doc has a name of 15
characters or fewer, so `len(name) <= 15` alone kept 17 docs, 16 of them rule pages (scripts/leak_check.py, check 1).
Real wikis have plenty of short page names, so the background gets them too: a fixed share of background docs, picked
per path, is renamed to the first words of its own title, the number of words drawn from the rule pages' own name
lengths. Nothing a grader reads changes: rule pages, traps and decoys (doc_plan.json, every stage) keep their names,
and so do the docs listed in --exclude (e.g. another branch's planned edits). The folder stays the same.

The map goes to docs_build/background_rename_map.json (old -> new, under docs/) for the generator's copy of the
sources (tools/doc-gen; sync_erb_sources.py) to follow; docs_build/base_corpus.txt and docs_build/split/judge.json follow here.
Run from tasks/skyway-air.
"""
import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "environment" / "app"
DOCS = APP / "docs"
MAP = ROOT / "docs_build" / "background_rename_map.json"
REPO = ROOT.parents[1]

STOP = set("a an and the of for to in on at by with from or as is are be was this that these those its it our your "
           "their via vs per into about after before during while when what who how why which new".split())
TELL = re.compile(r"\d|draft|thread|temporary|outdated|\bold\b|copy")  # what rename_rule_docs.py keeps out of names


def pick(rel, share):
    """A fixed pick per path: the same docs are chosen every run."""
    return int(hashlib.sha256(rel.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF < share


def words(text):
    return [w for w in re.sub(r"[^a-z0-9 ]+", " ", text.lower().replace("-", " ")).split()
            if w not in STOP and not TELL.search(w)]


def planned():
    """Every doc a stage plans (rule pages, rule-carrying docs, traps, decoys), as docs/... paths."""
    out = set()
    for p in [ROOT / "tests" / "doc_plan.json", *sorted((ROOT / "tests" / "stages").glob("stage*/doc_plan.json"))]:
        out |= set(json.loads(p.read_text())["docs"])
    for p in [ROOT / "tests" / "rules.json", *sorted((ROOT / "tests" / "stages").glob("stage*/rules.json"))]:
        for r in json.loads(p.read_text()):
            out |= set(r.get("sources", [])) | set(r.get("decoys", []))
    return out


def name_lengths(rule_paths):
    """The rule pages' name lengths in words, as a list to draw from."""
    return sorted(len(Path(p).stem.split("-")) for p in rule_paths)


def top(rel):
    """docs/confluence/customer-policies/... -> confluence/customer-policies (the folder a builder lists)."""
    return "/".join(rel.split("/")[1:3])


def plan_renames(share, exclude, policy_share=None):
    keep = planned() | exclude
    rules = [p for p in keep if p.startswith("docs/") and (APP / p).exists()]
    draw = name_lengths([p for p in json.loads((ROOT / "tests" / "rules.json").read_text()) for p in p["sources"]])
    taken = {p.relative_to(APP).as_posix() for p in DOCS.rglob("*.json")}
    sources = {s for r in json.loads((ROOT / "tests" / "rules.json").read_text()) for s in r["sources"]}
    count = Counter(top(p) for p in taken)
    ruled = Counter(top(p) for p in sources)
    policy = {f for f in ruled if ruled[f] / count[f] > 0.03}  # the policy spaces: rule pages over 3% of the docs
    own_draw = {f: name_lengths([s for s in sources if top(s) == f]) for f in policy} if policy_share is not None else {}
    renames = {}
    for path in sorted(DOCS.rglob("*.json")):
        rel = path.relative_to(APP).as_posix()
        own = policy_share if (policy_share is not None and top(rel) in policy) else share
        if rel in keep or not pick(rel, own):
            continue
        title = str(json.loads(path.read_text()).get("title") or "")
        ws = words(title) or words(path.stem)
        h = int(hashlib.sha256(("n" + rel).encode()).hexdigest()[:8], 16)
        lens = own_draw.get(top(rel)) or draw  # a policy space draws from its own rule pages' name lengths
        k = lens[h % len(lens)]
        if len(ws) <= k and len(ws) == len(path.stem.split("-")):
            continue  # already as short as it would get
        folder = rel.rsplit("/", 1)[0]
        new = None
        for n in range(k, len(ws) + 1):
            cand = f"{folder}/{'-'.join(ws[:n])}.json"
            if ws[:n] and cand not in taken:
                new = cand
                break
        if not new or len(Path(new).stem) >= len(path.stem):
            continue
        taken.discard(rel)
        taken.add(new)
        renames[rel] = new
    return renames, rules


def leak_lines(renames):
    """Leak check 1 (main rule pages, stage 0) on the docs as they would be named."""
    sys.path.insert(0, str(REPO / "scripts"))
    import leak_check as lc
    rules = {s for r in json.loads((ROOT / "tests" / "rules.json").read_text()) for s in r["sources"]}
    carried = set(json.loads((ROOT / "tests" / "doc_plan.json").read_text())["docs"])
    docs = {}
    for path in DOCS.rglob("*.json"):
        rel = path.relative_to(APP).as_posix()
        docs[renames.get(rel, rel)] = path.read_text()
    fails, lines = lc.check_names(docs, rules, carried)
    return fails, lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--share", type=float, default=0.35)
    ap.add_argument("--policy-share", type=float, default=0.8,
                    help="share renamed in the policy spaces (folders where rule pages are over 3%% of the docs)")
    ap.add_argument("--exclude", help="JSON list of docs/... paths that must keep their names")
    a = ap.parse_args()
    exclude = set(json.loads(Path(a.exclude).read_text())) if a.exclude else set()
    renames, _ = plan_renames(a.share, exclude, a.policy_share)
    total = sum(1 for _ in DOCS.rglob("*.json"))
    print(f"{len(renames)} of {total} docs renamed (share {a.share}, policy spaces {a.policy_share}, "
          f"{len(exclude)} excluded)")
    for old, new in list(renames.items())[:10]:
        print(f"  {old.rsplit('/', 1)[-1]} -> {new.rsplit('/', 1)[-1]}")
    lens = Counter(min(len(Path(n).stem) // 5 * 5, 50) for n in renames.values())
    print("new name lengths (chars, 5s):", sorted(lens.items()))
    fails, lines = leak_lines(renames)
    print("\n".join(lines))
    print("leak check 1:", "ok" if not fails else f"FAIL {fails}")
    if not a.apply:
        return
    for old, new in renames.items():
        (APP / old).rename(APP / new)
    prior = json.loads(MAP.read_text()) if MAP.exists() else {}
    prior.update(renames)
    MAP.write_text(json.dumps(prior, indent=1, sort_keys=True) + "\n")
    src = {"sources/" + o[5:]: "sources/" + n[5:] for o, n in renames.items()}
    for f in [ROOT / "docs_build" / "base_corpus.txt", ROOT / "docs_build" / "split" / "judge.json"]:
        if f.exists():
            t = f.read_text()
            for o, n in {**src, **renames}.items():
                t = t.replace(o, n)
            f.write_text(t)
    print(f"moved {len(renames)} docs; map in {MAP.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
