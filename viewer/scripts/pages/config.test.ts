import assert from "node:assert/strict";
import { test } from "node:test";
import { datasetUrl, parseSelection } from "../data/huggingface";
import { pagesBase } from "../pages-config";
import { parseRelease } from "../data/release";
import { publicAsset } from "../../src/lib/assets";

const selection = { schemaVersion: 1, provider: "huggingface", repository: "example/replays", revision: "a".repeat(40), path: "replays/v1", inventorySha256: "b".repeat(64) };
test("Pages supports organization/custom domains and the Context2Agent-Benchmark path", () => {
  assert.equal(pagesBase(), "/");
  assert.equal(pagesBase("/Context2Agent-Benchmark"), "/Context2Agent-Benchmark/");
  assert.equal(publicAsset("/monaco/vs", "/Context2Agent-Benchmark/"), "/Context2Agent-Benchmark/monaco/vs");
  for (const invalid of ["repo", "//repo/", "/../repo/", "/repo?x", "https://example.com/"]) assert.throws(() => pagesBase(invalid));
});
test("HF repository is configurable and URLs pin a commit, never a moving branch", () => {
  const parsed = parseSelection(selection);
  assert.equal(datasetUrl(parsed), `https://huggingface.co/datasets/example/replays/resolve/${"a".repeat(40)}/replays/v1`);
  assert.equal(parseSelection({ ...selection, repository: null }, "other/dataset").repository, "other/dataset");
  assert.throws(() => parseSelection(selection, "other/dataset"), /disagrees/);
  for (const revision of [null, "main", "latest", "abc"]) assert.throws(() => parseSelection({ ...selection, revision }));
  assert.throws(() => parseSelection({ ...selection, repository: null }), /not configured/);
  assert.throws(() => parseSelection({ ...selection, path: "../secret" }));
  assert.throws(() => datasetUrl(parsed, "https://untrusted.example.com"));
});
test("two-repository release requires independent immutable identities", () => {
  const ref = { repository: "example/benchmark", revision: "a".repeat(40), path: "", inventorySha256: "b".repeat(64) };
  const release = { schemaVersion: 2, provider: "huggingface", domains: ["redwood-inference", "skyway-air"], benchmark: ref, runs: { ...ref, repository: "example/runs" } };
  assert.equal(parseRelease(release).domains.length, 2);
  assert.throws(() => parseRelease({ ...release, runs: ref }), /distinct/);
  assert.throws(() => parseRelease({ ...release, benchmark: { ...ref, revision: null } }));
  assert.throws(() => parseRelease({ ...release, domains: ["../escape"] }));
  assert.throws(() => parseRelease({ ...release, domains: ["skyway-air", "skyway-air"] }));
});
test("the URL query keeps encoded filenames and filters", () => {
  const params = new URLSearchParams("?v=s1&f=dir%2Ffile.py&stage=1");
  assert.equal(params.get("v"), "s1");
  assert.equal(params.get("f"), "dir/file.py");
  params.set("f", "other.py");
  assert.equal(params.get("stage"), "1");
});
