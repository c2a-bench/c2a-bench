"""Second blending round (external review): three jobs on top of blend_docs.py, staged first, then applied.

    python3 blend_round2.py --job limits|invoice|refunds|topup|all [--limit N] [--workers 32]
    python3 blend_round2.py --apply      # writes staged docs into the env, the generator's sources and the stage folders

limits   150 background docs get one line where a team budget or card has a dollar limit ("capped at $500 a month"),
         so a "$" in a limiting sentence is not only in rule docs. Nothing in it is about a customer (policy_money).
invoice  the money lines that all said "headsets, the printer lease, a label printer repair" are rewritten into
         varied everyday contexts, same amount.
refunds  the 150 new #refunds-desk threads are rewritten into as many messages as the channel's own threads have
         (median 16, not 9), keeping their case and any amount.
topup    each stage update gets ordinary docs until rule docs are a third of its new docs or less; folders and
         lengths follow the stage 0 background, dates fall in the stage's window.
Staged in docs_build/blend/round2/, results in docs_build/blend/round2.json. No stage 0 doc is added or removed.
"""
import argparse
import collections
import concurrent.futures as cf
import hashlib
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import blend_docs as bd  # noqa: E402
import check_docs as cd  # noqa: E402

OUT = bd.OUT / "round2"
RESULTS = bd.OUT / "round2.json"
RULE_SHARE = 1 / 3  # rule docs at most this share of a stage update's new docs

LIMITS = [
    "the monthly limit on the team's corporate card",
    "the most a team lead can approve for office supplies without finance sign-off",
    "the quarterly cap on the shared software and tooling budget",
    "the limit for a single purchase on the equipment card",
    "the approval threshold for a vendor invoice before it needs a second signature",
    "the per-person cap on conference registration for the training budget",
    "the quarterly ceiling on the printing and courier contract",
    "the most the desk can spend on replacement headsets in a quarter without a purchase order",
    "the cap on the team's offsite venue booking",
    "the spending limit on the shared taxi account for late-shift staff",
    "the maximum for a petty cash withdrawal at the station office",
    "the upper limit on a single training course an agent can book without a manager's sign-off",
]
EVERYDAY = [
    "a vendor quote for new monitor arms for the desk",
    "the renewal cost of the screen-recording tool the trainers use",
    "an invoice for the call recording storage overage last month",
    "the cost of the courier who took the signed forms to the finance office",
    "the bill for the conference room AV repair",
    "the price of the replacement badge printer ribbons",
    "the catering invoice for the quarterly all-hands",
    "the annual fee for the translation glossary subscription",
    "a parking reimbursement form for a trainer who drove in for the workshop",
    "the cost of the ergonomic chairs ordered for the night shift",
    "the license true-up for the knowledge base editor seats",
    "the deposit for next quarter's training room booking",
]
LIMIT_WORDS = re.compile(r"(?i)\b(up to|cap(?:ped)?|limit|maximum|max|ceiling|threshold|approv\w*)\b")


def load_results():
    return json.loads(RESULTS.read_text()) if RESULTS.exists() else {}


def amount(rng):
    if rng.random() < 0.4:  # a rule's amount may appear in a team budget; it says nothing about customers
        pick = sorted(a for a in cd.rule_amounts() if re.fullmatch(r"\$\d[\d,]*", a))
        if pick:
            return rng.choice(pick)
    v = rng.choice([100, 150, 200, 250, 300, 400, 500, 600, 750, 1000, 1500, 2000, 2500, 5000])
    return f"${v:,}"


# ---------- jobs ----------

def add_line(doc, ask_for, rel, rng, feedback):
    """doc with one new message (Slack) or sentence/item (page) that does what ask_for says."""
    new = json.loads(json.dumps(doc))
    if doc.get("source_system") == "slack":
        msgs = doc["messages"]
        k = bd.msg_format(msgs[0])
        where = rng.randint(1, len(msgs))
        prev = msgs[where - 1]
        st = bd.stamp_of(prev)
        if not k or not st:
            return None
        names = [p for p in doc.get("participants") or [] if re.fullmatch(bd.NAME, str(p))]
        res = bd.ask(bd.SYSTEM, f"""A Slack thread so far:
{chr(10).join(msgs[max(0, where - 5):where])}

Write ONE more message that fits right here and naturally {ask_for}
Speaker: one of {', '.join(names)}.
Answer as {{"speaker": "...", "text": "..."}}.{feedback}""", f"round2:{rel}")
        if res.get("speaker") not in names or not res.get("text"):
            return None
        t = st[1] + bd.timedelta(minutes=rng.randint(1, 4))
        if t.date() != st[1].date():
            return None
        new["messages"] = msgs[:where] + [bd.FORMATS[st[0]][1](res["speaker"], t) + bd.clean(res["text"])] + msgs[where:]
    else:
        fields = [f for f in doc["content_field_names"] if isinstance(doc.get(f), (list, str))]
        f = rng.choice(fields)
        val = doc[f]
        res = bd.ask(bd.SYSTEM, f"""A section "{f}" of the Confluence page "{doc['title']}":
{json.dumps(val)[:1500]}

Write ONE more {'item' if isinstance(val, list) else 'sentence'} for it that fits and naturally {ask_for}
Answer as {{"text": "..."}}.{feedback}""", f"round2:{rel}")
        text = (res.get("text") or "").strip()
        if not text:
            return None
        new[f] = val + [text] if isinstance(val, list) else val.rstrip() + (" " if not val.endswith("\n") else "") + text
    return new


