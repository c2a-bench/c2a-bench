import { spawn } from "node:child_process";
import { createServer, type Server } from "node:http";
import { readFile, rm, stat } from "node:fs/promises";
import { migrate } from "../data/migrate";
import { pinRelease } from "../data/pin-release";
import { allFiles } from "../data/migration-io";
import path from "node:path";
import type { CodeData, DocsData, Meta } from "../../src/lib/types";
import type { PublishedIndex, JobSummary } from "../../src/lib/data-types";
import { fingerprint, inspectJson, INVENTORY_FILE, sha256, sorted, type Inventory } from "../data/inventory";

export const snapshot = "ci-fixture";
export const repository = "example/runs";
export const benchmarkRepository = "example/benchmark";
export const revision = "a".repeat(40);
export const benchmarkRevision = "b".repeat(40);
export const dataPath = "";
export const runKey = "redwood-inference.fixture";
const job: JobSummary = {
  key: runKey, id: "fixture", started: "2026-01-01T00:00:00Z", finished: true,
  score: 1, builder: { agent: "pi", model: "gpt-4.1" }, bot: "fixture", cost: null,
  tokens: { input: null, cached: null, output: null },
  scores: [0, 1].map((stage) => ({ stage, passed: 1, total: 1 })),
};
const catalog: PublishedIndex = { updatedAt: "2026-01-01T00:00:00Z", prefix: "fixture", tasks: [{ id: "redwood-inference", name: "Fixture Company", description: "Synthetic data, no real jobs or secrets", sources: [], jobs: [job] }] };
const meta: Meta = { job: "fixture", trial: "fixture", stages: [0, 1], scores: { "0": { step: "stage0", reward: 1, passed: 1, total: 1 }, "1": { step: "stage1", reward: 1, passed: 1, total: 1 } }, builder: job.builder, bot: "fixture" };
const code: CodeData = { stages: [0, 1].map((stage) => ({ stage, score: { passed: 1, total: 1 }, builder: { final: "done", cost: null, model: "fixture" }, files: [{ path: "agent.py", role: "code", lines: 1, text: "print('hello')" }, { path: "other.py", role: "code", lines: 1, text: "print('other')" }], knowledge: [] })), transitions: [] };
const doc = { title: "Policy", status: "active", updated: "2026-01-01", author: "fixture", text: "Version one", source: "confluence" as const, born: 0, edited: null };
const docs: DocsData = { "0": { "policy.md": doc, "obsolete.md": doc }, "1": { "policy.md": { ...doc, text: "Version two", edited: 1 } } };
const versions = [0, 1].map((n) => ({ step: `stage${n}`, title: "Fixture ticket", test: "Test", matters: "Matters", ticket: "Help", opening: "Hello", brief: "Brief", customer: { id: "customer", deployments: [] }, facts: [], rules: [], rule_facts: [], pass: {}, reply_checks: [], tags: { group: "fixture" }, result: { passed: true, verdict: "passed", failures: [] } }));
const passed = versions.map((v, n) => ({ id: "case", key: `case:${n}`, stage: n, passed: true, title: v.title, test: v.test, matters: v.matters, ticket: v.ticket, brief: v.brief, facts: [], customerId: "customer", group: "fixture", start: {}, end: {}, messages: ["Hello"], runs: [], failures: [], blocked: [], crash: "", turnsExact: true }));
const files = new Map<string, string>(Object.entries({
  "index.json": catalog,
  "redwood-inference/fixture/meta.json": meta,
  "redwood-inference/fixture/code.json": code,
  "redwood-inference/fixture/docs.json": docs,
  "redwood-inference/fixture/tickets.json": [],
  "redwood-inference/fixture/passed.json": passed,
  "redwood-inference/fixture/cases.json": { task: "redwood-inference", steps: ["stage0", "stage1"], tickets: [{ id: "case", versions }] },
  "redwood-inference/fixture/builds.json": { version: 1, harness: "fixture", stages: [] },
}).map(([name, body]) => [name, JSON.stringify(body)]));
const objects = sorted([...files].map(([path, body]) => ({ path, size: Buffer.byteLength(body), version: sha256(body) }))).map((entry) => ({ ...entry, sha256: sha256(files.get(entry.path)!), ...inspectJson(entry.path, JSON.parse(files.get(entry.path)!)) }));
const inventory: Inventory = { schemaVersion: 1, snapshot, sourcePrefix: "fixture", sourceFingerprint: fingerprint(objects), createdAt: "2026-01-01T00:00:00Z", totalBytes: objects.reduce((n, entry) => n + entry.size, 0), objects };
const inventoryRaw = JSON.stringify(inventory);
files.set(INVENTORY_FILE, inventoryRaw);
export function fixtureSource(emptyStage0 = false) {
  const sourceFiles = new Map(files);
  if (emptyStage0) { const value = JSON.parse(sourceFiles.get("redwood-inference/fixture/code.json")!); value.stages[0].files = []; sourceFiles.set("redwood-inference/fixture/code.json", JSON.stringify(value)); }
  return { async list() { return [...sourceFiles].filter(([name]) => name !== INVENTORY_FILE).map(([path, body]) => ({ path, size: Buffer.byteLength(body), version: sha256(body) })); }, async read(object: { path: string }) { const body = sourceFiles.get(object.path); if (body === undefined) throw new Error("Missing fixture"); return (async function* () { yield Buffer.from(body); })(); } };
}

