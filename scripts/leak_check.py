#!/usr/bin/env python3
"""Leak check: can a builder find the rule docs without reading the docs? No LLM, reads files only.

    python3 scripts/leak_check.py                                    # tasks/skyway-air, every stage
    python3 scripts/leak_check.py --task tasks/skyway-air --stages 0
    python3 scripts/leak_check.py --runs tasks/skyway-air/jobs/<run> ...   # also scan builder logs

"Rule docs" are each stage's main rule pages (rules.json `sources`, what a ticket's answer comes from); the wider set
(doc_plan.json: every doc that carries a rule) is reported beside them. Everything else is noise. Each check looks
for a cheap filter a builder could write without reading, and fails when it finds the rule docs far more often than
chance (lift: the rule-doc share inside the filter over the share in all docs; for a filter within folders, over the
share in those folders, since going to the policy folders is fair and only a signal inside them is a leak).

  1. names and shape   a filter on the file name (words, length), title, size, type or date, alone or with a few
                       folders, that keeps a small set holding a large part of the rule docs
  2. labels            a ticket label (agency-refund, ...) named in so few docs that grepping it lands on its rule doc
  3. stage changes     the docs a stage edits, adds or removes are mostly rule docs, so a diff against the last
                       stage's copy lists the changed rules; or, inside those, an edit's size, a changed number or
                       dollar amount, the folder (or an added doc's name, size, title) picks the rule docs out
  4. examples          the practice examples (app/examples/cases.json) state a graded rule outright, or list labels
  5. builder logs      (--runs) the builders' own commands: name-length filters, label greps, diffs of the docs

Exit code 1 when a check fails (5 only reports). The limits are the constants below.
"""

import argparse
import difflib
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

MAX_LIFT = 3.0         # 1, 3: a filter may find rule docs at most 3x more often than chance (1: within the folders it looks in)...
MIN_COVER = 0.25       # ...when it holds at least a quarter of the rule docs
MAX_FOLDERS = 3        # 1: filters may add up to this many folders (the densest ones), as builders do
MIN_LABEL_DOCS = 20    # 2: a label must be named in at least this many docs...
MAX_LABEL_RULE = 0.25  # ...and at most this share of them rule docs
MAX_EXAMPLE_RULES = 0  # 4: graded rule facts an example may state (word overlap below)
RULE_OVERLAP = 0.6     # 4: a fact is stated when this share of its content words (and at least 3) is in one example line

STOP = set("""a an and are as at be been but by can do does for from get gets has have if in into is it its may more
no not of on or out over per so than that the their them then there these they this to up was we when where which who
will with within without you your our us any all only each same also one two three""".split())


def words(text):
    return [w for w in re.findall(r"[a-z0-9$%]+", text.lower()) if w not in STOP and len(w) > 1]


def load(path):
    return json.loads(Path(path).read_text())


def stage_list(task):
    n = sorted(int(p.name[5:]) for p in (task / "tests" / "stages").glob("stage*") if p.name[5:].isdigit())
    return [0] + n


def stage_file(task, stage, name):
    p = task / "tests" / ("" if stage == 0 else f"stages/stage{stage}") / name
    return p if p.exists() else None


def labels_at(task, stage, all_labels):
    """The labels that exist at a stage: stage 0's are those its rules name, a later stage adds its changes.json
    "labels". A label is only checked from the stage it exists in."""
    named = lambda l, text: re.search(rf"(?<![\w-]){re.escape(l)}(?![\w-])", text)
    rules0 = json.dumps(load(stage_file(task, 0, "rules.json")))
    have = {l for l in all_labels if named(l, rules0)}
    for s in stage_list(task)[1:stage + 1]:
        ch = task / "tests" / "stages" / f"stage{s}" / "changes.json"
        have |= set(load(ch).get("labels", [])) if ch.exists() else set()
    return [l for l in all_labels if l in have]


