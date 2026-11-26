"""Make the planned rule docs hard to tell from the background, and the background less easy to skip.

    python3 blend_docs.py --plan                      # what each job will write; no model calls
    python3 blend_docs.py --job expand --limit 3      # generate a few into docs_build/blend/staged (model calls)
    python3 blend_docs.py --job all                   # generate everything not staged yet (resumable)
    python3 blend_docs.py --install                   # copy the staged docs into place, update the doc lists
    python3 blend_docs.py --trim [--apply]            # cut expanded rule docs back to their folder's usual size
    python3 blend_docs.py --planned [--apply]         # write planned docs not written yet (wrong and old versions)

Four jobs (a review, points 1 and 5, and our own giveaway audit):
  expand     every planned doc of every stage grows to about its folder's background length: Slack threads get more
             work talk before, between and after the planned messages, in a message format the folder's background
             uses; Confluence pages get more sections, and most become field-per-section pages like the background.
             The planned words stay as they are, so the stage patches and the checks still find them.
  lookalike  four docs per rule, in the folders of its real docs and the everyday support channels, that talk about its topic with its words but decide
             nothing (no amount, limit, deadline or who gets what). Dated in the stage the rule first appears.
  money      ordinary background docs get one line with a dollar amount that decides nothing (a fare paid, a vendor
             invoice, a card hold), or a mention of travel credit that decides nothing, so "$" and "travel credit"
             stop marking the rule docs.
  refunds    new background threads in #refunds-desk, where rule docs were 28% of the folder.
Every generated doc passes the same checks as check_docs.py before it is staged (a failed one is asked again, up to
three times). Files keep the generator's layout (indent 2, ASCII escapes, no trailing newline). After --install,
rerun package_stages.py and the checks.
"""
import argparse
import collections
import concurrent.futures as cf
import hashlib
import json
import os
import random
import re
import statistics
import sys
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_docs as cd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
import erb_paths  # noqa: E402
from erb_paths import SOURCES  # noqa: E402  (the generator's working copy)
ENV = ROOT / "environment/app/docs"
OUT = ROOT / "docs_build/blend"
STAGED = OUT / "staged"
WINDOWS = {0: ("2026-01-12", "2026-05-15"), 1: ("2026-05-26", "2026-06-30"), 2: ("2026-07-06", "2026-08-18"),
           3: ("2026-08-20", "2026-09-01"), 4: ("2026-09-08", "2026-11-03"), 5: ("2026-11-09", "2026-12-01")}
MODEL = os.environ.get("BLEND_MODEL", "gpt-5.6-terra")
LOOKALIKES = 4  # per rule
META = {"title", "author", "document_type", "owner_team", "status", "last_updated", "source_system", "channel",
        "created_at", "participants", "title_field_name", "content_field_names", "dataset_doc_uuid", "space"}
NAME = r"[A-Z][A-Za-z'\-]+(?: [A-Z][A-Za-z'\-]+){1,2}"
# message formats the background uses, each as (regex on a message, writer)
FORMATS = {
    "dash12": (rf"^({NAME}) — (\d{{1,2}}:\d\d [AP]M): ", lambda n, t: f"{n} — {t:%-I:%M %p}: "),
    "time24dash": (rf"^({NAME}) (\d\d:\d\d) — ", lambda n, t: f"{n} {t:%H:%M} — "),
    "datecolon": (rf"^({NAME}) (\d{{4}}-\d\d-\d\d \d\d:\d\d): ", lambda n, t: f"{n} {t:%Y-%m-%d %H:%M}: "),
    "dashdate": (rf"^({NAME}) — (\d{{4}}-\d\d-\d\d \d\d:\d\d): ", lambda n, t: f"{n} — {t:%Y-%m-%d %H:%M}: "),
    "time24colon": (rf"^({NAME}) (\d\d:\d\d): ", lambda n, t: f"{n} {t:%H:%M}: "),
    "datefirst": (rf"^(\d{{4}}-\d\d-\d\d \d\d:\d\d) ({NAME}): ", lambda n, t: f"{t:%Y-%m-%d %H:%M} {n}: "),
    # forms a third of the background threads use, which the expansion did not write (giveaway audit, review 3)
    "dash24colon": (rf"^({NAME}) — (\d\d:\d\d): ", lambda n, t: f"{n} — {t:%H:%M}: "),
    "paren24": (rf"^({NAME}) \((\d\d:\d\d)\): ", lambda n, t: f"{n} ({t:%H:%M}): "),
    "time24space": (rf"^({NAME}) (\d\d:\d\d) (?![—:-])", lambda n, t: f"{n} {t:%H:%M} "),
    "namecolon": (rf"^({NAME}): ", lambda n, t: f"{n}: "),
    "namedash": (rf"^({NAME}) — (?!\d)", lambda n, t: f"{n} — "),
}
NO_TIME = {"namecolon", "namedash"}
FORMAT_RE = {k: re.compile(r) for k, (r, _) in FORMATS.items()}
NO_DECIDING = ("Do not state any policy, amount, percentage, limit, deadline, number of hours or days, or who gets "
               "or does not get anything (refund, credit, compensation, hotel, meal, voucher, reimbursement). Do not "
               "show anyone giving, arranging, approving or refusing any of those. Do not mention weather, air traffic "
               "control or security as the cause of a disruption. Do not call anything outdated, old, replaced or "
               "draft, and do not tell people to see another page. Clock times and case numbers are fine.")
LOCK = threading.Lock()


def load(p):
    return json.loads(Path(p).read_text())


def write_doc(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2))


def folder_of(rel):
    return "/".join(rel.split("/")[:2])


def body_len(doc):
    return len(cd.text_of({k: doc.get(k) for k in doc.get("content_field_names", [])}))


def slug(title):
    words = re.sub(r"[^a-z0-9 ]+", " ", title.lower()).split()
    return "-".join(w for w in words if not w.isdigit())[:80].strip("-") or "notes"


# ---------- what the corpus looks like ----------

def planned_docs():
    """(stage, rel under docs/, manifest entry) for every planned doc."""
    out = []
    for n in range(6):
        for p, m in load(ROOT / f"docs_build/stage{n}/manifest.json")["docs"].items():
            out.append((n, p[len("sources/"):], m))
    return out


def stage_path(n, rel):
    """Where a stage's doc lives: stage 0 in the generator's sources (and the environment), later in its update."""
    if n == 0:
        return [SOURCES / rel, ENV / rel]
    return [ROOT / f"steps/stage{n}/workdir/stage{n}_update/new_docs" / rel]


class Corpus:
    def __init__(self):
        planned = {rel for _, rel, _ in planned_docs()}
        self.bg = collections.defaultdict(list)  # folder -> [(rel, doc)]
        for f in sorted(ENV.rglob("*.json")):
            rel = str(f.relative_to(ENV))
            if rel not in planned:
                self.bg[folder_of(rel)].append((rel, load(f)))
        self.taken = {str(f.relative_to(ENV)) for f in ENV.rglob("*.json")}
        if (OUT / "results.json").exists():  # names staged by an earlier run
            self.taken |= {e["rel"] for e in load(OUT / "results.json").values() if e["new"]}
        for n in range(1, 6):
            u = ROOT / f"steps/stage{n}/workdir/stage{n}_update/new_docs"
            self.taken |= {str(f.relative_to(u)) for f in u.rglob("*.json")}

    def median_len(self, folder):
        docs = self.bg.get(folder) or [d for v in self.bg.values() for d in v]
        return statistics.median(body_len(d) for _, d in docs)

    def lengths(self, folder):
        return [body_len(d) for _, d in self.bg[folder]]

    def formats(self, folder):
        c = collections.Counter()
        for _, d in self.bg[folder]:
            m = d.get("messages")
            if isinstance(m, list) and m:
                k = msg_format(m[0])
                if k:
                    c[k] += 1
        return c

    def roster(self, folder):
        c = collections.Counter()
        for _, d in self.bg[folder]:
            for p in d.get("participants") or ([d["author"]] if d.get("author") else []):
                if re.fullmatch(NAME, str(p)):
                    c[p] += 1
        return [p for p, _ in c.most_common(40)]

    def multi_share(self, folder):
        docs = [d for _, d in self.bg[folder]]
        return sum(len(d["content_field_names"]) > 1 for d in docs) / max(1, len(docs))

    def pick(self, folder, rng, key=None):
        """A random background doc of the folder (its shape is copied)."""
        return rng.choice(self.bg[folder])[1]


def msg_format(m):
    for k, r in FORMAT_RE.items():
        if r.match(m):
            return k
    return None


