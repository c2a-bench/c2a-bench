"""Ordinary edits in every stage update, so a diff against the last stage does not list only the rule changes.

    python3 blend_stage_churn.py --plan        # pick each stage's edited docs and edit kinds; freeze them
    python3 blend_stage_churn.py --report      # the frozen plan's numbers
    python3 blend_stage_churn.py --edits       # write the edits (model calls for the worded ones), staged
    python3 blend_stage_churn.py --removals    # pick each stage's removed docs (no model calls)

A review (point 5): a stage edited only rule docs, so builders hashed /app/docs against their saved copy and
read only what changed. Each stage now also edits about EDITS ordinary docs with one change shaped like a rule edit:
a number (a time, date, count, gate, flight), a dollar amount that decides nothing, a number and the words around it,
a reworded sentence, or an added sentence. They sit in every folder and heavily in the folders the stage's rule edits
are in, so neither the size of an edit, a changed number or dollar amount, added-only text nor the folder picks the
rule edits out. Each edit is checked: its text occurs once, the doc stays valid JSON, no background problem it did not
have (check_docs.py's rules), no rule wording, no ticket label.

The edits are staged in docs_build/blend/churn/edits/stage<N>.json; package_stages.py puts them in each stage's
changes.json among the rule patches, and the stage's setup.sh applies them. Rule docs, rules, tickets and facts do
not change.
"""
import argparse
import collections
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import blend_docs as bd  # noqa: E402
import blend_labels as bl  # noqa: E402

ROOT = bd.ROOT
STAGES = range(1, 6)
EDITS = 120                      # ordinary edits per stage
LABEL_EDITS = {}                 # edits that add a label mention (none: blend_labels.py's stage spread covers it)
TARGET = 2.5                     # aim: a folder's rule edits at most this many times richer than chance (limit 3)
EDIT_KINDS = [("number", 0.6), ("dollar", 0.1), ("wording", 0.3)]
# then, per stage: ADD_SHARE of the edits become an added sentence (from the wording ones), and a third of the number
# ones change the words around the number too, so edit sizes and "only adds text" match the rule edits
ADD_SHARE = 0.15
PHRASE_SHARE = 1 / 3
MAX_LIFT = 3.0


def load(p):
    return json.loads(Path(p).read_text())


def stage_update(n):
    return ROOT / f"steps/stage{n}/workdir/stage{n}_update"


def rule_docs(n):
    """Every doc that carries a rule at stage n (doc plan and rule sources), as rel paths under docs/."""
    p = ROOT / ("tests" if n == 0 else f"tests/stages/stage{n}")
    out = {d.removeprefix("docs/") for d in load(p / "doc_plan.json")["docs"]}
    for r in load(p / "rules.json"):
        out |= {s.removeprefix("docs/") for s in r.get("sources", [])}
    return out


def rule_changes(n):
    """(docs stage n's rule patches edit, docs it adds), from its changes.json and new_docs."""
    ch = load(stage_update(n) / "changes.json")
    edited = {p["doc"].removeprefix("docs/") for c in ch["changes"] for p in c.get("patches", [])
              if p["doc"].startswith("docs/")}
    new = stage_update(n) / "new_docs"
    added = {str(f.relative_to(new)) for f in new.rglob("*.json")}
    return edited, added


def label_docs():
    """Docs blend_labels.py wrote a label line into (left alone: their line must stay as it is)."""
    f = bl.OUT / "results.json"
    return {v["rel"] for v in load(f).values() if v["ok"]} if f.exists() else set()


def untouchable():
    """Docs the edits never touch: any stage's rule docs, lookalikes, patched docs, docs anything names,
    docs with a label line."""
    out = set().union(*(rule_docs(n) for n in [0, *STAGES]))
    out |= {d.removeprefix("docs/") for d in load(bd.OUT / "lookalikes.json")} | bd.referenced() | label_docs()
    for n in STAGES:
        out |= {p["doc"].removeprefix("docs/") for c in load(stage_update(n) / "changes.json")["changes"]
                for p in c.get("patches", [])}
    return out


