"""Give the stage-0 background docs dates that do not tell them apart from the rule docs.

    python3 spread_background_dates.py            # report only
    python3 spread_background_dates.py --apply    # rewrite created_at / last_updated

EnterpriseRAG's bulk step dated half the background docs on one day (2026-04-22). Rule docs keep their dates (a trap
page dated 2025 is how a bot tells an old draft from the current page), so the background follows them: each doc's
day is, half the time, the day of a rule doc and, otherwise, an even pick between 2026-01-01 and 2026-05-15 (the
folder guides' window). The pick is fixed per file path; the time of day and time zone stay. Files are written as the
generator writes them (indent 2, ASCII escapes, no trailing newline). Run before the stage-0 snapshot.
"""
import argparse
import collections
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import erb_paths  # noqa: E402
from erb_paths import SOURCES  # noqa: E402
FIELDS = ("created_at", "last_updated")
START, END = date(2026, 1, 1), date(2026, 5, 15)


def planned_paths():
    out = set()
    for m in ROOT.glob("docs_build/stage*/manifest.json"):
        out |= set(json.loads(m.read_text())["docs"])
    return out


def day_of(doc):
    return next((str(doc[k])[:10] for k in FIELDS if doc.get(k)), None)


def main():
    erb_paths.require_in_sync()  # the generator's copy must match the repo's docs (sync_erb_sources.py)
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    planned = planned_paths()
    files = sorted(SOURCES.rglob("*.json"))
    rule_days = sorted(d for f in files if "sources/" + str(f.relative_to(SOURCES)) in planned
                       for d in [day_of(json.loads(f.read_text()))] if d)
    span = (END - START).days
    before, after, changed = collections.Counter(), collections.Counter(), 0
    for f in files:
        rel = "sources/" + str(f.relative_to(SOURCES))
        if rel in planned:
            continue
        doc = json.loads(f.read_text())
        h = int(hashlib.sha256(rel.encode()).hexdigest(), 16)
        day = rule_days[(h >> 8) % len(rule_days)] if h % 2 else (START + timedelta(days=(h >> 8) % (span + 1))).isoformat()
        new = dict(doc)
        for k in FIELDS:
            if doc.get(k):
                new[k] = day + str(doc[k])[10:]
        before[day_of(doc)] += 1
        after[day] += 1
        if new != doc:
            changed += 1
            if args.apply:
                f.write_text(json.dumps(new, indent=2))  # the generator's own layout
    bg = sum(after.values())
    print(f"{'rewrote' if args.apply else 'would rewrite'} the dates of {changed} of {bg} background docs")
    print("  busiest day before:", [(d, f"{100 * c / bg:.0f}%") for d, c in before.most_common(3)])
    print("  busiest day after: ", [(d, f"{100 * c / bg:.1f}%") for d, c in after.most_common(3)])
    shares = sorted(((rule_days.count(d) / (rule_days.count(d) + after[d]), d) for d in set(rule_days)), reverse=True)
    print("  highest share of rule docs on any day:", f"{100 * shares[0][0]:.0f}% on {shares[0][1]}" if shares else "none")


if __name__ == "__main__":
    main()
