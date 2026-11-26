#!/usr/bin/env python3
"""Build the knowledge packs from Rcomplete, one controlled change per pack, and check them.

Rcomplete (steps/Rcomplete/workdir/pack/docs, downloaded by scripts/fetch_bench.py) is the source of truth. Every
other pack differs from it only by its own condition, so a score drop can be blamed on that condition alone:

  Rfragmented   the same sentences, with whole sections moved word for word onto sibling pages
  Rincomplete   the listed facts removed or replaced by placeholders (packs/_extras/Rincomplete/edits.json)
  Rconflicting  Rcomplete plus old drafts/archives that the current pages supersede (packs/_extras/Rconflicting)
  Rnoisy        Rcomplete plus look-alike pages that answer none of the tickets (packs/_extras/Rnoisy)

Builds every pack in a temporary folder, checks that each pack changes only what its condition allows, and compares
it with steps/<pack>/workdir/pack/docs. Exits non-zero if a check fails.

  python3 tasks/support-agent-knowledge/scripts/build_packs.py           # build, check, compare
  python3 tasks/support-agent-knowledge/scripts/build_packs.py --write   # also write the packs into steps/
"""

import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

TASK = Path(__file__).resolve().parents[1]
EXTRAS = TASK / "packs" / "_extras"
STEPS = TASK / "steps"
SOURCE = STEPS / "Rcomplete" / "workdir" / "pack" / "docs"
PACKS = None  # the build folder, set in main()
SP = "confluence/customer-success-and-support/support-process"

NOTES = {
    "Rcomplete": "Cleaned stage-0 docs: traps/decoys removed; authority notes on current policy pages.",
    "Rfragmented": "Same sentences as Rcomplete; whole sections moved word for word onto sibling pages.",
    "Rincomplete": "Listed facts removed (placeholders where a page would say so); nothing else changed.",
    "Rconflicting": "Rcomplete plus wrong archived/draft pages; current pages supersede them.",
    "Rnoisy": "Rcomplete plus look-alike pages that answer none of the tickets.",
}

# Rfragmented: (page, [(sibling page, [section headings moved, in order])]).
SPLITS = [
    (f"{SP}/audit-log-export-request-intake.json", [
        (f"{SP}/audit-log-export-legal-review.json", ["## 3) Legal/Privacy approval (conditional)"]),
        (f"{SP}/audit-log-export-routing.json", ["# Execution routing"]),
    ]),
    (f"{SP}/escalation-classification-and-tagging.json", [
        (f"{SP}/escalation-offering-labels.json", ["## 1) Deployment offering"]),
        (f"{SP}/escalation-symptom-timeout-label.json", ["## 2) Primary symptom", "# Notes on ‘request timeouts’"]),
    ]),
    (f"{SP}/support-playbook-api-key-rotation.json", [
        (f"{SP}/api-key-disable-authorization.json", ["# Emergency revoke procedure (internal)"]),
        (f"{SP}/api-key-compromise-labeling.json", ["# Post-actions"]),
    ]),
    (f"{SP}/token-accounting-discrepancy-intake-and-triage.json", [
        (f"{SP}/token-accounting-label.json", ["## How to avoid double counting"]),
    ]),
]


def field(page):
    return "content" if "content" in page else "body"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def take_section(text, heading):
    """Cut one section (its heading line up to the next heading of the same or a higher level)."""
    m = re.search(rf"(?m)^{re.escape(heading)}[ \t]*$", text)
    if not m:
        raise SystemExit(f"heading not found: {heading!r}")
    level = len(heading) - len(heading.lstrip("#"))
    nxt = re.compile(rf"(?m)^#{{1,{level}}} ").search(text, m.end())
    end = nxt.start() if nxt else len(text)
    return text[:m.start()] + text[end:], text[m.start():end].strip("\n")


def fresh(pack, root):
    out = root / pack / "docs"
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(SOURCE, out)
    return out


def build_fragmented(root):
    out = fresh("Rfragmented", root)
    for page_rel, moves in SPLITS:
        page = load(out / page_rel)
        key = field(page)
        text = page[key]
        for sibling_rel, headings in moves:
            parts = []
            for h in headings:
                text, part = take_section(text, h)
                parts.append(part)
            title = re.sub(r"^#+\s*(\d+\)\s*)?", "", headings[0]).strip()
            sibling = {k: v for k, v in page.items() if k not in ("title", key, "dataset_doc_uuid", "related_pages")}
            sibling = {"title": title, **sibling, key: "\n\n".join(parts) + "\n"}
            dump(out / sibling_rel, sibling)
        page[key] = re.sub(r"\n{3,}", "\n\n", text)
        dump(out / page_rel, page)


