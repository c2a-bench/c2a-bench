"""Set EnterpriseRAG up to write one later stage's new docs, and put stage 0 back afterwards.

    python3 stage_generation.py --stage N             # dry run: what stage N will generate, nothing changed
    python3 stage_generation.py --stage N --apply     # swap in stage N's projects and background top-up, print commands
    python3 stage_generation.py --restore             # put the stage-0 generation cache back
    python3 stage_generation.py --fix-dates N [--apply]  # after separate_stage_docs: date stage N's background docs in its window
    python3 stage_generation.py --apply-all           # stages 1-5 in one generation run (projects + one topic plan)
    python3 stage_generation.py --route-all [--apply] # after that run: every new doc to its stage's update folder

Stage N's new docs are its planned docs (docs_build/stage<N>/projects, written by step 7) and a background top-up
(doc_plan.json new_background_docs, written by step 9). The top-up comes from the stage-0 topic plan: every topic is
set to done, and k topics, picked by size with a fixed seed, get one more doc whose topic name carries the stage's
date window (the folder guides tell writers to date a doc inside the window its description gives). The stage-0
cache is saved once (generation_cache.stage0) and every stage starts from it, so stages never see each other's docs.
Refuses to --apply before the stage-0 snapshot (separate_stage_docs.py --snapshot) exists.
"""
import argparse
import copy
import json
import random
import shutil
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from erb_paths import ERB, REPO, SOURCES  # noqa: E402
CACHE, SAVED = ERB / "generation_cache", ERB / "generation_cache.stage0"
SNAPSHOT = ROOT / "docs_build/base_corpus.txt"
DATES = {0: "2026-05-20", 1: "2026-07-01", 2: "2026-08-19", 3: "2026-09-02", 4: "2026-11-04", 5: "2026-12-02"}
ENV = (f"cd {ERB} && . .venv/bin/activate && set -a && . {REPO}/.env && set +a && "
       "export LLM_PROVIDER=openai LLM_API_KEY=\"$OPENAI_API_KEY\" LLM_MODEL_NAME=gpt-5.6-terra "
       "CHEAP_LLM_MODEL_NAME=gpt-5.6-luna PYTHONPATH=$PWD USAGE_LOG=usage-skyway.jsonl")
STEP = "python -m src.scripts.data_gen_stage_1_generate_clean_data."


def window(n):
    """Background docs of stage n are dated after the previous stage and before stage n's tickets arrive."""
    day = timedelta(days=1)
    start = datetime.fromisoformat(DATES[n - 1]) + day
    end = datetime.fromisoformat(DATES[n]) - day
    return start.date().isoformat(), end.date().isoformat()


def leaves(topics, path=()):
    """(path, topic dict) for every leaf topic; a topic with sub_topics is not a leaf."""
    for name, t in topics.items():
        if t.get("sub_topics"):
            yield from leaves(t["sub_topics"], path + (name,))
        else:
            yield path + (name,), t


def parent_of(volume, path):
    node = volume["topics"]
    for part in path[:-1]:
        node = node[part]["sub_topics"]
    return node


def stage_volume(source, n, picks):
    """The stage-0 topic plan of one source with every topic done, and the picked leaves one doc short."""
    return plan_volume(source, {path: n for path in picks})


def plan_volume(source, stage_of):
    """The stage-0 topic plan of one source with every topic done, and each picked leaf (path -> stage) one doc short,
    its name carrying that stage's date window."""
    volume = json.loads((SAVED / "volume" / f"{source}.json").read_text())
    for path, t in list(leaves(volume["topics"])):
        t["desired"] = t.get("completed", 0)
        if path in stage_of:
            start, end = window(stage_of[path])
            node = parent_of(volume, path)
            renamed = f"{path[-1]} (date this document between {start} and {end})"
            node[renamed] = {**node.pop(path[-1]), "desired": t["completed"] + 1}
    total = sum(t["desired"] for _, t in leaves(volume["topics"]))
    volume.update({"total_docs_in_topics": total,
                   "remaining_doc_count": sum(t["desired"] - t.get("completed", 0) for _, t in leaves(volume["topics"]))})
    return volume


