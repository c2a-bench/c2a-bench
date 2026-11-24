# C2A viewer

GitHub Pages frontend: [`c2a-bench/c2a-bench`](https://github.com/c2a-bench/c2a-bench).
Data is split into two public, ungated Hugging Face datasets. No hosted server, Space, or runtime tokens.

## Canonical data layout

**`observeai/c2a-bench` — shared benchmark definitions**

```text
README.md                          dataset card/license and link to runs
inventory.json                     sizes and SHA-256 checksums
<domain>/task.json                  metadata and named stages
<domain>/stages/<n>/docs.json        complete initial corpus, then new/edited docs
<domain>/stages/<n>/changes.json     changes, patches, rule_changes, new_docs, deleted
<domain>/stages/<n>/cases.json       complete stage case definitions, without results
```

Domains: `redwood-inference`, `support-agent-knowledge`, `skyway-air`. Knowledge packs are named independent conditions (`Rcomplete`, `Rfragmented`,
`Rincomplete`, `Rconflicting`, `Rnoisy`) with `docs_mode: snapshot`, not chronological deltas.

**`observeai/c2a-bench-runs` — execution artifacts**

```text
README.md                          HF configs pointing to data/*.jsonl
inventory.json
data/<domain>.jsonl               one generated leaderboard row per run
<domain>/<job>/run.json             run metadata + pinned benchmark provenance
<domain>/<job>/stages/<n>/stage.json scores, builder summary, timing, log availability
<domain>/<job>/stages/<n>/results.json all graded cases, including missing traces
<domain>/<job>/stages/<n>/code.json  files, knowledge, and previous-stage changes
<domain>/<job>/stages/<n>/builder.json optional redacted normalized builder events
content/texts/<prefix>.json         globally deduplicated code/log text by full SHA-256
```

Documents have full text in the benchmark repo. Run-side code/log references resolve against the shared
content store. Binary artifacts remain explicitly metadata-only if that is all the source contains.
Builder exports are normalized events, not a claim to contain original system prompts/full trajectories.
Missing code, traces, metrics, or timing are kept missing; they are never fabricated.

The published catalog's overall score is retained as `run.score` (`published_trial_reward`). It is not
replaced by the pooled pass rate or mean stage reward. Differences are reported as `aggregateWarnings`.
Case-result `grading` is separate from conversation failures and `replayVerdict` (the fact judge's verdict; the field keeps an older name).

## Run locally

```bash
npm ci
npm run dev:local-hf     # downloads the pinned datasets to .local-data on first run, then serves http://localhost:5199/
```

Tests (no real data needed): `npm run test:data`, then `npx playwright install chromium && npm run test:pages`
(with an existing Chrome: `PLAYWRIGHT_CHANNEL=chrome npm run test:pages`). Python tests:
`python3 -m unittest discover -s scripts -p 'test_*.py'`. The tests convert fixtures into the real two-repo layout
and cover Pages base paths, queries, anchors, Monaco, workers and empty-code stages.

## Publish a release folder

A release folder holds `benchmark/`, `runs/` and `release.json` (both datasets in the layout above). The
published datasets were built from the original run folders; that converter is not part of this repo.

```bash
python3 -m venv .venv-hf
.venv-hf/bin/pip install -r scripts/requirements-hf.txt
# Export a dataset-scoped HF_TOKEN with write access to BOTH repositories.
.venv-hf/bin/python scripts/publish-release.py --dir RELEASE_DIR --manifest datasets/candidate.json
npm run verify:hf -- --manifest datasets/candidate.json
```

Repositories are set by `HF_BENCHMARK_REPO` / `HF_RUNS_REPO`. There is no default dataset: explicit targets are required. They must already exist,
be public, ungated, and appropriately licensed. The publisher never creates a repo or changes its visibility.

Publication order: validate locally → upload benchmark → verify its immutable commit anonymously → pin
that SHA in every run → regenerate JSONL/inventory → upload runs → anonymously verify all bytes in
both repos → produce a selectable candidate. Until then `release.json` has null revisions and cannot
build/deploy. Existing frontend releases stay pinned to their previous commits throughout uploading.

Large-folder uploading uses local `.cache/huggingface/` for resumption; this cache is excluded from release
inventories/uploads. Unexpected remote files block publishing. `--replace-managed` explicitly permits
removing retired files only in managed domain/data/content prefixes; it never removes unknown root files.
Public staging/uploads are already public—review sensitive data and rights BEFORE uploading.

## GitHub Pages

Review/copy a fully verified candidate into `datasets/production.json`. It pins both repo commits and
inventory hashes. No moving branches, tokens, or one-repo compatibility mode are used.

```bash
VITE_BASE_PATH=/c2a-bench/ npm run build:pages
npm run smoke:pages -- --url https://c2abench.com/
```

Settings → Pages → Source → GitHub Actions. Restrict `github-pages` to main, then set repository variable
`VIEWER_PAGES_ENABLED=true` only when ready. The frontend workflow has no data credentials. It derives
the repository/custom-domain base, checks public data/CORS, deploys, and records both versions.

### URLs and search engines

The site uses real URLs (`/`, `/blog/introducing-c2a/`, `/runs/...`), not hash routes; old `/#/...` links are moved to them by
a script in `index.html`. Pages has no rewrites, so `build:pages` ends with `npm run prerender`
(`scripts/prerender-static.ts`), which writes:

- `index.html` and `blog/<slug>/index.html`: the app shell plus each page's own title, description, canonical, Open Graph tags,
  JSON-LD and its text as plain HTML (hidden; the app replaces it, and it shows with JavaScript off);
- `404.html`: the bare app shell, which Pages serves (with a 404 status) for every other route, so deep links to runs still open the app;
- `sitemap.xml`, `robots.txt`, `llms.txt` and `blog/<slug>.md`.

Set `SITE_URL` to the site's public URL (the deploy workflow does, from Pages) so canonicals and the sitemap name the right host.
Only the home page and the blog posts are pre-rendered (a new post needs only its entry in `src/blog/posts.ts`).

Rollback means reverting the approved app/release configuration and rebuilding Pages; keep referenced
HF commits available. Test against the REAL public HF/CDN endpoint after publishing—local fixtures alone
cannot certify external CORS/account limits. Review outstanding npm audit advisories before production.