def weighted(counter, rng):
    keys = sorted(counter)
    return rng.choices(keys, weights=[counter[k] for k in keys])[0] if keys else "dash12"


def rule_list():
    """{rule id: (first stage, rule)} over all stages."""
    out = {}
    for n in range(6):
        p = ROOT / ("tests/rules.json" if n == 0 else f"tests/stages/stage{n}/rules.json")
        for r in load(p):
            out.setdefault(r["id"], (n, r))
    return out


def banned_words():
    pats = []
    for n in range(6):
        p = ROOT / ("tests/doc_plan.json" if n == 0 else f"tests/stages/stage{n}/doc_plan.json")
        plan = load(p)
        pats += [re.compile(rf"\b{re.escape(w)}\b", re.I) for v in plan["must_not_mention"].values() for w in v["words"]]
        pats += [re.compile(x) for v in plan["must_not_mention"].values() for x in v.get("patterns", [])]
    return pats


# ---------- the model ----------

_CLIENT = None


def ask(system, user, tag):
    global _CLIENT
    if _CLIENT is None:
        from openai import OpenAI
        _CLIENT = OpenAI()
    r = _CLIENT.chat.completions.create(model=MODEL, response_format={"type": "json_object"},
                                        messages=[{"role": "system", "content": system},
                                                  {"role": "user", "content": user}])
    u = r.usage
    with LOCK:
        with open(OUT / "usage.jsonl", "a") as f:
            f.write(json.dumps({"tag": tag, "input": u.prompt_tokens, "output": u.completion_tokens}) + "\n")
    return json.loads(r.choices[0].message.content)


SYSTEM = ("You write internal documents for Skyway Air, a US airline: Slack threads between support and operations "
          "staff and Confluence pages. Plain, specific, workmanlike; people talk about real cases, tools, queues, "
          "handoffs and training. Answer with JSON only.")


# ---------- checks (the same as check_docs.py) ----------

def bg_problems(doc, phrases, banned, strict_figures=False):
    body = cd.text_of(doc)
    flat = cd.norm(body)
    out = [f"banned topic: {b.pattern}" for b in banned if b.search(body)]
    hit = next((ph for ph in phrases if ph in flat), None)
    if hit:
        out.append(f"contains a rule sentence: {hit[:80]}")
    if cd.weather_benefit(body):
        out.append("weather disruption next to a benefit")
    if cd.STALE.search(body):
        out.append(f"stale wording: {cd.STALE.findall(body)[:2]}")
    money = cd.policy_money(body)
    if money:
        out.append(f"amount that grants, limits or decides something for a customer: {money[:3]}")
    if strict_figures and (cd.MONEY.search(body) or cd.PCT.search(body) or cd.SPAN.search(body)):
        out.append(f"figures in a doc that must decide nothing: {sorted(cd.figures(body))[:4]}")
    elif cd.PCT.search(body) or cd.SPAN.search(body):
        out.append(f"percentage or hours/days figure: {sorted(cd.figures(body))[:4]}")
    return out


def planned_problems(doc, m, banned):
    body = cd.text_of(doc)
    flat = cd.norm(body)
    out = [f"missing sentence: {s}" for s in m["must_contain"] if cd.norm(s).rstrip(".") not in flat]
    allowed = set().union(*(cd.figures(s) for s in m["must_contain"])) if m["must_contain"] else set()
    extra = sorted(cd.figures(body) - allowed)
    if extra:
        out.append(f"figures not in its sentences: {extra}")
    if cd.STALE.search(body):
        out.append(f"stale wording: {cd.STALE.findall(body)[:2]}")
    if cd.POINTER.search(body):
        out.append(f"points to another page: {cd.POINTER.findall(body)[:2]}")
    out += [f"banned topic: {b.pattern}" for b in banned if b.search(body)]
    if cd.weather_benefit(body):
        out.append("weather disruption next to a benefit")
    return out


# ---------- building docs ----------