def rule_sets(task, stage):
    """(main rule pages, every rule-carrying doc) at a stage, as paths like docs/confluence/..."""
    rules = load(stage_file(task, stage, "rules.json"))
    rules = rules if isinstance(rules, list) else rules.get("rules", rules)
    rules = rules if isinstance(rules, list) else list(rules.values())
    sources = {s for r in rules for s in r.get("sources", [])}
    plan = stage_file(task, stage, "doc_plan.json")
    carried = set(load(plan)["docs"]) if plan else set()
    return sources, carried | sources


def stage_docs(task):
    """Each stage's docs as the builder sees them: {stage: {path: text}}, plus {stage: (added, edited, removed, edits)}
    where edits is {path: (text before the stage, text after)} for the edited docs. A stage removes the docs its
    changes.json lists under "remove_docs" (paths like docs/...)."""
    app = task / "environment" / "app"
    docs = {os.path.relpath(p, app): Path(p).read_text(errors="ignore")
            for p in glob.glob(str(app / "docs" / "**" / "*"), recursive=True) if os.path.isfile(p)}
    out, delta = {0: dict(docs)}, {0: (set(), set(), set(), {})}
    for s in stage_list(task)[1:]:
        upd = task / "steps" / f"stage{s}" / "workdir" / f"stage{s}_update"
        before = dict(docs)
        added, edited = set(), set()
        new = upd / "new_docs"
        for p in glob.glob(str(new / "**" / "*"), recursive=True):
            if os.path.isfile(p):
                rel = "docs/" + os.path.relpath(p, new)
                text = Path(p).read_text(errors="ignore")
                (edited if rel in docs else added).add(rel)
                docs[rel] = text
        ch = upd / "changes.json"
        removed = {r for r in (load(ch).get("remove_docs", []) if ch.exists() else []) if r in docs}
        for r in removed:
            del docs[r]
        for c in (load(ch)["changes"] if ch.exists() else []):
            for patch in c.get("patches", []):
                rel = patch["doc"]
                if rel.startswith("docs/") and rel in docs and patch["find"] in docs[rel]:
                    docs[rel] = docs[rel].replace(patch["find"], patch["replace"])
                    if rel not in added:
                        edited.add(rel)
        edited -= removed
        out[s] = dict(docs)
        delta[s] = (added, edited, removed, {r: (before[r], docs[r]) for r in edited})
    return out, delta


def examples_at(task, stage):
    app = task / "environment" / "app" / "examples" / "cases.json"
    cases = load(app) if app.exists() else []
    for s in stage_list(task)[1:stage + 1]:
        extra = task / "steps" / f"stage{s}" / "workdir" / f"stage{s}_update" / "new_examples" / "cases.json"
        if extra.exists():
            ids = {c["id"] for c in cases}
            cases += [c for c in load(extra) if c["id"] not in ids]
    return cases


def features(path, text):
    """Things a builder can filter on without reading: name, title, size, type fields, date."""
    stem = Path(path).stem
    try:
        d = json.loads(text)
    except ValueError:
        d = {}
    title = str(d.get("title") or "")
    f = {"name words": len(stem.split("-")), "name chars": len(stem), "title words": len(title.split()),
         "size (KB)": round(len(text) / 1024, 1)}
    for k in ("document_type", "channel", "status", "source_system"):
        if isinstance(d.get(k), str):
            f[k] = d[k]
    if isinstance(d.get("created_at"), str):
        f["created month"] = d["created_at"][:7]
    return f


def folder(path, depth=3):
    return "/".join(path.split("/")[1:depth + 1][:-1]) if path.count("/") >= 2 else "."


