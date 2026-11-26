"""Labels in the background: ordinary docs name the ticket labels, so grepping a label does not land on its rule doc.

    python3 blend_labels.py --plan                 # which docs get which label; no model calls
    python3 blend_labels.py --run [--limit N]      # write the lines (model calls) into docs_build/blend/labels/
    python3 blend_labels.py --apply                # write the staged docs into place (skyway-air and skyway-arch)

A review (point 4): every label was named in 0-4 docs, almost all of them its rule doc, so `grep claim-late`
found the rule without reading. Each label now goes into PER_LABEL ordinary docs: one new Slack message from someone
already in the thread, or one new line in a Confluence section, about the label as a thing in the ticket tool (a
filter, a report count, a tag added by mistake, an export), never about when, why or on which tickets it is used.
Stage-0 labels go into stage-0 background docs; a label a later stage adds (awaiting-receipts, assistance-failure)
goes into that stage's and later stages' new background docs, so it does not appear before it exists.

Skipped: planned (rule) docs of any stage, lookalikes, docs a stage patch edits, docs that already name a label, and
social, company-wide and HR folders (SKIP_FOLDERS).
Every line passes the checks blend_docs.py uses (check_docs.py's background rules: no rule sentence, no deciding
amount, no percentage or hours/days figure, no banned topic, nothing called outdated) plus its own: the label exactly
once, no other label, no rule wording (if, when, should, must, only, eligible, ...) and none of the label's topic
words, so it says nothing about the case. A failed line is asked again, up to three times.
Files keep the generator's layout (indent 2, ASCII escapes, no trailing newline). After --apply, run check_docs.py,
giveaway_audit.py, package_stages.py --replay and scripts/leak_check.py.
"""
import argparse
import collections
import concurrent.futures as cf
import json
import random
import re
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import blend_docs as bd
import erb_paths  # noqa: E402
import check_docs as cd  # noqa: E402
import build_stage0_tickets as b0  # noqa: E402

ROOT = bd.ROOT
ARCH = ROOT.parent / "skyway-arch"
OUT = bd.OUT / "labels"
PER_LABEL = 45
SPARE = 10      # extra docs planned per label; --apply uses the first PER_LABEL of them that passed
# more spares for a label whose lines kept failing, planned after the rest with their own seed (the plan above stays)
EXTRA = {"awaiting-receipts": 10}
PER_FOLDER = 4  # at most this many docs of one folder per label, so the mentions spread
STAGES = range(1, 6)
# channels and spaces where talk about the ticket tool would not fit (social, company-wide, HR)
SKIP_FOLDERS = {"slack/random", "slack/general", "slack/announcements", "confluence/company-handbook"}
LOCK = threading.Lock()

# what the line is about: the label as a thing in the ticket tool, never the case behind it
SEEDS = [
    "a ticket that was tagged {L} by mistake, and the tag was taken off",
    "this week's queue report and how many open tickets carry the {L} tag",
    "a saved view in the ticket tool that filters on the {L} tag",
    "an agent who could not find the {L} tag in the tag picker",
    "a dashboard tile that counts {L} tickets and showed a wrong number after last night's sync",
    "the weekly QA sample, which included one {L} ticket, and a remark about how its case notes were written",
    "an export for the data team that dropped the {L} column",
    "the {L} tag showing up twice in the tag list after the tool update",
    "renaming a saved search that lists {L} tickets",
    "whether {L} tickets are counted in the team's weekly volume chart",
    "a bulk edit that removed {L} from a few tickets by accident, and restoring it from the ticket history",
    "the tag list tidy-up meeting, where {L} was one of the tags kept as it is",
    "an automation alert that fired on a {L} ticket at night",
    "an analyst asking for last month's count of {L} tickets",
    "the colour the {L} tag got in the new interface",
    "a customer email that showed the internal tag {L} in its footer by mistake",
    "merging two duplicate tickets, one of which had the {L} tag",
    "tag autocomplete offering {L} while someone typed a different tag",
    "handover notes listing a few ticket numbers, one of them tagged {L}",
    "searching for {L} timing out in the ticket tool",
    "who can create new tags in the tool, versus who can apply existing ones such as {L}",
    "an audit log line showing {L} added and removed on the same ticket within a minute",
    "the training sandbox, where the {L} tag is missing and trainees asked about it",
    "the API sync to the reporting warehouse that lowercases tags, including {L}",
]
# a line must not read like a rule for its label
RULE_WORDS = re.compile(r"\b(if|when|whenever|unless|should|must|always|never|only|eligible|qualif\w*|entitled|"
                        r"policy|policies|rule|rules|require[sd]?|need(?:s|ed)? to|supposed to|correct(?:ly)?|"
                        r"wrong(?:ly)?|right one|means|because|so that)\b", re.I)
