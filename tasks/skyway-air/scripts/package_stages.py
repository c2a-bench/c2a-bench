"""Write what Harbor needs for each stage: steps/stage<N>/instruction.md, workdir/setup.sh and stage<N>_update/changes.json.

    python3 package_stages.py               # write the files
    python3 package_stages.py --replay DOCS # also apply stages 1-5 in order to a copy of DOCS (the stage-0 corpus)

The builder's changes.json keeps only what setup.sh needs (patches, and whether the stage has new docs), so nothing in
the container says what changed or why. setup.sh deletes it before the builder starts. New docs come from
separate_stage_docs.py, which puts them in stage<N>_update/new_docs. --replay runs every stage's setup on a temp copy
and fails if a patch's text is missing, so a patch that misses a generated doc is caught before a run.
"""
import argparse
import json
import random
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STEPS = ROOT / "steps"

INSTRUCTION = """\
Skyway Air's support team wants an LLM agent that handles incoming customer support tickets and acts on them in the support system the same way a well-trained support agent would.

## What to build

Build an LLM agent that would answer customer queries and make appropriate actions when required.
by default BOT_MODEL=openai/gpt-5.6-sol

Put the LLM agent in `/app/bot/`. The entrypoint is `/app/bot/run` (executable).

Materials: `/app/docs` (company docs), `/app/api_docs` (support API), `/app/examples` (example tickets + practice data). Practice desk: `python3 /app/server.py --data /tmp/desk --reset-from /app/examples/seed` (see `/app/api_docs`).

At test time `/app/docs` is not readable, so plan accordingly for the knowledge of the LLM agent

The customer sends the first message. The LLM agent is then started:

- **stdin:** `{"ticket_id": "SKY-1234", "customer_id": "cust_x", "message": "customer text"}`
- **stdout:** last line must be `{"ok": true, "reply": "your message to the customer"}`, exit code `0`. Leave out `reply` if you have nothing to say to the customer this time. Add `"end": true` when the conversation is finished (the request is handled, or the customer has been told it cannot be): the customer is then not asked again.

The customer sees only `reply`. Ticket comments are part of the ticket record and are not shown to the customer.

After the LLM agent finishes, the customer may reply again, whether or not the LLM agent replied, unless the LLM agent ended the conversation; the customer can also end it. The new `message` is the conversation so far, one `Customer: ...` or `Support: ...` line per message. The customer sends at most 5 messages, including the first one. All starts of the LLM agent for one ticket share 240 seconds.

Follow-up tickets from the same customer may arrive later. Anything you want to remember about a ticket must be on the ticket or under `/app/bot`.

At test time the LLM agent gets `SUPPORT_API_URL` (support API base URL) `BOT_MODEL`, the model it must use for every chat call, and `EMBED_MODEL`, the model it must use for any embedding call, both in LiteLLM format (e.g. `openai/gpt-5.6-sol`, `openai/text-embedding-3-small`). Call them through the installed `litellm` Python package, without streaming. The model and its settings (reasoning effort, temperature and the like) are fixed at test time: any you set are ignored. The matching provider key is already in the environment. `BOT_MODEL`, `EMBED_MODEL` and the key are also set while you build.

## How the LLM agent works

The LLM agent is LLM-based: the model reads the ticket and decides what to do. Any logic you write in code (lookups, checks, support API actions) must be a tool the model can call; the code must not make decisions on its own. You may also write system prompts or skills, files under `/app/bot` that the LLM agent loads at runtime.

How the company knowledge reaches the model is your choice. Two ways that are supported:

- Retrieval: `rank-bm25` (sparse) and `numpy` are installed, and `litellm.embedding` with `EMBED_MODEL` gives dense vectors. Use sparse, dense or both.
- Notes: compile the docs into linked notes the LLM agent reads or greps at runtime. `/app/skills/llm-wiki/SKILL.md` describes one way.

Only `/app/bot` exists at test time, so any index, notes or prompts must be saved there.


## Describe what you built

Write `/app/bot/ARCHITECTURE.json`. Fill every value with what you actually built. The first five are your own words. `rag` and `subagent` are examples, and any other word is valid.

```json
{
  "architecture_choice": "",
  "how_it_works": "",
  "parts": "",
  "how_docs_reach_the_model": "",
  "memory": "",
  "knowledge_access": [],
  "max_model_calls_per_ticket": null,
  "tools": [],
  "prompt_files": [],
  "skills": [],
  "extra_libraries": [],
  "human_handoff": null,
  "writes_files_at_runtime": null
}
```

- `architecture_choice`: the kind of design, in your own words. `rag` and `subagent` are examples. Any other word is valid.
- `how_it_works`: how a ticket is handled.
- `parts`: the roles in the LLM agent, if there is more than one.
- `how_docs_reach_the_model`: how the company docs get to the model.
- `memory`: what the LLM agent keeps between steps, or none.
- `knowledge_access`: every way the company knowledge reaches the model at runtime; pick all that apply from `llm_wiki` (notes compiled from the docs, read or grepped at runtime), `sparse_retrieval` (keyword search such as BM25) and `dense_retrieval` (embedding search). Leave it empty if none apply.
- `max_model_calls_per_ticket`: the loop's limit for one bot run (the bot runs once per customer message); no run may use more.
- `tools`: every tool offered to the model. Each item is `{"name": "...", "does": "..."}`.
- `prompt_files`, `skills`: files under `/app/bot` whose text is sent to the model (paths relative to `/app/bot`).
- `extra_libraries`: libraries you installed, apart from `litellm`, `requests`, `numpy` and `rank-bm25`.
- `human_handoff`: true if the LLM agent can send a ticket to a person.
- `writes_files_at_runtime`: true if the LLM agent writes files while handling a ticket.
"""

