import { readFile } from "node:fs/promises";
import { parseArgs } from "node:util";
import { parseRelease, releaseUrl } from "./data/release";
import { createDatasetLoader } from "../src/lib/dataset-v2";

const { values } = parseArgs({ options: { url: { type: "string" }, manifest: { type: "string", default: "datasets/production.json" }, "data-only": { type: "boolean" }, help: { type: "boolean" } } });
if (values.help) console.log("Usage: npm run smoke:pages -- --url https://c2abench.com/ [--manifest FILE] [--data-only]\nChecks the two pinned public datasets, JSONL/legacy UI projections, CORS, and Pages assets. No tokens used.");
else {
  try {
    if (!values.url) throw new Error("--url is required");
    const pages = new URL(values.url);
    if (!/^https?:$/.test(pages.protocol) || pages.search || pages.hash || pages.username || pages.password) throw new Error("Use the Pages base URL without a query/hash");
    if (!pages.pathname.endsWith("/")) pages.pathname += "/";
    const release = parseRelease(JSON.parse(await readFile(values.manifest, "utf8")));
    const hub = process.env.VIEWER_TEST_BUILD === "1" ? process.env.HF_TEST_HUB : undefined;
    const request = async (url: URL | string, options: RequestInit = {}) => fetch(url, { ...options, signal: AbortSignal.timeout(180_000) });
    if (!values["data-only"]) {
      const response = await request(pages), html = await response.text();
      if (!response.ok || !html.includes('id="root"')) throw new Error("Pages did not return the React shell");
      // Only the page's own files (scripts, styles, icons, images): canonical/alternate links name pages, not assets.
      for (const match of html.matchAll(/<(?:script|link|img|source)\b[^>]*?\b(?:src|href)="([^"]+)"[^>]*>/g)) {
        if (/rel="(?:canonical|alternate)"/.test(match[0])) continue;
        const url = new URL(match[1], pages);
        if (url.origin !== pages.origin || !url.pathname.startsWith(pages.pathname)) throw new Error(`Asset escapes Pages base: ${url}`);
        const res = await request(url, { method: "HEAD" });
        if (!res.ok || res.headers.get("content-type")?.includes("text/html")) throw new Error(`Missing/misrouted asset ${url}`);
      }
      const monaco = await request(new URL("monaco/vs/loader.js", pages), { method: "HEAD" });
      if (!monaco.ok || !/javascript/.test(monaco.headers.get("content-type") || "")) throw new Error("Monaco asset path/type incorrect");
      const missing = await request(new URL("assets/__missing__.js", pages));
      if (missing.ok) throw new Error("Missing Pages asset returned success"); await missing.arrayBuffer();
    }
    const responses = new Map<string, Promise<string>>();
    const text = (side: "benchmark" | "runs", file: string): Promise<string> => {
      const url = `${releaseUrl(release[side], hub)}/${file}`;
      if (!responses.has(url)) responses.set(url, (async () => {
        const res = await request(url, { headers: { Origin: pages.origin } });
        if (!res.ok || res.headers.get("content-type")?.includes("text/html")) throw new Error(`Public data missing or HTML: ${file} (${res.status})`);
        if (![pages.origin, "*"].includes(res.headers.get("access-control-allow-origin") || "")) throw new Error(`CORS does not allow Pages origin: ${file}`);
        return res.text();
      })());
      return responses.get(url)!;
    };
    const loader = createDatasetLoader({ release, read: async <T>(side: "benchmark" | "runs", file: string) => JSON.parse(await text(side, file)) as T, text });
    const catalog = await loader.index();
    if (!catalog.tasks.length) throw new Error("No task data");
    for (const task of catalog.tasks) {
      const job = task.jobs[0]; if (!job) throw new Error(`Empty leaderboard ${task.id}`);
      const [meta, code, cases] = await Promise.all([loader.meta(task.id, job.id), loader.code(task.id, job.id), loader.cases(task.id, job.id)]);
      if (!meta.stages.length || code.stages.length !== meta.stages.length || !cases.tickets.length) throw new Error("Incomplete run projection");
      const ref = code.stages.flatMap((s) => s.files).find((f) => f.ref)?.ref;
      if (ref) await loader.text(ref);
      const builds = await loader.builds(task.id, job.id);
      const stage = builds?.stages.find((s) => s.format);
      if (stage) await loader.events(task.id, job.id, stage.index);
    }
    console.log(`Pages/data HTTP checks passed: ${pages.href}; ${catalog.tasks.reduce((n, t) => n + t.jobs.length, 0)} runs in two pinned repositories`);
  } catch (error) { console.error(error instanceof Error ? error.stack : error); process.exitCode = 1; }
}
