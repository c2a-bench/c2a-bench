"""Third blending round (external review 3): three jobs, staged first, then applied to the docs they change only.

    python3 blend_round3.py --job longer|speakers|credit|all [--limit N] [--workers 32]
    python3 blend_round3.py --apply

longer    rule threads whose messages are much shorter than their folder's: the added talk between the planned
          messages is rewritten into fewer, longer messages. Planned messages, patched passages and the first message
          stay byte for byte; the thread keeps about its length, form and people.
speakers  the #refunds-desk threads round 2 rewrote with people the thread did not have: rewritten again from their
          round-1 version with only its own people.
credit    "travel credit" in about 200 more background docs, said in passing (a field in a tool, a training topic, a
          customer asking where it shows), deciding nothing; rule docs say it 13 times as often as the background.
Staged in docs_build/blend/round3/, results in docs_build/blend/round3.json.
"""
import argparse
import collections
import concurrent.futures as cf
import hashlib
import json
import random
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import blend_docs as bd  # noqa: E402
import check_docs as cd  # noqa: E402

OUT = bd.OUT / "round3"
RESULTS = bd.OUT / "round3.json"
CREDIT = 200


def load_results():
    return json.loads(RESULTS.read_text()) if RESULTS.exists() else {}


def patch_finds():
    out = collections.defaultdict(list)
    for n in range(1, 6):
        for c in bd.load(bd.ROOT / f"steps/stage{n}/workdir/stage{n}_update/changes.json")["changes"]:
            for p in c.get("patches", []):
                out[p["doc"].removeprefix("docs/")].append(p["find"])
    return out


def split_msg(m):
    """(format, name, stamp or None, text) of a message, or None."""
    k = bd.msg_format(m)
    if not k:
        return None
    g = bd.FORMAT_RE[k].match(m)
    name = g.group(2) if k == "datefirst" else g.group(1)
    st = bd.stamp_of(m)
    return k, name, st[1] if st else None, m[g.end():]


def longer(item, corpus, phrases, banned, rng):
    n, rel = item["stage"], item["rel"]
    doc = bd.load(bd.stage_path(n, rel)[0])
    m = item["manifest"]
    msgs = doc["messages"]
    parts = [split_msg(x) for x in msgs]
    if any(p is None for p in parts) or len({p[0] for p in parts}) != 1:
        return None, "mixed or unknown message form"
    k = parts[0][0]
    keep_text = [cd.norm(x).rstrip(".") for x in m["must_contain"]] + [cd.norm(x) for x in item["finds"]]
    fixed = {i for i, x in enumerate(msgs) if any(t in cd.norm(x) for t in keep_text)} | {0}
    names = [p for p in dict.fromkeys(p[1] for p in parts)]
    want_len = int(item["msg_len"])
    listing = "\n".join(f"[{i}]{' FIXED' if i in fixed else ''} {p[1]}: {p[3]}" for i, p in enumerate(parts))
    feedback = ""
    for _ in range(2):
        res = bd.ask(bd.SYSTEM, f"""A Slack thread, numbered. Messages marked FIXED must stay exactly as they are and in this order.
Rewrite the other messages into fewer, longer ones: people in this channel write full messages of about {want_len}
characters (a few sentences each), not quick one-liners. Keep the same conversation, facts and speakers ({', '.join(names)});
keep each FIXED message's question or lead-in before it. The whole thread should be about {int(max(len(cd.text_of(msgs)), min(1.1 * corpus.median_len(bd.folder_of(rel)), 2 * len(cd.text_of(msgs)))))} characters.
{bd.NO_DECIDING}
Thread:
{listing}
Answer as {{"thread": [{{"fixed": <number>}} or {{"speaker": "...", "text": "..."}}, ...]}} covering the whole thread in order.{feedback}""",
                     f"round3:longer:{rel}")
        seq = res.get("thread", [])
        used = [x["fixed"] for x in seq if isinstance(x.get("fixed"), int)]
        if used != sorted(fixed):
            feedback = f"\nInclude every FIXED message exactly once, in order: {sorted(fixed)}."
            continue
        out, last = [], parts[0][2]
        for j, x in enumerate(seq):
            if isinstance(x.get("fixed"), int):
                out.append(msgs[x["fixed"]])
                last = parts[x["fixed"]][2] or last
                continue
            if x.get("speaker") not in names or not x.get("text"):
                continue
            nxt = next((parts[y["fixed"]][2] for y in seq[j + 1:] if isinstance(y.get("fixed"), int)), None)
            t = None
            if last is not None:
                t = last + bd.timedelta(minutes=1)
                if nxt is not None and t > nxt:
                    t = last
                last = t
            out.append(bd.FORMATS[k][1](x["speaker"], t) + bd.clean(x["text"]))
        new = dict(doc)
        new["messages"] = out
        probs = bd.planned_problems(new, m, banned)
        probs += [f"a later stage's patch no longer finds {f!r}" for f in item["finds"] if f not in cd.text_of(new)]
        med = statistics.median(len(x) for x in out)
        if med < want_len * 0.8:
            probs.append(f"messages still short (median {int(med)} characters, want about {want_len})")
        total, before = len(cd.text_of(out)), len(cd.text_of(msgs))
        most = max(1.25 * before, 1.15 * corpus.median_len(bd.folder_of(rel)))  # a short thread may grow to its folder's size
        if not 0.75 * before <= total <= most:
            probs.append(f"thread length {total} characters, was {before} (at most {int(most)})")
        if not probs:
            return new, f"{len(msgs)} -> {len(out)} messages, median {int(med)} characters"
        feedback = "\nA first try had these problems; fix them: " + "; ".join(probs)
    return None, "; ".join(probs)


