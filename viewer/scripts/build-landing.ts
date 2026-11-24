// The landing page's data, committed with the site so the page needs no Hugging Face request: the catalog index and
// each run's scores (what the graphs use) from the pinned runs dataset. Run after pinning; pin:production does it.
//
//   npm run build:landing        # writes public/landing.json
//
// The site ignores the file if its runsRevision or benchmarkRevision is not datasets/production.json's, and falls back to Hugging Face.
import { readFile, writeFile } from "node:fs/promises";
import { parseRelease, releaseUrl } from "./data/release";
import { createDatasetLoader } from "../src/lib/dataset-v2";
import { parseRunKey } from "../src/lib/data-types";

const release = parseRelease(JSON.parse(await readFile("datasets/production.json", "utf8")));
const get = async (url: string) => {
  const res = await fetch(url, { signal: AbortSignal.timeout(120_000) });
  if (!res.ok) throw new Error(`${res.status} for ${url}`);
  return res;
};
const url = (side: "benchmark" | "runs", file: string) => `${releaseUrl(release[side])}/${file}`;
const loader = createDatasetLoader({ release, read: async (side, file) => (await get(url(side, file))).json() as never, text: async (side, file) => (await get(url(side, file))).text() });

// Only the fields of each stage the graphs read (MetaStage in src/landing/data.ts).
type Stage = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
const trim = (v: Stage): Stage => ({
  passed: v.passed, total: v.total, ticket_types: v.ticket_types, failure_taxonomy: v.failure_taxonomy,
  behavior_coverage: v.behavior_coverage ? { n_behaviors: v.behavior_coverage.n_behaviors } : v.behavior_coverage,
  facts: v.facts ? { rule_recall: v.facts.rule_recall } : v.facts,
  architecture: v.architecture ? { observed: v.architecture.observed ? { knowledge_access: v.architecture.observed.knowledge_access, model_calls_avg: v.architecture.observed.model_calls_avg } : v.architecture.observed } : v.architecture,
  latency: v.latency ? { ticket: v.latency.ticket ? { median: v.latency.ticket.median } : v.latency.ticket } : v.latency,
  cost: v.cost ? { bot: v.cost.bot ? { in: v.cost.bot.in, usd: v.cost.bot.usd } : v.cost.bot } : v.cost,
});

const index = await loader.index();
const metas: Record<string, unknown> = {};
for (const task of index.tasks) {
  for (const job of task.jobs) {
    const { task: domain, job: id } = parseRunKey(job.key);
    const m = (await loader.meta(domain, id)) as { scores?: unknown; failure_summary?: unknown };
    metas[job.key] = { scores: Object.fromEntries(Object.entries((m.scores ?? {}) as Record<string, Stage>).map(([k, v]) => [k, trim(v)])), failure_summary: m.failure_summary };
  }
}
const out = JSON.stringify({ runsRevision: release.runs.revision, benchmarkRevision: release.benchmark.revision, index, metas });
await writeFile("public/landing.json", out + "\n");
console.log(`public/landing.json: ${index.tasks.reduce((n, t) => n + t.jobs.length, 0)} runs, ${(out.length / 1024).toFixed(0)} KB`);