def pick(n, k, exclude=()):
    """k leaf topics over both sources, weighted by their stage-0 size, the same every time for a stage."""
    pool = []
    for source in ("confluence", "slack"):
        volume = json.loads(((SAVED if SAVED.exists() else CACHE) / "volume" / f"{source}.json").read_text())
        pool += [(source, path, t.get("desired", 0)) for path, t in leaves(volume["topics"])
                 if t.get("desired", 0) > 0 and (source, path) not in exclude]
    rng, chosen = random.Random(1000 + n), []
    pool.sort(key=lambda x: (x[0], x[1]))
    while len(chosen) < k and pool:
        i = rng.choices(range(len(pool)), weights=[w for _, _, w in pool])[0]
        chosen.append(pool.pop(i)[:2])
    return chosen


def plan(n):
    doc_plan = json.loads((ROOT / f"tests/stages/stage{n}/doc_plan.json").read_text())
    projects = sorted((ROOT / f"docs_build/stage{n}/projects").glob("*.json"))
    manifest = json.loads((ROOT / f"docs_build/stage{n}/manifest.json").read_text())
    k = doc_plan["new_background_docs"]
    return projects, manifest, k, pick(n, k)


def show(n):
    projects, manifest, k, picks = plan(n)
    start, end = window(n)
    print(f"stage {n}: {len(projects)} projects -> {len(manifest['docs'])} planned docs (step 7); "
          f"{len(manifest['edits'])} doc edits applied at run time by setup.sh, not generated")
    print(f"  background top-up: {k} docs (step 9), dated {start} .. {end}")
    for source, path in picks:
        print(f"    {source}: {' > '.join(path)[:110]}")
    return projects, k, picks


def apply(n):
    if not SNAPSHOT.exists():
        raise SystemExit("freeze stage 0 first: separate_stage_docs.py --snapshot (after the stage-0 run and its checks)")
    sources = SOURCES
    extra = {"sources/" + str(f.relative_to(sources)) for f in sources.rglob("*.json")} - set(SNAPSHOT.read_text().splitlines())
    if extra:
        raise SystemExit(f"{len(extra)} docs in the sources are not in the stage-0 snapshot (an earlier stage not "
                         "separated, or a failed one): separate_stage_docs.py --stage N --apply, or --discard")
    if not SAVED.exists():
        shutil.copytree(CACHE, SAVED)
        print(f"saved the stage-0 cache to {SAVED}")
    projects, k, picks = show(n)
    shutil.rmtree(CACHE)
    shutil.copytree(SAVED, CACHE)
    shutil.rmtree(CACHE / "projects")
    (CACHE / "projects").mkdir()
    (CACHE / "projects.json").unlink(missing_ok=True)  # step 7 writes it from the project files
    for p in projects:
        shutil.copyfile(p, CACHE / "projects" / p.name)
    for source in ("confluence", "slack"):
        mine = {path for s, path in picks if s == source}
        (CACHE / "volume" / f"{source}.json").write_text(json.dumps(stage_volume(source, n, mine), indent=2))
    print(f"\nthe cache now holds stage {n} only. Run, from any folder:\n")
    print(f"  {ENV} && {STEP}step_7_generate_project_documents && "
          + (f"echo y | {STEP}step_9_generate_volume_documents --doc-parallelism 10 --doc-limit {k}" if k else "true"))
    print(f"\nthen: python3 {ROOT / 'scripts/separate_stage_docs.py'} --stage {n} --apply"
          f"\n      python3 {ROOT / 'scripts/stage_generation.py'} --fix-dates {n} --apply"
          f"\n      python3 {ROOT / 'scripts/check_docs.py'} --stage {n}"
          f"\n      python3 {ROOT / 'scripts/stage_generation.py'} --restore")


def pick_all():
    """Every stage's top-up topics, stage by stage, a topic never picked twice (one name carries one window)."""
    out, taken = {}, set()
    for n in range(1, 6):
        k = json.loads((ROOT / f"tests/stages/stage{n}/doc_plan.json").read_text())["new_background_docs"]
        out[n] = pick(n, k, taken)
        taken |= set(out[n])
    return out


