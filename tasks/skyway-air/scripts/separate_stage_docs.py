"""Keep the base corpus at stage 0: snapshot it, and move a later stage's new docs into that stage's update.

    python3 separate_stage_docs.py --snapshot          # once, when stage 0 is final
    python3 separate_stage_docs.py --stage N [--apply] # after generating stage N's docs
    python3 separate_stage_docs.py --discard           # move docs not in the snapshot to a quarantine folder

--stage N moves out of EnterpriseRAG's sources every doc that is not in the stage-0 snapshot (the stage's planned docs
and its background top-up) into steps/stage<N>/workdir/stage<N>_update/new_docs/, the layout redwood-inference uses,
and lists them. Without --apply it only reports. It refuses if a planned doc of stage N is missing (run step 7 again:
it skips the docs it already wrote) or if the background top-up is short or long (step 9 counts --doc-limit as a
maximum and does not fail on a failed doc: run it again). A move that stops halfway can be run again; new_docs.txt
lists everything in the stage's folder. --discard clears a failed stage out of the sources so the base corpus is the
snapshot again.
"""
import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from erb_paths import ERB, SOURCES  # noqa: E402
SNAPSHOT = ROOT / "docs_build" / "base_corpus.txt"
BACKUP = ERB / "pilot-backup-2026-10-31"  # --discard puts a failed stage's docs here


def current():
    return {"sources/" + str(f.relative_to(SOURCES)) for f in SOURCES.rglob("*.json")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", action="store_true")
    ap.add_argument("--stage", type=int)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--discard", action="store_true")
    args = ap.parse_args()
    if args.snapshot:
        docs = sorted(current())
        SNAPSHOT.write_text("".join(d + "\n" for d in docs))
        print(f"stage-0 snapshot: {len(docs)} docs -> {SNAPSHOT}")
        return
    if args.discard:
        if not SNAPSHOT.exists():
            raise SystemExit("no snapshot to compare with")
        extra = sorted(current() - set(SNAPSHOT.read_text().splitlines()))
        quarantine = BACKUP / f"quarantine-{len(list(BACKUP.glob('quarantine-*'))) + 1}"
        for d in extra:
            target = quarantine / d[len("sources/"):]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(SOURCES / d[len("sources/"):]), str(target))
        print(f"moved {len(extra)} docs that are not in the stage-0 snapshot to {quarantine}" if extra else "nothing to discard")
        return
    if not args.stage or not SNAPSHOT.exists():
        raise SystemExit("take the stage-0 snapshot first (--snapshot), then pass --stage N")
    base = set(SNAPSHOT.read_text().splitlines())
    manifest = json.loads((ROOT / f"docs_build/stage{args.stage}/manifest.json").read_text())["docs"]
    new = sorted(current() - base)
    dest = ROOT / f"steps/stage{args.stage}/workdir/stage{args.stage}_update/new_docs"
    moved = {"sources/" + str(f.relative_to(dest)) for f in dest.rglob("*.json")} if dest.exists() else set()
    missing = sorted(set(manifest) - set(new) - moved)  # a resumed move already put some in the stage's folder
    if missing:
        raise SystemExit(f"{len(missing)} planned stage-{args.stage} docs are not generated yet, e.g. {missing[:3]}")
    planned = [d for d in sorted(set(new) | moved) if d in manifest]
    background = [d for d in sorted(set(new) | moved) if d not in manifest]
    want = json.loads((ROOT / f"tests/stages/stage{args.stage}/doc_plan.json").read_text())["new_background_docs"]
    print(f"stage {args.stage}: {len(planned)} planned docs + {len(background)} background docs (plan: {want}) -> {dest}")
    if len(background) != want:
        raise SystemExit(f"the background top-up has {len(background)} docs, the plan {want}: run step 9 again for the "
                         "missing ones, or --discard and start the stage again")
    if not args.apply:
        return
    for d in new:
        target = dest / d[len("sources/"):]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(SOURCES / d[len("sources/"):]), str(target))
    listed = sorted("sources/" + str(f.relative_to(dest)) for f in dest.rglob("*.json"))
    (dest.parent / "new_docs.txt").write_text("".join(d + "\n" for d in listed))
    print(f"moved {len(new)} ({len(listed)} in the stage's folder); the base corpus is back to {len(current())} docs")
    if current() != base:
        raise SystemExit("the sources still differ from the stage-0 snapshot")


if __name__ == "__main__":
    main()
