"""Fill the doc generator's working copy (generated_data/sources) from the repo's stage-0 docs.

    python3 sync_erb_sources.py            # report what differs
    python3 sync_erb_sources.py --apply    # make the generator's sources an exact copy of environment/app/docs

The repo's docs are the source of truth: renames, new docs and edits made here (for example the background renames
and policy look-alikes from shorten_background_names.py and add_policy_lookalikes.py) reach the generator's copy, never the other way round. Only .json docs are copied
or removed; the folder guides (agents.md) the generator reads stay as they are. Run it before any script that writes
stage-0 docs into both places (they call erb_paths.require_in_sync() and stop otherwise), and after pulling.
"""
import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from erb_paths import ENV_DOCS, SOURCES, differences  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    missing, extra, changed = differences()
    print(f"{SOURCES}: {len(missing)} docs missing, {len(extra)} extra, {len(changed)} different from {ENV_DOCS}")
    if not a.apply:
        return
    for rel in missing + changed:
        dst = SOURCES / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ENV_DOCS / rel, dst)
    for rel in extra:
        (SOURCES / rel).unlink()
    for d in sorted((p for p in SOURCES.rglob("*") if p.is_dir()), key=lambda p: -len(p.parts)):
        if not any(d.iterdir()):
            d.rmdir()
    missing, extra, changed = differences()
    print(f"after: {len(missing)} missing, {len(extra)} extra, {len(changed)} different")
    sys.exit(1 if missing or extra or changed else 0)


if __name__ == "__main__":
    main()