TOPIC = {  # the topic of each label's rule: none of it next to the label
    "agency-refund": r"agenc|travel agent|refund|money back",
    "receipts-needed": r"receipt|meal|hotel|expense|reimburs",
    "awaiting-receipts": r"receipt|meal|hotel|expense|reimburs",
    "claim-late": r"claim|deadline|late|days? after|window",
    "wear-and-tear": r"\bwear\b|wheel|handle|scuff|bag|luggage|suitcase|damage",
    "change-denied": r"basic|fare|change fee|rebook|moved? (?:the|a|my|their) flight|flight change",
    "not-authorized": r"authori[sz]|booking contact|on behalf|permission to act|friend|relative",
    "assistance-failure": r"assist|wheelchair|mobility|escort|special service",
}
NO_CASE = ("Do not say when, why or on which tickets the {L} tag is used, what kind of customer problem it is about, or "
           "what anyone did or should do for the customer. Write the tag exactly as {L}, once, in lowercase with its "
           "hyphens. Name no other ticket tag. Do not use the words if, when, should, must, only, always, never, "
           "rule or policy. Start the way the other messages start: no lead-in such as 'Separate note:', "
           "'Side note:', 'Heads-up:' or 'Dashboard note:'.")
# a lead-in that marks the line as off-topic for its thread ("Separate desk note: ...")
LEAD_IN = re.compile(r"^\W*(?:[\w-]+ ){0,3}(?:note|notes|heads-up|fyi|aside|update|ps)\b[^:.]{0,20}:", re.I)


def labels_by_stage():
    """{label: first stage}: stage 0's labels, then each later stage's new ones."""
    out = {l: 0 for l in b0.LABELS}
    for n in STAGES:
        for l in bd.load(ROOT / f"tests/stages/stage{n}/changes.json").get("labels", []):
            out.setdefault(l, n)
    return out


def label_re(label):
    return re.compile(rf"(?<![\w-]){re.escape(label)}(?![\w-])", re.I)


def any_label(text, labels):
    return [l for l in labels if label_re(l).search(text)]


def excluded():
    """Docs no line may go into: planned docs of any stage, lookalikes, docs any stage patch edits."""
    out = {rel for _, rel, _ in bd.planned_docs()} | set(bd.load(bd.OUT / "lookalikes.json"))
    for n in STAGES:
        f = ROOT / f"steps/stage{n}/workdir/stage{n}_update/changes.json"
        if f.exists():
            out |= {p["doc"].removeprefix("docs/") for c in bd.load(f)["changes"] for p in c.get("patches", [])}
        plan = ROOT / f"tests/stages/stage{n}/doc_plan.json"
        if plan.exists():
            out |= {d.removeprefix("docs/") for d in bd.load(plan)["docs"]}
    out |= {d.removeprefix("docs/") for d in bd.load(ROOT / "tests/doc_plan.json")["docs"]}
    return out


