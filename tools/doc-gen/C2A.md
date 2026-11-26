# EnterpriseRAG doc generator (copy used for Skyway Air)

This is the [EnterpriseRAG-Bench](https://github.com/onyx-dot-app/EnterpriseRAG-Bench) generator (MIT, see `LICENSE`)
at upstream commit `d36685e273713975ee20299bbf1ab64165575b3c` (2026-05-07), the one Skyway Air's docs were generated
with. It is kept here so anyone can regenerate or extend the Skyway docs.

## What differs from upstream

- `src/llm/openai_llm.py`: logs token usage per model call to `USAGE_LOG` (default `usage.jsonl`);
  `usage_report.py` adds it up. Nothing else in the code is changed.
- `generated_data/`: the Skyway Air company instead of upstream's example company: `company_overview.md`,
  `employee_directory.yaml`, `initiatives.md`, `source_tree.txt`, `visual_employee_directory.txt`, and the folder
  guides the writers follow (`sources/slack/agents.md`, `sources/confluence/agents.md`,
  `sources/confluence/customer-policies/agents.md`, `sources/confluence/support-playbooks/agents.md`).
- `generation_cache.stage0/`: the stage-0 topic plan (`projects.json`, `projects/`, `volume/`). Each later stage's
  generation starts from it (`tasks/skyway-air/scripts/stage_generation.py`).
- Left out: upstream's sample questions (`questions*.jsonl`) and editor settings. The generated docs
  (`generated_data/sources/**/*.json`) are not kept here: the repo's docs are the source of truth.

## The generated docs

In this repo the docs are downloaded, not kept in git: run `python3 scripts/fetch_bench.py --revision <commit>` from
the repo root first.

`generated_data/sources/` is a working copy of `tasks/skyway-air/environment/app/docs` (the stage-0 docs). Fill it
from the repo before using the Skyway scripts:

```bash
python3 tasks/skyway-air/scripts/sync_erb_sources.py --apply
```

Renames and edits made in the repo (for example shorten_background_names.py's renames) reach this copy that way, never the
other way round. Scripts that write stage-0 docs into both places stop if the copy does not match.

To use another checkout of the generator, set `ERB_GEN_DIR` (see `tasks/skyway-air/scripts/erb_paths.py`).
