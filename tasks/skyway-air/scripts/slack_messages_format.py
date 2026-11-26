"""Store the planned Slack docs' text the way the background Slack docs store it: a "messages" list.

    python3 slack_messages_format.py            # report only
    python3 slack_messages_format.py --apply    # rewrite the planned Slack docs of every stage

EnterpriseRAG's project step (the planned rule docs) writes a Slack thread as one "body" or "content" string; its bulk
step (the background) writes a "messages" list of "Name — 2:22 PM: text". Left as is, the field alone tells rule docs
from noise. Each turn becomes one message in the background's most common form; continuation lines join their turn.
The words do not change: a doc is refused if any of its required sentences, or any speaker turn, would be lost.
Rewrites stage 0 in EnterpriseRAG's sources and in environment/app/docs, and stages 1-5 in their update folders, in
the generator's layout (indent 2, ASCII escapes, no trailing newline).
"""
import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import erb_paths  # noqa: E402
from erb_paths import SOURCES  # noqa: E402
NAME = r"[A-Z][A-Za-z'\-]+(?: [A-Z][A-Za-z'\-]+){1,2}"  # McKay, O'Neil
TIME = r"(?:\d{4}-\d{2}-\d{2}[ T]|[A-Z][a-z]{2} \d{1,2}, )?\d{1,2}:\d{2}(?: ?[AP]M)?"  # "10:14 AM", "Aug 14, 10:18 AM"
TURN = re.compile(rf"^\s*({NAME})\s*(?:—|-|·|\[|\()?\s*({TIME})\s*[\])]?\s*(?:—|-|:)?\s*(.*)$")
UNTIMED = re.compile(rf"^\s*({NAME}):\s+(.*)$")  # "Mina Shah: text"


def clock(start, i):
    """A time for an untimed turn: the doc's own start, three minutes a turn ("10:18 AM")."""
    h, m = divmod(start + 3 * i, 60)
    return f"{(h % 12) or 12}:{m:02d} {'AM' if h % 24 < 12 else 'PM'}"


def turns(text, start=600):
    out = []
    for line in str(text).split("\n"):
        m = TURN.match(line)
        u = None if m else UNTIMED.match(line)
        if m:
            out.append([m.group(1), m.group(2), m.group(3).strip()])
        elif u:
            out.append([u.group(1), clock(start, len(out)), u.group(2).strip()])
        elif line.strip():
            if not out:
                return None  # text before any speaker: not a thread this script understands
            out[-1][2] = (out[-1][2] + " " + line.strip()).strip()
    return [f"{name} — {time}: {words}" for name, time, words in out]


def norm(s):
    return " ".join(str(s).replace("’", "'").split()).lower()


def convert(doc, must_contain):
    field = (doc.get("content_field_names") or [None])[0]
    if field not in doc:
        return None, "no content field"
    if field == "messages" and isinstance(doc[field], list):
        return None, "already messages"  # a list, as the background has it (a "messages" string still needs splitting)
    value = doc[field]
    when = re.search(r"T(\d{2}):(\d{2})", str(doc.get("created_at") or ""))
    start = int(when.group(1)) * 60 + int(when.group(2)) if when else 600
    if isinstance(value, list):
        msgs = [m for item in value for m in (turns(item, start) or [str(item)])]
    else:
        msgs = turns(value, start)
    if not msgs:
        return None, "no speaker turns found"
    before, after = norm(value if isinstance(value, str) else " ".join(map(str, value))), norm(" ".join(msgs))
    lost = [s for s in must_contain if norm(s).rstrip(".") in before and norm(s).rstrip(".") not in after]
    if lost:
        return None, f"would lose {lost[0][:50]!r}"
    new = {}
    for k, v in doc.items():  # same key order, the text field renamed in place
        if k == field:
            new["messages"] = msgs
        elif k == "content_field_names":
            new[k] = ["messages"]
        else:
            new[k] = v
    return new, f"{len(msgs)} messages"


def targets():
    """(stage, path, must_contain) for every planned Slack doc, where it lives now."""
    out = []
    for n in range(6):
        man = json.loads((ROOT / f"docs_build/stage{n}/manifest.json").read_text())["docs"]
        for rel, m in man.items():
            if not rel.startswith("sources/slack/"):
                continue
            if n == 0:
                for base in (SOURCES, ROOT / "environment/app/docs"):
                    out.append((0, base / rel[len("sources/"):], m["must_contain"]))
            else:
                out.append((n, ROOT / f"steps/stage{n}/workdir/stage{n}_update/new_docs" / rel[len("sources/"):],
                            m["must_contain"]))
    return out


def main():
    erb_paths.require_in_sync()  # the generator's copy must match the repo's docs (sync_erb_sources.py)
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    done, skipped, refused = 0, 0, []
    for n, path, must in targets():
        doc = json.loads(path.read_text())
        new, why = convert(doc, must)
        if new is None:
            if why == "already messages":
                skipped += 1
            else:
                refused.append(f"stage {n} {path.name}: {why}")
            continue
        done += 1
        if args.apply:
            path.write_text(json.dumps(new, indent=2))
    print(f"{'converted' if args.apply else 'would convert'} {done} planned Slack docs; {skipped} already use messages")
    for r in refused:
        print("  REFUSED", r)


if __name__ == "__main__":
    main()