def pools(labels):
    """{stage: [(rel, path)]}: the background docs a line can go into, stage 0 from the environment, stage N from its
    update folder."""
    skip = excluded()
    out = {}
    for n in [0, *STAGES]:
        base = bd.ENV if n == 0 else ROOT / f"steps/stage{n}/workdir/stage{n}_update/new_docs"
        docs = []
        for f in sorted(base.rglob("*.json")):
            rel = str(f.relative_to(base))
            if rel in skip or bd.folder_of(rel) in SKIP_FOLDERS:
                continue
            doc = bd.load(f)
            if any_label(cd.text_of(doc), labels):
                continue
            if doc.get("source_system") == "slack":
                msgs = doc.get("messages")
                if not (isinstance(msgs, list) and msgs and bd.msg_format(msgs[0]) and doc.get("participants")):
                    continue
            elif not [k for k in doc.get("content_field_names", []) if isinstance(doc.get(k), (list, str))]:
                continue
            docs.append((rel, f))
        out[n] = docs
    return out


def used_ticket_ids():
    ids = set()
    for p in list(ROOT.glob("tests/**/cases.json")) + list(ROOT.glob("steps/**/cases.json")) + \
            [ROOT / "environment/app/examples/cases.json"]:
        ids |= set(re.findall(r"SKY-\d+", p.read_text()))
    return ids


def plan(rng):
    labels = labels_by_stage()
    pool = pools(list(labels))
    taken = set()
    used = used_ticket_ids()
    items = []
    for label, first in sorted(labels.items()):
        stages = [0] if first == 0 else [n for n in STAGES if n >= first]
        cands = [(n, rel, f) for n in stages for rel, f in pool[n] if (n, rel) not in taken]
        rng.shuffle(cands)
        per_folder = collections.Counter()
        chosen = []
        for n, rel, f in cands:
            if per_folder[bd.folder_of(rel)] >= PER_FOLDER:
                continue
            per_folder[bd.folder_of(rel)] += 1
            chosen.append((n, rel, f))
            if len(chosen) == PER_LABEL + SPARE:
                break
        for n, rel, f in chosen:
            taken.add((n, rel))
            while True:
                tid = f"SKY-{rng.randint(1200, 9899)}"
                if tid not in used:
                    used.add(tid)
                    break
            items.append({"key": f"{label}|{n}|{rel}", "label": label, "stage": n, "rel": rel, "path": str(f),
                          "seed": rng.choice(SEEDS).format(L=label), "ticket": tid, "rng": rng.randint(0, 10**9)})
    xr = random.Random(2027)
    for label, extra in sorted(EXTRA.items()):
        first = labels[label]
        stages = [0] if first == 0 else [n for n in STAGES if n >= first]
        cands = [(n, rel, f) for n in stages for rel, f in pool[n] if (n, rel) not in taken]
        xr.shuffle(cands)
        for n, rel, f in cands[:extra]:
            taken.add((n, rel))
            while True:
                tid = f"SKY-{xr.randint(1200, 9899)}"
                if tid not in used:
                    used.add(tid)
                    break
            items.append({"key": f"{label}|{n}|{rel}", "label": label, "stage": n, "rel": rel, "path": str(f),
                          "seed": xr.choice(SEEDS).format(L=label), "ticket": tid, "rng": xr.randint(0, 10**9)})
    return items


def added_text(old, new):
    """The text the line added (a new message, or what a field gained)."""
    if "messages" in old and isinstance(old["messages"], list):
        o = collections.Counter(old["messages"])
        out = []
        for m in new["messages"]:
            if o[m] > 0:
                o[m] -= 1
            else:
                out.append(m)
        return " ".join(out)
    parts = []
    for k in new.get("content_field_names", []):
        a, b = old.get(k), new.get(k)
        if a != b:
            if isinstance(b, list):
                parts += [x if isinstance(x, str) else json.dumps(x) for x in b[len(a):]]
            else:
                parts.append(str(b)[len(str(a)):])
    return " ".join(parts)