UPDATE = """\
# Update your LLM agent for Skyway Air

You built this LLM agent earlier. It is in `/app/bot/`, as you left it.

The company docs are in `/app/docs`. Update the LLM agent so it follows them as they are now.

Work from the current docs only. Do not compare `/app/docs` with any earlier copy, whether saved in `/app/bot` or anywhere else: no diffs, checksums, file lists or saved manifests used to find which docs are new or changed. If your agent keeps a copy of the docs or an index, rebuild it from the current docs.

Also update `/app/bot/ARCHITECTURE.json` if anything in the design changes.

At test time `/app/docs` is not readable again, so the updated LLM agent must already contain anything it needs under `/app/bot`.


---
"""

SETUP = """\
#!/bin/bash
# Harbor runs this as root, in the same container, before the stage{n} builder.
# Earlier stages already updated /app/docs. This adds this stage's new docs,
# applies its doc and API patches, removes the docs it retires, adds its practice examples, and removes the staging files so the builder
# only sees /app/docs, /app/api_docs and /app/examples. The earlier bot stays at /app/bot.
set -euo pipefail

python3 - "${{1:-/app}}" <<'PY'
import json
import os
import shutil
import sys
from pathlib import Path

DOC_TIME = 1779235200  # 2026-05-20 00:00 UTC, the same time the image gives the stage-0 docs
app = Path(sys.argv[1])
docs = app / "docs"
staging = app / "stage{n}_update"

if (staging / "new_docs").exists():
    shutil.copytree(staging / "new_docs", docs, dirs_exist_ok=True)
changes = json.loads((staging / "changes.json").read_text())
for change in changes["changes"]:
    for patch in change.get("patches", []):
        rel = patch["doc"]
        path = app / rel if rel.startswith("api_docs/") else docs / rel.removeprefix("docs/")
        text = path.read_text()
        if patch["find"] not in text:
            sys.exit(f"{{change['id']}}: {{patch['find']!r}} not found in {{patch['doc']}}")
        path.write_text(text.replace(patch["find"], patch["replace"]))
# docs this stage retires (ordinary pages archived, as a real docs space does)
for rel in changes.get("remove_docs", []):
    path = docs / rel.removeprefix("docs/")
    if not path.exists():
        sys.exit(f"remove_docs: {{rel}} not found")
    path.unlink()
# this stage's new practice examples (a ticket with a hidden runtime condition), with their practice data
extra = staging / "new_examples"
if extra.exists():
    examples = app / "examples"
    cases_path = examples / "cases.json"
    cases = json.loads(cases_path.read_text())
    ids = {{c["id"] for c in cases}}
    cases += [c for c in json.loads((extra / "cases.json").read_text()) if c["id"] not in ids]
    cases_path.write_text(json.dumps(cases, indent=2) + "\\n")
    for src in sorted((extra / "seed").glob("*.json")):
        dest = examples / "seed" / src.name
        data = json.loads(dest.read_text()) if dest.exists() else {{}}
        data.update(json.loads(src.read_text()))
        dest.write_text(json.dumps(data, indent=2) + "\\n")
# one file time for every doc, so new and edited docs do not stand out by their time
for f in list(docs.rglob("*")) + list((app / "api_docs").rglob("*")):
    os.utime(f, (DOC_TIME, DOC_TIME))
shutil.rmtree(staging)
(app / "setup.sh").unlink(missing_ok=True)
PY
"""