def guard():
    if not SNAPSHOT.exists():
        raise SystemExit("freeze stage 0 first: separate_stage_docs.py --snapshot (after the stage-0 run and its checks)")
    extra = current_docs() - set(SNAPSHOT.read_text().splitlines())
    if extra:
        raise SystemExit(f"{len(extra)} docs in the sources are not in the stage-0 snapshot (an earlier stage not "
                         "separated, or a failed one): separate_stage_docs.py --stage N --apply, or --discard")




def current_docs():
    return {"sources/" + str(f.relative_to(SOURCES)) for f in SOURCES.rglob("*.json")}


def apply_all():
    """Stages 1-5 in one run: every stage's projects, and one topic plan with every stage's top-up."""
    guard()
    if not SAVED.exists():
        shutil.copytree(CACHE, SAVED)
        print(f"saved the stage-0 cache to {SAVED}")
    picks = pick_all()
    shutil.rmtree(CACHE)
    shutil.copytree(SAVED, CACHE)
    shutil.rmtree(CACHE / "projects")
    (CACHE / "projects").mkdir()
    (CACHE / "projects.json").unlink(missing_ok=True)
    docs = 0
    for n in range(1, 6):
        for p in sorted((ROOT / f"docs_build/stage{n}/projects").glob("*.json")):
            shutil.copyfile(p, CACHE / "projects" / p.name)
        docs += len(json.loads((ROOT / f"docs_build/stage{n}/manifest.json").read_text())["docs"])
    for source in ("confluence", "slack"):
        stage_of = {path: n for n, ps in picks.items() for s, path in ps if s == source}
        (CACHE / "volume" / f"{source}.json").write_text(json.dumps(plan_volume(source, stage_of), indent=2))
    k = sum(len(v) for v in picks.values())
    print(f"stages 1-5: {len(list((CACHE / 'projects').glob('*.json')))} projects -> {docs} planned docs; "
          f"{k} background docs ({', '.join(f'stage {n}: {len(v)}' for n, v in picks.items())})")
    print(f"\nRun:\n  {ENV} && {STEP}step_7_generate_project_documents --project-parallelism 20 && "
          f"echo y | {STEP}step_9_generate_volume_documents --doc-parallelism 20 --doc-limit {k}")
    print(f"then: python3 {ROOT / 'scripts/stage_generation.py'} --route-all --apply")


def route_all(write):
    """Every new doc to its stage: planned docs by the stage manifests, background docs by the window in the name of
    the topic that wrote them (the topic plan lists each topic's files). Refuses unless every stage is complete and
    every new doc has a stage; after moving, the sources must be the stage-0 snapshot again. A move that stopped
    halfway can be run again: docs already in a stage's folder count for that stage."""
    base = set(SNAPSHOT.read_text().splitlines())
    new = current_docs() - base
    moved = {}
    for n in range(1, 6):
        dest = ROOT / f"steps/stage{n}/workdir/stage{n}_update/new_docs"
        for f in (dest.rglob("*.json") if dest.exists() else []):
            moved["sources/" + str(f.relative_to(dest))] = n
    have = new | set(moved)
    stage_of = dict(moved)
    for n in range(1, 6):
        for d in json.loads((ROOT / f"docs_build/stage{n}/manifest.json").read_text())["docs"]:
            if d in moved and moved[d] != n:
                raise SystemExit(f"{d} is stage {n}'s planned doc but sits in stage {moved[d]}'s folder")
            stage_of[d] = n
    windows = {window(n): n for n in range(1, 6)}
    for source in ("confluence", "slack"):
        volume = json.loads((CACHE / "volume" / f"{source}.json").read_text())
        for path, t in leaves(volume["topics"]):
            m = __import__("re").search(r"date this document between (\S+) and (\S+)\)$", path[-1])
            if m:
                for f in t.get("files", []):
                    rel = f if f.startswith("sources/") else "sources/" + f.split("sources/", 1)[-1]
                    if rel in new:
                        stage_of[rel] = windows[(m.group(1), m.group(2))]
                    elif rel in moved and moved[rel] != windows[(m.group(1), m.group(2))]:
                        raise SystemExit(f"{rel} is in stage {moved[rel]}'s folder but its topic is dated for another stage")
    problems = [f"no stage for {d}" for d in sorted(new - set(stage_of))]
    for n in range(1, 6):
        manifest = json.loads((ROOT / f"docs_build/stage{n}/manifest.json").read_text())["docs"]
        want = json.loads((ROOT / f"tests/stages/stage{n}/doc_plan.json").read_text())["new_background_docs"]
        planned = [d for d in manifest if d in have]
        bg = [d for d in have if stage_of.get(d) == n and d not in manifest]
        print(f"stage {n}: {len(planned)}/{len(manifest)} planned docs, {len(bg)}/{want} background docs")
        if len(planned) != len(manifest):
            problems.append(f"stage {n}: {len(manifest) - len(planned)} planned docs missing (run step 7 again)")
        if len(bg) != want:
            problems.append(f"stage {n}: background {len(bg)} of {want} (run step 9 again)")
    if problems:
        raise SystemExit("NOT MOVED:\n  " + "\n  ".join(problems[:20]))
    if not write:
        return
    for d in sorted(new):
        n = stage_of[d]
        target = ROOT / f"steps/stage{n}/workdir/stage{n}_update/new_docs" / d[len("sources/"):]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(SOURCES / d[len("sources/"):]), str(target))
    for n in range(1, 6):
        dest = ROOT / f"steps/stage{n}/workdir/stage{n}_update/new_docs"
        listed = sorted("sources/" + str(f.relative_to(dest)) for f in dest.rglob("*.json"))
        (dest.parent / "new_docs.txt").write_text("".join(d + "\n" for d in listed))
    if current_docs() != base:
        raise SystemExit("the sources still differ from the stage-0 snapshot")
    print(f"moved {len(new)} docs into stages 1-5; the base corpus is the stage-0 snapshot again")


