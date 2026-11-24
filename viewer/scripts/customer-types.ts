// Pass rate and customer facts recall per customer behavior, pooled over every published run with customer types
// (Redwood Inference and Skyway Air; the knowledge packs have none). Plain numbers, no adjustment.
//
//   npm run customer-types        # prints the JSON that blog/viewers.tsx (CUSTOMER_TYPES) holds, from the pinned runs
//
// Per type: [tickets, attempts, pass %, customer facts recall %]. Recall is the share of a ticket's customer facts the agent got the
// customer to tell, averaged over attempts that have a recall score.
import { readFile } from "node:fs/promises";
import { parseRelease, releaseUrl } from "./data/release";
import { createDatasetLoader } from "../src/lib/dataset-v2";

const release = parseRelease(JSON.parse(await readFile("datasets/production.json", "utf8")));
const get = async (url: string) => {
  for (let i = 0; i < 4; i++) {
    const res = await fetch(url, { signal: AbortSignal.timeout(60_000) }).catch(() => null);
    if (res?.ok) return res;
    await new Promise((r) => setTimeout(r, 1500 * (i + 1)));
  }
  throw new Error(`cannot fetch ${url}`);
};
const url = (side: "benchmark" | "runs", file: string) => `${releaseUrl(release[side])}/${file}`;
const loader = createDatasetLoader({ release, read: async (s, f) => (await get(url(s, f))).json() as never, text: async (s, f) => (await get(url(s, f))).text() });

type Attempt = { ticket: string; behavior: string; passed: number; recall: number | null };
const attempts: Attempt[] = [];
const jobs = (await loader.index()).tasks.flatMap((t) => t.jobs.map((j) => [t.id, j.key.slice(t.id.length + 1)] as const));
let next = 0;
await Promise.all(Array.from({ length: 8 }, async () => {
  while (next < jobs.length) {
    const [task, job] = jobs[next++];
    for (const n of (await loader.run(task, job)).stages) {
      const cases = new Map((await loader.definitions(task, n)).map((c) => [c.id, c]));
      for (const r of (await loader.results(task, job, n)) as { id: string; passed: boolean; factCheck?: { customer_recall?: number | null } }[]) {
        const behavior = (cases.get(r.id)?.tags as Record<string, string> | undefined)?.behavior;
        if (behavior) attempts.push({ ticket: `${task}/${n}/${r.id}`, behavior, passed: +r.passed, recall: r.factCheck?.customer_recall ?? null });
      }
    }
  }
}));

const out: Record<string, number[]> = {};
for (const behavior of [...new Set(attempts.map((a) => a.behavior))]) {
  const mine = attempts.filter((a) => a.behavior === behavior);
  const scored = mine.filter((a) => a.recall !== null);
  out[behavior] = [
    new Set(mine.map((a) => a.ticket)).size, mine.length,
    Math.round((1000 * mine.reduce((s, a) => s + a.passed, 0)) / mine.length) / 10,
    Math.round((1000 * scored.reduce((s, a) => s + a.recall!, 0)) / scored.length) / 10,
  ];
}
const all = attempts.reduce((s, a) => s + a.passed, 0) / attempts.length;
console.log(JSON.stringify({ revision: release.runs.revision, passRate: Math.round(all * 1000) / 10, byType: Object.fromEntries(Object.entries(out).sort((a, b) => b[1][2] - a[1][2])) }, null, 1));
