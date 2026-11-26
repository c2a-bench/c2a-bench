"""Replace staff names that are not in the employee directory with real directory people, in background docs.

    python3 fix_staff_names.py            # report only
    python3 fix_staff_names.py --apply    # rewrite the docs

EnterpriseRAG's bulk step invents staff (a few invented people in most docs), while the planned rule docs name only
directory staff, so the names alone would tell rule docs from noise. Each invented person becomes a directory person
of the departments that work in that channel or folder: the same invented name is the same real person within a team,
and different people across teams. Within one doc two different people never collapse into one. Only person names
count (two or three capitalised words, no job words), so a participant like "Loyalty operations lead" is left alone.
Full names, and first names where the first name is unambiguous in that doc, are replaced in every text field. Files
are written exactly as the generator writes them (indent 2, ASCII escapes, no trailing newline). Planned rule docs
are left alone (they were written with real staff). The mapping is kept in docs_build/staff_name_map.json, so later
stages' docs get the same replacements.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import erb_paths  # noqa: E402
from erb_paths import SOURCES  # noqa: E402
from erb_paths import STAFF as DIRECTORY  # noqa: E402
MAP = ROOT / "docs_build" / "staff_name_map.json"
NAME = r"[A-Z][a-z'\-]+(?: [A-Z][a-z'\-]+){1,2}"
SPEAKER = re.compile(rf"(?m)^\s*({NAME})\s+(?:[—\-]\s+\d|\d{{1,2}}:\d{{2}})")
ROLE_ITEM = re.compile(rf"^\s*({NAME})\s*(?:—|-|,|\()\s*[A-Z]")  # "Priya Nair — Privacy and Compliance", "Evan Brooks, Content Design"
JOB_WORDS = {"Lead", "Team", "Desk", "Support", "Operations", "Ops", "Manager", "Agent", "Agents", "Representative",
             "Partner", "Coordinator", "Analyst", "Specialist", "Officer", "Director", "Supervisor", "Station", "Finance",
             "Digital", "Customer", "Airport", "Group", "Bot", "System", "Skyway", "Owner", "Service", "Center",
             "Loyalty", "Member", "Product", "Engineering", "Quality", "Duty", "Shift", "Control", "Legal", "Refunds"}
# Which departments work in each channel or folder (the whole company stands in for company-wide channels).
TEAMS = {
    "slack/airport-ops": ["Airport & Ground Operations"],
    "slack/baggage-desk": ["Customer Support", "Airport & Ground Operations"],
    "slack/digital-team": ["Digital & Technology"],
    "slack/finance-ops": ["Finance"],
    "slack/irregular-ops": ["Flight Operations", "Airport & Ground Operations", "Customer Support"],
    "slack/loyalty-team": ["Loyalty", "Marketing & Communications"],
    "slack/policy-updates": ["Policy & Compliance", "Customer Support"],
    "slack/refunds-desk": ["Customer Support", "Finance"],
    "slack/support-escalations": ["Customer Support"],
    "slack/support-policy-questions": ["Customer Support", "Policy & Compliance"],
    "slack/support-team": ["Customer Support"],
    "confluence/airport-operations": ["Airport & Ground Operations"],
    "confluence/customer-policies": ["Policy & Compliance", "Customer Support"],
    "confluence/digital": ["Digital & Technology"],
    "confluence/finance": ["Finance"],
    "confluence/loyalty-programme": ["Loyalty", "Marketing & Communications"],
    "confluence/policy-and-compliance": ["Policy & Compliance", "Legal"],
    "confluence/support-playbooks": ["Customer Support"],
}


def directory():
    """{department: [names]} from the employee directory."""
    out, dept = {}, None
    for line in DIRECTORY.read_text().splitlines():
        m = re.match(r"^  (\S[^:]*):\s*$", line)
        if m:
            dept = m.group(1)
            continue
        m = re.match(r'^\s+- name: "?([^"\n]+)"?', line)
        if m and dept:
            out.setdefault(dept, []).append(m.group(1).strip())
    return out


def planned_paths():
    out = set()
    for m in ROOT.glob("docs_build/stage*/manifest.json"):
        out |= set(json.loads(m.read_text())["docs"])
    return out


def is_person(name):
    return re.fullmatch(NAME, name) is not None and not (set(name.split()) & JOB_WORDS)


def people_in(doc):
    names = []
    for key in ("participants", "author", "owner", "attendees"):
        v = doc.get(key)
        for p in (v if isinstance(v, list) else [v] if v else []):
            names.append(p if isinstance(p, str) else (p or {}).get("name", ""))
    for v in doc.values():
        for s in (v if isinstance(v, list) else [v]):
            if isinstance(s, str):
                names += SPEAKER.findall(s)
                if isinstance(v, list):
                    names += ROLE_ITEM.findall(s)
    return [n.strip() for n in names if n and is_person(n.strip())]


def replace_all(value, table):
    """Every name in one pass (longest first), so a name just put in is never replaced again: "Priya Nair" ->
    "Lucia Mendoza" must not then have "Lucia" swapped by another person's first-name replacement."""
    if isinstance(value, dict):
        return {k: replace_all(v, table) if k not in ("dataset_doc_uuid",) else v for k, v in value.items()}
    if isinstance(value, list):
        return [replace_all(v, table) for v in value]
    if isinstance(value, str) and table:
        new = dict(table)
        pattern = "|".join(re.escape(old) for old in sorted(new, key=len, reverse=True))
        return re.sub(rf"\b(?:{pattern})\b", lambda m: new[m.group(0)], value)
    return value


