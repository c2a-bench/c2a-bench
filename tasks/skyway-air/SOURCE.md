# Source

Skyway Air is a fictional airline. Its docs were generated with the [EnterpriseRAG-Bench](https://github.com/onyx-dot-app/EnterpriseRAG-Bench) generator (MIT) from the policy, ticket and doc plans in `scripts/`.

## Regenerate or extend the docs

The generator, with the Skyway company setup it was run with, is in `tools/doc-gen` (see its `C2A.md`).
The docs are not in git. Download them first, from the repo root:

```bash
python3 scripts/fetch_bench.py --revision <commit>
```

That fills `environment/app/docs`, each stage's `new_docs` and the grader's files. Those downloaded docs are the source
of truth.

The published task is these scripts' output plus one more step, the large policy (`large_policy/`, see its
`DESIGN.md`): about 550 extra policy docs in areas no ticket touches, and a 12,000-token cap on every model call of the
support agent. `skyway-arch` in the scripts' comments is the internal name of that published task.

1. Set up the generator (Python 3.10+):

   ```bash
   cd tools/doc-gen && python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
   ```

2. Fill its working copy of the docs from the repo (run it again after every pull):

   ```bash
   python3 tasks/skyway-air/scripts/sync_erb_sources.py --apply
   ```

3. Model keys come from the repo's `.env` (`OPENAI_API_KEY`). `scripts/stage_generation.py` prints the generator
   commands it needs, with the environment set (`LLM_MODEL_NAME`, `USAGE_LOG`, ...); each script in `scripts/` says
   in its own docstring what it writes and which checks to run after it (`check_docs.py`, `giveaway_audit.py`,
   `package_stages.py --replay`, and `scripts/leak_check.py` at the repo root).

Scripts that write stage-0 docs into both the repo and the generator's copy stop when the two do not match; run
step 2 and try again. `ERB_GEN_DIR` points the scripts at another generator checkout.

Every ticket has one customer behaviour, set in the ticket scripts (`scripts/behavior/types.json` at the repo root
lists them). The facts the judge checks come from `python3 scripts/build_facts.py tasks/skyway-air`, run from the repo
root after the ticket scripts. `tests/rule_parts.json` lists which parts of its rules each ticket needs (made by
`scripts/label_rule_parts.py`); the ticket scripts and `build_facts.py` read it, one fact per needed part.

## Stage 0 from scratch

The generator writes with a model, so a rerun gives a new corpus with the same plan, not the same files. Commands run from `tasks/skyway-air` unless they say otherwise; `GEN` is the
generator command prefix that `stage_generation.py` prints (venv, `.env`, model names, `PYTHONPATH`, `USAGE_LOG`).

1. **Company** (generator steps 1-5): already done. `tools/doc-gen/generated_data/` holds the company
   overview, initiatives, employee directory, folder layout and folder guides. Skip these steps.
2. **Tickets, rules and doc plans**: `python3 scripts/build_stage0_tickets.py`, then
   `python3 scripts/build_stage_tickets.py` (stages 1-5).
3. **Planned docs as generator projects**: `python3 scripts/build_doc_projects.py` writes
   `docs_build/stage<N>/projects/` and `manifest.json` for every stage.
4. **Generate**: copy `tools/doc-gen/generation_cache.stage0` to `generation_cache` (it holds stage 0's
   projects and the topic plan for the background), then, in `tools/doc-gen`:
   `GEN && python -m src.scripts.data_gen_stage_1_generate_clean_data.step_7_generate_project_documents` (the planned
   rule docs) and `... .step_9_generate_volume_documents --doc-parallelism 10` (the background, about 9,800 docs).
   They write into `generated_data/sources`. The saved topic plan records the docs already written (each topic's
   `completed`): for a full rerun, set every `completed` to 0 in `generation_cache/volume/*.json` first, or step 9
   writes only what is left.
5. **Fix the generated docs** (each has a report-only mode; `--apply` writes):
   `check_docs.py --stage 0` (planned docs that fail are listed in `docs_build/stage0/regenerate.txt`: delete them
   and run step 7 again, it skips docs it already wrote), `add_policy_sentences.py`, `fix_staff_names.py`,
   `slack_messages_format.py`, `spread_background_dates.py` (before the snapshot), `drift_check.py`.
6. **Make it the repo's stage 0**: copy `generated_data/sources` to `environment/app/docs`, then
   `python3 scripts/separate_stage_docs.py --snapshot`.
7. **Later stages**: `stage_generation.py --stage N --apply` (or `--apply-all`), run the commands it prints,
   `separate_stage_docs.py --stage N --apply`, `stage_generation.py --fix-dates N --apply`, then `--restore`.
8. **Blending and leak fixes**, in the order they were added: `blend_docs.py`, `blend_round2.py` to
   `blend_round4.py`, `split_docs.py`, `rename_rule_docs.py`, `shorten_background_names.py`,
   `add_policy_lookalikes.py`, `blend_labels.py`. Each stages its output first and applies with `--apply` or
   `--install` (see its docstring).
9. **Package and check**: `package_stages.py --replay environment/app/docs`, `check_docs.py --stage N` for every
   stage, `giveaway_audit.py`, `split_check.py`, and `python3 ../../scripts/leak_check.py` from here.

Step 4 is where most of the model cost is (the generator's own note: steps 7 and 9 write the corpus).
