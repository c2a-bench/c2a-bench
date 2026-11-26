"""Reword every station, country and Slack-update sentence once, so no script can pack the pages.

    uv run --no-project --with litellm==1.103.2 python3 reword.py      # with the model keys from the repo's .env; fills reword_map.json
    python3 reword.py --check                                           # check the map only

facts.py builds each fact from one of 2-3 templates per fact type. Gate B (2026-11-12) showed a builder packing all
202 station pages with ~50 regex rewrites into ~7k tokens. Here a model (REWORD_MODEL, default openai/gpt-6.1-terra)
rewrites each sentence on its own, so the same kind of fact reads differently on every page. A rewrite is kept only
if it keeps every number, time, capitalised name, code and label of the original, changes the wording, and uses no
excluded term; a sentence that fails three times keeps its original wording.

Sentences: every version a page has in any stage (stage changes move facts, and the moved sentences are reworded
too). The map (original -> rewrite) is fixed once written: plan.py reads it, so rerunning only fills what is missing.
"""
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
MAP = HERE / "reword_map.json"
MODEL = os.environ.get("REWORD_MODEL", "openai/gpt-6.1-terra")

PROMPT = """You reword sentences from an airline's internal station handbook and travel-document pages.

Rewrite each sentence below so it says exactly the same thing in clearly different words: change the sentence
structure and the word order, not just a synonym or two, the way a different colleague would write it. Keep every
number, time (as written, e.g. 05:30), day, month, gate, terminal, zone, partner or network name, airport code, city,
country, phone number and label (e.g. facility-info, docs-check) exactly as it is. Keep every condition and exception
(e.g. "except on Mondays", "for wide-body aircraft", "unless they stay under 12 days"). Do not add facts, advice or
words about refunds, money, delays, bags or anything else. One sentence in, one sentence (or two short ones) out.

Answer with a JSON list of strings, one rewrite per input, in the same order, and nothing else.

{sentences}"""


def tokens_to_keep(s):
    """What a rewrite must keep: numbers and times, capitalised words (names, codes, days, months), labels."""
    keep = set(re.findall(r"\+?\d[\d:]*", s))
    keep |= {w for w in re.findall(r"\b[A-Z][A-Za-z'-]*\b", s)}
    keep |= set(re.findall(r"\b[a-z]+-[a-z]+\b", s)) & {"facility-info", "docs-check"}
    keep.discard(s.split()[0]) if s.split()[0][0].isupper() and not re.match(r"[A-Z]{3}\b", s.split()[0]) else None
    return keep


def problems(orig, new, own=None):
    import plan as P
    out = []
    if not isinstance(new, str) or not new.strip():
        return ["empty"]
    missing = [t for t in tokens_to_keep(orig) if t not in new and t.lower() not in new.lower()]
    if missing:
        out.append(f"lost {missing[:5]}")
    # structure, not vocabulary: share of the original's word pairs still in the rewrite
    pairs = lambda t: set(zip(re.findall(r"[a-z0-9:]+", t.lower()), re.findall(r"[a-z0-9:]+", t.lower())[1:]))
    a, b = pairs(orig), pairs(new)
    if a and len(a & b) / len(a) > 0.7:
        out.append("too close to the original")
    hits = P.excluded_hits(new, own or P.own_station_for_text(new))
    if hits:
        out.append(f"excluded {hits}")
    if len(new) > 2.2 * len(orig) + 40:
        out.append("too long")
    return out


def all_sentences():
    """{group key: [original sentences]}: every version of every station, country and update sentence."""
    import plan as P
    import build_docs as B
    groups = {}
    for code, city in P.STATIONS:
        ss = []
        for n in range(6):
            ch = B.changed_by(code, n)
            ss += P.station_page(code, city, ch, reword=False) + P.station_current(code, city, ch, reword=False)
        u = P.station_update(code, city, reword=False)
        if u:
            ss += u[1]
        groups["station " + code] = list(dict.fromkeys(ss))
    for c in P.COUNTRIES:
        ss = []
        for n in range(6):
            ss += P.country_page(c, B.changed_by(c, n), reword=False)
        groups["country " + c] = list(dict.fromkeys(ss))
    return groups


def ask(sentences):
    import litellm
    text = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(sentences))
    r = litellm.completion(model=MODEL, messages=[{"role": "user", "content": PROMPT.format(sentences=text)}],
                           max_tokens=8000)
    out = r.choices[0].message.content.strip()
    out = re.sub(r"^```(?:json)?\s*|\s*```$", "", out)
    got = json.loads(out)
    if not isinstance(got, list) or len(got) != len(sentences):
        raise ValueError(f"expected {len(sentences)} rewrites, got {len(got) if isinstance(got, list) else type(got)}")
    return got


def own_of(key):
    import plan as P
    kind, name = key.split(" ", 1)
    return (name, dict(P.STATIONS)[name]) if kind == "station" else None


def reword_group(item):
    key, sentences = item
    own = own_of(key)
    done, todo = {}, list(sentences)
    for attempt in range(3):
        if not todo:
            break
        try:
            got = ask(todo)
        except Exception as e:  # a bad answer: try the whole group again
            print(f"  {key}: attempt {attempt + 1} failed: {str(e)[:120]}", flush=True)
            continue
        left = []
        for orig, new in zip(todo, got):
            if problems(orig, new, own):
                left.append(orig)
            else:
                done[orig] = new.strip()
        todo = left
    return key, done, todo


def main():
    import plan as P  # noqa: F401
    rmap = json.loads(MAP.read_text()) if MAP.exists() else {}
    groups = all_sentences()
    total = sum(len(v) for v in groups.values())
    if "--check" in sys.argv:
        owner = {s: own_of(k) for k, ss in groups.items() for s in ss}
        bad = [(o, problems(o, n, owner.get(o))) for o, n in rmap.items() if problems(o, n, owner.get(o))]
        print(f"{len(rmap)} of {total} sentences reworded; {len(bad)} with problems")
        for o, p in bad[:10]:
            print(f"  {o[:70]}: {p}")
        return 1 if bad else 0
    work = [(k, [s for s in v if s not in rmap]) for k, v in groups.items()]
    work = [w for w in work if w[1]]
    print(f"{total} sentences in {len(groups)} pages; {sum(len(w[1]) for w in work)} to reword with {MODEL}")
    kept = 0
    with ThreadPoolExecutor(16) as pool:
        for key, done, left in pool.map(reword_group, work):
            rmap.update(done)
            kept += len(left)
            if left:
                print(f"  {key}: {len(left)} keep their original wording", flush=True)
            MAP.write_text(json.dumps(rmap, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(rmap)} reworded; {kept} kept their original wording")


if __name__ == "__main__":
    raise SystemExit(main())
