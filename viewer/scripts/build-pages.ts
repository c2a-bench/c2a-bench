import { spawnSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import { parseArgs } from "node:util";
import { pagesBase } from "./pages-config";
import { parseRelease, releaseUrl } from "./data/release";

try {
  const { values } = parseArgs({ options: { "out-dir": { type: "string" } } });
  const release = parseRelease(JSON.parse(await readFile(process.env.DATASET_MANIFEST || "datasets/production.json", "utf8")));
  const base = pagesBase(process.env.VITE_BASE_PATH);
  // Production always uses the public Hub. Loopback is permitted only for offline browser tests.
  const testHub = process.env.VIEWER_TEST_BUILD === "1" ? process.env.HF_TEST_HUB : undefined;
  const urls = { benchmark: releaseUrl(release.benchmark, testHub), runs: releaseUrl(release.runs, testHub) };
  const args = ["run", "build"];
  if (values["out-dir"]) args.push("--", "--outDir", values["out-dir"]);
  const result = spawnSync("npm", args, {
    stdio: "inherit", env: { ...process.env, VITE_BASE_PATH: base, VITE_DATA_MODE: "published", VITE_DATA_RELEASE: JSON.stringify({ release, urls }) },
  });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exitCode = result.status ?? 1;
  else {
    const pre = spawnSync("npm", ["run", "prerender", "--", ...(values["out-dir"] ? ["--out-dir", values["out-dir"]] : [])], { stdio: "inherit" });
    if (pre.error) throw pre.error;
    if (pre.status !== 0) process.exitCode = pre.status ?? 1;
  }
  if (!process.exitCode) console.log(`GitHub Pages build: base=${base}, benchmark=${urls.benchmark}, runs=${urls.runs}`);
} catch (error) {
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = 1;
}
