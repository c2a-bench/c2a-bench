// Runs the viewer against a local copy of the two pinned HF datasets (<root>/{benchmark,runs}; downloaded on first run).
// <root> is shared by every checkout and worktree: C2A_LOCAL_DATA, else ~/.cache/c2a-bench/local-data.
import { createServer } from "node:http";
import { createReadStream, existsSync, readFileSync, statSync } from "node:fs";
import { spawn, spawnSync } from "node:child_process";
import { homedir } from "node:os";
import path from "node:path";

const root = path.resolve(process.env.C2A_LOCAL_DATA || path.join(homedir(), ".cache/c2a-bench/local-data"));
// First run: download the pinned datasets (~1 GB); `npm run dev:local-hf` again resumes an interrupted download.
if (process.argv.includes("--fetch") || !existsSync(path.join(root, ".done"))) {
  const r = spawnSync("uv", ["run", "--with", "huggingface_hub", "python3", "scripts/fetch-local-hf.py"], { stdio: "inherit", env: { ...process.env, C2A_LOCAL_DATA: root } });
  if (r.status !== 0) process.exit(r.status ?? 1);
}
const release = JSON.parse(readFileSync("datasets/production.json", "utf8"));
createServer((req, res) => {
  const file = path.join(root, decodeURIComponent(new URL(req.url, "http://x").pathname));
  res.setHeader("Access-Control-Allow-Origin", "*");
  if (!file.startsWith(root + path.sep) || !statSync(file, { throwIfNoEntry: false })?.isFile()) { res.statusCode = 404; return res.end(); }
  res.setHeader("Content-Type", file.endsWith(".json") ? "application/json" : "text/plain");
  res.setHeader("Accept-Ranges", "bytes");
  res.setHeader("Access-Control-Expose-Headers", "Content-Range");
  // A byte range (one doc out of a big docs.json), as Hugging Face serves it.
  const range = /^bytes=(\d+)-(\d+)$/.exec(req.headers.range ?? "");
  if (range) {
    const size = statSync(file).size, start = Number(range[1]), end = Math.min(Number(range[2]), size - 1);
    res.statusCode = 206;
    res.setHeader("Content-Range", `bytes ${start}-${end}/${size}`);
    return createReadStream(file, { start, end }).pipe(res);
  }
  createReadStream(file).pipe(res);
}).listen(0, "127.0.0.1", function () {
  const port = this.address().port; // any free port
  const urls = { benchmark: `http://127.0.0.1:${port}/benchmark`, runs: `http://127.0.0.1:${port}/runs` };
  spawn("npx", ["vite", "--port", "5199"], { stdio: "inherit", env: { ...process.env, VITE_DATA_MODE: "published", VITE_DATA_RELEASE: JSON.stringify({ release, urls }) } });
});
