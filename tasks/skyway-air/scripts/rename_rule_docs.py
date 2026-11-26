"""Name rule docs like the background docs, and give them the background's document types.

    python3 rename_rule_docs.py            # report only
    python3 rename_rule_docs.py --apply    # move the files and fix document types; then rerun the builders

A planned doc whose name gives it away (ends in a number, starts with a date, says thread, draft, temporary, old or
outdated, or carries an amount) gets a name made from its own title, the way background docs are named. It stays in
its folder. A planned doc whose document type the background in that folder never uses gets the folder's most common
background type. The map (docs_build/rename_map.json) is applied by the builders when they write, so rules, doc plans,
stage changes and tickets follow; this script moves the files in EnterpriseRAG's sources, environment/app/docs and the
stage update folders, and the stage-0 snapshot and new_docs lists. Files keep the generator's layout.
"""
import argparse
import collections
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import erb_paths  # noqa: E402
from erb_paths import SOURCES  # noqa: E402
ENV = ROOT / "environment/app/docs"
MAP = ROOT / "docs_build/rename_map.json"
TELL = re.compile(r"(-\d+\.json$|^\d{4}-\d\d-\d\d|thread|draft|temporary|outdated|\bold\b|\d)")
BANNED = {"draft", "temporary", "outdated", "old", "thread", "lookalike", "v", "copy"}


def where(n, rel):
    """Every place a planned doc of stage n lives (rel: path under docs/)."""
    if n == 0:
        return [SOURCES / rel, ENV / rel]
    return [ROOT / f"steps/stage{n}/workdir/stage{n}_update/new_docs" / rel]


TIME_WORDS = {"hour", "hours", "day", "days", "minute", "minutes", "week", "weeks"}


def slug(title):
    """Title words, lowercase. A number stays only before a time word ("24-hour"); amounts and counts go."""
    words = re.sub(r"[^a-z0-9 ]+", " ", title.lower()).split()
    keep = [w for i, w in enumerate(words) if w not in BANNED
            and (not w.isdigit() or (i + 1 < len(words) and words[i + 1] in TIME_WORDS))]
    return "-".join(keep[:8])


def plan():
    """(stage, rel) for every planned doc of every stage."""
    out = []
    for n in range(6):
        for p in json.loads((ROOT / f"docs_build/stage{n}/manifest.json").read_text())["docs"]:
            out.append((n, p[len("sources/"):]))
    return out


def main():
    erb_paths.require_in_sync()  # the generator's copy must match the repo's docs (sync_erb_sources.py)
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    taken = {str(f.relative_to(ENV)) for f in ENV.rglob("*.json")}
    for n in range(1, 6):
        u = ROOT / f"steps/stage{n}/workdir/stage{n}_update/new_docs"
        taken |= {str(f.relative_to(u)) for f in u.rglob("*.json")}
    planned = plan()
    planned_rel = {rel for _, rel in planned}
    # the document types background docs use, per top folder
    types = collections.defaultdict(collections.Counter)
    for f in ENV.rglob("*.json"):
        rel = str(f.relative_to(ENV))
        if rel not in planned_rel:
            types["/".join(rel.split("/")[:2])][json.loads(f.read_text()).get("document_type")] += 1
    renames, retyped = {}, []
    for n, rel in planned:
        path = where(n, rel)[0]
        doc = json.loads(path.read_text())
        name = rel.rsplit("/", 1)[-1]
        if TELL.search(name) and slug(doc.get("title") or "") + ".json" != name:  # already named after its title
            base, folder = slug(doc.get("title") or ""), rel.rsplit("/", 1)[0]
            new, i = f"{folder}/{base}.json", 0
            for extra in ("notes", "question", "follow-up", "check", "update", "review", "handling", "case"):
                if base and new not in taken:
                    break
                new = f"{folder}/{base}-{extra}.json"
            if not base or new in taken:
                raise SystemExit(f"no free name for {rel} (title {doc.get('title')!r})")
            taken.discard(rel)
            taken.add(new)
            renames[rel] = (n, new)
        folder_types = types["/".join(rel.split("/")[:2])]
        if folder_types and folder_types[doc.get("document_type")] < 5:
            retyped.append((n, rel, doc.get("document_type"), folder_types.most_common(1)[0][0]))
    for rel, (n, new) in sorted(renames.items())[:12]:
        print(f"  stage {n}: {rel.rsplit('/', 1)[-1]} -> {new.rsplit('/', 1)[-1]}")
    print(f"{len(renames)} renames, {len(retyped)} document types changed "
          f"({collections.Counter((a, b) for _, _, a, b in retyped).most_common(4)})")
    if not args.apply:
        return
    for n, rel, _, new_type in retyped:
        for path in where(n, rel):
            doc = json.loads(path.read_text())
            doc["document_type"] = new_type
            path.write_text(json.dumps(doc, indent=2))
    old_map = json.loads(MAP.read_text()) if MAP.exists() else {}
    for rel, (n, new) in renames.items():
        for path in where(n, rel):
            target = Path(str(path)[: -len(rel)]) / new  # the same docs root, the new name
            target.parent.mkdir(parents=True, exist_ok=True)
            path.rename(target)
        old_map["docs/" + rel] = "docs/" + new
    # a renamed doc renamed again keeps one hop from its first name
    for k, v in list(old_map.items()):
        while v in old_map and old_map[v] != v:
            v = old_map[v]
        old_map[k] = v
    MAP.write_text(json.dumps(old_map, indent=1, sort_keys=True) + "\n")
    snap = ROOT / "docs_build/base_corpus.txt"
    src = {"sources/" + k[5:]: "sources/" + v[5:] for k, v in old_map.items()}
    snap.write_text("".join(src.get(x, x) + "\n" for x in snap.read_text().splitlines()))
    for n in range(1, 6):
        f = ROOT / f"steps/stage{n}/workdir/stage{n}_update/new_docs.txt"
        f.write_text("".join(src.get(x, x) + "\n" for x in f.read_text().splitlines()))
    print(f"moved; map in {MAP}. Now rerun the builders, build_doc_projects.py and package_stages.py.")


if __name__ == "__main__":
    main()