def filters(feats):
    """Candidate filters: (name, predicate) on one feature: numeric <= / >= at each value, or one categorical value."""
    vals = defaultdict(set)
    for f in feats.values():
        for k, v in f.items():
            vals[k].add(v)
    for k, vs in vals.items():
        if all(isinstance(v, (int, float)) for v in vs):
            vs = sorted(vs)
            for v in sorted({vs[min(len(vs) - 1, int(q * len(vs) / 40))] for q in range(40)}):  # ~40 cut points
                yield f"{k} <= {v}", (lambda f, k=k, v=v: f.get(k) is not None and f[k] <= v)
                yield f"{k} >= {v}", (lambda f, k=k, v=v: f.get(k) is not None and f[k] >= v)
        elif len(vs) <= 40:
            for v in vs:
                yield f"{k} = {v}", (lambda f, k=k, v=v: f.get(k) == v)


def best_filters(docs, rules, feats):
    """The strongest filters: each feature filter, alone and within the 1..MAX_FOLDERS folders holding the most rule
    docs (ranked once over all docs, as a builder picks folders by their names), that covers at least MIN_COVER of
    the rule docs. Returns [(lift, kept, found, name, folders-alone lift)], strongest first.

    A filter within folders is measured against the rule share of those same folders, not of the whole corpus:
    going to the policy folders is what anyone building a support agent would do (the company keeps its policies
    there), so it is not a leak. The leak is a cheap signal that picks the rule pages out from the other pages of
    those folders. The folders' own lift over the corpus is still reported beside each filter."""
    n, r = len(docs), len(rules)
    base = r / n
    count = Counter(folder(p) for p in docs)
    ruled = Counter(folder(p) for p in docs if p in rules)
    dense = sorted(ruled, key=lambda d: (-ruled[d], -ruled[d] / count[d]))[:MAX_FOLDERS]
    sets = [[]] + [dense[:k] for k in range(1, len(dense) + 1)]
    alone, share = {}, {}
    for fs in sets:
        sel = [p for p in docs if not fs or folder(p) in fs]
        share[tuple(fs)] = sum(p in rules for p in sel) / len(sel)
        alone[tuple(fs)] = share[tuple(fs)] / base
    out = []
    for name, pred in [("all docs", lambda f: True)] + list(filters(feats)):
        kept = [p for p in docs if pred(feats[p])]
        for fs in sets:
            sel = [p for p in kept if not fs or folder(p) in fs]
            found = sum(p in rules for p in sel)
            if not sel or found < MIN_COVER * r:
                continue
            lift = (found / len(sel)) / share[tuple(fs)]  # chance = the rule share where the filter looks
            out.append((lift, len(sel), found, name + (f" in {', '.join(fs)}" if fs else ""), alone[tuple(fs)]))
    return sorted(out, reverse=True)


def check_names(docs, sources, carried):
    feats = {p: features(p, t) for p, t in docs.items()}
    fails, lines = [], []
    for kind, rules in (("main rule pages", sources), ("rule-carrying docs", carried)):
        rules = rules & set(docs)
        if not rules:
            continue
        top = best_filters(list(docs), rules, feats)
        lines.append(f"  {kind}: {len(rules)} of {len(docs)} docs ({100 * len(rules) / len(docs):.1f}%)")
        seen = set()
        for lift, kept, found, name, alone in top:
            key = name.split(" in ")[0].split(" <=")[0].split(" >=")[0].split(" =")[0]
            if key in seen:
                continue
            seen.add(key)
            bad = lift > MAX_LIFT
            lines.append(f"    {'FAIL' if bad else 'ok  '} lift {lift:5.1f}: {name}: keeps {kept} docs, "
                         f"{found}/{len(rules)} {kind}" + (f" (those folders alone: lift {alone:.1f})" if " in " in name else ""))
            if bad and kind == "main rule pages":
                fails.append(f"{name} (lift {lift:.1f})")
            if len(seen) >= 6:
                break
    return fails, lines


def decoded(text):
    """A JSON doc's text with its escapes read (\\u201c is a curly quote), so a label next to one still counts."""
    try:
        return json.dumps(json.loads(text), ensure_ascii=False)
    except ValueError:
        return text


