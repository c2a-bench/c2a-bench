"""Check the split on the docs as they are on disk, stage by stage. Reads only.

    python3 split_check.py

1. The split test: of the rule parts the step's tickets need, how many a builder gets from the policy pages alone
   (confluence/customer-policies and confluence/support-playbooks). Before the split: every one.
2. No doc states a whole rule (a rule with 2+ parts), apart from traps, quick references and old copies.
3. Every part has a home: a doc on disk that states it word for word (case, quotes and spacing aside).
4. Every ticket has part labels for its current version (tests/rule_parts.json), and each part it needs is stated
   by one of its expected docs.
5. Every wrong version a stage adds is dated before every doc of that stage that states the same rule (the newest
   dated statement wins, so a tie or a later wrong version would be unfair).
Exit code 1 if 2, 3, 4 or 5 fails.
"""
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_docs as cd  # noqa: E402
import label_rule_parts as lp  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
POLICY = ("confluence/customer-policies/", "confluence/support-playbooks/")
NOT_SPLIT = {"R25"}  # only an announcement ("details to follow"): the announcement is the rule


def corpus(n):
    """{doc id: normalized text} of the docs as they are at stage n (stage 0 plus every update up to n)."""
    out = {}
    roots = [ROOT / "environment/app/docs"] + [ROOT / f"steps/stage{m}/workdir/stage{m}_update/new_docs" for m in range(1, n + 1)]
    for r in roots:
        for f in r.rglob("*.json"):
            out["docs/" + str(f.relative_to(r))] = cd.norm(cd.text_of(json.loads(f.read_text())))
    return out


def patched(n, docs):
    """Apply the stage patches up to n to the texts (the patch text is matched on the normalized text)."""
    for m in range(1, n + 1):
        for c in json.loads((ROOT / f"steps/stage{m}/workdir/stage{m}_update/changes.json").read_text())["changes"]:
            for p in c.get("patches", []):
                d = p["doc"] if p["doc"].startswith("docs/") else None
                if d in docs:
                    docs[d] = docs[d].replace(cd.norm(p["find"]), cd.norm(p["replace"]))
    return docs


def main():
    labels = json.loads((ROOT / "tests/rule_parts.json").read_text())["steps"] if (ROOT / "tests/rule_parts.json").exists() else {}
    bad = 0
    updates = {}  # rule -> docs a stage added or patched when it changed every part of the rule (they state it whole)
    for step, folder in lp.steps():
        n = int(step[5:])
        rules = lp.rules_of(folder)
        cases = lp.cases_of(folder)
        plan = json.loads((folder / "doc_plan.json").read_text())["docs"]
        # not a home: a wrong or old version, a quick reference (goes stale on purpose), a change note
        skip = {d for d, x in plan.items() if x.get("role") in ("quick reference", "change log")}
        trap_for = {d: x["trap"].get("for") for d, x in plan.items() if x.get("trap")}
        prev = lp.rules_of(ROOT / "tests" if n == 1 else ROOT / f"tests/stages/stage{n - 1}") if n else {}
        docs = patched(n, corpus(n))
        part = lambda e: cd.norm(e).rstrip(".")  # noqa: E731
        # 1. The split test
        need = {(r, e) for c in cases for r in c.get("rules", []) if r in rules for e in rules[r]["evidence"]
                if not e.startswith("This applies")}
        policy_text = " ".join(t for d, t in docs.items() if d[5:].startswith(POLICY) and d not in skip)
        on_policy = sum(1 for _, e in need if part(e) in policy_text)
        # 2. a whole rule in one doc
        whole = []
        for rid, r in rules.items():
            ps = [part(e) for e in r["evidence"] if not e.startswith("This applies")]
            if len(ps) < 2:
                continue
            if rid in NOT_SPLIT:
                continue
            if prev.get(rid) and not set(r["evidence"]) & set(prev[rid]["evidence"]):
                # this stage changed every part: its update states the new rule whole, as an update does
                updates.setdefault(rid, set()).update(
                    {d for d, x in plan.items() if x.get("added_in") == n} | {
                        p["doc"] for c in json.loads((folder / "changes.json").read_text())["changes"]  # ours, with rules
                        if rid in c["rules"] for p in c.get("patches", [])})
            whole += [f"{rid} in {d[5:]}" for d, t in docs.items() if d not in skip and trap_for.get(d) != rid
                      and d not in updates.get(rid, set()) and all(x in t for x in ps)]
        # 3. homes
        homeless = sorted({f"{r}: {e}" for r, e in need if not any(part(e) in t for d, t in docs.items()
                                                                  if d not in skip and trap_for.get(d) != r)})
        # 4. labels and expected docs
        unlabelled, uncovered, sizes = [], [], []
        for c in cases:
            lab = labels.get(step, {}).get(c["id"])
            if not lab or lab["key"] != lp.key(c, rules):
                unlabelled.append(c["id"])
                continue
            sizes.append(len(c.get("expected_doc_ids", [])))
            for e in lab["needed"]:
                if not any(part(e) in docs.get(d, "") for d in c.get("expected_doc_ids", [])) and not e.startswith("This applies"):
                    uncovered.append(f"{c['id']}: {e}")
        # 5. wrong versions dated first
        import blend_docs as bd
        def date(d):
            f = bd.stage_path(n, d[5:])[0] if d.startswith("docs/") else None
            return bd.doc_date(bd.load(f)) if f and f.exists() else None
        late = []
        for d, x in plan.items():
            t = x.get("trap")
            if t and not t.get("stale") and x.get("added_in", 0) == n and date(d):
                same = [date(e) for e, y in plan.items() if e != d and not y.get("trap") and y.get("added_in", 0) == n
                        and t["for"] in y.get("carries", []) and date(e)]
                if same and date(d) >= min(same):
                    late.append(f"wrong version {d[5:]} is not dated before the {t['for']} docs")
        whole += late
        print(f"{step}: policy pages alone give {on_policy}/{len(need)} needed parts; whole rule in one doc: "
              f"{len(whole)}; parts with no home: {len(homeless)}; tickets without labels: {len(unlabelled)}; "
              f"needed parts no expected doc states: {len(uncovered)}; wrong versions not dated first: {len(late)}; "
              f"expected docs per ticket: "
              f"median {statistics.median(sizes) if sizes else '-'}")
        for x in whole[:5] + homeless[:5] + unlabelled[:5] + uncovered[:8]:
            print("   ", x)
        bad += len(whole) + len(homeless) + len(unlabelled) + len(uncovered)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