def build_incomplete(root):
    out = fresh("Rincomplete", root)
    for e in load(EXTRAS / "Rincomplete" / "edits.json"):
        path = out / e["file"]
        page = load(path)
        key = field(page)
        if page[key].count(e["old"]) != 1:
            raise SystemExit(f"Rincomplete edit not found once in {e['file']}: {e['old'][:60]!r}")
        page[key] = page[key].replace(e["old"], e["new"])
        if "\n\n\n" not in load(SOURCE / e["file"])[key]:
            page[key] = re.sub(r"\n{3,}", "\n\n", page[key])  # a removed section leaves no extra gap
        dump(path, page)


def build_additive(pack, root):
    out = fresh(pack, root)
    shutil.copytree(EXTRAS / pack / "docs", out, dirs_exist_ok=True)


def build_all(root):
    """Build every pack from Rcomplete and packs/_extras into root/<pack>/docs."""
    shutil.copytree(SOURCE, root / "Rcomplete" / "docs")
    build_fragmented(root)
    build_incomplete(root)
    build_additive("Rconflicting", root)
    build_additive("Rnoisy", root)


def tree(path):
    return {str(p.relative_to(path)): p.read_bytes() for p in path.rglob("*") if p.is_file()} if path.exists() else {}


# ---------- checks ----------

def page_text(path):
    if path.suffix != ".json":
        return path.read_text(encoding="utf-8", errors="ignore")
    d = load(path)
    if not isinstance(d, dict):
        return json.dumps(d)
    body = d.get("content") if "content" in d else d.get("body")
    return body if isinstance(body, str) else json.dumps(body)


def lines(pack, skip_titles=False):
    docs = PACKS / pack / "docs"
    out = []
    for p in sorted(docs.rglob("*")):
        if p.is_file() and p.name != "UPSTREAM_LICENSE":
            out += [" ".join(l.split()) for l in page_text(p).splitlines() if l.strip()]
    return out


def check():
    problems = []
    base = sorted(lines("Rcomplete"))
    if sorted(lines("Rfragmented")) != base:
        problems.append("Rfragmented: its page text is not exactly Rcomplete's lines (moved, not changed)")
    for pack in ("Rconflicting", "Rnoisy"):
        docs, ref = PACKS / pack / "docs", PACKS / "Rcomplete" / "docs"
        for p in ref.rglob("*"):
            if p.is_file() and (not (docs / p.relative_to(ref)).exists() or (docs / p.relative_to(ref)).read_bytes() != p.read_bytes()):
                problems.append(f"{pack}: changes Rcomplete page {p.relative_to(ref)} (may only add pages)")
    edits = load(EXTRAS / "Rincomplete" / "edits.json")
    allowed = {e["file"] for e in edits}
    docs, ref = PACKS / "Rincomplete" / "docs", PACKS / "Rcomplete" / "docs"
    for p in ref.rglob("*"):
        if p.is_file():
            q = docs / p.relative_to(ref)
            if not q.exists():
                problems.append(f"Rincomplete: drops page {p.relative_to(ref)}")
            elif q.read_bytes() != p.read_bytes() and str(p.relative_to(ref)) not in allowed:
                problems.append(f"Rincomplete: changes page {p.relative_to(ref)} outside its edit list")
    incomplete = "\n".join(lines("Rincomplete"))
    for term in ("symptom-timeout", "offering-hosted", "offering-dedicated", "offering-private",
                 "Mark the SUP ticket label", "route to Eng Infra", "cross-region export is requested",
                 "escalation_status = Eng engaged"):
        if term in incomplete:
            problems.append(f"Rincomplete: removed fact still readable: {term!r}")
    for pack in NOTES:
        if tree(PACKS / pack / "docs") != tree(STEPS / pack / "workdir" / "pack" / "docs"):
            problems.append(f"{pack}: steps/{pack}/workdir/pack/docs differs from the fresh build"
                            + ("" if "--write" in sys.argv else "; --write replaces it"))
    for p in problems:
        print("  -", p)
    print("packs check:", "OK" if not problems else f"{len(problems)} problem(s)")
    return not problems


def main():
    global PACKS
    if not SOURCE.is_dir():
        sys.exit(f"{SOURCE} missing: run python3 scripts/fetch_bench.py --revision <commit> from the repo root first")
    with tempfile.TemporaryDirectory() as tmp:
        PACKS = Path(tmp)
        build_all(PACKS)
        if "--write" in sys.argv:
            for pack in NOTES:
                dst = STEPS / pack / "workdir" / "pack" / "docs"
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(PACKS / pack / "docs", dst)
        ok = check()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