def team_of(path):
    return "/".join(path.split("/")[1:3])


def main():
    erb_paths.require_in_sync()  # the generator's copy must match the repo's docs (sync_erb_sources.py)
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--sources", default=str(SOURCES))
    args = ap.parse_args()
    depts = directory()
    everyone = sorted({n for names in depts.values() for n in names})
    mapping = json.loads(MAP.read_text()) if MAP.exists() else {}
    if mapping and not all(isinstance(v, dict) for v in mapping.values()):
        mapping = {}  # an older flat, report-only mapping
    planned = planned_paths()
    known = sorted({n for names in mapping.values() for n in names if n not in everyone}, key=len, reverse=True)
    changed, invented = 0, set()
    for f in sorted(Path(args.sources).rglob("*.json")):
        path = "sources/" + str(f.relative_to(args.sources))
        if path in planned:
            continue
        raw = f.read_text()
        doc = json.loads(raw)
        # people named in the doc's fields, and any invented person already mapped who is mentioned in its text
        names = list(dict.fromkeys(people_in(doc) + [n for n in known if n in raw]))
        fake = [n for n in names if n not in everyone]
        if not fake:
            continue
        team = team_of(path)
        pool = sorted({n for d in TEAMS.get(team, depts) for n in depts.get(d, [])}) or everyone
        taken = {n for n in names if n in everyone}
        table = []
        for n in fake:
            invented.add(n)
            chosen = mapping.setdefault(team, {}).get(n)
            if chosen is None:
                chosen = pool[int(hashlib.sha256(f"{team}|{n}".encode()).hexdigest(), 16) % len(pool)]
                mapping[team][n] = chosen
            target, i = chosen, everyone.index(chosen)
            while target in taken:  # two different people in one doc stay two people
                i = (i + 1) % len(everyone)
                target = everyone[i]
            taken.add(target)
            table.append((n, target))
        firsts = {}
        for old, new in table:
            firsts.setdefault(old.split()[0], []).append((old, new))
        first_table = [(f0, pairs[0][1].split()[0]) for f0, pairs in firsts.items()
                       if len(pairs) == 1 and sum(1 for n in names if n.split()[0] == f0) == 1]
        new_doc = replace_all(doc, table + first_table)
        if new_doc != doc:
            changed += 1
            if args.apply:
                f.write_text(json.dumps(new_doc, indent=2))  # the generator's own layout
    MAP.parent.mkdir(parents=True, exist_ok=True)
    MAP.write_text(json.dumps(mapping, indent=2, sort_keys=True) + "\n")
    print(f"{'rewrote' if args.apply else 'would rewrite'} {changed} background docs; {len(invented)} invented names "
          f"mapped to directory staff by team (mapping: {MAP})")


if __name__ == "__main__":
    main()