def check_labels(docs, rules, labels):
    fails, lines = [], []
    for lab in sorted(labels):
        pat = re.compile(rf"(?<![\w-]){re.escape(lab)}(?![\w-])", re.I)
        hits = [p for p, t in docs.items() if pat.search(t) or ("\\u" in t and pat.search(decoded(t)))]
        ruled = sum(p in rules for p in hits)
        bad = len(hits) < MIN_LABEL_DOCS or (hits and ruled / len(hits) > MAX_LABEL_RULE)
        if bad:
            fails.append(lab)
        lines.append(f"    {'FAIL' if bad else 'ok  '} {lab}: named in {len(hits)} docs, {ruled} of them rule docs")
    return fails, lines


NUM = re.compile(r"\d[\d,.:/-]*")
DOLLAR = re.compile(r"\$\s?\d[\d,.]*")


def edit_features(path, old, new):
    """What a builder can see of an edit without judging it: how big it is, whether it changes a number or a dollar
    amount, whether it only adds text, and the folder."""
    sm = difflib.SequenceMatcher(None, old, new, autojunk=False)
    gone, came = [], []
    for op, a1, a2, b1, b2 in sm.get_opcodes():
        if op != "equal":
            gone.append(old[a1:a2])
            came.append(new[b1:b2])
    gone, came = " ".join(gone), " ".join(came)
    # numbers and dollar amounts compared over the whole doc: a diff of "$75" -> "$90" only shows "75" -> "90"
    return {"changed chars": len(gone) + len(came),
            "changes a number": Counter(NUM.findall(old)) != Counter(NUM.findall(new)),
            "changes a dollar amount": Counter(DOLLAR.findall(old)) != Counter(DOLLAR.findall(new)),
            "only adds text": not gone.strip(),
            "folder": folder(path)}


def within(items, rules, feats, what):
    """Inside one set of changed docs (base = its own rule share): the strongest single-feature filter that holds
    at least MIN_COVER of its rule docs. Returns (lift, kept, found, name) or None."""
    r = len(items & rules)
    if r < 3 or r == len(items):
        return None
    base = r / len(items)
    best = None
    vals = defaultdict(set)
    for p in items:
        for k, v in feats[p].items():
            vals[k].add(v)
    for k, vs in vals.items():
        preds = []
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vs):
            preds = [(f"{k} <= {v}", lambda f, k=k, v=v: k in f and f[k] <= v) for v in sorted(vs)] + \
                    [(f"{k} >= {v}", lambda f, k=k, v=v: k in f and f[k] >= v) for v in sorted(vs)]
        else:
            preds = [(f"{k} = {v}", lambda f, k=k, v=v: f.get(k) == v) for v in vs]
        for name, pred in preds:
            kept = [p for p in items if pred(feats[p])]
            found = sum(p in rules for p in kept)
            if kept and found >= MIN_COVER * r:
                lift = (found / len(kept)) / base
                if best is None or lift > best[0]:
                    best = (lift, len(kept), found, f"{what} with {name}")
    return best


