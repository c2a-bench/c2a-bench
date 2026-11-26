"""Add short policy pages that carry no rule to the two policy spaces, so a small, short-named page there is not a rule page.

    uv run --no-project --with litellm==1.103.2 python3 scripts/add_policy_lookalikes.py          # write the missing pages
    python3 scripts/add_policy_lookalikes.py --check                                              # only check written pages

The rule pages in confluence/customer-policies and confluence/support-playbooks are short pages with short names
(delayed-bags, compensation), while the background there is long (scripts/leak_check.py, check 1: "size <= 4.7 KB in
those folders" kept 74 docs, 16 of them rule pages). Real policy spaces hold many short pages on other topics, so these
are added: one per topic in TOPICS, on a subject no Skyway rule touches (no refunds, credits, fees, claims, labels,
assistance, minors, pets...), written by LOOKALIKE_MODEL (default anthropic/claude-sonnet-5-5) in the shape of a
short background page of the same subfolder, then checked: no digit in the text, no word from AVOID, no
must_not_mention topic, no stale wording, no pointer to another page, at most MAX_BYTES on disk. A page that fails is
asked for again (up to 3 tries) and left out if it never passes.

Written into environment/app/docs (and listed in docs_build/base_corpus.txt and docs_build/lookalike_pages.json for
the generator's copy of the sources to follow). Fixed per path: metadata (author, date, type, uuid) come from a hash
of the path, so a rerun writes only the pages that are missing.
"""
import argparse
import hashlib
import json
import os
import re
import sys

from collections import Counter
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "environment" / "app"
DOCS = APP / "docs"
LIST = ROOT / "docs_build" / "lookalike_pages.json"
MODEL = os.environ.get("LOOKALIKE_MODEL", "anthropic/claude-sonnet-5-5")
MAX_BYTES = 4500
WINDOW = (date(2026, 1, 12), date(2026, 5, 15))  # stage 0's doc window (build_doc_projects.py)

TOPICS = {
    "confluence/customer-policies/baggage": ["Sports Equipment", "Musical Instruments", "Fragile Items",
                                             "Baggage Locks", "Bag Drop", "Oversize Items"],
    "confluence/customer-policies/cancellations-and-refunds": ["Name Corrections", "Booking Confirmations",
                                                               "Itinerary Emails", "Booking Holds"],
    "confluence/customer-policies/delays-and-disruptions": ["Flight Status Alerts", "Gate Changes", "Aircraft Swaps",
                                                            "Boarding Announcements"],
    "confluence/customer-policies/fares-and-changes": ["Fare Display", "Group Bookings", "Upgrade Requests",
                                                       "Price Alerts", "Multi-City Trips"],
    "confluence/customer-policies/loyalty": ["Member Profiles", "Account Merges", "Miles Statements",
                                             "Partner Earning", "Status Letters"],
    "confluence/customer-policies/special-assistance": ["Quiet Spaces", "Hearing Loops", "Large Print",
                                                        "Sign Language"],
    "confluence/support-playbooks/case-handling": ["Call Notes", "Case Merging", "Language Lines",
                                                   "Callback Etiquette", "Duplicate Contacts", "Shift Notes"],
    "confluence/support-playbooks/escalation": ["Shift Handover", "On-Call Rota", "Incident Bridge",
                                                "Paging Etiquette"],
    "confluence/support-playbooks/templates": ["Greeting Lines", "Closing Lines", "Apology Wording",
                                               "Holding Replies", "Out of Office"],
    "confluence/support-playbooks/approvals-and-limits": ["Approver Rota", "Delegation Notes", "Audit Samples"],
}

# Words of the rule topics (every stage's rules.json): a page that uses one could be read as a rule, so it is asked again.
AVOID = ["refund", "credit", "compensat", "reimburs", "hotel", "meal", "voucher", "fee", "label", "tag", "goodwill",
         "claim", "damage", "delayed bag", "wheelchair", "assistance fail", "pet", "minor", "infant", "child", "family",
         "travel manager", "authori", "illness", "doctor", "taxi", "rideshare", "connect", "weather", "storm",
         "injur", "medical", "legal", "lawyer", "discriminat", "approve", "eligib", "entitle", "cancel", "delay",
         "receipt", "allowance", "change fee", "fare difference", "agency", "skyway-controlled", "wear and tear",
         "deadline", "confirmation_id", "payment", "card", "money", "cost", "price", "free", "charge", "paid", "pay "]
# a few topic words are fine in their own title (e.g. "Price Alerts" may say price); checked per page
ALLOW = {"Price Alerts": {"price"}, "Booking Confirmations": set(), "Upgrade Requests": set()}
STALE = re.compile(r"\b(superseded|outdated|obsolete|out of date|deprecated|expired|no longer|replaced)\b", re.I)
POINTER = re.compile(r"\b(see|refer to|check) (the )?[\"'A-Z][^.]{0,60}\b(page|article|playbook|guide|doc)\b", re.I)


def slug(title):
    return "-".join(re.sub(r"[^a-z0-9 ]+", " ", title.lower()).split())


def h(path, salt):
    return int(hashlib.sha256((salt + path).encode()).hexdigest()[:12], 16)


def meta(rel, folder_docs):
    """Author, owner team, document type and date, drawn from the subfolder's own docs (fixed per path)."""
    pick = lambda field: sorted(Counter(d.get(field) for d in folder_docs if d.get(field)).items())
    out = {}
    for field in ("author", "owner_team", "document_type"):
        choices = [v for v, n in pick(field) for _ in range(n)]
        out[field] = choices[h(rel, field) % len(choices)]
    span = (WINDOW[1] - WINDOW[0]).days
    out["last_updated"] = (WINDOW[0] + timedelta(days=h(rel, "date") % (span + 1))).isoformat()
    out["dataset_doc_uuid"] = "dsid_" + hashlib.sha256(("uuid" + rel).encode()).hexdigest()[:32]  # 32 hex, as the corpus
    return out


