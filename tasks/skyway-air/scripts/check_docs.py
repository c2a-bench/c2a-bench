"""Check generated docs against a stage's doc plan.

    python3 check_docs.py --stage 0 [--sources tools/doc-gen/generated_data/sources]

Planned docs (docs_build/stage<N>/manifest.json):
  - the file exists and is valid JSON;
  - every planned sentence is in it, word for word (case, curly quotes and spacing aside);
  - it states no money amount, percentage or hours/days figure that its own sentences do not contain;
  - it does not call itself outdated, superseded or replaced, and does not point to another page;
  - traps read as current (the same), and lookalikes stay on their topic.
Every doc (planned or background):
  - no topic from must_not_mention;
  - background docs state no dollar amount that grants, limits or decides something for a customer, no rule amount
    said about a customer, and no percentage next to a policy word. Team budgets and vendor costs may use any amount.
Writes docs_build/stage<N>/check.json and docs_build/stage<N>/regenerate.txt (planned docs to delete and write again).
"""
import argparse
import json
import re
from erb_paths import SOURCES  # noqa: E402
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "})
MONEY = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?")
PCT = re.compile(r"\b\d+(?:\.\d+)?\s?%")
SPAN = re.compile(r"\b\d+\+?\s?(?:hours?|days?)\b", re.I)
STALE = re.compile(r"\b(superseded|outdated|obsolete|out of date|no longer (?:valid|applies|in effect|current)|deprecated|"
                   r"(?:rule|policy|limit|rate|guidance|page|amount)s? (?:has|have|was|were) (?:been )?replaced|"
                   r"old (?:rule|policy|limit|rate)|expired)\b", re.I)  # "the card was replaced" is not about policy
WEATHER = re.compile(r"\b(weather|storms?|snow|thunderstorms?|air traffic control|airport security)\b", re.I)
BENEFIT = re.compile(r"\b(goodwill|compensation|travel credit|meal (?:money|vouchers?|allowance)|vouchers?|hotels?|reimburs\w+)\b", re.I)
GRANT = re.compile(r"\b(arrang\w*|book(?:ed|ing)? (?:the |a )?(?:rooms?|hotels?)|we can (?:offer|give|cover|arrange)|go ahead|approved?|"
                   r"offer(?:ed|ing)?|giv(?:e|en|ing)|stag(?:e|ed|ing)|issu(?:e|ed|ing)|cover(?:ed|ing)?)\b", re.I)
REFUSE = re.compile(r"\b(cannot|can't|can not|not eligible|isn't covered|is not covered|no (?:hotel|meal|voucher|goodwill)|"
                    r"only for (?:delays|overnights|cancellations)|not on us)\b", re.I)


def weather_benefit(body):
    """A weather-type disruption next to a benefit being given, in a message (or a message and its reply), that is not
    refused within the next few messages by a reply about the same benefit. A refusal of something else, or one
    elsewhere in the doc, does not excuse a grant here."""
    paras = [x for x in body.split("\n") if x.strip()]  # a message, or a line or field of a page
    for i in range(len(paras)):
        for para in paras[i:i + 2], paras[i:i + 1]:  # a message and the reply after it, or the message alone
            text = " ".join(para)
            if WEATHER.search(text) and BENEFIT.search(text) and GRANT.search(text):
                given = {m.group(0).lower().rstrip("s") for m in BENEFIT.finditer(text)}
                refused = any(REFUSE.search(x) and given & {m.group(0).lower().rstrip("s") for m in BENEFIT.finditer(x)}
                              for x in paras[i:i + 4])  # a question answered "no" a few messages on
                if not refused:
                    return text.strip()[:160]
    return None


POINTER = re.compile(r"\bsee (?:the )?[\w' -]{2,40} (?:page|pages|policy|playbook|thread)\b", re.I)


def norm(s):
    return re.sub(r"\s+", " ", s.translate(QUOTES)).strip().lower()


def text_of(value):
    """Every string in a generated doc, joined; metadata keys and ids left out."""
    if isinstance(value, dict):
        # one line a field, so a page's sections stay apart (a refusal in one does not answer a grant in another)
        return "\n".join(text_of(v) for k, v in value.items() if k not in ("dataset_doc_uuid", "content_field_names", "title_field_name"))
    if isinstance(value, list):
        return "\n".join(text_of(v) for v in value)  # one line a message, so a Slack doc splits into its messages
    return value if isinstance(value, str) else ""