async function listen(server: Server) {
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("Missing server address");
  return `http://127.0.0.1:${address.port}`;
}
export async function closeServer(server: Server) {
  server.closeAllConnections();
  await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
}
export async function fixtures(root: string, base: string) {
  const datasetDir = `${root}-dataset`;
  await migrate({ source: fixtureSource(base !== "/"), out: datasetDir, id: snapshot, benchmarkRepository, runsRepository: repository, expectedRuns: 1 });
  const selection = await pinRelease(datasetDir, benchmarkRevision, revision);
  const requests: string[] = [];
  const types: Record<string, string> = { ".html": "text/html", ".js": "application/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".ico": "image/x-icon", ".woff2": "font/woff2", ".jpg": "image/jpeg", ".png": "image/png", ".wasm": "application/wasm" };
  const pagesServer = createServer(async (request, response) => {
    try {
      const uri = new URL(request.url || "/", "http://localhost").pathname;
      requests.push(uri);
      if (!uri.startsWith(base)) throw new Error("outside Pages base");
      let file = path.resolve(root, decodeURIComponent(uri.slice(base.length) || "index.html"));
      if (!file.startsWith(root + path.sep)) throw new Error("unsafe path");
      // Like Pages: a folder serves its index.html, and without the trailing slash it redirects to it.
      if ((await stat(file).catch(() => null))?.isDirectory()) {
        if (!uri.endsWith("/")) { response.statusCode = 301; response.setHeader("location", `${uri}/`); response.end(); return; }
        file = path.join(file, "index.html");
      }
      const body = await readFile(file);
      response.setHeader("content-type", types[path.extname(file)] || "application/octet-stream");
      response.end(request.method === "HEAD" ? undefined : body);
    } catch {
      // Like Pages: a missing path answers 404 with the site's own 404.html, which for this app is the shell (client-side routes).
      response.statusCode = 404;
      response.setHeader("content-type", "text/html");
      response.end(await readFile(path.join(root, "404.html")).catch(() => "<h1>Pages 404</h1>"));
    }
  });
  const pagesOrigin = await listen(pagesServer);
  const dataRequests: string[] = [];
  const dataFiles = new Map<string, string>();
  for (const side of ["benchmark", "runs"]) for (const file of await allFiles(path.join(datasetDir, side))) dataFiles.set(`${side}/${file}`, await readFile(path.join(datasetDir, side, file), "utf8"));
  const dataServer = createServer((request, response) => {
    const uri = new URL(request.url || "/", "http://localhost").pathname;
    dataRequests.push(uri);
    response.setHeader("access-control-allow-origin", "*");
    for (const side of ["benchmark", "runs"] as const) {
      const ref = selection[side], resolve = `/datasets/${ref.repository}/resolve/${ref.revision}/`;
      if (uri.startsWith(resolve)) {
        response.statusCode = 302;
        response.setHeader("location", `/cdn/${side}/${uri.slice(resolve.length)}`);
        response.end(); return;
      }
    }
    const prefix = "/cdn/";
    const body = uri.startsWith(prefix) ? dataFiles.get(uri.slice(prefix.length)) : undefined;
    if (body === undefined) {
      response.statusCode = 403;
      response.setHeader("content-type", "application/xml");
      response.end("<Error>AccessDenied</Error>");
      return;
    }
    response.setHeader("content-type", "text/plain");
    response.end(request.method === "HEAD" ? undefined : body);
  });
  const dataOrigin = await listen(dataServer);
  return { pagesUrl: `${pagesOrigin}${base}`, pagesOrigin, dataOrigin, requests, dataRequests, selection, datasetDir, corrupt(file: string, body: string) { dataFiles.set(file, body); }, async close() { await closeServer(pagesServer); await closeServer(dataServer); await rm(datasetDir, { recursive: true, force: true }); } };
}

export function run(command: string, args: string[], env: NodeJS.ProcessEnv = process.env) {
  return new Promise<string>((resolve, reject) => {
    const child = spawn(command, args, { env, stdio: ["ignore", "pipe", "pipe"] });
    let output = "";
    child.stdout.on("data", (chunk) => { output += chunk; });
    child.stderr.on("data", (chunk) => { output += chunk; });
    child.once("error", reject);
    child.once("exit", (code) => code === 0 ? resolve(output) : reject(new Error(`${command} exited ${code}\n${output}`)));
  });
}
