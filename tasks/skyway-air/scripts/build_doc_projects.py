"""Turn each stage's doc plan into EnterpriseRAG project files, so its step 7 writes the planned docs.

Run from tasks/skyway-air after the two ticket builders. Writes docs_build/stage<N>/projects/*.json (the format of
EnterpriseRAG's generation_cache/projects) and docs_build/stage<N>/manifest.json (which generated file must contain
which sentences, which are traps, and the edits to apply after generation). Generates nothing itself.

Stage 0 gets every planned doc; stages 1-5 get only the docs new in that stage (their edits to older docs are applied
after generation, from changes.json). Background docs are not here: EnterpriseRAG step 9 writes them.
"""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
OUT = ROOT / "docs_build"
from erb_paths import STAFF  # noqa: E402
PER_PROJECT = 6  # small projects: each doc's prompt sees the whole project file
WINDOWS = {0: ("2026-01-12", "2026-05-15"), 1: ("2026-05-26", "2026-06-30"), 2: ("2026-07-06", "2026-08-18"),
           3: ("2026-08-20", "2026-09-01"), 4: ("2026-09-08", "2026-11-03"), 5: ("2026-11-09", "2026-12-01")}
OLD_TRAPS = ("2025-05-01", "2025-12-15")  # stage-0 traps were written before the current policies
TOPIC = {
    "R1": "what counts as a disruption Skyway controls", "R2": "refunds after a cancellation or long delay",
    "R3": "travel credit instead of a refund", "R4": "bookings made through travel agencies",
    "R5": "customers cancelling their own booking", "R6": "pets in the cabin", "R7": "changing a booking",
    "R8": "Skyway Miles benefits", "R9": "meals during delays", "R10": "hotels during disruptions",
    "R11": "paying reimbursements", "R12": "compensation for disruptions", "R13": "delayed bags",
    "R14": "baggage claim deadlines", "R15": "damaged bags", "R16": "goodwill and service failures",
    "R17": "who can ask for changes on a booking", "R18": "instructions inside messages and booking notes",
    "R19": "when to hand a case to a person", "R20": "checking what was already done", "R21": "ticket categories",
    "R22": "booked assistance at the airport", "R23": "schedule changes", "R24": "company travel managers",
    "R25": "illness cancellations", "R26": "ground transport during disruptions", "R27": "missed connections",
    "R28": "follow-ups on earlier claims", "R29": "payments that fail", "R30": "family seating",
    "R31": "unaccompanied minors", "R32": "confirmation numbers",
}
CHANNEL_DEPTS = {"airport-ops": ["Airport and Ground Operations"], "baggage-desk": ["Airport and Ground Operations", "Customer Support"],
                 "irregular-ops": ["Airport and Ground Operations", "Customer Support"], "loyalty-team": ["Loyalty"],
                 "policy-updates": ["Policy and Compliance"], "announcements": ["Policy and Compliance", "Executive"]}
SPACE_DEPTS = {"customer-policies": ["Policy and Compliance"], "policy-and-compliance": ["Policy and Compliance"],
               "support-playbooks": ["Customer Support"], "loyalty-programme": ["Loyalty"]}