def example(folder_docs, rel):
    """A short background page of the same subfolder, as the shape to copy."""
    small = sorted(folder_docs, key=lambda d: len(json.dumps(d)))[: max(3, len(folder_docs) // 3)]
    return small[h(rel, "ex") % len(small)]


def body_text(doc):
    keep = {k: v for k, v in doc.items() if k not in ("dataset_doc_uuid", "last_updated", "title_field_name",
                                                      "content_field_names")}
    return json.dumps(keep, ensure_ascii=False)


def problems(doc, title, banned):
    text = body_text(doc)
    low = text.lower()
    out = []
    if re.search(r"\d", text):
        out.append("has a digit")
    allow = ALLOW.get(title, set())
    hits = [w for w in AVOID if w in low and w.strip() not in allow]
    if hits:
        out.append(f"rule-topic words {hits[:6]}")
    for b in banned:
        if b.search(text):
            out.append(f"banned topic {b.pattern[:30]}")
    if STALE.search(text):
        out.append("stale wording")
    if POINTER.search(text):
        out.append("points to another page")
    size = len(json.dumps(doc, indent=2).encode())
    if size > MAX_BYTES:
        out.append(f"{size} bytes")
    if doc.get("title") != title:
        out.append("title changed")
    return out


PROMPT = """You write one internal Confluence page for Skyway Air, a fictional airline. It goes in the space "{folder}".

Here is another page from the same space. Copy its JSON shape: the same kinds of fields (keep the metadata fields
exactly as given below), the same plain, practical tone, written for support staff.

{example}

Write the page titled "{title}". It is a short working page about that subject only. Rules:
- Total length: well under 3,000 characters of text. Short paragraphs or short lists.
- No digits anywhere, and no amounts, prices, percentages, times or durations written in words either.
- Do not mention refunds, travel credit, compensation, reimbursements, hotels, meals, vouchers, fees, charges,
  payments, prices, claims, damage, delays, cancellations, eligibility, approvals, labels or tags, pets, children,
  minors, infants, families, wheelchairs or assistance failures, medical or legal matters, weather, connections,
  agencies, travel managers or who is authorised to ask for things. If the subject brushes one of these, leave it out.
- Do not say the page is old, replaced or superseded, and do not refer the reader to another page or document.
- Describe how staff handle the subject in general terms; do not state customer entitlements.

Metadata (use exactly): {meta}
Set "title" to "{title}", "status" to "current", "source_system" to "confluence", "title_field_name" to "title",
and "content_field_names" to the list of your body field names.

Answer with the JSON object only."""


def ask(prompt):
    import litellm
    r = litellm.completion(model=MODEL, messages=[{"role": "user", "content": prompt}], max_tokens=4000)
    text = r.choices[0].message.content.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    return json.loads(text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="only check the pages already written")
    a = ap.parse_args()
    plan = json.loads((ROOT / "tests" / "doc_plan.json").read_text())
    banned = [re.compile(rf"\b{re.escape(w)}\b", re.I) for v in plan["must_not_mention"].values() for w in v["words"]]
    banned += [re.compile(p) for v in plan["must_not_mention"].values() for p in v.get("patterns", [])]
    written = json.loads(LIST.read_text()) if LIST.exists() else []
    todo, bad = [], 0
    for folder, titles in TOPICS.items():
        for title in titles:
            rel = f"docs/{folder}/{slug(title)}.json"
            if (APP / rel).exists():
                if rel not in written:
                    sys.exit(f"{rel} exists and is not one of ours: pick another title")
                p = problems(json.loads((APP / rel).read_text()), title, banned)
                if p:
                    bad += 1
                    print(f"  FAIL {rel}: {p}")
                continue
            todo.append((folder, title, rel))
    if a.check:
        print(f"{len(written)} pages written, {bad} with problems")
        return 1 if bad else 0
    for folder, title, rel in todo:
        folder_docs = [json.loads(p.read_text()) for p in (DOCS / folder).glob("*.json")]
        m = meta(rel, folder_docs)
        ex = example(folder_docs, rel)
        prompt = PROMPT.format(folder=folder, example=json.dumps(ex, indent=2)[:6000], title=title,
                               meta=json.dumps(m))
        doc, why = None, []
        for _ in range(3):
            try:
                cand = ask(prompt + (f"\n\nYour last answer had these problems, fix them: {why}" if why else ""))
            except (ValueError, KeyError) as e:
                why = [f"not valid JSON: {e}"]
                continue
            cand.update(m)
            cand.update({"title": title, "status": "current", "source_system": "confluence", "title_field_name": "title"})
            why = problems(cand, title, banned)
            if not why:
                doc = cand
                break
        if doc is None:
            print(f"  skipped {rel}: {why}")
            continue
        (APP / rel).write_text(json.dumps(doc, indent=2))
        written.append(rel)
        LIST.write_text(json.dumps(sorted(set(written)), indent=1) + "\n")
        corpus = ROOT / "docs_build" / "base_corpus.txt"
        lines = corpus.read_text().splitlines()
        src = "sources/" + rel[len("docs/"):]
        if src not in lines:
            corpus.write_text("\n".join(lines + [src]) + "\n")
        print(f"  wrote {rel} ({len(json.dumps(doc, indent=2).encode())} bytes)")
    print(f"{len(written)} lookalike pages in total")


if __name__ == "__main__":
    raise SystemExit(main())
