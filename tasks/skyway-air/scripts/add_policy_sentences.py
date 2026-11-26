"""Write into a planned doc any sentence its plan now requires and the generated doc does not have.

    python3 add_policy_sentences.py            # report only
    python3 add_policy_sentences.py --apply    # write them

When a rule gains a sentence after its docs were generated (compensation is given even when the customer did not ask;
a moved missed connection is a change ticket), the doc plan requires it but the doc lacks it. A Confluence page gets it
as a new paragraph; a Slack thread gets it as a new message from someone already in the thread, three minutes after
the last one. Stage 0 is written in EnterpriseRAG's sources and environment/app/docs; stage N in its update folder.
Files keep the generator's layout (indent 2, ASCII escapes, no trailing newline). check_docs.py then checks them.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_docs  # noqa: E402

import erb_paths  # noqa: E402
from erb_paths import SOURCES  # noqa: E402  (the generator's working copy)
TIME = re.compile(r"^(.*?) — (\d{1,2}):(\d{2}) ([AP]M): ")


def later(message):
    """'Name — 2:22 PM: ...' -> (name, '2:25 PM'), or None."""
    m = TIME.match(message)
    if not m:
        return None
    h, mi = int(m.group(2)) % 12 + (12 if m.group(4) == "PM" else 0), int(m.group(3)) + 3
    h, mi = h + mi // 60, mi % 60
    return m.group(1), f"{(h % 12) or 12}:{mi:02d} {'AM' if h % 24 < 12 else 'PM'}"


def add(doc, sentence):
    text = sentence.rstrip(".") + "."
    field = (doc.get("content_field_names") or ["content"])[0]
    value = doc.get(field)
    if isinstance(value, list):
        last = next((later(m) for m in reversed(value) if isinstance(m, str) and later(m)), None)
        if not last:
            return False
        value.append(f"{last[0]} — {last[1]}: {text}")
    elif isinstance(value, str):
        doc[field] = value.rstrip() + "\n\n" + text
    else:
        return False
    return True


def places(n):
    if n == 0:
        return [SOURCES, ROOT / "environment/app/docs"]
    return [ROOT / f"steps/stage{n}/workdir/stage{n}_update/new_docs"]


def main():
    erb_paths.require_in_sync()  # the generator's copy must match the repo's docs (sync_erb_sources.py)
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    changed = 0
    for n in range(6):
        plan = json.loads((ROOT / ("tests/doc_plan.json" if n == 0 else f"tests/stages/stage{n}/doc_plan.json")).read_text())["docs"]
        for d, x in plan.items():
            if n and x.get("added_in") != n:
                continue  # an older doc changes only through its stage's patches
            for base in places(n):
                path = base / d.removeprefix("docs/")
                if not path.exists():
                    continue
                doc = json.loads(path.read_text())
                flat = check_docs.norm(check_docs.text_of(doc))
                missing = [s for s in x["states"] if check_docs.norm(s).rstrip(".") not in flat]
                if not missing:
                    continue
                for s in missing:
                    if not add(doc, s):
                        raise SystemExit(f"stage {n} {d}: cannot place {s!r}")
                print(f"stage {n} {path.relative_to(base.parent)}: + {missing}")
                changed += 1
                if args.apply:
                    path.write_text(json.dumps(doc, indent=2))
    print(f"{'wrote' if args.apply else 'would write'} {changed} docs")


if __name__ == "__main__":
    main()