NOT_CUSTOMER = ("It is about the team's own spending, not about customers: do not use the words customer, passenger, "
                "traveller, guest, member, credit, refund, reimburse, compensation, voucher, goodwill, hotel, meal or "
                "bag, and do not mention flights, delays or cancellations. No percentages, hours or days figures.")


def limits(item, corpus, phrases, banned, rng):
    rel = item["rel"]
    doc = bd.load(bd.SOURCES / rel)
    amt = amount(rng)
    ask_for = (f"says, in one sentence with the word \"limit\", \"cap\", \"up to\" or \"maximum\", that {amt} is "
               f"{rng.choice(LIMITS)}. Write the amount exactly as {amt}. {NOT_CUSTOMER}")
    feedback = ""
    for _ in range(3):
        new = add_line(doc, ask_for, rel, rng, feedback)
        if new is None:
            feedback = "\nUse one of the listed speakers."
            continue
        body = cd.text_of(new)
        probs = bd.bg_problems(new, phrases, banned)
        if not any(LIMIT_WORDS.search(cd.sentence_at(body, m.start())) for m in cd.MONEY.finditer(body)
                   if cd.norm(m.group(0)).rstrip(",.;:") == cd.norm(amt)):
            probs.append(f"{amt} is not in the same sentence as limit, cap, up to or maximum")
        if not probs:
            return new, f"limit {amt}"
        feedback = "\nA first try had these problems; avoid them: " + "; ".join(probs)
    return None, "; ".join(probs)


def invoice(item, corpus, phrases, banned, rng):
    rel = item["rel"]
    doc = bd.load(bd.ENV / rel)
    ctx = rng.choice(EVERYDAY)
    feedback = ""
    for _ in range(3):
        new = json.loads(json.dumps(doc))
        hit = None
        for f in new["content_field_names"]:
            val = new[f]
            units = val if isinstance(val, list) else re.split(r"(?<=[.!?])\s+", val)
            for u in units:
                if isinstance(u, str) and "label printer" in u and cd.MONEY.search(u):
                    hit = (f, u)
                    break
            if hit:
                break
        if not hit:
            return None, "no invoice line found"
        f, unit = hit
        amt = cd.MONEY.search(unit)
        if not amt:
            return None, "no amount in the invoice line"
        st = bd.stamp_of(unit) if new.get("source_system") == "slack" else None
        prefix = unit[:bd.FORMAT_RE[st[0]].match(unit).end()] if st else ""
        res = bd.ask(bd.SYSTEM, f"""Rewrite this line so the {amt.group(0)} is {ctx} instead. Keep its tone, keep the
amount written exactly as {amt.group(0)}, keep anything else the line says, and do not mention headsets, a printer
lease or a label printer. {bd.NO_DECIDING}
Line: {unit[len(prefix):]}
Answer as {{"text": "..."}}.{feedback}""", f"round2:{rel}")
        text = bd.clean(res.get("text") or "") if prefix else (res.get("text") or "").strip()
        if not text:
            continue
        if isinstance(new[f], list):
            new[f] = [prefix + text if u == unit else u for u in new[f]]
        else:
            new[f] = new[f].replace(unit, text, 1)
        probs = bd.bg_problems(new, phrases, banned)
        if amt.group(0) not in cd.text_of(new):
            probs.append(f"does not keep {amt.group(0)}")
        if "label printer" in cd.text_of(new):
            probs.append("still mentions the label printer")
        if not probs:
            return new, f"invoice -> {ctx[:40]}"
        feedback = "\nA first try had these problems; avoid them: " + "; ".join(probs)
    return None, "; ".join(probs)