def check_changes(docs, rules, added, edited, removed, edits, prev):
    """The stage's changes against the last stage's copy, as a diff shows them. Rule docs here are every doc that
    carries a rule. Each of edited / added / removed must not be far richer in rule docs than the corpus, and inside
    each, no plain feature (edit size, a changed number or dollar amount, the folder; for added docs their name, size
    and title) may pick the rule docs out."""
    fails, lines = [], []
    base = len(rules & set(docs)) / len(docs)
    for kind, ds in (("edited", edited), ("added", added), ("removed", removed)):
        if not ds:
            lines.append(f"    {'ok  '} {kind}: none" + (" (a stage that never removes a doc is a tell too)" if kind == "removed" else ""))
            continue
        r = len(ds & rules)
        lift = (r / len(ds)) / base if base else 0
        bad = lift > MAX_LIFT and r
        if bad:
            fails.append(f"{kind} docs: {r}/{len(ds)} are rule docs (lift {lift:.1f})")
        lines.append(f"    {'FAIL' if bad else 'ok  '} {kind}: {len(ds)} docs, {r} rule docs (lift {lift:.1f})")
    if edits:
        ef = {p: edit_features(p, *edits[p]) for p in edits}
        best = within(set(edits), rules, ef, "edited docs")
        if best:
            bad = best[0] > MAX_LIFT
            if bad:
                fails.append(f"{best[3]} (lift {best[0]:.1f})")
            lines.append(f"    {'FAIL' if bad else 'ok  '} strongest edit filter: {best[3]}: keeps {best[1]}, "
                         f"{best[2]}/{len(set(edits) & rules)} rule edits (lift {best[0]:.1f} over the edited docs)")
        rule_edits = [ef[p] for p in edits if p in rules]
        if rule_edits:
            lines.append(f"         rule edits: median {sorted(e['changed chars'] for e in rule_edits)[len(rule_edits) // 2]} chars changed, "
                         f"{sum(e['changes a number'] for e in rule_edits)}/{len(rule_edits)} change a number, "
                         f"{sum(e['changes a dollar amount'] for e in rule_edits)} a dollar amount")
    if added:
        af = {p: features(p, docs[p]) for p in added}
        for p in added:
            af[p]["folder"] = folder(p)
        best = within(set(added), rules, af, "added docs")
        if best:
            bad = best[0] > MAX_LIFT
            if bad:
                fails.append(f"{best[3]} (lift {best[0]:.1f})")
            lines.append(f"    {'FAIL' if bad else 'ok  '} strongest added-doc filter: {best[3]}: keeps {best[1]}, "
                         f"{best[2]}/{len(added & rules)} rule docs (lift {best[0]:.1f} over the added docs)")
    return fails, lines


def check_examples(cases, facts, labels):
    fails, lines = [], []
    texts = [(c["id"], c.get("test", "")) for c in cases]
    stated = []
    for f in facts:
        if f.get("kind") != "rule":
            continue
        body = f["text"].split("): ", 1)[-1]
        fw = set(words(body))
        if len(fw) < 3:
            continue
        nums = {w for w in fw if re.search(r"\d", w)}
        for cid, t in texts:
            tw = set(words(t))
            shared = fw & tw
            if len(shared) >= 3 and len(shared) / len(fw) >= RULE_OVERLAP and (not nums or nums <= tw):
                stated.append((f["id"], cid, body))
                break
    if len(stated) > MAX_EXAMPLE_RULES:
        fails.append(f"{len(stated)} graded rule facts stated in example lines")
    lines.append(f"    {'FAIL' if len(stated) > MAX_EXAMPLE_RULES else 'ok  '} {len(stated)} of "
                 f"{sum(f.get('kind') == 'rule' for f in facts)} rule facts likely stated in an example's test line (word overlap: check by eye)")
    for fid, cid, body in stated[:12]:
        lines.append(f"         {fid} in {cid}: {body[:90]}")
    named = Counter()
    for c in cases:
        blob = json.dumps({k: c.get(k) for k in ("test", "expect", "contains", "not_contains")})
        for lab in labels:
            if re.search(rf"(?<![\w-]){re.escape(lab)}(?![\w-])", blob):
                named[lab] += 1
    if named:
        fails.append(f"examples name {len(named)} labels")
    lines.append(f"    {'FAIL' if named else 'ok  '} labels named in the examples: "
                 + (", ".join(f"{l} ({n})" for l, n in sorted(named.items())) or "none"))
    return fails, lines