def docs_before(n, removed):
    """The docs a builder has at the start of stage n (stage 0's, plus earlier stages' new docs, less removals)."""
    docs = {str(f.relative_to(bd.ENV)) for f in bd.ENV.rglob("*.json")}
    for m in range(1, n):
        new = stage_update(m) / "new_docs"
        docs |= {str(f.relative_to(new)) for f in new.rglob("*.json")}
    return docs - removed


def pick_by_folder(pool, total, need, rng):
    """total docs from pool: first `need[folder]` in each folder that has rule changes, the rest spread by folder size."""
    by = collections.defaultdict(list)
    for p in sorted(pool):
        by[bd.folder_of(p)].append(p)
    for v in by.values():
        rng.shuffle(v)
    chosen = []
    for f, k in sorted(need.items()):
        chosen += by[f][:k]
        by[f] = by[f][k:]
    rest = [p for v in by.values() for p in v]
    rng.shuffle(rest)
    chosen += rest[:max(0, total - len(chosen))]
    return chosen


def capability(rel):
    """'dollar' if the doc has a $ amount an edit may change, 'number' if it has another number, '' if neither."""
    import blend_stage_churn as me  # the edit job's patterns, defined further down
    src = me.where(rel)
    if src is None:
        return ""
    doc = json.loads(me.doc_path(src, rel).read_text())
    strs = me.strings_of(doc)
    if any(me.number_candidates(t, pre, True) for _, _, pre, t in strs):
        return "dollar"
    return "number" if any(me.number_candidates(t, pre, False) for _, _, pre, t in strs) else ""


def lift(r, n, base):
    return (r / n) / base if n and base else 0.0