CHECK = """\
\"\"\"Grade the stage {n} fixtures and blame fixtures. No model, no Harbor run.

python3 tasks/skyway-air/steps/stage{n}/check/check.py

With environment/app/docs in place, also checks every rule's evidence against the docs as they are at stage {n}
(stages 1-{n} applied with their setup.sh, in order).
\"\"\"

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

N = {n}
HERE = Path(__file__).resolve().parent
TASK = HERE.parents[2]
STAGE = TASK / f"tests/stages/stage{{N}}"
TESTS = TASK / "tests"


def load(path):
    return json.loads(Path(path).read_text())


def main():
    cases = load(STAGE / "cases.json")
    case_ids = {{c["id"] for c in cases}}
    changed = {{c["id"] for c in cases if c.get("change_type", "none") != "none"}}
    blame = [f for f in load(TESTS / "blame_fixtures.json") if f["case"] in case_ids and f["case"] not in changed]
    blame += load(HERE / "blame_fixtures.json")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        blame_path = root / "blame_fixtures.json"
        blame_path.write_text(json.dumps(blame, indent=2) + "\\n")
        app_args = []
        if (TASK / "environment/app/docs").is_dir():
            app = root / "app"
            shutil.copytree(TASK / "environment/app", app)
            for k in range(1, N + 1):
                shutil.copytree(TASK / f"steps/stage{{k}}/workdir/stage{{k}}_update", app / f"stage{{k}}_update")
                subprocess.run(["bash", str(TASK / f"steps/stage{{k}}/workdir/setup.sh"), str(app)], check=True)
            app_args = ["--app", str(app)]
        else:
            print("environment/app/docs is not there yet: rule evidence is not checked against the docs")
        result = subprocess.run([
            sys.executable, str(TESTS / "verify.py"), "check",
            "--cases", str(STAGE / "cases.json"),
            "--seed", str(STAGE / "seed"),
            "--fixtures", str(STAGE / "fixtures"),
            "--rules", str(STAGE / "rules.json"),
            "--blame-fixtures", str(blame_path),
            *app_args,
        ])
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
"""


def escaped(s, doc):
    """Generated docs are ASCII-escaped JSON, so a doc patch's text sits in the file escaped (the API doc is plain)."""
    return s if doc.startswith("api_docs/") else json.dumps(s)[1:-1]


def churn_patches(n):
    """Stage n's ordinary edits (blend_stage_churn.py --edits): small changes to ordinary docs, so a diff against the
    last stage does not list only the rule changes. Not in tests/: the grader never sees them as rule changes."""
    f = ROOT / f"docs_build/blend/churn/edits/stage{n}.json"
    if not f.exists():
        return []
    return [{"doc": v["doc"], "find": v["find"], "replace": v["replace"]}
            for _, v in sorted(json.loads(f.read_text()).items()) if v.get("ok")]


def stripped(n):
    changes = json.loads((ROOT / f"tests/stages/stage{n}/changes.json").read_text())["changes"]
    groups = [c["patches"] for c in changes if c["patches"]] + [[p] for p in churn_patches(n)]
    # rule changes and ordinary edits mixed, in a fixed order per stage: nothing in the file tells them apart
    random.Random(f"stage{n}").shuffle(groups)
    out = []
    for patches in groups:
        out.append({"id": f"change-{len(out) + 1:02d}",
                    "patches": [{"doc": p["doc"], "find": escaped(p["find"], p["doc"]),
                                 "replace": escaped(p["replace"], p["doc"])} for p in patches]})
    removals = ROOT / "docs_build/blend/churn/removals.json"
    remove = json.loads(removals.read_text()).get(str(n), []) if removals.exists() else []
    return {"changes": out, **({"remove_docs": remove} if remove else {})}


def write():
    # The grader runs its own copy of the support server (tests/server.py); it must be the builder's server.
    shutil.copyfile(ROOT / "environment/app/server.py", ROOT / "tests/server.py")
    (STEPS / "stage0").mkdir(parents=True, exist_ok=True)
    (STEPS / "stage0/instruction.md").write_text("# Build an LLM agent for Skyway Air\n\n" + INSTRUCTION)
    for n in range(1, 6):
        work = STEPS / f"stage{n}/workdir"
        (work / f"stage{n}_update").mkdir(parents=True, exist_ok=True)
        (STEPS / f"stage{n}/instruction.md").write_text(UPDATE + INSTRUCTION)
        (work / "setup.sh").write_text(SETUP.format(n=n))
        (STEPS / f"stage{n}/check").mkdir(parents=True, exist_ok=True)
        (STEPS / f"stage{n}/check/check.py").write_text(CHECK.format(n=n))
        (work / "setup.sh").chmod(0o755)
        (work / f"stage{n}_update/changes.json").write_text(json.dumps(stripped(n), indent=1) + "\n")
        print(f"stage {n}: {len(stripped(n)['changes'])} patched changes; new docs: "
              f"{(work / f'stage{n}_update/new_docs').exists()}")


def replay(docs):
    import subprocess
    app = Path(tempfile.mkdtemp())
    shutil.copytree(docs, app / "docs")
    shutil.copytree(ROOT / "environment/app/api_docs", app / "api_docs")
    try:
        for n in range(1, 6):
            shutil.copytree(STEPS / f"stage{n}/workdir/stage{n}_update", app / f"stage{n}_update")
            r = subprocess.run(["bash", str(STEPS / f"stage{n}/workdir/setup.sh"), str(app)], capture_output=True, text=True)
            if r.returncode:
                raise SystemExit(f"stage {n} setup failed: {r.stderr.strip()}")
            print(f"stage {n} applied: {sum(1 for _ in (app / 'docs').rglob('*.json'))} docs")
    finally:
        shutil.rmtree(app)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--replay", type=Path)
    args = ap.parse_args()
    write()
    if args.replay:
        replay(args.replay)


if __name__ == "__main__":
    main()