LOG_PATTERNS = {
    "name-length filter": re.compile(r"split\(\\*['\"]-\\*['\"]\)\)?\s*\)?\s*(<=?|>=?|==)\s*\d|len\(\s*\w+\.stem"),
    "label grep": None,  # built from the labels
    "docs diff / hash": re.compile(r"(diff|hashlib|filecmp|md5sum|sha\d+sum|mtime|st_mtime)[^\n]{0,200}(app/docs|docs/)"
                                   r"|(app/docs|['\"]docs['\"])[^\n]{0,200}(diff|hashlib|filecmp|md5sum|sha\d+sum)"),
}


def scan_logs(runs, labels):
    lab = re.compile(r"(rg|grep|re\.search|re\.findall|in p\.read_text|in text)[^\n]{0,160}("
                     + "|".join(re.escape(l) for l in labels) + ")")
    pats = dict(LOG_PATTERNS, **{"label grep": lab})
    lines = []
    for run in runs:
        # the run's own trial (resume-*/ folders keep older copies of re-run stages)
        trajs = [t for t in glob.glob(os.path.join(run, "*", "steps", "stage*", "agent", "trajectory.json"))
                 if "/resume-" not in t] or glob.glob(os.path.join(run, "steps", "stage*", "agent", "trajectory.json"))
        try:
            arch = load(os.path.join(run, "config.json")).get("extra_instruction_paths") or []
            arch = Path(arch[0]).stem if arch else ""
        except (OSError, ValueError, AttributeError):
            arch = ""
        for traj in sorted(trajs, key=lambda t: int(re.search(r"stage(\d+)", t).group(1))):
            steps = load(traj).get("steps", [])
            calls = [json.dumps(tc.get("arguments", tc)) for s in steps for tc in (s.get("tool_calls") or [])]
            hits = {n: [i + 1 for i, c in enumerate(calls) if p.search(c)] for n, p in pats.items()}
            stage = next((p for p in Path(traj).parts if re.fullmatch(r"stage\d+", p)), "?")
            name = arch or Path(run).name
            lines.append(f"    {name} {stage}: {len(calls)} calls | "
                         + " | ".join(f"{n}: {len(v)}" + (f" (calls {', '.join(map(str, v[:5]))})" if v else "")
                                      for n, v in hits.items()))
    return lines


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--task", default=str(REPO / "tasks" / "skyway-air"))
    ap.add_argument("--stages", help="comma list, default every stage")
    ap.add_argument("--runs", nargs="*", default=[], help="run folders whose builder logs to scan (check 5)")
    a = ap.parse_args()
    task = Path(a.task).resolve()
    sys.path.insert(0, str(task / "tests"))
    from customer import LABELS  # the ticket labels a Skyway rule assigns

    all_docs, delta = stage_docs(task)
    stages = [int(s) for s in a.stages.split(",")] if a.stages else stage_list(task)
    failed = []
    for s in stages:
        docs = all_docs[s]
        sources, carried = rule_sets(task, s)
        facts_path = stage_file(task, s, "facts.json")
        facts = load(facts_path)["facts"] if facts_path else []
        print(f"\n=== stage {s}: {len(docs)} docs")
        for title, (fails, lines) in (
            ("1. names and shape", check_names(docs, sources, carried)),
            ("2. labels", check_labels(docs, carried, labels_at(task, s, LABELS))),
            ("3. stage changes", check_changes(docs, carried, *delta[s], all_docs[s - 1]) if s
             else ([], ["    ok   stage 0 has no changes"])),
            ("4. examples", check_examples(examples_at(task, s), facts, LABELS)),
        ):
            print(f"  {title}: {'FAIL' if fails else 'ok'}")
            print("\n".join(lines))
            failed += [f"stage {s}, {title}: {f}" for f in fails]
    if a.runs:
        print("\n=== 5. builder logs (report only)")
        print("\n".join(scan_logs(a.runs, LABELS)))
    print(f"\n{'FAILED' if failed else 'PASSED'}: {len(failed)} problem(s)")
    for f in failed[:40]:
        print(f"  - {f}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