def figures(s):
    s = s.translate(QUOTES)
    return {norm(x).rstrip(",.;:") for x in MONEY.findall(s) + PCT.findall(s) + SPAN.findall(s)}  # "$200," is "$200"


KEY_PHRASES = ["per room per night", "full 24 hours", "per affected passenger", "travel credit for the fare",
               "fare minus", "original form of payment", "not_covered", "agency-refund", "awaiting-receipts",
               "receipts-needed", "claim-late", "wear-and-tear", "change-denied", "not-authorized", "assistance-failure"]


def rule_phrases():
    """Every planned sentence in any stage (12+ characters) and the key rule phrases, normalized."""
    out = {norm(k) for k in KEY_PHRASES}
    for m in ROOT.glob("docs_build/stage*/manifest.json"):
        for x in json.loads(m.read_text())["docs"].values():
            out |= {norm(s).rstrip(".") for s in x["must_contain"]
                    if (re.search(r"\d|-[a-z]+-|_", s) or len(s) >= 30)  # distinctive only: "do not guess" is everyday wording
                    and not s.startswith("This applies to every request handled from")}  # a date line, decides nothing:
                    # ordinary process notes in the stage updates carry it too (blend_round4.py)
    # A bare label (agency-refund, claim-late, ...) is the name of a tag in the ticket tool, not a rule: ordinary docs
    # name labels too (blend_labels.py), so grepping one does not land on its rule doc. Sentences that say which
    # label goes on which ticket ("label the ticket agency-refund") stay.
    out = {p for p in out if not re.fullmatch(r"[a-z]+(?:-[a-z]+)+", p)}
    return sorted(out, key=len, reverse=True)


DECIDES = re.compile(r"(?i)\b(up to|cap(?:ped)?|limit|maximum|max|per (?:night|passenger|person|day|traveller|bag)|"
                     r"eligib\w*|entitled|qualif\w*|approv\w*|we (?:can )?(?:offer|give|issue|cover)|compensat\w*|"
                     r"vouchers?|goodwill|allowance|travel credit|reimburs\w*|receiv(?:e|es|ed)|grant(?:s|ed)?|award\w*|"
                     r"pa(?:y|id|ys) (?:out|back)|put\w* [^.]{0,30}?towards?|(?:we|i) (?:can|will|'ll|could) "
                     r"(?:put|give|send|add|issue|cover|pay|offer|approve|refund))\b")
# who the money is for: a sentence about a customer or a benefit, not a team budget or a vendor invoice
CUSTOMER_SIDE = re.compile(r"(?i)\b(customers?|passengers?|travell?ers?|guests?|members?|goodwill|compensat\w*|"
                           r"vouchers?|travel credit|credit|hotels?|meals?|refund\w*|reimburs\w*|bags?|baggage)\b")


def policy_money(body):
    """Dollar amounts a background doc must not have: one in a sentence that grants, limits or decides something for a
    customer, or one a rule uses (in any stage) said about a customer. A team card limit or a vendor invoice is fine,
    even "capped at $175 a month", so rule docs are not the only docs with a "$" in a limiting sentence."""
    out = []
    for m in MONEY.finditer(body):
        sent = sentence_at(body, m.start())
        if not CUSTOMER_SIDE.search(sent):
            continue
        if DECIDES.search(sent) or norm(m.group(0)).rstrip(",.;:") in rule_amounts():
            out.append(m.group(0))
    return out


def sentence_at(body, i):
    start = max(body.rfind(c, 0, i) for c in ".!?\n") + 1
    ends = [j for j in (body.find(c, i) for c in ".!?\n") if j >= 0]
    return body[start:min(ends) if ends else len(body)]


_AMOUNTS = None


def rule_amounts():
    """Every dollar amount in any stage's planned sentences or edits."""
    global _AMOUNTS
    if _AMOUNTS is None:
        _AMOUNTS = set()
        for m in ROOT.glob("docs_build/stage*/manifest.json"):
            man = json.loads(m.read_text())
            texts = [s for x in man["docs"].values() for s in x["must_contain"]]
            texts += [e.get(k, "") for e in man.get("edits", []) for k in ("find", "replace")]
            _AMOUNTS |= {norm(a).rstrip(",.;:") for t in texts for a in MONEY.findall(t)}
    return _AMOUNTS