def speakers(item, corpus, phrases, banned, rng):
    """refunds() from round 2 with the thread's own people only, from its round-1 version."""
    rel = item["rel"]
    doc = bd.load(bd.STAGED / "0" / rel)  # the round-1 thread
    msgs = doc["messages"]
    st = bd.stamp_of(msgs[0])
    if not st:
        return None, "unknown message format"
    want = item["count"]
    names = [p for p in doc.get("participants") or [] if re.fullmatch(bd.NAME, str(p))]
    words = len(cd.text_of(msgs).split())
    amt = [x.group(0) for x in cd.MONEY.finditer(cd.text_of(msgs))]
    current = bd.load(bd.ENV / rel)
    feedback = ""
    for _ in range(3):
        res = bd.ask(bd.SYSTEM, f"""Rewrite this #refunds-desk Slack thread as {want} messages (shorter ones, the way
people really chat: quick replies, follow-ups, small asides), about {words} words in all. Keep the same case, people
and facts{'; keep ' + ', '.join(amt) + ' written exactly so' if amt else ''}. Speakers: only {', '.join(names)}.
{bd.NO_DECIDING}
Thread:
{chr(10).join(msgs)[:6000]}
Answer as {{"messages": [{{"speaker": "...", "text": "..."}}]}}.{feedback}""", f"round3:speakers:{rel}")
        turns = [(x["speaker"], bd.clean(x["text"])) for x in res.get("messages", []) if x.get("speaker") in names and x.get("text")]
        k = bd.msg_format(current["messages"][0]) or st[0]  # the form the thread has now (shapes() may have changed it)
        new = dict(current)
        new["messages"] = bd.thread(turns, k, bd.datetime.fromisoformat(current["created_at"][:16]), rng)
        new["participants"] = [p for p in names if p in {s for s, _ in turns}]
        new["created_at"] = bd.match_clock(new) or new["created_at"]
        probs = bd.bg_problems(new, phrases, banned)
        if abs(len(turns) - want) > max(2, want // 4):
            probs.append(f"{len(turns)} messages, not {want}")
        if any(a not in cd.text_of(new) for a in amt):
            probs.append(f"lost the amount {amt}")
        if set(new["participants"]) - set(names):
            probs.append("a speaker who was not in the thread")
        if not probs:
            return new, f"refunds thread with its own people, {len(turns)} messages"
        feedback = "\nA first try had these problems; avoid them: " + "; ".join(probs)
    return None, "; ".join(probs)


def in_order(msgs):
    """A new message's time no later than the next message's (money() adds 1-4 minutes to the one before)."""
    out = list(msgs)
    for i in range(1, len(out) - 1):
        a, b, c = (bd.stamp_of(x) for x in out[i - 1:i + 2])
        if a and b and c and b[1] > c[1] and a[1] <= c[1]:
            g = bd.FORMAT_RE[b[0]].match(out[i])
            name = g.group(2) if b[0] == "datefirst" else g.group(1)
            out[i] = bd.FORMATS[b[0]][1](name, a[1].replace(year=b[1].year, month=b[1].month, day=b[1].day)
                                         if b[1].year == 2000 else a[1]) + out[i][g.end():]
    return out


def credit(item, corpus, phrases, banned, rng):
    doc, note = bd.money({"rel": item["rel"], "kind": "credit"}, corpus, phrases, banned, rng)
    if doc and isinstance(doc.get("messages"), list):
        doc["messages"] = in_order(doc["messages"])
    return doc, note


def plan(corpus, rng):
    items = []
    finds = patch_finds()
    habit = {}
    made = set()
    done1 = bd.load(bd.OUT / "results.json")
    done2 = bd.load(bd.OUT / "round2.json")
    made |= {e["rel"] for e in list(done1.values()) + list(done2.values())}
    for f, docs in corpus.bg.items():
        lens = [statistics.median(len(x) for x in d["messages"]) for r, d in docs if r not in made
                and isinstance(d.get("messages"), list) and d["messages"] and all(isinstance(x, str) for x in d["messages"])]
        if lens:
            habit[f] = statistics.median(lens)
    for n, rel, m in bd.planned_docs():
        path = bd.stage_path(n, rel)[0]
        if not rel.startswith("slack/") or not path.exists() or bd.folder_of(rel) not in habit:
            continue
        doc = bd.load(path)
        msgs = doc.get("messages")
        if not isinstance(msgs, list) or not msgs or m.get("trap") and len(msgs) < 3:
            continue
        if statistics.median(len(x) for x in msgs) < habit[bd.folder_of(rel)] * 0.8:
            items.append({"job": "longer", "key": f"longer/{n}/{rel}", "stage": n, "rel": rel, "manifest": m,
                          "finds": finds.get(rel, []), "msg_len": habit[bd.folder_of(rel)]})
    counts = [len(d["messages"]) for r, d in corpus.bg["slack/refunds-desk"] if r not in made and isinstance(d.get("messages"), list)]
    for k, e in sorted(done2.items()):
        if e.get("job") != "refunds" or not (bd.STAGED / "0" / e["rel"]).exists():
            continue
        before = set(bd.load(bd.STAGED / "0" / e["rel"]).get("participants") or [])
        now = set(bd.load(bd.ENV / e["rel"]).get("participants") or [])
        if now - before:
            items.append({"job": "speakers", "key": f"speakers/{e['rel']}", "stage": 0, "rel": e["rel"],
                          "count": max(6, min(30, rng.choice(counts)))})
    planned = {rel for _, rel, _ in bd.planned_docs()}
    touched = made | planned | bd.referenced()
    pool = sorted(rel for f, docs in corpus.bg.items() for rel, d in docs if rel not in touched
                  and "travel credit" not in json.dumps(d).lower()
                  and (d.get("source_system") != "slack" or (isinstance(d.get("messages"), list) and d["messages"]
                                                            and isinstance(d["messages"][0], str)
                                                            and bd.stamp_of(d["messages"][0]))))
    for rel in rng.sample(pool, CREDIT):
        items.append({"job": "credit", "key": f"credit/{rel}", "stage": 0, "rel": rel})
    return items


def apply():
    done = load_results()
    for key, e in sorted(done.items()):
        text = (OUT / str(e["stage"]) / e["rel"]).read_text()
        for p in bd.stage_path(e["stage"], e["rel"]):
            p.write_text(text)
    print(f"applied {len(done)} docs: {dict(collections.Counter(e['job'] for e in done.values()))}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", choices=["longer", "speakers", "credit", "all"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=32)
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if args.apply:
        return apply()
    corpus = bd.Corpus()
    items = plan(corpus, random.Random(2028))
    if args.plan:
        print(dict(collections.Counter(i["job"] for i in items)))
        return
    done = load_results()
    todo = [i for i in items if args.job in ("all", i["job"]) and i["key"] not in done]
    if args.limit:
        todo = todo[:args.limit]
    phrases, banned = cd.rule_phrases(), bd.banned_words()
    fns = {"longer": longer, "speakers": speakers, "credit": credit}

    def run(item):
        rng = random.Random(int(hashlib.md5(item["key"].encode()).hexdigest()[:8], 16))
        try:
            return item, *fns[item["job"]](item, corpus, phrases, banned, rng)
        except Exception as e:  # noqa: BLE001 - one bad answer must not stop the run
            return item, None, f"error: {type(e).__name__}: {e}"[:300]

    failed = []
    with cf.ThreadPoolExecutor(args.workers) as ex:
        for item, doc, note in ex.map(run, todo):
            if doc is None:
                failed.append((item["key"], note))
                continue
            bd.write_doc(OUT / str(item["stage"]) / item["rel"], doc)
            done[item["key"]] = {"stage": item["stage"], "rel": item["rel"], "job": item["job"], "note": note}
    RESULTS.write_text(json.dumps(done, indent=1, sort_keys=True) + "\n")
    print(f"staged {len(todo) - len(failed)}/{len(todo)}; all staged: {len(done)}/{len(items)}")
    for key, note in failed:
        print("  FAILED", key, "-", note[:200])


if __name__ == "__main__":
    main()