def clock_from(doc, rng):
    ca = str(doc.get("created_at") or "")
    try:
        return datetime.fromisoformat(ca.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return datetime.fromisoformat(doc.get("last_updated", "2026-03-02")) + timedelta(hours=rng.randint(8, 16))


def created_at(day, rng, folder_docs, exact=False):
    """A created_at in the style the folder's background uses (most use a -04:00 offset)."""
    styles = collections.Counter(re.sub(r"\d", "9", str(d.get("created_at", "")))[19:] for _, d in folder_docs)
    tail = weighted(styles, rng)
    t = day if exact else day.replace(hour=rng.randint(8, 17), minute=rng.randint(0, 59), second=0)
    return t.strftime("%Y-%m-%dT%H:%M:%S") + {"Z": "Z", "-99:99": "-04:00", "-9999": "-0400"}.get(tail, "-04:00"), t


def match_clock(doc):
    """created_at set to the first message's time (and date, when messages carry one), keeping its offset style.
    Dropping the first messages must not leave a thread starting before its first message. None: nothing to do."""
    msgs = doc.get("messages")
    ca = str(doc.get("created_at") or "")
    k = msg_format(msgs[0]) if isinstance(msgs, list) and msgs else None
    if not k or k in NO_TIME or len(ca) < 16:
        return None
    g = FORMAT_RE[k].match(msgs[0])
    stamp = g.group(1) if k == "datefirst" else g.group(2)
    if k == "dash12":
        t = datetime.strptime(stamp, "%I:%M %p")
        new = f"{ca[:11]}{t:%H:%M}{ca[16:]}"
    elif len(stamp) == 5:
        new = f"{ca[:11]}{stamp}{ca[16:]}"
    else:
        new = f"{stamp[:10]}T{stamp[11:]}{ca[16:]}"
    return new if new != ca else None


PREFIX = re.compile(rf"^\s*(?:{NAME}\s*)?(?:[—\-]\s*)?(?:\d{{4}}-\d\d-\d\d\s*)?\d{{1,2}}:\d\d(?:\s?[AP]M)?\s*[—:\-]\s*")


def clean(text):
    """A message's words without a name or time the model put in front."""
    text = PREFIX.sub("", text.strip())
    return re.sub(rf"^{NAME}:\s+", "", text).strip()


def thread(turns, fmt, start, rng):
    """[(speaker, text)] -> messages in format fmt, a few minutes apart from start."""
    t, out = start, []
    for name, text in turns:
        out.append(FORMATS[fmt][1](name, t) + text)
        t += timedelta(minutes=rng.randint(1, 9))
    return out


def parse_planned_messages(msgs):
    """[(speaker, text)] for a planned thread's messages ("Name — 10:18 AM: text")."""
    out = []
    for m in msgs:
        k = msg_format(m)
        if k:
            g = FORMAT_RE[k].match(m)
            out.append((g.group(2) if k == "datefirst" else g.group(1), m[g.end():]))
            continue
        g = ANY_TURN.match(m)
        if not g:
            return None
        out.append((g.group(1), m[g.end():]))
    return out


ANY_TURN = re.compile(rf"^({NAME})\s*(?:—|·|-)\s*(?:[A-Z][a-z]{{2}} \d{{1,2}}, |\d{{4}}-\d\d-\d\d )?\d{{1,2}}:\d\d(?: ?[AP]M)?\s*(?::\s*|\n)")


def md_sections(text):
    """A planned page's markdown -> (title line or None, [(heading, [lines])])."""
    lines = text.split("\n")
    title = lines.pop(0) if lines and lines[0].startswith("# ") else None
    secs, cur = [], None
    for ln in lines:
        if ln.startswith("## "):
            cur = (ln[3:].strip(), [])
            secs.append(cur)
        elif cur is None:
            if ln.strip():
                cur = ("Overview", [ln])
                secs.append(cur)
        else:
            cur[1].append(ln)
    return title, [(h, [x for x in ls]) for h, ls in secs]


def field_value(lines):
    body = [x for x in lines if x.strip()]
    items = [re.sub(r"^(\s*[-*]|\s*\d+[.)])\s+", "", x) for x in body]
    if body and all(re.match(r"^\s*([-*]|\d+[.)])\s+", x) for x in body):
        return items
    return "\n\n".join(x.strip() for x in body) if not any(x.startswith("#") for x in body) else "\n".join(body).strip()


def field_name(heading, used):
    base = re.sub(r"[^a-z0-9]+", "_", heading.lower()).strip("_")[:40] or "notes"
    if base in META:
        base += "_notes"
    name, i = base, 2
    while name in used:
        name, i = f"{base}_{i}", i + 1
    used.add(name)
    return name


def expand(item, corpus, phrases, banned, rng):
    n, rel, m = item["stage"], item["rel"], item["manifest"]
    path = stage_path(n, rel)[0]
    doc = load(path)
    folder = folder_of(rel)
    target = int(corpus.median_len(folder) * rng.uniform(0.8, 1.3))
    feedback = ""
    for attempt in range(3):
        if doc.get("source_system") == "slack":
            turns = parse_planned_messages(doc["messages"])
            if turns is None:
                return None, "planned messages in an unknown format"
            names = list(dict.fromkeys([t[0] for t in turns] + corpus.roster(folder)[:6]))
            numbered = "\n".join(f"[{i}] {s}: {t}" for i, (s, t) in enumerate(turns))
            words = max(120, (target - body_len(doc)) // 7)
            res = ask(SYSTEM, f"""This is a Slack thread in #{folder.split('/')[1]}. Its messages are numbered:

{numbered}

Make the thread longer, about {words} more words, so it reads like an ordinary working conversation: add messages
before, between and after the numbered ones (other cases in the queue, tools, handoffs, small talk about the work,
follow-up questions that do not change anything). The numbered messages stay exactly as they are and in the same order.
Speakers: {', '.join(names)}. {NO_DECIDING} Do not end with a summary of the answer.
Answer as {{"thread": [...]}} where each entry is either {{"keep": <number>}} for a numbered message, or
{{"speaker": "...", "text": "..."}} for a new one.{feedback}""", f"expand:{rel}")
            new_turns, kept = [], []
            for e in res.get("thread", []):
                if "keep" in e:
                    i = int(e["keep"])
                    if 0 <= i < len(turns):
                        kept.append(i)
                        new_turns.append(turns[i])
                elif e.get("speaker") in names and e.get("text"):
                    new_turns.append((e["speaker"], clean(e["text"])))
            if kept != list(range(len(turns))):
                feedback = "\nEvery numbered message must appear once, in order, as {\"keep\": n}."
                continue
            fmt = weighted(corpus.formats(folder), rng)
            start = clock_from(doc, rng) - timedelta(minutes=rng.randint(5, 40))
            new = dict(doc)
            new["participants"] = list(dict.fromkeys(s for s, _ in new_turns))
            new["messages"] = thread(new_turns, fmt, start, rng)
            new["created_at"] = created_at(start.replace(second=0, microsecond=0), rng, corpus.bg[folder], exact=True)[0]
        else:
            field = doc["content_field_names"][0]
            if len(doc["content_field_names"]) != 1 or not isinstance(doc.get(field), str):
                return None, "page is not one markdown field"
            title, secs = md_sections(doc[field])
            listing = "\n".join(f"[{i}] ## {h}" for i, (h, _) in enumerate(secs))
            words = max(150, (target - body_len(doc)) // 7)
            res = ask(SYSTEM, f"""This is a Confluence page, "{doc['title']}", in {folder}. Its sections:

{doc[field]}

Add about {words} words of new sections that a real page like this would have (who uses it, how cases come in,
working steps with tools and handoffs, quality checks, examples of what to record, contacts), placed between the
existing ones. The existing sections stay as they are. {NO_DECIDING}
Section numbers: {listing}
Answer as {{"sections": [{{"after": <number of the existing section it follows, -1 for the top>, "heading": "...",
"paragraphs": ["..."] or "items": ["..."]}}]}}.{feedback}""", f"expand:{rel}")
            add = collections.defaultdict(list)
            for s in res.get("sections", []):
                lines = [f"- {x}" for x in s.get("items", [])] or [p for x in s.get("paragraphs", []) for p in (x, "")]
                add[int(s.get("after", len(secs) - 1))].append((s.get("heading", "Notes"), lines))
            merged = add[-1] + [x for i, sec in enumerate(secs) for x in [sec] + add[i]]
            merged += [x for k, v in add.items() if k >= len(secs) for x in v]
            new = {k: v for k, v in doc.items() if k not in (field, "title_field_name", "content_field_names",
                                                              "dataset_doc_uuid")}
            if rng.random() < corpus.multi_share(folder):
                used = set(new)
                names = []
                for h, ls in merged:
                    f = field_name(h, used)
                    new[f] = field_value(ls)
                    names.append(f)
            else:
                md = [title] if title else []
                for h, ls in merged:
                    md += ["", f"## {h}"] + [x for x in ls]
                new[field] = re.sub(r"\n{3,}", "\n\n", "\n".join(md)).strip() + "\n"
                names = [field]
            new.update({"title_field_name": "title", "content_field_names": names,
                        "dataset_doc_uuid": doc["dataset_doc_uuid"]})
        probs = planned_problems(new, m, banned)
        if body_len(new) < 0.6 * target:
            probs.append(f"too short ({body_len(new)} of about {target} characters)")
        if not probs:
            return new, f"{body_len(doc)} -> {body_len(new)} characters (folder median {int(corpus.median_len(folder))})"
        feedback = "\nA first try had these problems; avoid them: " + "; ".join(probs)
    return None, "; ".join(probs)


def new_doc(folder, day, rng, corpus, content, title, participants=None, ca=None):
    """A new background-shaped doc for the folder: metadata copied from a random background doc there."""
    tpl = corpus.pick(folder, rng)
    doc = {}
    for k, v in tpl.items():
        if k in META or k not in tpl.get("content_field_names", []):
            doc[k] = v
    doc["title"] = title
    if tpl.get("source_system") == "slack":
        doc["created_at"] = ca or created_at(day, rng, corpus.bg[folder])[0]
        doc["participants"] = participants
    else:
        doc["last_updated"] = day.strftime("%Y-%m-%d")
        if doc.get("author"):
            doc["author"] = rng.choice(corpus.roster(folder)[:15] or [doc["author"]])
    keys = [k for k in tpl if k not in tpl.get("content_field_names", [])]
    out = {}
    for k in keys:
        if k in ("title_field_name", "content_field_names", "dataset_doc_uuid"):
            break
        out[k] = doc[k]
    out.update(content)
    out["title_field_name"] = "title"
    out["content_field_names"] = list(content)
    out["dataset_doc_uuid"] = "dsid_" + uuid.UUID(int=rng.getrandbits(128)).hex
    return out


def free_name(folder_dir, title, corpus):
    base = slug(title)
    for extra in ("", "-notes", "-question", "-follow-up", "-check", "-update", "-review", "-handling", "-case"):
        rel = f"{folder_dir}/{base}{extra}.json"
        with LOCK:
            if rel not in corpus.taken:
                corpus.taken.add(rel)
                return rel
    return None


def make_thread(folder, day, rng, corpus, brief, words, feedback="", rules_ok=False):
    names = corpus.roster(folder)[:12]
    rng.shuffle(names)
    names = names[:rng.randint(3, 5)]
    examples = []
    for _, d in rng.sample(corpus.bg[folder], 2):
        examples.append("\n".join(str(x) for x in d.get("messages", [])[:6])[:1200])
    res = ask(SYSTEM, f"""Write a Slack thread in #{folder.split('/')[1]}, about {words} words. {brief}
Speakers: {', '.join(names)}. {"" if rules_ok else NO_DECIDING}
Two threads from this channel, for the tone only (do not reuse their cases):
---
{examples[0]}
---
{examples[1]}
---
Answer as {{"title": "a short title like the channel's thread titles", "messages": [{{"speaker": "...", "text": "..."}}]}}.{feedback}""",
              f"thread:{folder}")
    turns = [(m["speaker"], clean(m["text"])) for m in res.get("messages", []) if m.get("speaker") in names and m.get("text")]
    fmt = weighted(corpus.formats(folder), rng)
    ca, start = created_at(day, rng, corpus.bg[folder])
    content = {"messages": thread(turns, fmt, start, rng)}
    return res.get("title") or "Queue notes", content, list(dict.fromkeys(s for s, _ in turns)), ca


def make_page(folder, day, rng, corpus, brief, words, feedback="", rules_ok=False):
    tpl = corpus.pick(folder, rng)
    shape = ", ".join(tpl.get("content_field_names", [])[:10])
    res = ask(SYSTEM, f"""Write a Confluence page in {folder}, about {words} words. {brief} {"" if rules_ok else NO_DECIDING}
Shape it like this folder's pages, which use fields such as: {shape}.
Answer as {{"title": "...", "fields": [{{"name": "snake_case_name", "value": "text" or ["item", "..."]}}]}}.{feedback}""",
              f"page:{folder}")
    used, content = set(META), {}
    for f in res.get("fields", []):
        content[field_name(f.get("name", "notes"), used)] = f.get("value", "")
    return res.get("title") or "Working notes", content


def random_day(n, rng):
    a, b = (datetime.fromisoformat(x) for x in WINDOWS[n])
    return a + timedelta(days=rng.randint(0, (b - a).days))


def lookalike(item, corpus, phrases, banned, rng):
    n, rid, folder_dir, topic, words_hint = item["stage"], item["rule"], item["dir"], item["topic"], item["words"]
    folder = folder_of(folder_dir)
    if not corpus.bg.get(folder):  # a folder with no background to copy the shape from
        folder_dir = folder = "slack/support-policy-questions"
    brief = (f"The topic is {topic}: staff talk about it using its everyday words ({words_hint}) — a case that came "
             f"in, how to record it, a tool or queue problem, a training note, a customer who asked and was told the "
             f"team would check — but nothing in it decides or states the rule itself. Do not use internal labels or codes written with hyphens or "
             f"underscores.")
    target = int(statistics.median(corpus.lengths(folder)) / 7)
    feedback = ""
    for attempt in range(3):
        day = random_day(n, rng)
        if folder.startswith("slack/"):
            title, content, people, ca = make_thread(folder, day, rng, corpus, brief, target, feedback)
            doc = new_doc(folder, day, rng, corpus, content, title, people, ca)
        else:
            title, content = make_page(folder, day, rng, corpus, brief, target, feedback)
            doc = new_doc(folder, day, rng, corpus, content, title)
        probs = bg_problems(doc, phrases, banned, strict_figures=True)
        if not cd.text_of(content).strip():
            probs.append("empty")
        if not probs:
            rel = free_name(folder_dir, title, corpus)
            return (rel, doc), f"{rid} lookalike, {body_len(doc)} characters"
        feedback = "\nA first try had these problems; avoid them: " + "; ".join(probs)
    return None, "; ".join(probs)


CONTEXTS = [
    ("the fare the customer paid for the booking, which is just a fact on the case", (89, 690)),
    ("a seat upgrade the customer bought before the trip, read off the receipt", (29, 189)),
    ("a pending card authorisation hold the customer's bank shows", (49, 640)),
    ("an invoice from a vendor for team equipment (headsets, a printer lease, a label printer repair)", (60, 2400)),
    ("the team's training or offsite budget line", (300, 4800)),
    ("the total on a group booking the customer is asking about", (700, 5200)),
    ("a software licence or tool subscription the team is reviewing", (120, 3600)),
]
TRAVEL_CREDIT = [
    "the travel credit field in the case tool showing up blank for some agents",
    "a customer asking where a travel credit appears in their account",
    "how to label a case that mentions travel credit so reporting picks it up",
    "a training session where travel credit came up as a topic to cover later",
    "a macro or reply template that mentions travel credit and needs a wording tidy-up",
    "a customer chat transferred mid-way where the customer had mentioned travel credit",
]


def amount(lo, hi, rng):
    while True:
        v = rng.randint(lo, hi)
        s = f"${v:,}" if v >= 1000 or rng.random() < 0.6 else f"${v:,}.{rng.randint(0, 99):02d}"
        if cd.norm(s).rstrip(",.;:") not in cd.rule_amounts() and f"${v}" not in cd.rule_amounts():
            return s


def money(item, corpus, phrases, banned, rng):
    rel = item["rel"]
    doc = load(SOURCES / rel)
    if item["kind"] == "dollar":
        ctx, (lo, hi) = rng.choice(CONTEXTS)
        amt = amount(lo, hi, rng)
        ask_for = f"mentions {amt} as {ctx}. Write the amount exactly as {amt}."
        must = amt
    else:
        ask_for = f"mentions travel credit, about {rng.choice(TRAVEL_CREDIT)}."
        must = "travel credit"
    feedback = ""
    for attempt in range(3):
        new = json.loads(json.dumps(doc))
        if doc.get("source_system") == "slack":
            msgs = doc["messages"]
            k = msg_format(msgs[0])
            if not isinstance(msgs, list) or not k:
                return None, "unknown message format"
            where = rng.randint(1, len(msgs))
            ctx_text = "\n".join(msgs[max(0, where - 5):where])
            names = list(doc.get("participants") or [])
            res = ask(SYSTEM, f"""A Slack thread so far:
{ctx_text}

Write ONE more message that fits right here and naturally {ask_for} {NO_DECIDING}
The amount or mention must not decide anything for anyone. Speaker: one of {', '.join(names)}.
Answer as {{"speaker": "...", "text": "..."}}.{feedback}""", f"money:{rel}")
            if res.get("speaker") not in names or not res.get("text"):
                feedback = "\nUse one of the listed speakers."
                continue
            prev = msgs[where - 1]
            g = FORMAT_RE[k].match(prev)
            if not g:
                return None, "unknown message format"
            t = re.search(r"\d{1,2}:\d\d(?: [AP]M)?", prev).group(0)
            base = datetime.strptime(t, "%I:%M %p" if "M" in t else "%H:%M")
            dm = re.search(r"\d{4}-\d\d-\d\d", prev)
            if dm:
                base = datetime.fromisoformat(dm.group(0)).replace(hour=base.hour, minute=base.minute)
            line = FORMATS[k][1](res["speaker"], base + timedelta(minutes=rng.randint(1, 4))) + clean(res["text"])
            new["messages"] = msgs[:where] + [line] + msgs[where:]
        else:
            fields = [f for f in doc["content_field_names"] if isinstance(doc.get(f), (list, str))]
            f = rng.choice(fields)
            val = doc[f]
            res = ask(SYSTEM, f"""A section "{f}" of the Confluence page "{doc['title']}":
{json.dumps(val)[:1500]}

Write ONE more {'item' if isinstance(val, list) else 'sentence'} for it that fits and naturally {ask_for} {NO_DECIDING}
Answer as {{"text": "..."}}.{feedback}""", f"money:{rel}")
            text = (res.get("text") or "").strip()
            if isinstance(val, list):
                new[f] = val + [text]
            else:
                new[f] = val.rstrip() + (" " if not val.endswith("\n") else "") + text
        probs = bg_problems(new, phrases, banned)
        if must.lower() not in cd.text_of(new).lower():
            probs.append(f"does not mention {must}")
        if not probs:
            return new, f"{item['kind']}: {must}"
        feedback = "\nA first try had these problems; avoid them: " + "; ".join(probs)
    return None, "; ".join(probs)


REFUND_SEEDS = [
    "a morning queue review: who takes which refund cases and which ones wait for finance",
    "a duplicate case cleanup after two agents opened cases for the same booking",
    "a payment processor batch file that arrived late and how the desk tracks it",
    "a chargeback paperwork request from the card team and who gathers the case history",
    "a customer who wrote in three times in one day and how to merge the threads",
    "a new hire shadowing the desk and questions they had about the case tool",
    "the weekly audit sample of closed refund cases and what the reviewer flagged about notes",
    "a macro that inserts the wrong customer name and the workaround until it is fixed",
    "handoff notes before a long weekend and who covers the shared inbox",
    "a case where the customer used a different email than the booking and how identity was checked",
    "a confusing bank statement a customer sent and how the desk reads the line items",
    "case tags that drifted and a tidy-up of the tag list",
    "a call-back schedule for customers who asked to be phoned rather than emailed",
    "a translation request for a customer writing in Portuguese",
    "the finance team's month-end cut-off and which cases need their reference numbers before it",
    "a group booking organiser asking for one combined status update",
    "a customer who disputes the date on their receipt and how the desk finds the right record",
    "a dashboard showing ageing cases and what the colours mean",
    "a polite but very long customer email and how to summarise it in the case",
    "an agent asking how to note a phone conversation that had no reference number",
]


def refunds(item, corpus, phrases, banned, rng):
    folder = "slack/refunds-desk"
    brief = f"The thread is about {item['seed']}."
    if item.get("amount"):
        ctx, (lo, hi) = rng.choice(CONTEXTS)
        amt = amount(lo, hi, rng)
        brief += f" Somewhere one message mentions {amt} as {ctx}, written exactly as {amt}; it decides nothing."
    words = int(rng.choice(corpus.lengths(folder)) / 7)
    feedback = ""
    for attempt in range(3):
        day = random_day(0, rng)
        title, content, people, ca = make_thread(folder, day, rng, corpus, brief, max(150, words), feedback)
        doc = new_doc(folder, day, rng, corpus, content, title, people, ca)
        probs = bg_problems(doc, phrases, banned)
        if len(content["messages"]) < 4:
            probs.append("too few messages")
        if not probs:
            rel = free_name(folder, title, corpus)
            return (rel, doc), f"refunds thread, {body_len(doc)} characters"
        feedback = "\nA first try had these problems; avoid them: " + "; ".join(probs)
    return None, "; ".join(probs)


# ---------- the plan ----------

def plan(corpus, rng):
    items = []
    for n, rel, m in planned_docs():
        items.append({"job": "expand", "key": f"expand/{n}/{rel}", "stage": n, "rel": rel, "manifest": m})
    keywords = load(ROOT / "tests/rule_keywords.json")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from build_doc_projects import TOPIC
    for rid, (n, r) in sorted(rule_list().items(), key=lambda x: int(x[0][1:])):
        # next to its real docs first, then where its decoys sit, then the everyday support channels
        dirs = list(dict.fromkeys(s[len("docs/"):].rsplit("/", 1)[0] for s in r["sources"]))
        dirs = sorted(dirs, key=lambda d: not d.startswith("confluence"))
        dirs += [x[len("docs/"):].rsplit("/", 1)[0] for x in r.get("decoys", [])]
        dirs += ["slack/support-policy-questions", "slack/support-team", "slack/support-escalations"]
        dirs = list(dict.fromkeys(dirs))
        kw = keywords.get(rid, {})
        words = ", ".join(sorted({w for g in kw.get("all", []) for w in g
                                  if not str(w).startswith("re:") and not re.search(r"[$\d_-]", str(w))})[:8]) \
            if isinstance(kw, dict) else ""
        for i, d in enumerate(dirs[:2 if n == 1 else LOOKALIKES]):  # stage 1 has no background top-up to give way
            items.append({"job": "lookalike", "key": f"lookalike/{rid}/{i}", "stage": n, "rule": rid, "dir": d,
                          "topic": TOPIC.get(rid, r["rule"][:80]), "words": words or TOPIC.get(rid, "")})
    folders = ["slack/refunds-desk", "slack/support-team", "slack/support-escalations", "slack/support-policy-questions",
               "slack/baggage-desk", "slack/irregular-ops", "slack/loyalty-team", "slack/airport-ops",
               "confluence/support-playbooks", "confluence/customer-policies"]
    pool = sorted(rel for f in folders for rel, d in corpus.bg[f]
                  if d.get("source_system") != "slack" or (isinstance(d.get("messages"), list) and d["messages"]
                                                           and msg_format(d["messages"][0])))
    pool = [p for p in pool if (SOURCES / p).exists()]
    picks = rng.sample(pool, 230)
    for i, rel in enumerate(picks):
        items.append({"job": "money", "key": f"money/{rel}", "rel": rel, "kind": "dollar" if i < 150 else "credit"})
    for i in range(150):
        items.append({"job": "refunds", "key": f"refunds/{i}", "seed": REFUND_SEEDS[i % len(REFUND_SEEDS)],
                      "amount": i % 3 == 0})
    return items


def original(n, rel):
    """A planned doc as it was before expanding: the checkpoint commit, under its name before the renames."""
    import subprocess
    back = {v[len("docs/"):]: k[len("docs/"):] for k, v in load(ROOT / "docs_build/rename_map.json").items()}
    old = back.get(rel, rel)
    base = "environment/app/docs" if n == 0 else f"steps/stage{n}/workdir/stage{n}_update/new_docs"
    r = subprocess.run(["git", "show", f"{CHECKPOINT}:tasks/skyway-air/{base}/{old}"], cwd=ROOT, capture_output=True,
                       text=True)
    return json.loads(r.stdout) if r.returncode == 0 else None


CHECKPOINT = "3be9da55904"  # the commit with the planned docs before blend_docs.py expanded them


def shorten(apply):
    """Expanded planned docs drop added messages or sections, outermost first, until they are about their folder's
    background size (length, and for Slack the number of messages). What the doc had before expanding is never
    dropped, so its sentences, the stage patches and the conversation around each sentence stay."""
    corpus = Corpus()
    done = load(OUT / "results.json")
    counts = {f: statistics.median(len(d.get("messages") or []) for _, d in docs)
              for f, docs in corpus.bg.items() if f.startswith("slack/")}
    changed, report = 0, collections.Counter()
    for key, e in sorted(done.items()):
        if not key.startswith("expand/"):
            continue
        n, rel = e["stage"], e["rel"]
        path = stage_path(n, rel)[0]
        doc, before = load(STAGED / str(n) / rel), original(n, rel)  # from the expanded copy, so it can be redone
        if before is None:
            report["no original found"] += 1
            continue
        rng = random.Random(key)
        folder = folder_of(rel)
        target = corpus.median_len(folder) * rng.uniform(0.85, 1.15)
        old_text = cd.norm(cd.text_of({k: before.get(k) for k in before.get("content_field_names", [])}))
        fields = doc["content_field_names"]
        if doc.get("source_system") == "slack":
            msgs = doc["messages"]
            keep = [cd.norm(PREFIX.sub("", m) if not msg_format(m) else m[FORMAT_RE[msg_format(m)].match(m).end():])
                    in old_text for m in msgs]
            # length decides; planned messages are shorter than the background's, so allow more of them
            limit = max(sum(keep), round(counts.get(folder, 13) * 1.5))
            order = sorted((i for i, k in enumerate(keep) if not k),
                           key=lambda i: -min(abs(i - j) for j, k in enumerate(keep) if k) if any(keep) else 0)
            alive = set(range(len(msgs)))
            for i in order:
                size = sum(len(msgs[j]) for j in alive)
                if size <= target and len(alive) <= limit:
                    break
                alive.discard(i)
            if len(alive) < len(msgs):
                new = dict(doc)
                new["messages"] = [m for i, m in enumerate(msgs) if i in alive]
                speakers = []
                for m in new["messages"]:
                    k = msg_format(m)
                    g = FORMAT_RE[k].match(m) if k else ANY_TURN.match(m)
                    if g:
                        speakers.append(g.group(2) if k == "datefirst" else g.group(1))
                new["participants"] = [p for p in doc.get("participants", []) if p in speakers] or doc.get("participants")
                new["created_at"] = match_clock(new) or new["created_at"]
                doc_new = new
            else:
                doc_new = None
        else:
            if fields == [fields[0]] and isinstance(doc[fields[0]], str):  # one markdown field: drop ## sections
                title, secs = md_sections(doc[fields[0]])
                keep = [all(cd.norm(x) in old_text for x in ls if x.strip()) and cd.norm(h) in old_text
                        for h, ls in secs]
                alive = list(range(len(secs)))
                for i in [i for i in range(len(secs) - 1, -1, -1) if not keep[i]]:
                    if sum(len(h) + sum(len(x) for x in secs[j][1]) for j, (h, _) in enumerate(secs) if j in alive) <= target:
                        break
                    alive.remove(i)
                if len(alive) < len(secs):
                    md = [title] if title else []
                    for i in alive:
                        md += ["", f"## {secs[i][0]}"] + secs[i][1]
                    doc_new = dict(doc)
                    doc_new[fields[0]] = re.sub(r"\n{3,}", "\n\n", "\n".join(md)).strip() + "\n"
                else:
                    doc_new = None
            else:  # a field per section: drop added fields
                keep = {f: cd.norm(cd.text_of(doc[f])) in old_text or all(
                    cd.norm(x) in old_text for x in (doc[f] if isinstance(doc[f], list) else [doc[f]])) for f in fields}
                alive = list(fields)
                for f in [f for f in reversed(fields) if not keep[f]]:
                    if sum(len(cd.text_of(doc[x])) for x in alive) <= target:
                        break
                    alive.remove(f)
                if len(alive) < len(fields):
                    doc_new = {k: v for k, v in doc.items() if k not in fields or k in alive}
                    doc_new["content_field_names"] = alive
                else:
                    doc_new = None
        if doc_new is None:
            report["already about the folder's size"] += 1
            continue
        m = next(x for x in planned_docs() if x[0] == n and x[1] == rel)[2]
        probs = planned_problems(doc_new, m, banned_words())
        if probs:
            report["left as is: trimming would break it"] += 1
            print("  kept", rel, probs[:1])
            continue
        report["trimmed"] += 1
        changed += 1
        if apply:
            for p in stage_path(n, rel):
                write_doc(p, doc_new)
    print(dict(report), "(applied)" if apply else "(dry run)")


def doc_date(doc):
    v = str(doc.get("created_at") or doc.get("last_updated") or "")[:10]
    return datetime.fromisoformat(v) if v else None


def plan_of(n):
    return load(ROOT / ("tests/doc_plan.json" if n == 0 else f"tests/stages/stage{n}/doc_plan.json"))["docs"]


def when(n, rel, m, rng):
    """A date for a new planned doc. A wrong version is older than every doc of its stage that states the rule, so the
    newest statement (the rule) wins; anything else falls anywhere in its stage's window."""
    start, end = (datetime.fromisoformat(x) for x in WINDOWS[n])
    if not m.get("trap"):
        return start + timedelta(days=rng.randint(0, (end - start).days))
    rid, plan = m["trap"]["for"], plan_of(n)
    dates = []
    for d, e in plan.items():
        if rid in e.get("carries", []) and d.startswith("docs/") and not e.get("trap"):
            f = stage_path(n, d[len("docs/"):])[0]
            if f.exists() and doc_date(load(f)):
                dates.append(doc_date(load(f)))
    first = min(dates) if dates else end
    latest = first - timedelta(days=2)
    earliest = max(start - timedelta(days=20 if n == 0 else 0), latest - timedelta(days=30))
    return earliest + timedelta(days=rng.randint(0, max(0, (latest - earliest).days)))


def write_planned(n, rel, m, corpus, banned, rng):
    folder = folder_of(rel)
    trap = m.get("trap")
    sentences = "\n".join(f"- {x}" for x in m["must_contain"])
    if trap:
        brief = ("A colleague states the following as plain fact, confidently, as the way things are done; nobody "
                 "questions or corrects it, and nothing says it is old, a draft or temporary. Use these words exactly:\n"
                 f"{sentences}")
    else:
        brief = f"It must contain these sentences word for word:\n{sentences}"
    extra = (" Apart from those sentences, state no amount, percentage, number of hours or days, limit or deadline, and "
             "do not tell people to see another page. Do not mention weather, air traffic control or security as a "
             "cause unless the sentences do.")
    words = int(statistics.median(corpus.lengths(folder)) / 7)
    feedback = ""
    for attempt in range(3):
        day = when(n, "docs/" + rel, m, rng)
        if folder.startswith("slack/"):
            title, content, people, ca = make_thread(folder, day, rng, corpus, brief + extra, words, feedback,
                                                     rules_ok=True)
            doc = new_doc(folder, day, rng, corpus, content, title, people, ca)
        else:
            title, content = make_page(folder, day, rng, corpus, brief + extra, words, feedback, rules_ok=True)
            doc = new_doc(folder, day, rng, corpus, content, title)
        probs = planned_problems(doc, m, banned)
        if not probs:
            return doc, f"{'wrong version' if trap else 'planned'}, dated {day:%Y-%m-%d}, {body_len(doc)} characters"
        feedback = "\nA first try had these problems; avoid them: " + "; ".join(probs)
    return None, "; ".join(probs)


def planned(apply):
    """Planned docs in the manifests that are not on disk yet: generate, stage, and with --apply put them in place,
    keeping each stage's size (stage 0 gives up support-playbooks background docs; later stages give up top-up or
    lookalike docs, never one anything refers to)."""
    corpus, banned = Corpus(), banned_words()
    todo = []
    for n, rel, m in planned_docs():
        if not stage_path(n, rel)[0].exists():
            todo.append((n, rel, m))
    print(f"{len(todo)} planned docs to write")
    done = load(OUT / "planned.json") if (OUT / "planned.json").exists() else {}

    def run(x):
        n, rel, m = x
        key = f"{n}/{rel}"
        if key in done:
            return key, True, "staged before"
        rng = random.Random(key)
        try:
            doc, note = write_planned(n, rel, m, corpus, banned, rng)
        except Exception as e:  # noqa: BLE001
            return key, False, f"error: {type(e).__name__}: {e}"[:300]
        if doc is None:
            return key, False, note
        write_doc(STAGED / "planned" / str(n) / rel, doc)
        return key, True, note

    with cf.ThreadPoolExecutor(16) as ex:
        for key, ok, note in ex.map(run, todo):
            print(("  " if ok else "  FAILED ") + key, "-", note[:160])
            if ok and key not in done:
                done[key] = note
    (OUT / "planned.json").write_text(json.dumps(done, indent=1, sort_keys=True) + "\n")
    if not apply:
        return
    keep = referenced() | {r for _, r, _ in planned_docs()} | set(load(OUT / "lookalikes.json"))
    rng, removed = random.Random(9), collections.defaultdict(list)
    for n, rel, m in todo:
        src = STAGED / "planned" / str(n) / rel
        if not src.exists():
            continue
        for p in stage_path(n, rel):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(src.read_text())
        lst = ROOT / ("docs_build/base_corpus.txt" if n == 0 else f"steps/stage{n}/workdir/stage{n}_update/new_docs.txt")
        lines = lst.read_text().splitlines()
        if "sources/" + rel not in lines:
            lst.write_text("".join(x + "\n" for x in lines + ["sources/" + rel]))
    for n in range(6):
        root = ENV if n == 0 else ROOT / f"steps/stage{n}/workdir/stage{n}_update/new_docs"
        files = sorted(str(f.relative_to(root)) for f in root.rglob("*.json"))
        limit = 9999 if n == 0 else (50 if n <= 2 else 40)
        extra = len(files) - limit
        if extra <= 0:
            continue
        if n == 0:
            pool = [f for f in files if f.startswith("confluence/support-playbooks/") and f not in keep]
        else:
            pool = [f for f in files if f not in keep]
            if len(pool) < extra:  # then lookalikes of this stage, keeping two per rule where it can
                looks = load(OUT / "lookalikes.json")
                pool += [f for f in files if f in looks and looks[f]["stage"] == n][: extra - len(pool)]
        for rel in sorted(rng.sample(pool, min(extra, len(pool)))):
            for p in stage_path(n, rel):
                p.unlink()
            removed[n].append(rel)
        lst = ROOT / ("docs_build/base_corpus.txt" if n == 0 else f"steps/stage{n}/workdir/stage{n}_update/new_docs.txt")
        drop = {"sources/" + r for r in removed[n]}
        lst.write_text("".join(x + "\n" for x in lst.read_text().splitlines() if x not in drop))
    looks = load(OUT / "lookalikes.json")
    gone = {r for v in removed.values() for r in v}
    (OUT / "lookalikes.json").write_text(json.dumps({k: v for k, v in looks.items() if k not in gone}, indent=1,
                                                    sort_keys=True) + "\n")
    old = load(OUT / "removed.json")
    for n, v in removed.items():
        old[str(n)] = sorted(set(old.get(str(n), [])) | set(v))
    (OUT / "removed.json").write_text(json.dumps(old, indent=1) + "\n")
    print("removed to keep the stage sizes:", {n: len(v) for n, v in removed.items()})


def stamp_of(m):
    """(format, datetime of the message's stamp on a dummy day if it has no date), or None."""
    k = msg_format(m)
    if not k or k in NO_TIME:
        return None
    g = FORMAT_RE[k].match(m)
    st = g.group(1) if k == "datefirst" else g.group(2)
    if k == "dash12":
        return k, datetime.strptime("2000-01-01 " + st, "%Y-%m-%d %I:%M %p")
    if len(st) == 5:
        return k, datetime.strptime("2000-01-01 " + st, "%Y-%m-%d %H:%M")
    return k, datetime.strptime(st, "%Y-%m-%d %H:%M")


def retime(doc, start):
    """The thread's message stamps moved by one shift so the first is at start (hh, mm), same day. None if a stamp
    cannot be read or the shift would cross midnight."""
    msgs = doc["messages"]
    stamps = [stamp_of(m) for m in msgs]
    if not stamps or any(x is None for x in stamps):
        return None
    first = stamps[0][1]
    shift = first.replace(hour=start[0], minute=start[1]) - first
    out = []
    for m, (k, t) in zip(msgs, stamps):
        t2 = t + shift
        if t2.date() != t.date():
            return None
        g = FORMAT_RE[k].match(m)
        name = g.group(2) if k == "datefirst" else g.group(1)
        out.append(FORMATS[k][1](name, t2) + m[g.end():])
    return out


def clocks(apply):
    """Every Slack doc this script made or expanded starts at a time the folder's background threads start at (a third
    of them at 14:18), moving all its stamps by one shift within the day, and its created_at matches the first
    message (match_clock)."""
    done = load(OUT / "results.json")
    rels = {(n, rel) for n, rel, _ in planned_docs()}
    rels |= {(e["stage"], e["rel"]) for k, e in done.items() if e.get("new")}
    if (OUT / "round2.json").exists():  # blend_round2.py's new docs
        rels |= {(e["stage"], e["rel"]) for e in load(OUT / "round2.json").values() if e.get("new")}  # money edits keep their thread's clock
    corpus = Corpus()
    starts = {}
    for f, docs in corpus.bg.items():
        c = collections.Counter()
        for _, d in docs:
            m = d.get("messages")
            x = stamp_of(m[0]) if isinstance(m, list) and m and isinstance(m[0], str) else None
            if x:
                c[(x[1].hour, x[1].minute)] += 1
        starts[f] = c
    report = collections.Counter()
    for n, rel in sorted(rels):
        paths = [p for p in stage_path(n, rel) if p.exists()]
        if not paths:
            continue
        doc = load(paths[0])
        old = json.dumps(doc)
        if isinstance(doc.get("messages"), list) and starts.get(folder_of(rel)):
            rng = random.Random("clock/" + rel)
            for _ in range(30):  # a start the folder uses that keeps the whole thread inside its day
                msgs = retime(doc, weighted(starts[folder_of(rel)], rng))
                if msgs:
                    break
            if msgs and msgs != doc["messages"]:
                doc["messages"] = msgs
                report["retimed"] += 1
        new = match_clock(doc)
        if new:
            if new[:10] != str(doc["created_at"])[:10]:
                report["created_at date moved to the messages' date"] += 1
                print(f"  {n} {rel}: {doc['created_at']} -> {new}")
            report["created_at reset"] += 1
            doc["created_at"] = new
        if apply and json.dumps(doc) != old:
            for p in paths:
                write_doc(p, doc)
    print(dict(report), "(applied)" if apply else "(dry run)")


def patched_docs():
    """Docs a stage patch edits with a quote in its text (that text must stay byte for byte)."""
    out = set()
    for n in range(1, 6):
        f = ROOT / f"steps/stage{n}/workdir/stage{n}_update/changes.json"
        if f.exists():
            out |= {p["doc"].removeprefix("docs/") for c in load(f)["changes"] for p in c.get("patches", [])
                    if re.search(r"['\u2018\u2019\"\u201c\u201d]|\\u20", p["find"] + p["replace"])}
    return out


CURLY = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"'})


def straight(value):
    if isinstance(value, dict):
        return {k: straight(v) for k, v in value.items()}
    if isinstance(value, list):
        return [straight(v) for v in value]
    return value.translate(CURLY) if isinstance(value, str) else value


def styles(apply):
    """Every planned or new doc gets its folder's background habits: whether it has a status field, curly or straight
    apostrophes, and the order of its keys (drawn from background docs with the same keys)."""
    done = load(OUT / "results.json")
    rels = {(n, rel) for n, rel, _ in planned_docs()}
    rels |= {(e["stage"], e["rel"]) for k, e in done.items() if e.get("new")}
    if (OUT / "round2.json").exists():  # blend_round2.py's new docs
        rels |= {(e["stage"], e["rel"]) for e in load(OUT / "round2.json").values() if e.get("new")}
    corpus = Corpus()
    patched = patched_docs()
    habits = {}
    made = {rel for n, rel in rels}
    for f, docs in corpus.bg.items():
        docs = [(r, d) for r, d in docs if r not in made]  # the background as it came, not what this script added
        n = len(docs)
        orders = collections.defaultdict(collections.Counter)
        for _, d in docs:
            orders[frozenset(d)][tuple(d)] += 1
        habits[f] = {"status": sum("status" in d for _, d in docs) / n,
                     "curly": sum("\u2019" in json.dumps(d, ensure_ascii=False) for _, d in docs) / n,
                     "orders": orders}
    report = collections.Counter()
    for n, rel in sorted(rels):
        paths = [p for p in stage_path(n, rel) if p.exists()]
        h = habits.get(folder_of(rel))
        if not paths or not h:
            continue
        doc = load(paths[0])
        old = json.dumps(doc)
        rng = random.Random("style/" + rel)
        if "status" in doc and str(doc["status"]).lower() not in ("draft", "superseded", "archived", "deprecated") \
                and rng.random() > h["status"]:
            del doc["status"]
            report["status dropped"] += 1
        if "\u2019" in json.dumps(doc, ensure_ascii=False) and rng.random() > h["curly"] and rel not in patched:
            doc = straight(doc)
            report["straight quotes"] += 1
        orders = h["orders"].get(frozenset(doc))
        if orders:
            order = weighted(orders, rng)
            if tuple(doc) != order:
                doc = {k: doc[k] for k in order}
                report["keys reordered"] += 1
        if json.dumps(doc) != old:
            report["docs changed"] += 1
            if apply:
                for p in paths:
                    write_doc(p, doc)
    print(dict(report), "(applied)" if apply else "(dry run)")


def title_style(t):
    t = str(t)
    if " " not in t and "-" in t:
        return "slug"
    return "lower" if t[:1].islower() else "upper"


def restyle_title(t, style):
    if style == "slug":
        return slug(t)
    if style == "lower":
        return " ".join(w if re.search(r"\d|[A-Z]{2}", w) else w.lower() for w in t.split())
    return t[:1].upper() + t[1:]


def shapes(apply):
    """Rule threads shaped like their folder's background threads (review 3): message form drawn from the folder's
    forms, fewer and longer messages (the shortest added talk goes, never a planned sentence, a patched passage, the
    first message or the message right before a planned one), and title casing (Capitalised, lower case, slug)
    drawn from the folder's titles. New docs this script wrote get the form and the title casing."""
    done = load(OUT / "results.json")
    planned = {(n, rel): m for n, rel, m in planned_docs()}
    rels = set(planned) | {(e["stage"], e["rel"]) for e in done.values() if e.get("new")}
    if (OUT / "round2.json").exists():
        rels |= {(e["stage"], e["rel"]) for e in load(OUT / "round2.json").values() if e.get("new")}
    corpus = Corpus()
    made = {rel for _, rel in rels}
    finds = collections.defaultdict(list)
    for n in range(1, 6):
        for c in load(ROOT / f"steps/stage{n}/workdir/stage{n}_update/changes.json")["changes"]:
            for pt in c.get("patches", []):
                finds[pt["doc"].removeprefix("docs/")].append(pt["find"])
    habit = {}
    for f, docs in corpus.bg.items():
        docs = [d for r, d in docs if r not in made and d.get("source_system") == "slack"]
        if not docs:
            continue
        forms = collections.Counter(msg_format(d["messages"][0]) or "other" for d in docs
                                    if isinstance(d.get("messages"), list) and d["messages"] and isinstance(d["messages"][0], str))
        lens = [statistics.median(len(x) for x in d["messages"]) for d in docs
                if isinstance(d.get("messages"), list) and d["messages"] and all(isinstance(x, str) for x in d["messages"])]
        habit[f] = {"forms": forms, "titles": collections.Counter(title_style(d.get("title", "")) for d in docs),
                    "msg_len": statistics.median(lens), "count": statistics.median(len(d.get("messages") or []) for d in docs)}
    report = collections.Counter()
    for n, rel in sorted(rels):
        h = habit.get(folder_of(rel))
        paths = [p for p in stage_path(n, rel) if p.exists()]
        if not h or not paths:
            continue
        doc = load(paths[0])
        msgs = doc.get("messages")
        if not isinstance(msgs, list) or not msgs or not all(isinstance(x, str) for x in msgs):
            continue
        old = json.dumps(doc)
        rng = random.Random("shape/" + rel)
        m = planned.get((n, rel))
        if m:  # fewer, longer messages: drop the shortest added talk
            keep_text = [cd.norm(x).rstrip(".") for x in m["must_contain"]] + [cd.norm(x) for x in finds.get(rel, [])]
            fixed = {i for i, x in enumerate(msgs) if any(k in cd.norm(x) for k in keep_text)}
            fixed |= {0} | {i - 1 for i in fixed if i > 0}
            alive = list(range(len(msgs)))
            for i in sorted((i for i in alive if i not in fixed), key=lambda i: len(msgs[i])):
                lens = [len(msgs[j]) for j in alive]
                if (statistics.median(lens) >= h["msg_len"] * 0.9 and len(alive) <= h["count"] + 1) or len(alive) <= 6:
                    break
                if sum(lens) - len(msgs[i]) < corpus.median_len(folder_of(rel)) * 0.7:
                    break  # the thread stays about its folder's length
                alive.remove(i)
            if len(alive) < len(msgs):
                doc["messages"] = [msgs[i] for i in alive]
                speakers = {(stamp_of(x) and FORMAT_RE[stamp_of(x)[0]].match(x).group(1)) for x in doc["messages"]}
                doc["participants"] = [x for x in doc.get("participants", []) if x in speakers] or doc.get("participants")
                report["messages dropped"] += len(msgs) - len(alive)
        k = msg_format(doc["messages"][0])
        st = [stamp_of(x) for x in doc["messages"]]
        target = weighted(h["forms"], rng)
        if k and target not in (k, "other") and all(msg_format(x) == k for x in doc["messages"]) \
                and (target in NO_TIME or all(st)):
            out = []
            day = datetime.fromisoformat(str(doc.get("created_at") or "2026-03-02")[:10])
            for x, s_ in zip(doc["messages"], st):
                g = FORMAT_RE[k].match(x)
                name = g.group(2) if k == "datefirst" else g.group(1)
                t = s_[1] if s_ else None
                if t is not None and t.year == 2000:  # a time with no date: the thread's own day
                    t = t.replace(year=day.year, month=day.month, day=day.day)
                out.append(FORMATS[target][1](name, t) + x[g.end():])
            doc["messages"] = out
            report[f"form {k} -> {target}"] += 1
        style = weighted(h["titles"], rng)
        if title_style(doc.get("title", "")) != style:
            doc["title"] = restyle_title(doc["title"], style)
            report["title restyled"] += 1
        if json.dumps(doc) != old:
            report["docs changed"] += 1
            if apply:
                for p in paths:
                    write_doc(p, doc)
    print(dict(sorted(report.items(), key=lambda x: -x[1])[:14]), "(applied)" if apply else "(dry run)")


def main():
    erb_paths.require_in_sync()  # the generator's copy must match the repo's docs (sync_erb_sources.py)
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--job", choices=["expand", "lookalike", "money", "refunds", "all"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--install", action="store_true")
    ap.add_argument("--trim", action="store_true")
    ap.add_argument("--planned", action="store_true")
    ap.add_argument("--clock", action="store_true")
    ap.add_argument("--style", action="store_true")
    ap.add_argument("--shape", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    corpus = Corpus()
    items = plan(corpus, random.Random(2026))
    if args.plan:
        c = collections.Counter(i["job"] for i in items)
        print(dict(c))
        for f in ("slack/refunds-desk", "confluence/customer-policies", "slack/support-team"):
            print(f, "median", int(corpus.median_len(f)), "formats", dict(corpus.formats(f).most_common(3)),
                  "multi-field share", round(corpus.multi_share(f), 2))
        for i in items:
            if i["job"] == "lookalike" and i["rule"] in ("R1", "R12"):
                print(" ", i["key"], i["dir"], "|", i["words"][:80])
        return
    if args.install:
        return install(items)
    if args.trim:
        return shorten(args.apply)
    if args.planned:
        return planned(args.apply)
    if args.clock:
        return clocks(args.apply)
    if args.style:
        return styles(args.apply)
    if args.shape:
        return shapes(args.apply)
    done = load(OUT / "results.json") if (OUT / "results.json").exists() else {}
    todo = [i for i in items if (args.job in ("all", i["job"])) and i["key"] not in done]
    if args.limit:
        todo = todo[:args.limit]
    phrases, banned = cd.rule_phrases(), banned_words()
    fns = {"expand": expand, "lookalike": lookalike, "money": money, "refunds": refunds}

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
            if item["job"] in ("lookalike", "refunds"):
                rel, doc = res
                if rel is None:
                    failed.append((item["key"], "no free name"))
                    continue
                staged = STAGED / str(item.get("stage", 0)) / rel
                entry = {"stage": item.get("stage", 0), "rel": rel, "new": True, "rule": item.get("rule")}
            else:
                doc, staged = res, STAGED / str(item.get("stage", 0)) / item["rel"]
                entry = {"stage": item.get("stage", 0), "rel": item["rel"], "new": False}
            write_doc(staged, doc)
            done[item["key"]] = {**entry, "note": note}
            if k % 20 == 0:
                (OUT / "results.json").write_text(json.dumps(done, indent=1, sort_keys=True) + "\n")
                print(f"  {k}/{len(todo)}", flush=True)
    (OUT / "results.json").write_text(json.dumps(done, indent=1, sort_keys=True) + "\n")
    usage = [json.loads(x) for x in (OUT / "usage.jsonl").read_text().splitlines()] if (OUT / "usage.jsonl").exists() else []
    print(f"staged {len(todo) - len(failed)}/{len(todo)}; all staged so far: {len(done)}/{len(items)}; tokens so far: "
          f"{sum(u['input'] for u in usage):,} in, {sum(u['output'] for u in usage):,} out over {len(usage)} calls")
    for key, note in failed:
        print("  FAILED", key, "-", note[:200])


def referenced():
    """Every doc path any ticket, rule, plan, stage change or manifest names (those docs are never removed)."""
    out = set()
    files = [f for f in (ROOT / "tests").rglob("*.json")] + list((ROOT / "docs_build").glob("stage*/manifest.json"))
    files += [f for f in (ROOT / "steps").rglob("changes.json")]
    for f in files:
        out |= set(re.findall(r"(?:docs|sources)/((?:slack|confluence)/[^\"\s]+?\.json)", f.read_text()))
    return out


def trim(items, done):
    """Docs to remove so each stage keeps its size: stage 0 stays at 9,999 (from the oversized support-playbooks
    folder, 15.7% of the corpus against a 5% guide); a later stage gives up one background top-up doc per new
    lookalike, as far as it has top-up docs."""
    rng = random.Random(7)
    keep = referenced() | {i["rel"] for i in items if i["job"] in ("money", "expand")}
    keep |= {e["rel"] for e in done.values() if e["new"]}
    new = collections.Counter(s for s, _ in {(e["stage"], e["rel"]) for e in done.values() if e["new"]})
    out = {}
    corpus = Corpus()
    pool = sorted(rel for rel, _ in corpus.bg["confluence/support-playbooks"] if rel not in keep)
    out[0] = sorted(rng.sample(pool, new[0]))
    for n in range(1, 6):
        u = ROOT / f"steps/stage{n}/workdir/stage{n}_update/new_docs"
        planned = {p[len("sources/"):] for p in load(ROOT / f"docs_build/stage{n}/manifest.json")["docs"]}
        topup = sorted(str(f.relative_to(u)) for f in u.rglob("*.json")
                       if str(f.relative_to(u)) not in planned and str(f.relative_to(u)) not in keep)
        out[n] = sorted(rng.sample(topup, min(new[n], len(topup))))
    return out


def install(items):
    done = load(OUT / "results.json")
    keys = {i["key"] for i in items}
    missing = keys - set(done)
    if missing:
        print(f"{len(missing)} items not staged, left out: {', '.join(sorted(missing))}")
    added = collections.defaultdict(list)
    for key, e in sorted(done.items()):
        n, rel = e["stage"], e["rel"]
        text = (STAGED / str(n) / rel).read_text()
        for p in stage_path(n, rel):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        if e["new"]:
            added[n].append("sources/" + rel)
    snap = ROOT / "docs_build/base_corpus.txt"
    lines = snap.read_text().splitlines()
    snap.write_text("".join(x + "\n" for x in lines + [a for a in added[0] if a not in lines]))
    for n in range(1, 6):
        f = ROOT / f"steps/stage{n}/workdir/stage{n}_update/new_docs.txt"
        lines = f.read_text().splitlines()
        f.write_text("".join(x + "\n" for x in lines + [a for a in added[n] if a not in lines]))
    gone = trim(items, done)
    for n, rels in gone.items():
        for rel in rels:
            for p in stage_path(n, rel):
                p.unlink()
    snap = ROOT / "docs_build/base_corpus.txt"
    drop = {"sources/" + r for r in gone[0]}
    snap.write_text("".join(x + "\n" for x in snap.read_text().splitlines() if x not in drop))
    for n in range(1, 6):
        f = ROOT / f"steps/stage{n}/workdir/stage{n}_update/new_docs.txt"
        drop = {"sources/" + r for r in gone[n]}
        f.write_text("".join(x + "\n" for x in f.read_text().splitlines() if x not in drop))
    (OUT / "removed.json").write_text(json.dumps(gone, indent=1) + "\n")
    looks = {e["rel"]: {"stage": e["stage"], "rule": e["rule"]} for e in done.values() if e.get("rule")}
    (OUT / "lookalikes.json").write_text(json.dumps(looks, indent=1, sort_keys=True) + "\n")
    print(f"installed {len(done)} docs ({sum(len(v) for v in added.values())} new: "
          f"{', '.join(f'stage {n}: {len(v)}' for n, v in sorted(added.items()))}); removed "
          f"{', '.join(f'stage {n}: {len(v)}' for n, v in sorted(gone.items()))}. "
          "Now rerun package_stages.py and the checks.")


if __name__ == "__main__":
    main()