def restore():
    if not SAVED.exists():
        raise SystemExit("nothing to restore: the stage-0 cache was never saved")
    shutil.rmtree(CACHE)
    shutil.copytree(SAVED, CACHE)
    print("stage-0 generation cache restored")


DATE_FIELDS = ("created_at", "last_updated")


def fix_dates(n, write):
    """Stage n's background docs (moved into its update, not in its manifest) dated outside its window get a date
    inside it: the same day of the window for the same file every time."""
    update = ROOT / f"steps/stage{n}/workdir/stage{n}_update"
    listed = (update / "new_docs.txt").read_text().splitlines()
    planned = set(json.loads((ROOT / f"docs_build/stage{n}/manifest.json").read_text())["docs"])
    start, end = window(n)
    span = (datetime.fromisoformat(end) - datetime.fromisoformat(start)).days
    moved = 0
    for rel in listed:
        if rel in planned:
            continue
        path = update / "new_docs" / rel.removeprefix("sources/")
        doc = json.loads(path.read_text())
        before = moved
        for field in DATE_FIELDS:
            value = str(doc.get(field) or "")
            if value and not (start <= value[:10] <= end):
                day = datetime.fromisoformat(start) + timedelta(days=sum(map(ord, rel)) % (span + 1))
                doc[field] = day.date().isoformat() + value[10:]
                moved += 1
                print(f"  {rel}: {field} {value[:10]} -> {doc[field][:10]}")
        if write and moved > before:  # the generator's layout (indent 2, ASCII escapes, no trailing newline)
            path.write_text(json.dumps(doc, indent=2))
    print(f"stage {n}: {moved} dates outside {start} .. {end}" + ("" if write else " (dry run; --apply writes them)"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", type=int, choices=range(1, 6))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--restore", action="store_true")
    ap.add_argument("--fix-dates", type=int, choices=range(1, 6))
    ap.add_argument("--apply-all", action="store_true")
    ap.add_argument("--route-all", action="store_true")
    args = ap.parse_args()
    if args.apply_all:
        apply_all()
    elif args.route_all:
        route_all(args.apply)
    elif args.restore:
        restore()
    elif args.fix_dates:
        fix_dates(args.fix_dates, args.apply)
    elif args.stage and args.apply:
        apply(args.stage)
    elif args.stage:
        show(args.stage)
    else:
        ap.error("pass --stage N, --restore or --fix-dates N")


if __name__ == "__main__":
    main()