def refunds(item, corpus, phrases, banned, rng):
    rel = item["rel"]
    doc = bd.load(bd.ENV / rel)
    msgs = doc["messages"]
    st = bd.stamp_of(msgs[0])
    if not st:
        return None, "unknown message format"
    want = item["count"]
    names = [p for p in doc.get("participants") or [] if re.fullmatch(bd.NAME, str(p))]
    extra = [p for p in corpus.roster("slack/refunds-desk")[:12] if p not in names]
    rng.shuffle(extra)
    speakers = names + extra[:max(0, rng.randint(3, 6) - len(names))]
    words = len(cd.text_of(msgs).split())
    amt = [m.group(0) for m in cd.MONEY.finditer(cd.text_of(msgs))]
    feedback = ""
    for _ in range(3):
        res = bd.ask(bd.SYSTEM, f"""Rewrite this #refunds-desk Slack thread as {want} messages (shorter ones, the way
people really chat: quick replies, follow-ups, small asides), about {words} words in all. Keep the same case, people
and facts{'; keep ' + ', '.join(amt) + ' written exactly so' if amt else ''}. Speakers: {', '.join(speakers)}.
{bd.NO_DECIDING}
Thread:
{chr(10).join(msgs)[:6000]}
Answer as {{"messages": [{{"speaker": "...", "text": "..."}}]}}.{feedback}""", f"round2:{rel}")
        turns = [(m["speaker"], bd.clean(m["text"])) for m in res.get("messages", [])
                 if m.get("speaker") in speakers and m.get("text")]
        new = dict(doc)
        new["messages"] = bd.thread(turns, st[0], bd.datetime.fromisoformat(doc["created_at"][:16]), rng)
        new["participants"] = list(dict.fromkeys(s for s, _ in turns))
        new["created_at"] = bd.match_clock(new) or new["created_at"]
        probs = bd.bg_problems(new, phrases, banned)
        if abs(len(turns) - want) > max(2, want // 4):
            probs.append(f"{len(turns)} messages, not {want}")
        if any(a not in cd.text_of(new) for a in amt):
            probs.append(f"lost the amount {amt}")
        if not probs:
            return new, f"refunds thread, {len(msgs)} -> {len(turns)} messages"
        feedback = "\nA first try had these problems; avoid them: " + "; ".join(probs)
    return None, "; ".join(probs)


def topup(item, corpus, phrases, banned, rng):
    folder, n = item["folder"], item["stage"]
    seed_rel, seed = rng.choice(corpus.bg[folder])
    brief = (f"It is an everyday {folder.split('/')[1]} matter of the same kind as \"{seed.get('title', '')}\" but a "
             f"different case with different details.")
    words = int(rng.choice(corpus.lengths(folder)) / 7)
    feedback = ""
    for _ in range(3):
        day = bd.random_day(n, rng)
        if seed.get("source_system") == "slack":
            title, content, people, ca = bd.make_thread(folder, day, rng, corpus, brief, max(150, words), feedback)
            doc = bd.new_doc(folder, day, rng, corpus, content, title, people, ca)
        else:
            title, content = bd.make_page(folder, day, rng, corpus, brief, max(150, words), feedback)
            doc = bd.new_doc(folder, day, rng, corpus, content, title)
        probs = bd.bg_problems(doc, phrases, banned)
        if not cd.text_of(content).strip():
            probs.append("empty")
        if not probs:
            rel = bd.free_name(seed_rel.rsplit("/", 1)[0], title, corpus)  # next to the doc it is like
            return (rel, doc), f"stage {n} top-up, {bd.body_len(doc)} characters"
        feedback = "\nA first try had these problems; avoid them: " + "; ".join(probs)
    return None, "; ".join(probs)


# ---------- plan ----------

def plan(corpus, rng):
    done = json.loads((bd.OUT / "results.json").read_text())
    planned = {rel for _, rel, _ in bd.planned_docs()}
    touched = {e["rel"] for e in done.values()} | planned | bd.referenced()
    items = []
    folders = ["slack/support-team", "slack/support-escalations", "slack/support-policy-questions", "slack/baggage-desk",
               "slack/irregular-ops", "slack/loyalty-team", "slack/airport-ops", "slack/finance-ops",
               "slack/digital-team", "confluence/support-playbooks", "confluence/customer-policies",
               "confluence/airport-operations"]
    pool = sorted(rel for f in folders for rel, d in corpus.bg.get(f, []) if rel not in touched
                  and (d.get("source_system") != "slack" or (isinstance(d.get("messages"), list) and d["messages"]
                                                            and bd.stamp_of(d["messages"][0]))))
    for rel in rng.sample(pool, 150):
        items.append({"job": "limits", "key": f"limits/{rel}", "rel": rel, "stage": 0})
    for k, e in sorted(done.items()):  # only the lines the money job added; airport desks mention label printers anyway
        if k.startswith("money/") and "label printer" in (bd.ENV / e["rel"]).read_text():
            items.append({"job": "invoice", "key": f"invoice/{e['rel']}", "rel": e["rel"], "stage": 0})
    counts = [len(d["messages"]) for rel, d in corpus.bg["slack/refunds-desk"]
              if rel not in {e["rel"] for e in done.values() if e.get("new")} and isinstance(d.get("messages"), list)]
    for k, e in sorted(done.items()):
        if k.startswith("refunds/"):
            items.append({"job": "refunds", "key": f"refunds/{e['rel']}", "rel": e["rel"], "stage": 0,
                          "count": max(6, min(30, rng.choice(counts)))})
    sizes = collections.Counter(bd.folder_of(rel) for f, docs in corpus.bg.items() for rel, _ in docs)
    names = sorted(sizes)
    for n in range(1, 6):
        u = bd.ROOT / f"steps/stage{n}/workdir/stage{n}_update/new_docs"
        rules = len(json.loads((bd.ROOT / f"docs_build/stage{n}/manifest.json").read_text())["docs"])
        have = sum(1 for _ in u.rglob("*.json"))
        for i in range(max(0, round(rules / RULE_SHARE) - have)):
            folder = rng.choices(names, weights=[sizes[x] for x in names])[0]
            items.append({"job": "topup", "key": f"topup/{n}/{i}", "stage": n, "folder": folder})
    return items


# ---------- apply ----------

def apply():
    done = load_results()
    added = collections.defaultdict(list)
    for key, e in sorted(done.items()):
        n, rel = e["stage"], e["rel"]
        text = (OUT / str(n) / rel).read_text()
        for p in bd.stage_path(n, rel):
            if e["new"] and p.exists():
                sys.exit(f"{p} exists: a new doc would overwrite it")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        if e["new"]:
            added[n].append("sources/" + rel)
    for n in range(1, 6):
        f = bd.ROOT / f"steps/stage{n}/workdir/stage{n}_update/new_docs.txt"
        lines = f.read_text().splitlines()
        f.write_text("".join(x + "\n" for x in lines + [a for a in added[n] if a not in lines]))
    for k, e in done.items():
        e["applied"] = True
    RESULTS.write_text(json.dumps(done, indent=1, sort_keys=True) + "\n")
    print(f"applied {len(done)} docs; new: {', '.join(f'stage {n}: {len(v)}' for n, v in sorted(added.items()))}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", choices=["limits", "invoice", "refunds", "topup", "all"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=32)
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if args.apply:
        return apply()
    corpus = bd.Corpus()
    items = plan(corpus, random.Random(2027))
    if args.plan:
        print(dict(collections.Counter(i["job"] for i in items)),
              dict(collections.Counter(i["stage"] for i in items if i["job"] == "topup")))
        return
    done = load_results()
    corpus.taken |= {e["rel"] for e in done.values() if e["new"]}
    todo = [i for i in items if args.job in ("all", i["job"]) and i["key"] not in done]
    if args.limit:
        todo = todo[:args.limit]
    phrases, banned = cd.rule_phrases(), bd.banned_words()
    fns = {"limits": limits, "invoice": invoice, "refunds": refunds, "topup": topup}

    def run(item):
        rng = random.Random(int(hashlib.md5(item["key"].encode()).hexdigest()[:8], 16))
        try:
            return item, *fns[item["job"]](item, corpus, phrases, banned, rng)
        except Exception as e:  # noqa: BLE001 - one bad answer must not stop the run
            return item, None, f"error: {type(e).__name__}: {e}"[:300]

    failed = []
    with cf.ThreadPoolExecutor(args.workers) as ex:
        for k, (item, res, note) in enumerate(ex.map(run, todo), 1):
            if res is None:
                failed.append((item["key"], note))
                continue
            if item["job"] == "topup":
                rel, doc = res
                if rel is None:
                    failed.append((item["key"], "no free name"))
                    continue
                entry = {"stage": item["stage"], "rel": rel, "new": True}
            else:
                doc, entry = res, {"stage": 0, "rel": item["rel"], "new": False}
            bd.write_doc(OUT / str(entry["stage"]) / entry["rel"], doc)
            done[item["key"]] = {**entry, "job": item["job"], "note": note}
            if k % 20 == 0:
                RESULTS.write_text(json.dumps(done, indent=1, sort_keys=True) + "\n")
                print(f"  {k}/{len(todo)}", flush=True)
    RESULTS.write_text(json.dumps(done, indent=1, sort_keys=True) + "\n")
    print(f"staged {len(todo) - len(failed)}/{len(todo)}; all staged: {len(done)}/{len(items)}")
    for key, note in failed:
        print("  FAILED", key, "-", note[:200])


if __name__ == "__main__":
    main()