def line_problems(old, new, label, labels, phrases, banned):
    probs = bd.bg_problems(new, phrases, banned, strict_figures=True)
    text = added_text(old, new)
    if len(label_re(label).findall(text)) != 1:
        probs.append(f"the line must name {label} exactly once")
    others = [l for l in any_label(text, labels) if l != label]
    if others:
        probs.append(f"names another tag: {others}")
    rest = label_re(label).sub(" ", text)
    body = text
    for k, (r, _) in bd.FORMATS.items():  # the message without its speaker and time
        m = re.match(r, text)
        if m:
            body = text[m.end():]
            break
    if LEAD_IN.match(body):
        probs.append(f"starts with a lead-in: {body[:30]!r}")
    if RULE_WORDS.search(rest):
        probs.append(f"rule wording: {sorted(set(m.lower() for m in RULE_WORDS.findall(rest)))[:4]}")
    topic = re.findall(TOPIC.get(label, r"$^"), rest, re.I)
    if topic:
        probs.append(f"says what the tag is about: {sorted(set(t.lower() for t in topic))[:4]}")
    return probs, text


def write_line(item, labels, phrases, banned):
    rng = random.Random(item["rng"])
    doc = bd.load(item["path"])
    label = item["label"]
    ask_for = f"is about {item['seed']}. If a ticket number helps, use {item['ticket']}."
    rules = NO_CASE.format(L=label) + " " + bd.NO_DECIDING
    feedback, probs = "", []
    for _ in range(3):
        new = json.loads(json.dumps(doc))
        if doc.get("source_system") == "slack":
            msgs = doc["messages"]
            k = bd.msg_format(msgs[0])
            where = rng.randint(1, len(msgs))
            ctx = "\n".join(msgs[max(0, where - 5):where])
            names = list(doc.get("participants") or [])
            res = bd.ask(bd.SYSTEM, f"""A Slack thread so far:
{ctx}

Write ONE more message that fits right here and naturally {ask_for} {rules}
Speaker: one of {', '.join(names)}.
Answer as {{"speaker": "...", "text": "..."}}.{feedback}""", f"labels:{item['key']}")
            if res.get("speaker") not in names or not res.get("text"):
                feedback = "\nUse one of the listed speakers."
                continue
            prev = msgs[where - 1]
            m = re.search(r"\d{1,2}:\d\d(?: [AP]M)?", prev)
            if k in bd.NO_TIME or not m:
                stamp = datetime(2026, 1, 1, 9, 0)
            else:
                t = m.group(0)
                stamp = datetime.strptime(t, "%I:%M %p" if "M" in t else "%H:%M")
                dm = re.search(r"\d{4}-\d\d-\d\d", prev)
                if dm:
                    stamp = datetime.fromisoformat(dm.group(0)).replace(hour=stamp.hour, minute=stamp.minute)
            line = bd.FORMATS[k][1](res["speaker"], stamp + timedelta(minutes=rng.randint(1, 4))) + bd.clean(res["text"])
            new["messages"] = msgs[:where] + [line] + msgs[where:]
        else:
            fields = [f for f in doc["content_field_names"] if isinstance(doc.get(f), (list, str))]
            f = rng.choice(fields)
            val = doc[f]
            res = bd.ask(bd.SYSTEM, f"""A section "{f}" of the Confluence page "{doc['title']}":
{json.dumps(val)[:1500]}

Write ONE more {'item' if isinstance(val, list) else 'sentence'} for it that fits and naturally {ask_for} {rules}
Answer as {{"text": "..."}}.{feedback}""", f"labels:{item['key']}")
            text = bd.clean((res.get("text") or "").strip())
            if not text:
                feedback = "\nWrite the text."
                continue
            if isinstance(val, list):
                new[f] = val + [text]
            else:
                new[f] = val.rstrip() + ("\n\n" if "\n\n" in val else " ") + text
        probs, text = line_problems(doc, new, label, labels, phrases, banned)
        if not probs:
            return new, text
        feedback = "\nA first try had these problems; avoid them: " + "; ".join(probs)
    return None, "; ".join(probs)