def plan(rng):
    skip = untouchable()
    removed_all, edited_all, out = set(), set(), {}  # nothing is removed; docs_before keeps the parameter
    for n in STAGES:
        before = docs_before(n, removed_all)
        rules = rule_docs(n)
        r_edit, r_add = rule_changes(n)
        r_add_rules = r_add & rules
        pool = sorted(p for p in before if p not in skip and p not in edited_all and bd.folder_of(p) not in bl.SKIP_FOLDERS)
        # edits: heavy where the rule edits are (a folder holding k of the r rule edits gets enough ordinary edits that
        # its rule share is at most TARGET x the edits' overall rule share), the rest spread
        e_all = EDITS + len(r_edit)
        need = collections.Counter(bd.folder_of(p) for p in r_edit)
        need = {f: max(0, -(-int(k * e_all) // int(TARGET * len(r_edit))) - k) for f, k in need.items()}
        edits = pick_by_folder(pool, EDITS, need, rng)
        # most rule edits change a number, so most ordinary ones must too: within each folder, swap docs that have no
        # number to change for ones that do, until the number and dollar share of EDIT_KINDS is met
        want_num = round(sum(w for k, w in EDIT_KINDS if k != "wording") * len(edits))
        cap = {p: capability(p) for p in edits}
        chosen = set(edits)
        spare = collections.defaultdict(list)
        for p in pool:
            if p not in chosen:
                spare[bd.folder_of(p)].append(p)
        for v in spare.values():
            rng.shuffle(v)
        have = sum(bool(cap[p]) for p in edits)
        for i, p in enumerate(list(edits)):
            if have >= want_num:
                break
            if cap[p]:
                continue
            f = bd.folder_of(p)
            while spare[f]:
                q = spare[f].pop()
                c = capability(q)
                if c:
                    edits[i], cap[q] = q, c
                    have += 1
                    break
        want_dollar = round(dict(EDIT_KINDS)["dollar"] * len(edits))
        kinds = []
        n_dollar = 0
        for p in edits:
            c = cap.get(p, "")
            if c == "dollar" and n_dollar < want_dollar:
                kinds.append("dollar")
                n_dollar += 1
            elif c:
                kinds.append("number")
            else:
                kinds.append("wording")
        # added sentences (from the wording ones) and number-plus-words edits (from the number ones), so a replan keeps
        # the mix the rule edits need to hide among
        wi = [i for i, k in enumerate(kinds) if k == "wording"]
        ni = [i for i, k in enumerate(kinds) if k == "number"]
        rng.shuffle(wi)
        rng.shuffle(ni)
        for i in wi[:round(ADD_SHARE * len(kinds))]:
            kinds[i] = "add"
        for i in ni[:round(PHRASE_SHARE * len(ni))]:
            kinds[i] = "number_phrase"
        label_n = LABEL_EDITS.get(n, 0)
        for i in range(label_n):
            kinds[i] = "label"
        edited_all |= set(edits)
        after = len(before) + len(r_add)
        out[n] = {"docs_before": len(before), "docs_after": after, "rule_docs": len(rules), "base": len(rules) / after,
                  "rule_edits": sorted(r_edit), "edits": [{"rel": p, "kind": k} for p, k in zip(edits, kinds)]}
    return out


def report(p):
    print("stage | docs | rule docs | edited: rule / all (lift) | edit folders: worst lift")
    for n, s in p.items():
        e_all = len(s["rule_edits"]) + len(s["edits"])
        # within the edited docs: the folder holding rule edits with the highest rule share
        ef = collections.Counter(bd.folder_of(e["rel"]) for e in s["edits"])
        rf = collections.Counter(bd.folder_of(r) for r in s["rule_edits"])
        e_base = len(s["rule_edits"]) / e_all
        worst = max((lift(rf[f], rf[f] + ef[f], e_base) for f in rf), default=0)
        print(f"  {n}   | {s['docs_after']:>6} | {s['rule_docs']:>3} ({100 * s['base']:.1f}%) | "
              f"{len(s['rule_edits'])} / {e_all} ({lift(len(s['rule_edits']), e_all, s['base']):.1f}) | {worst:.1f}")
    for n, s in p.items():
        kinds = collections.Counter(e["kind"] for e in s["edits"])
        print(f"  stage {n}: edit kinds {dict(kinds)}; "
              f"edit folders {collections.Counter(bd.folder_of(e['rel']) for e in s['edits']).most_common(4)}")


REMOVALS = bd.OUT / "churn" / "removals.json"
REMOVES = 40            # docs each stage removes
POLICY_SHARE = 0.5      # of them, docs that look like policy (so "what was removed" reads like rules withdrawn)
POLICY_FOLDERS = {"confluence/customer-policies", "confluence/support-playbooks", "confluence/policy-and-compliance",
                  "slack/refunds-desk", "slack/support-policy-questions"}
POLICY_TOPIC = re.compile(r"(?i)\b(refund|compensat|baggage|bag claim|delay|cancell?|travel credit|voucher|reimburs|"
                          r"hotel|meal|rebook|fare|goodwill)\w*")


def removals_job():
    """Pick each stage's removed docs: never a doc any stage's plan names (rule docs, traps, old versions), a
    look-alike, a label-line doc, a doc shorten_background_names.py renamed, a doc any stage edits, or a doc a ticket, rule, patch or
    manifest names. About half
    look like policy (a policy folder, or a refund, delay, baggage or credit topic) and decide nothing, the rest are
    everyday docs. Writes docs_build/blend/churn/removals.json: {stage: [docs/...]}."""
    plan = frozen_plan()
    keep = untouchable() | {d.removeprefix("docs/") for d in load(ROOT / "docs_build/lookalike_pages.json")}
    # shorten_background_names.py's short-named background docs stay: removing them would thin its fix (short names no longer mark rules)
    keep |= {d.removeprefix("docs/") for d in load(ROOT / "docs_build/background_rename_map.json").values()}
    keep |= {e["rel"] for st in plan.values() for e in st["edits"]}
    gone, out = set(), {}
    for n in STAGES:
        rng = random.Random(3000 + n)
        before = sorted(p for p in docs_before(n, gone) if p not in keep)
        policy, other = [], []
        for rel in before:
            src = where(rel)
            title = str(load(doc_path(src, rel)).get("title") or "") if src is not None else ""
            # looks like policy at a glance: a policy space, or a policy topic in its title or file name
            (policy if bd.folder_of(rel) in POLICY_FOLDERS or POLICY_TOPIC.search(title + " " + rel) else other).append(rel)
        k = round(POLICY_SHARE * REMOVES)
        pick = rng.sample(policy, min(k, len(policy)))
        pick += rng.sample(other, REMOVES - len(pick))
        gone |= set(pick)
        out[n] = sorted("docs/" + p for p in pick)
        print(f"stage {n}: remove {len(pick)} ({min(k, len(policy))} policy-looking of {len(policy)} candidates, "
              f"{len(pick) - min(k, len(policy))} everyday); folders {collections.Counter(bd.folder_of(p) for p in pick).most_common(4)}")
    REMOVALS.write_text(json.dumps(out, indent=1) + "\n")
    print(f"written {REMOVALS}")


PLAN = bd.OUT / "churn" / "plan.json"
EDITS_DIR = bd.OUT / "churn" / "edits"

# ---------- the edit job: one small patch per planned edit ----------

import check_docs as cd  # noqa: E402

TIME = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b(?! ?[AaPp]\.?[Mm])")
TIME12 = re.compile(r"\b(1[0-2]|[1-9]):([0-5]\d) ?([AP]M)\b")
GATE = re.compile(r"\b([A-E])([1-9]\d?)\b")
COUNT = re.compile(r"(?<![\w$.,:/-])([2-9]|[1-9]\d)(?![\w.,:/%-])")
ISO = re.compile(r"\b(2026)-(0[1-9]|1[0-2])-([0-2]\d)\b")
MONTHDAY = re.compile(r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|"
                      r"Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?) ([1-9]|[12]\d)\b(?!,? ?\d{4}\b)")
FLIGHT = re.compile(r"\b(SW|SK|SX)(\d{3,4})\b")
NOUN_COUNT = re.compile(r"(?<![\w$.,:/-])(\d{1,3})(?= (?:bags?|agents?|people|passengers?|cases?|tickets?|messages?|"
                        r"calls?|screens?|carts?|chairs?|gates?|desks?|lanes?|rows?|seats?|items?|steps?|slides?|"
                        r"forms?|fields?|tags?|shifts?|staff|trainees?|stations?|flights?|records?|errors?|alerts?|"
                        r"pages?|emails?|chats?|threads?|screenshots?|reports?|files?|boxes?|tablets?|scanners?|"
                        r"printers?|kiosks?)\b)")
DOLLAR = re.compile(r"\$(\d{1,3}(?:,\d{3})*|\d+)(?:\.(\d\d))?")
# a number next to these is a duration, a limit or a share: never changed (it could read as a rule)
NEAR_RULE = re.compile(r"(?i)^\s*(?:%|percent|hours?|hrs?|days?|nights?|weeks?|months?|years?|per\b|minutes? (?:late|delay))")
POLICY_WORD = re.compile(r"(?i)\b(refund|credit|compensat|reimburs|voucher|hotel|meal|allowance|fee|fare|claim|"
                         r"eligib|entitled|policy|limit|cap|deadline|within)\w*")


PREFIX_TIME = re.compile(r"\d{1,2}:\d\d(?:\s?[AP]M)?")
PREFIX_SEP = re.compile(r": |\s[—–-]\s|\s·\s|\n")


def message_prefix(m):
    """How long a Slack message's speaker-and-time prefix is, or None when it cannot be told safely. The corpus writes
    it many ways ("Name — 2:22 PM: ", "05:49 Renée Brooks: ", "Victor Huang 2026-04-22 06:52 — ", "Erin McKay · 14:58\n",
    "Will Brennan — 14:24 — ", "Connor Blake: "): it runs to the separator after the last time in the first 70
    characters, or, with no time there, to the first separator. Edits never touch it: speaker and time stay."""
    k = bd.msg_format(m)
    known = re.match(bd.FORMATS[k][0], m).end() if k else 0
    head = m[:70]
    times = list(PREFIX_TIME.finditer(head))
    seps = [x.end() for x in PREFIX_SEP.finditer(head)]
    if times:
        after = [e for e in seps if e >= times[-1].end()]
        return max(known, after[0] if after else times[-1].end())
    if seps:
        return max(known, seps[0])
    return known or None


def strings_of(doc):
    """(field, index, prefix_len, text) for every editable string: Slack message bodies (after speaker and time) and
    Confluence content strings / list items. A message whose prefix cannot be told is left out."""
    out = []
    if isinstance(doc.get("messages"), list):
        for i, m in enumerate(doc["messages"]):
            if not isinstance(m, str):
                continue
            pre = message_prefix(m)
            if pre is not None:
                out.append(("messages", i, pre, m))
    else:
        for f in doc.get("content_field_names", []):
            v = doc.get(f)
            if isinstance(v, str):
                out.append((f, None, 0, v))
            elif isinstance(v, list):
                out += [(f, i, 0, x) for i, x in enumerate(v) if isinstance(x, str)]
    return out


def shifted(kind, m, rng):
    """The new text for a matched number, or None."""
    if kind == "time":
        h, mi = int(m.group(1)), int(m.group(2))
        t = (h * 60 + mi + rng.choice([-1, 1]) * rng.choice([5, 10, 15, 20, 25, 30, 40])) % (24 * 60)
        return f"{t // 60:0{len(m.group(1))}d}:{t % 60:02d}"
    if kind == "time12":
        h, mi = int(m.group(1)) % 12, int(m.group(2))
        t = (h * 60 + mi + rng.choice([-1, 1]) * rng.choice([5, 10, 15, 20, 30])) % (12 * 60)
        hh = t // 60 or 12
        return f"{hh}:{t % 60:02d}{' ' if ' ' in m.group(0) else ''}{m.group(3)}"
    if kind == "gate":
        n = max(1, int(m.group(2)) + rng.choice([-3, -2, -1, 1, 2, 3, 4]))
        return f"{m.group(1)}{n}"
    if kind in ("count", "noun_count"):
        n = int(m.group(1)) + rng.choice([-2, -1, 1, 2, 3])
        return str(n) if n >= 2 else None
    if kind == "monthday":
        d = max(1, min(28, int(m.group(2)) + rng.choice([-2, -1, 1, 2])))
        return f"{m.group(1)} {d}"
    if kind == "flight":
        num = int(m.group(2)) + rng.choice([-6, -4, -2, 2, 4, 6])
        return f"{m.group(1)}{num:0{len(m.group(2))}d}" if num > 0 else None
    if kind == "iso":
        d = max(1, min(28, int(m.group(3)) + rng.choice([-2, -1, 1, 2])))
        return f"{m.group(1)}-{m.group(2)}-{d:02d}"
    if kind == "dollar":
        whole = int(m.group(1).replace(",", ""))
        v = max(1, round(whole * rng.uniform(0.85, 1.15)))
        if v == whole:
            v += 1
        cents = f".{rng.randint(0, 99):02d}" if m.group(2) else ""
        new = f"${v:,}" if "," in m.group(1) else f"${v}"
        new += cents
        amounts = cd.rule_amounts()
        return None if cd.norm(new).rstrip(",.;:") in amounts or f"${v}" in amounts else new
    return None


def number_candidates(text, start, want_dollar):
    pats = [("dollar", DOLLAR)] if want_dollar else [("time", TIME), ("time12", TIME12), ("gate", GATE),
                                                       ("iso", ISO), ("monthday", MONTHDAY), ("flight", FLIGHT),
                                                       ("noun_count", NOUN_COUNT), ("count", COUNT)]
    out = []
    for kind, pat in pats:
        for m in pat.finditer(text, start):
            after = text[m.end():m.end() + 20]
            if NEAR_RULE.match(after):
                continue
            if kind in ("time", "time12") and after[:2].lstrip().startswith(":"):
                continue  # a message's own time ("Samir Patel 2:35 PM: ..."), not something it says
            window = text[max(0, m.start() - 25):m.end() + 25]
            if kind in ("count", "noun_count") and POLICY_WORD.search(window):  # near a policy word: could read as a limit
                continue
            out.append((kind, m))
    return out


def unique_find(raw, text, a, b):
    """The smallest piece of text around [a, b) whose escaped form occurs once in the raw file."""
    for pad in (10, 16, 24, 36, 50, 80):
        lo, hi = max(0, a - pad), min(len(text), b + pad)
        piece = text[lo:hi]
        if raw.count(json.dumps(piece)[1:-1]) == 1:
            return lo, hi
    return None


def number_edit(doc, raw, kind, rng):
    want_dollar = kind == "dollar"
    cands = []
    for field, idx, pre, text in strings_of(doc):
        cands += [(field, idx, text, k, m) for k, m in number_candidates(text, pre, want_dollar)]
    rng.shuffle(cands)
    for field, idx, text, k, m in cands:
        new_tok = shifted(k, m, rng)
        if not new_tok or new_tok == m.group(0):
            continue
        span = unique_find(raw, text, m.start(), m.end())
        if not span:
            continue
        lo, hi = span
        find = text[lo:hi]
        replace = text[lo:m.start()] + new_tok + text[m.end():hi]
        return {"find": find, "replace": replace, "what": f"{k}: {m.group(0)} -> {new_tok}"}
    return None


def wording_edit(doc, raw, rng, phrases, banned, big=False):
    """A few words of one sentence changed (model call), nothing else; big: most of the sentence rewritten."""
    sents = []
    for field, idx, pre, text in strings_of(doc):
        for m in re.finditer(r"[^.!?]{40,260}[.!?]", text[pre:]):
            sents.append((text, pre + m.start(), pre + m.end()))
    rng.shuffle(sents)
    # sizes like the rule edits (a few characters to a whole clause): some small, many mid, some a full rewrite
    size = "most of the sentence, keeping its point" if big else \
        rng.choices(["two to four words", "five to ten words", "most of the sentence, keeping its point"], weights=[3, 4, 3])[0]
    for text, a, b in sents[:3]:
        sentence = text[a:b].strip()
        a = text.index(sentence, a)
        b = a + len(sentence)
        res = bd.ask(bd.SYSTEM, f"""One sentence from an internal Skyway Air doc:
{sentence}

Rewrite it with an edit someone might make when tidying the doc: change {size} (a clearer wording, a name of a
tool or team, a small correction, a reordered clause). Keep its meaning. Add no number, amount,
date, time, rule, policy, limit or deadline, and no ticket tag. Answer as {{"text": "..."}}.""", "churn:wording")
        new = bd.clean((res.get("text") or "").strip())
        if not new or new == sentence or abs(len(new) - len(sentence)) > 120:
            continue
        if re.search(r"\d", new) and re.findall(r"\d+", new) != re.findall(r"\d+", sentence):
            continue
        span = unique_find(raw, text, a, b)
        if not span:
            continue
        lo, hi = span
        return {"find": text[lo:hi], "replace": text[lo:a] + new + text[b:hi], "what": "wording"}
    return None


def add_edit(doc, raw, rng, phrases, banned):
    """One ordinary sentence or clause appended to an existing message or line (model call)."""
    strs = [(t, pre) for _, _, pre, t in strings_of(doc) if len(t) - pre >= 60]
    rng.shuffle(strs)
    for text, pre in strs[:3]:
        tail_at = max(pre, len(text) - 60)
        res = bd.ask(bd.SYSTEM, f"""The end of a passage from an internal Skyway Air doc:
...{text[tail_at:]}

Write ONE short sentence or clause (about {rng.choice([5, 8, 12, 18, 25])} words) that someone might add right after
it: a small clarification, who is following up, or where a note was saved. Add no amount, percentage, deadline,
limit, rule or policy, no ticket tag, and no new number. Answer as {{"text": "..."}}.""", "churn:add")
        new = bd.clean((res.get("text") or "").strip())
        if not new or re.search(r"\d", new):
            continue
        span = unique_find(raw, text, len(text) - 1, len(text))
        if not span:
            continue
        lo, hi = span
        piece = text[lo:hi]
        return {"find": piece, "replace": piece + (" " if not piece.endswith(" ") else "") + new, "what": "add"}
    return None


def number_phrase_edit(doc, raw, rng, phrases, banned):
    """A number changed and the few words around it reworded (model call)."""
    cands = []
    for field, idx, pre, text in strings_of(doc):
        for k, m in number_candidates(text, pre, False):
            new_tok = shifted(k, m, rng)
            if new_tok and new_tok != m.group(0):
                cands.append((text, pre, m, new_tok))
    rng.shuffle(cands)
    for text, pre, m, new_tok in cands[:3]:
        a = max(pre, text.rfind(" ", 0, max(0, m.start() - 30)) + 1)
        b = text.find(" ", min(len(text), m.end() + 30))
        b = len(text) if b < 0 else b
        clause = text[a:b]
        res = bd.ask(bd.SYSTEM, f"""A piece of an internal Skyway Air doc:
{clause}

Rewrite it so that {m.group(0)} becomes {new_tok}, and reword two to six of the words around it the way someone
tidying the note would. Keep its meaning. Add no other number, amount, deadline, limit, rule or policy, and no ticket
tag. Answer as {{"text": "..."}}.""", "churn:number_phrase")
        new = bd.clean((res.get("text") or "").strip())
        if not new or new_tok not in new or new == clause:
            continue
        if sorted(re.findall(r"\d+", new)) != sorted(re.findall(r"\d+", clause.replace(m.group(0), new_tok, 1))):
            continue
        span = unique_find(raw, text, a, b)
        if not span:
            continue
        lo, hi = span
        return {"find": text[lo:hi], "replace": text[lo:a] + new + text[b:hi],
                "what": f"number_phrase: {m.group(0)} -> {new_tok}"}
    return None


def doc_path(stage_of_doc, rel):
    return bd.ENV / rel if stage_of_doc == 0 else stage_update(stage_of_doc) / "new_docs" / rel


def where(rel):
    """The stage a doc was added in (0 for the base corpus)."""
    if (bd.ENV / rel).exists():
        return 0
    for n in STAGES:
        if (stage_update(n) / "new_docs" / rel).exists():
            return n
    return None


def check_edit(raw, patch, phrases, banned, labels):
    """The doc after the patch: still valid JSON, one change, and no background problem it did not have."""
    find_e, rep_e = json.dumps(patch["find"])[1:-1], json.dumps(patch["replace"])[1:-1]
    if raw.count(find_e) != 1:
        return "find text not exactly once"
    new_raw = raw.replace(find_e, rep_e)
    try:
        old, new = json.loads(raw), json.loads(new_raw)
    except ValueError:
        return "not valid JSON after the patch"
    if isinstance(old.get("messages"), list):
        om, nm = old["messages"], new["messages"]
        if len(nm) != len(om):
            return "changes the number of messages"
        for a, b in zip(om, nm):
            if isinstance(a, str) and a != b:
                pa = message_prefix(a)
                if pa is None or b[:pa] != a[:pa]:
                    return "changes a message's speaker or time"
    before = set(bd.bg_problems(old, phrases, banned))
    after = set(bd.bg_problems(new, phrases, banned))
    if after - before:
        return f"new background problem: {sorted(after - before)[:2]}"
    added = patch["replace"]
    if [l for l in labels if bl.label_re(l).search(added)] != [l for l in labels if bl.label_re(l).search(patch["find"])]:
        return "adds or drops a ticket label"
    if patch["what"].split(":")[0] in ("wording", "add", "number_phrase") and bl.RULE_WORDS.search(added) \
            and not bl.RULE_WORDS.search(patch["find"]):
        return "adds rule wording"
    return None


def edits_job(only_stage=None):
    p = frozen_plan()
    EDITS_DIR.mkdir(parents=True, exist_ok=True)
    phrases, banned = cd.rule_phrases(), bd.banned_words()
    labels = list(bl.labels_by_stage())
    for n, s in sorted(p.items()):
        if only_stage and n != only_stage:
            continue
        out_f = EDITS_DIR / f"stage{n}.json"
        done = load(out_f) if out_f.exists() else {}
        rng = random.Random(1000 + n)
        made = collections.Counter()
        for e in s["edits"]:
            rel, kind = e["rel"], e["kind"]
            if rel in done and done[rel].get("ok"):
                made[done[rel]["kind"]] += 1
                continue
            src = where(rel)
            if src is None:  # renamed or gone since the plan was frozen (e.g. shorten_background_names.py's renames)
                done[rel] = {"ok": False, "kind": kind, "note": "doc no longer exists"}
                out_f.write_text(json.dumps(done, indent=1, sort_keys=True) + "\n")
                continue
            raw = doc_path(src, rel).read_text()
            doc = json.loads(raw)
            r = random.Random(f"{n}|{rel}")
            patch = None
            tried = [kind] + [k for k in ("number", "dollar", "wording") if k != kind]
            makers = {"number": lambda: number_edit(doc, raw, "number", r), "dollar": lambda: number_edit(doc, raw, "dollar", r),
                      "wording": lambda: wording_edit(doc, raw, r, phrases, banned),
                      "wording_big": lambda: wording_edit(doc, raw, r, phrases, banned, big=True),
                      "add": lambda: add_edit(doc, raw, r, phrases, banned),
                      "number_phrase": lambda: number_phrase_edit(doc, raw, r, phrases, banned)}
            note = ""
            for k in tried:
                try:
                    patch = makers[k]()
                except Exception as exc:  # a model error: the next kind, or the next run
                    patch, note = None, f"error: {exc}"[:200]
                if patch:
                    problem = check_edit(raw, patch, phrases, banned, labels)
                    if problem:
                        note, patch = problem, None
                        continue
                    patch["kind"] = k
                    break
            done[rel] = ({"ok": True, "doc": "docs/" + rel, **patch} if patch else {"ok": False, "kind": kind, "note": note or "no editable spot"})
            if patch:
                made[patch["kind"]] += 1
            out_f.write_text(json.dumps(done, indent=1, sort_keys=True) + "\n")
        bad = sum(not v["ok"] for v in done.values())
        print(f"stage {n}: {sum(v['ok'] for v in done.values())} edits ready, {bad} failed; kinds {dict(made)}")


def frozen_plan():
    """The plan as written by --plan: every later step uses this file, never a fresh plan (a fresh plan would see
    the docs this job already changed and pick others)."""
    if not PLAN.exists():
        sys.exit(f"no {PLAN}: run --plan first")
    return {int(k): v for k, v in load(PLAN).items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true", help="make the plan and freeze it (refuses if one exists)")
    ap.add_argument("--replan", action="store_true", help="make the plan again, replacing the frozen one")
    ap.add_argument("--report", action="store_true", help="the frozen plan's numbers")
    ap.add_argument("--edits", action="store_true", help="write the edits into docs_build/blend/churn/edits/ (staged)")
    ap.add_argument("--stage", type=int)
    ap.add_argument("--removals", action="store_true", help="pick each stage's removed docs (no model calls)")
    a = ap.parse_args()
    if a.report:
        return report(frozen_plan())
    if a.edits:
        return edits_job(a.stage)
    if a.removals:
        return removals_job()
    if PLAN.exists() and not a.replan:
        sys.exit(f"{PLAN} exists (frozen); --replan to replace it, --report to see it")
    p = plan(random.Random(2026))
    report(p)
    PLAN.parent.mkdir(parents=True, exist_ok=True)
    PLAN.write_text(json.dumps(p, indent=1) + "\n")
    print(f"plan frozen in {PLAN}")


if __name__ == "__main__":
    main()
