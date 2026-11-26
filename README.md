<img width="6400" height="3600" alt="Option C · Ticket field" src="https://github.com/user-attachments/assets/f07fd8d2-0d03-4332-8f08-53ba3a4c9a5c" />

# C2A Bench

C2A (Context to Agent) tests how well an AI model builds a customer support agent from a company's internal docs, and
keeps it right as the docs change. A **builder** model reads the docs and writes an agent; the **grader** sends the
agent graded support tickets, a simulated customer answers its questions, and each ticket passes or fails on what the
agent did. A **fact judge** then explains every failure.

- Benchmark data (docs, changes, tickets, seed): [`observeai/c2a-bench`](https://huggingface.co/datasets/observeai/c2a-bench)
- Results of every published run: [`observeai/c2a-bench-runs`](https://huggingface.co/datasets/observeai/c2a-bench-runs)
- This repo: the code to run the benchmark (`tasks/`, `scripts/`), the code that made its data, and the results viewer (`viewer/`)

| Task | What it tests |
|---|---|
| `redwood-inference` | 6 stages: the docs change between stages and the builder updates its agent (290 graded tickets) |
| `support-agent-knowledge` | the same 67 tickets with 5 versions of the docs: complete, fragmented, incomplete, conflicting, noisy |
| `skyway-air` | 6 stages on a large airline doc base, with the agent's design fixed per run (6 architectures, 311 tickets) |

## Run the benchmark

### 1. Install

```bash
git clone https://github.com/c2a-bench/c2a-bench && cd c2a-bench
```

- Python 3.11+, [uv](https://docs.astral.sh/uv/), Docker (running)
- [Harbor](https://pypi.org/project/harbor/), which runs the stages in containers: `uv tool install harbor`

### 2. Download the data

The tasks here hold only code. Fill them with the benchmark data from Hugging Face, pinned to a commit:

```bash
uv run --with huggingface_hub python3 scripts/fetch_bench.py --revision 76e9806cbd77860265fab7c3473e94860c5014bb
```

This writes, per task, what the builder gets (the docs, API reference, practice tickets, instructions, each stage's
doc changes, each knowledge pack, Skyway's architectures) and what the grader reads (the graded tickets, rules, facts
and seed). The downloaded files are git-ignored.

Check the setup: each stage ships hand-written outcomes that must pass or fail (`steps/<stage>/check/`).

```bash
python3 tasks/redwood-inference/steps/stage1/check/check.py
```

### 3. Keys and settings

```bash
cp .env.example .env
```

Fill in the provider keys your models need (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`,
`OPENROUTER_API_KEY`). `BOT_MODEL` is the model every agent uses (published results: `openai/gpt-5.6-sol`, which also
plays the customer), so builders compare on what they built, not on the model behind it. The fact judge uses
`JUDGE_MODEL` / `FACTS_MODEL` (default `openai/gpt-6.1-sol`).

### 4. Run

One command runs every stage of a task and then judges it:

```bash
# Codex
bash scripts/run_with_judge.sh redwood-inference -a codex -m openai/gpt-6.1-sol \
    --agent-setup-timeout-multiplier 3 --ak web_search=disabled --ak reasoning_effort=high

# Claude Code
bash scripts/run_with_judge.sh redwood-inference -a claude-code -m anthropic/claude-opus-5-5 \
    --agent-setup-timeout-multiplier 3 --ak disallowed_tools=WebSearch,WebFetch --ak reasoning_effort=high

# pi (any LiteLLM model, e.g. through OpenRouter)
bash scripts/run_with_judge.sh redwood-inference -a pi -m openrouter/z-ai/glm-5.3 \
    --agent-setup-timeout-multiplier 3 --ak thinking=high
```

Use `support-agent-knowledge` the same way. For `skyway-air`, give the architecture (a name from
`tasks/skyway-air/architectures/`, or `all` for all six at once):

```bash
bash scripts/run_arch.sh wiki-index -a codex -m openai/gpt-6.1-sol \
    --agent-setup-timeout-multiplier 3 --ak web_search=disabled --ak reasoning_effort=high
```

These are the settings of the published runs. The builder's web tools are off, so it works only from the docs.

Want your model on the leaderboard? See [CONTRIBUTING.md](CONTRIBUTING.md).

### What happens

1. **Run** (Harbor): for each stage, the builder builds or updates the agent in its container; then the grader
   (`tasks/<task>/tests/`) resets the support system from the seed, plays each ticket with the simulated customer,
   and checks the end state, the agent's calls and its reply. The run lands in `tasks/<task>/jobs/<run>/`.
2. **Fact judge**, automatically once the run finishes:
   - `scripts/fact_metrics.py`: a model reads the agent's files and decides which facts from the docs it has (rule
     recall and precision), and another reads each conversation for the customer facts the agent obtained. Every failed
     ticket gets its reasons: the builder missed a fact, the agent misused it, or the failure was on the harness's side.
   - `scripts/fact_run.py`: writes `tasks/<task>/jobs/<run>-facts/`, the run with those reasons. This is the result
     to read. Pass/fail and scores are the run's own.

   The judge has two modes: `paste` (default; the agent's files go into the judge's prompt) and `folder` (Codex CLI or
   Claude Code in Docker opens the agent's files itself; used for Skyway, whose agents hold indexes and graphs).
   At most `JUDGE_SLOTS` judges (default 2) run at once on the machine.

Useful variants:

```bash
bash scripts/run_with_judge.sh --judge-only tasks/<task>/jobs/<run>         # judge a finished run again
SKIP_JUDGE=1 bash scripts/run_with_judge.sh redwood-inference ...            # run without judging
python3 scripts/regrade.py --help                                           # re-grade chosen tickets of a finished run
```

`regrade.py` re-tests only some tickets with the same agent (no rebuild), e.g. tickets lost on the harness's side
(a model provider timing out). Then judge the run again with `--judge-only`.

## How the data was made

Each task's `SOURCE.md` says how its docs, rules and tickets were made, and how to run the scripts again:

- [`tasks/redwood-inference/SOURCE.md`](tasks/redwood-inference/SOURCE.md): rules and tickets from
  `tasks/redwood-inference/scripts`, on docs from EnterpriseRAG-Bench.
- [`tasks/support-agent-knowledge/SOURCE.md`](tasks/support-agent-knowledge/SOURCE.md): the five knowledge packs, each
  built from the complete one with one change, and the tickets, from `tasks/support-agent-knowledge/scripts`.
- [`tasks/skyway-air/SOURCE.md`](tasks/skyway-air/SOURCE.md): rules and tickets from `tasks/skyway-air/scripts`, and
  docs written from the rules with the doc generator in [`tools/doc-gen`](tools/doc-gen/C2A.md).

Customer behaviours are listed in [`scripts/behavior/types.json`](scripts/behavior/types.json); the facts the judge
checks come from `scripts/build_facts.py`.

## Viewer

Static site (graphs + run viewer). The landing page graphs read `viewer/public/landing.json`, committed with the site, so
they load without any Hugging Face request; the run viewer reads the two commit-pinned Hugging Face datasets. Live at
https://c2abench.com/.

### View it locally

Needs Node 20+, [uv](https://docs.astral.sh/uv/).

```bash
cd viewer
npm ci
npm run dev:local-hf     # first run downloads ~1 GB of data into ~/.cache/c2a-bench/local-data (outside the repo, shared by all worktrees; override with C2A_LOCAL_DATA), then serves
```

Open http://localhost:5199/. Re-run the same command later; it reuses the download. After a new pin, re-download with
`npm run dev:local-hf -- --fetch`.

### Tests

```bash
cd viewer
npm run test:data
npx playwright install chromium && npm run test:pages
```

Tests need no real data or secrets. Never embed a Hugging Face token in the app.

### Publish new results

The site is built with fixed commits of both datasets (`viewer/datasets/production.json`), so a bad upload never
reaches it. After new runs (or a new benchmark version) are on Hugging Face's `main`:

```bash
cd viewer && npm run pin:production    # also regenerates public/landing.json and public/doc-index/
```

It looks up both datasets' latest commits, checks without a token that every run points to that exact benchmark commit
(and with `--full`, every file's SHA-256), and writes `production.json`. When the benchmark commit changed, it also
rebuilds the doc index (`public/doc-index/<commit>/`, each doc's place in its `docs.json`, so the site fetches one doc
at a time). Commit and push these files: the Pages workflow rebuilds and deploys the site. Runs must be linked to the benchmark commit they are scored against before they are
published; the command refuses otherwise.

- [Viewer, publishing tools, and deployment setup](viewer/README.md)

## License

MIT, see [`LICENSE`](LICENSE). The two Hugging Face datasets are MIT too. Docs for `redwood-inference` and
`support-agent-knowledge` derive from [EnterpriseRAG-Bench](https://github.com/onyx-dot-app/EnterpriseRAG-Bench) (MIT,
DanswerAI, Inc.); their license is kept at `tasks/*/environment/app/docs/UPSTREAM_LICENSE`.