def simhash(text):
    words = re.findall(r"[a-z0-9']+", text.lower())
    shingles = {" ".join(words[i:i + 5]) for i in range(max(1, len(words) - 4))}
    v = [0] * 64
    for sh in shingles:
        h = int.from_bytes(__import__("hashlib").md5(sh.encode()).digest()[:8], "big")
        for i in range(64):
            v[i] += 1 if h >> i & 1 else -1
    return sum(1 << i for i in range(64) if v[i] > 0)


def shape(bodies, titles, sources):
    """Folder spread vs the guides' targets, duplicate titles, near-duplicate bodies, tiny docs."""
    folders = {}
    for path in bodies:
        parts = path.split("/")
        folders[f"{parts[1]}/{parts[2]}"] = folders.get(f"{parts[1]}/{parts[2]}", 0) + 1
    targets = {}
    for src in ("slack", "confluence"):
        g = (sources / src / "agents.md").read_text() if (sources / src / "agents.md").exists() else ""
        m = re.search(r"Suggested distribution: ([^\n]+)", g)
        for part in (m.group(1).rstrip(".").split(";") if m else []):
            name, _, num = part.strip().rpartition(" ")
            if num.isdigit():
                targets[f"{src}/{name}"] = int(num)
    spread = []
    for src in ("slack", "confluence"):
        total_t = sum(v for k, v in targets.items() if k.startswith(src)) or 1
        total_a = sum(v for k, v in folders.items() if k.startswith(src)) or 1
        for k in sorted({*targets, *folders}):
            if k.startswith(src):
                spread.append((k, folders.get(k, 0), round(100 * folders.get(k, 0) / total_a, 1),
                               round(100 * targets.get(k, 0) / total_t, 1)))
    seen_titles = {}
    for path, t in titles.items():
        seen_titles.setdefault(norm(t), []).append(path)
    dup_titles = {t: ps for t, ps in seen_titles.items() if t and len(ps) > 1}
    hashes = {p: simhash(b) for p, b in bodies.items()}
    buckets = {}
    for p, h in hashes.items():
        for band in range(4):
            buckets.setdefault((band, h >> (16 * band) & 0xFFFF), []).append(p)
    near = set()
    for ps in buckets.values():
        if 1 < len(ps) < 50:
            for i, x in enumerate(ps):
                for y in ps[i + 1:]:
                    if bin(hashes[x] ^ hashes[y]).count("1") <= 3:
                        near.add(tuple(sorted((x, y))))
    lengths = sorted(len(b) for b in bodies.values())
    tiny = [p for p, b in bodies.items() if len(b) < 300]
    return {"folders": spread, "duplicate_titles": dup_titles, "near_duplicates": sorted(near), "tiny": tiny,
            "length": {"min": lengths[0], "median": lengths[len(lengths) // 2], "max": lengths[-1]} if lengths else {}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", type=int, required=True)
    ap.add_argument("--sources", default=str(SOURCES))
    args = ap.parse_args()
    n, sources = args.stage, Path(args.sources)
    out = ROOT / "docs_build" / f"stage{n}"
    manifest = json.loads((out / "manifest.json").read_text())
    plan = json.loads(((ROOT / "tests") if n == 0 else (ROOT / f"tests/stages/stage{n}")).joinpath("doc_plan.json").read_text())
    banned = [re.compile(rf"\b{re.escape(w)}\b", re.I) for v in plan["must_not_mention"].values() for w in v["words"]]
    banned += [re.compile(p) for v in plan["must_not_mention"].values() for p in v.get("patterns", [])]

    report, regenerate = {"planned": {}, "background": {}}, []
    for path, m in manifest["docs"].items():
        f = sources / path[len("sources/"):]
        problems = []
        if not f.exists():
            report["planned"][path] = ["not generated"]
            regenerate.append(path)
            continue
        try:
            doc = json.loads(f.read_text())
        except json.JSONDecodeError:
            report["planned"][path] = ["invalid JSON"]
            regenerate.append(path)
            continue
        body = text_of(doc)
        flat = norm(body)
        for s in m["must_contain"]:
            if norm(s).rstrip(".") not in flat:
                problems.append(f"missing sentence: {s}")
        allowed = set().union(*(figures(s) for s in m["must_contain"])) if m["must_contain"] else set()
        extra = sorted(figures(body) - allowed)
        if extra:
            problems.append(f"figures not in its sentences: {extra}")
        if STALE.search(body):
            problems.append(f"stale wording: {STALE.findall(body)[:3]}")
        if POINTER.search(body):
            problems.append(f"points to another page: {POINTER.findall(body)[:2]}")
        for b in banned:
            if b.search(body):
                problems.append(f"banned topic: {b.pattern}")
        wb = weather_benefit(body)
        if wb:
            problems.append(f"weather disruption with a benefit given: {wb}")
        if str(doc.get("status", "")).lower() in ("superseded", "archived", "deprecated"):
            problems.append(f"status {doc.get('status')}")
        report["planned"][path] = problems
        if problems:
            regenerate.append(path)

    planned = set(manifest["docs"])
    phrases = rule_phrases()
    bodies, titles = {}, {}
    for f in sorted(sources.rglob("*.json")):
        path = "sources/" + str(f.relative_to(sources))
        if path in planned:
            continue
        try:
            doc = json.loads(f.read_text())
            body = text_of(doc)
        except json.JSONDecodeError:
            report["background"][path] = ["invalid JSON"]
            continue
        bodies[path], titles[path] = body, str(doc.get("title", ""))
        problems = [f"banned topic: {b.pattern}" for b in banned if b.search(body)]
        flat = norm(body)
        hit = next((ph for ph in phrases if ph in flat), None)
        if hit:
            problems.append(f"rule phrase in a background doc: {hit[:80]}")
        wb = weather_benefit(body)
        if wb:
            problems.append(f"weather disruption with a benefit given: {wb}")
        # a dollar amount that decides something for a customer (policy_money); a percentage next to a policy word
        # (zoom levels and rollout shares are fine). A fare paid or a vendor cost is everyday noise, so rule docs are
        # not the only docs with a "$".
        money = policy_money(body)
        money += [m.group(0) for m in re.finditer(
            r"(?i)\b(?:credit|refund|fee|compensation|bonus|discount|extra|voucher|goodwill)\b[^.]{0,40}\b\d+(?:\.\d+)?\s?%|"
            r"\b\d+(?:\.\d+)?\s?%[^.]{0,40}\b(?:credit|refund|fee|compensation|bonus|discount|extra|voucher|goodwill)\b", body)]
        if money:
            problems.append(f"amounts in a background doc: {money[:4]}")
        if problems:
            report["background"][path] = problems

    report["shape"] = shape(bodies, titles, sources)
    (out / "check.json").write_text(json.dumps(report, indent=2) + "\n")
    (out / "regenerate.txt").write_text("".join(p + "\n" for p in regenerate))
    bad_bg = {k: v for k, v in report["background"].items() if v}
    ok = sum(1 for v in report["planned"].values() if not v)
    print(f"stage {n}: planned docs {ok}/{len(manifest['docs'])} pass; background docs with problems: {len(bad_bg)}")
    kinds = {}
    for v in report["planned"].values():
        for p in v:
            kinds[p.split(":")[0]] = kinds.get(p.split(":")[0], 0) + 1
    for k, c in sorted(kinds.items(), key=lambda x: -x[1]):
        print(f"  {k}: {c}")
    for path, v in list(bad_bg.items())[:10]:
        print(f"  background {path}: {v}")
    sh = report["shape"]
    print(f"background shape: {len(bodies)} docs; lengths {sh['length']}; {len(sh['duplicate_titles'])} duplicate titles; "
          f"{len(sh['near_duplicates'])} near-duplicate pairs; {len(sh['tiny'])} tiny docs")
    off = [(k, a, pa, pt) for k, a, pa, pt in sh["folders"] if abs(pa - pt) >= 5]
    for k, a, pa, pt in off:
        print(f"  folder {k}: {a} docs = {pa}% (guide {pt}%)")
    print(f"details: {out / 'check.json'}; to write again: {out / 'regenerate.txt'} ({len(regenerate)})")


if __name__ == "__main__":
    main()