def run(limit, workers):
    OUT.mkdir(parents=True, exist_ok=True)
    items = plan(random.Random(2026))
    done_path = OUT / "results.json"
    done = bd.load(done_path) if done_path.exists() else {}
    todo = [i for i in items if i["key"] not in done or not done[i["key"]]["ok"]]
    finished = len(items) - len(todo)
    if limit:
        todo = todo[:limit]
    labels = list(labels_by_stage())
    phrases, banned = cd.rule_phrases(), bd.banned_words()
    print(f"{len(items)} lines planned, {finished} done, writing {len(todo)}")

    def one(item):
        try:
            new, note = write_line(item, labels, phrases, banned)
        except Exception as exc:  # a model or parse error: try it again on the next --run
            new, note = None, f"error: {exc}"[:300]
        with LOCK:
            if new is not None:
                bd.write_doc(OUT / "staged" / str(item["stage"]) / item["rel"], new)
            done[item["key"]] = {"ok": new is not None, "stage": item["stage"], "rel": item["rel"],
                                 "label": item["label"], "line": note}
            done_path.write_text(json.dumps(done, indent=1, sort_keys=True) + "\n")
        return new is not None

    with cf.ThreadPoolExecutor(workers) as ex:
        ok = sum(ex.map(one, todo))
    bad = [k for k, v in done.items() if not v["ok"]]
    print(f"written {ok} of {len(todo)}; still failing {len(bad)}" + (f": {bad[:5]}" if bad else ""))


def targets(stage, rel):
    """Every copy of a doc: stage 0 in the generator's sources and both tasks' environments, stage N in both tasks'
    update folders."""
    arch = [ARCH] if ARCH.is_dir() else []  # a separate skyway-arch copy, when there is one
    if stage == 0:
        return [bd.SOURCES / rel, bd.ENV / rel, *(a / "environment/app/docs" / rel for a in arch)]
    sub = f"steps/stage{stage}/workdir/stage{stage}_update/new_docs"
    return [ROOT / sub / rel, *(a / sub / rel for a in arch)]


def apply():
    erb_paths.require_in_sync()  # the generator's copy must match the repo's docs (sync_erb_sources.py)
    done = bd.load(OUT / "results.json")
    n, per = 0, collections.Counter()
    for item in plan(random.Random(2026)):  # plan order: the first PER_LABEL that passed, per label
        v = done.get(item["key"])
        if not v or not v["ok"] or per[v["label"]] >= PER_LABEL:
            continue
        per[v["label"]] += 1
        staged = OUT / "staged" / str(v["stage"]) / v["rel"]
        text = staged.read_text()
        for t in targets(v["stage"], v["rel"]):
            if not t.exists():
                sys.exit(f"missing {t}")
            t.write_text(text)
        n += 1
    print(f"wrote {n} docs ({len(targets(0, 'x'))} copies each at stage 0, 2 later); per label: {dict(sorted(per.items()))}")
    short = {l: per[l] for l in labels_by_stage() if per[l] < PER_LABEL}
    if short:
        print(f"short of {PER_LABEL}: {short} (run --run again, or raise SPARE)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=16)
    a = ap.parse_args()
    if a.run:
        return run(a.limit, a.workers)
    if a.apply:
        return apply()
    items = plan(random.Random(2026))
    labels = labels_by_stage()
    print(f"{len(items)} lines: " + ", ".join(f"{l} (from stage {s}) {sum(i['label'] == l for i in items)}"
                                              for l, s in sorted(labels.items())))
    by = collections.Counter((i["label"], i["stage"]) for i in items)
    print("by stage:", dict(sorted(collections.Counter(i["stage"] for i in items).items())))
    folders = collections.Counter(bd.folder_of(i["rel"]) for i in items)
    print(f"{len(folders)} folders; most used:", folders.most_common(6))
    kinds = collections.Counter("slack" if "/slack/" in i["path"] or i["rel"].startswith("slack/") else "confluence"
                                for i in items)
    print("kinds:", dict(kinds))
    for i in items[:3]:
        print(" ", i["label"], i["stage"], i["rel"], "|", i["seed"], "|", i["ticket"])


if __name__ == "__main__":
    main()