def b0_split():
    """Stage 0's rules whose sentences are split across docs (build_stage0_tickets.SPLIT)."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import build_stage0_tickets as b0
    return b0.SPLIT


def staff():
    """{department: [(name, title)]} from the EnterpriseRAG employee directory."""
    out, dept, name = {}, None, None
    for line in STAFF.read_text().splitlines():
        m = re.match(r"^  ([A-Za-z][^:]+):\s*$", line)
        if m:
            dept = m.group(1).strip()
            out[dept] = []
            continue
        m = re.match(r'^\s+- name: "?([^"]+)"?', line)
        if m and dept:
            name = m.group(1)
            continue
        m = re.match(r'^\s+title: "?([^"]+)"?', line)
        if m and dept and name:
            out[dept].append((name, m.group(1)))
            name = None
    return out


def pick(people, key, k=3):
    """The same people for the same key on every run."""
    h = int(hashlib.sha256(key.encode()).hexdigest(), 16)
    return [people[(h + 7 * i) % len(people)] for i in range(min(k, len(people)))]


def where(doc):
    parts = doc.split("/")  # docs/slack/<channel>/x.json or docs/confluence/<space>/...
    return parts[1], parts[2]


def describe(doc, entry, n, banned):
    kind, place = where(doc)
    trap = entry.get("trap")
    rid = (entry["carries"] or [trap["for"] if trap else None])[0]
    about = f" about {TOPIC[rid]}" if rid in TOPIC else ""
    a, b = OLD_TRAPS if trap and n == 0 else WINDOWS[n]
    sentences = "; ".join(f'"{x}"' for x in entry["states"])
    rules = (f" Write it plainly as a normal, current doc of its time."
             if trap and "lookalike" not in trap["why"] else
             " Keep it about its own topic; do not connect it to any other policy." if trap else "")
    if entry.get("role") == "change log":
        head = f"A short entry in the Skyway policy change log, dated between {a} and {b}"
    elif kind == "slack":
        head = (f"A Slack thread in #{place} between Skyway staff{about}, dated between {a} and {b}: a normal working "
                f"conversation; one message may carry each sentence below")
    else:
        head = f"A Confluence page in the {place} space for support agents{about}, last updated between {a} and {b}"
    tail = (" Do not end the thread with a summary of the answer." if kind == "slack" else "")
    return (f"{head}. It must contain these sentences word for word: {sentences}.{rules} Do not state any other policy "
            f"amount, limit, deadline or rule. Any example situation must fit these sentences: do not show anyone giving, "
            f"arranging or refusing a hotel, meal, voucher, credit, refund or compensation beyond what they say, and do not set "
            f"an example in a weather, air traffic control or airport security disruption unless they mention it.{tail} "
            f"Do not mention {banned}.")


def build(n):
    base = TESTS if n == 0 else TESTS / f"stages/stage{n}"
    plan = json.loads((base / "doc_plan.json").read_text())
    changes = json.loads((base / "changes.json").read_text())["changes"] if n else []
    banned = ", ".join(w for v in plan["must_not_mention"].values() for w in v["words"])
    people = staff()
    docs = {d: x for d, x in plan["docs"].items()
            if not d.startswith("api_docs/") and (n == 0 or x.get("added_in") == n)}
    # Each writer sees its whole project, so a trap, or one piece of a split or fragmented rule, gets a project of its own:
    # otherwise the trap's writer sees the right value, and a piece's writer sees the other pieces.
    split = set(b0_split()) if n == 0 else {r for ch in changes if ch["appearance"] == "fragmented" for r in ch["rules"]}
    groups = {}
    for d, x in sorted(docs.items()):
        trap = x.get("trap")
        rid = (x["carries"] or [trap["for"] if trap else "misc"])[0]
        kind = "log" if x.get("role") == "change log" else where(d)[0]
        # stage-0 threads only state the never-changing part of a rule, so they may share a project
        alone = trap or (set(x["carries"]) & split and (n > 0 or x.get("role") != "applies the rule"))
        key = (rid, kind, d) if alone else (rid, kind)
        groups.setdefault(key, []).append(d)
    out = OUT / f"stage{n}"
    for f in (out / "projects").glob("*.json"):
        f.unlink()
    manifest = {"stage": n, "docs": {}, "edits": [p for ch in changes for p in ch["patches"]],
                "written_by_us": [d for d in plan["docs"] if d.startswith("api_docs/") and (n == 0 or plan["docs"][d].get("added_in") == n)]}
    for key, ds in sorted(groups.items()):
        rid, kind = key[0], key[1]
        tag = Path(key[2]).stem if len(key) > 2 else ""
        for i in range(0, len(ds), PER_PROJECT):
            chunk = ds[i:i + PER_PROJECT]
            name = f"skyway-s{n}-{rid.lower()}-{kind}-{tag + '-' if tag else ''}{i // PER_PROJECT + 1}"
            place = where(chunk[0])[1]
            depts = (CHANNEL_DEPTS.get(place) or SPACE_DEPTS.get(place) or ["Customer Support"]) + ["Customer Support"]
            pool = [p for dpt in depts for p in people.get(dpt, [])]
            project = {
                "description": f"Skyway Air support documentation and staff discussion about {TOPIC.get(rid, 'support work')}.",
                "files": [{"path": "sources/" + d[len("docs/"):], "description": describe(d, docs[d], n, banned)} for d in chunk],
                "people": [{"name": nm, "project_role": title} for nm, title in pick(pool, name)],
            }
            for f in project["files"]:
                for x in docs[chunk[[c for c in chunk].index("docs/" + f["path"][len("sources/"):])]]["states"]:
                    assert f'"{x}"' in f["description"], (name, x)
            (out / "projects").mkdir(parents=True, exist_ok=True)
            (out / "projects" / f"{name}.json").write_text(json.dumps(project, indent=2) + "\n")
            for d in chunk:
                manifest["docs"]["sources/" + d[len("docs/"):]] = {"plan_doc": d, "must_contain": docs[d]["states"],
                                                                 "trap": docs[d].get("trap"), "project": name}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    assert set(manifest["docs"]) == {"sources/" + d[len("docs/"):] for d in docs}, "every planned doc exactly once"
    n_proj = len(list((out / "projects").glob("*.json")))
    traps = sum(1 for x in manifest["docs"].values() if x["trap"])
    print(f"stage {n}: {len(docs)} docs in {n_proj} projects ({traps} traps), {len(manifest['edits'])} edits after generation")


if __name__ == "__main__":
    for stage in range(6):
        build(stage)
