import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { test } from "node:test";
import { chromium, expect } from "@playwright/test";
import { fixtures, run, runKey } from "./fixtures";

for (const base of ["/", "/Context2Agent-Benchmark/"]) {
  test(`Pages-only production build and browser navigation at ${base}`, { timeout: 120_000 }, async () => {
    const dir = await mkdtemp(path.join(tmpdir(), "viewer-pages-"));
    const dist = path.join(dir, "dist");
    const server = await fixtures(dist, base);
    const selection = server.selection;
    let browser: Awaited<ReturnType<typeof chromium.launch>> | undefined;
    try {
      const manifest = path.join(dir, "selection.json");
      await writeFile(manifest, JSON.stringify(selection));
      // Build production assets using the real Pages configuration, not Vite dev/preview middleware.
      await run("npm", ["run", "build:pages", "--", "--out-dir", dist], {
        ...process.env, VITE_BASE_PATH: base, SITE_URL: server.pagesUrl, VIEWER_TEST_BUILD: "1", HF_TEST_HUB: server.dataOrigin, DATASET_MANIFEST: manifest,
      });
      const smoke = await run(process.execPath, ["--import", "tsx", "scripts/smoke-pages.ts", "--url", server.pagesUrl, "--manifest", manifest], { ...process.env, VIEWER_TEST_BUILD: "1", HF_TEST_HUB: server.dataOrigin });
      assert.match(smoke, /Pages\/data HTTP checks passed/);
      browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}) });
      const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
      const errors: string[] = [];
      const failed: string[] = [];
      page.on("pageerror", (error) => errors.push(error.message));
      page.on("requestfailed", (request) => {
        if (!request.failure()?.errorText.includes("ERR_ABORTED")) failed.push(`${request.url()}: ${request.failure()?.errorText}`);
      });
      await page.goto(server.pagesUrl);
      await expect(page.locator(".lp-nav")).toBeVisible();
      await expect(page.getByRole("link", { name: "Read the blog", exact: true }).first()).toHaveJSProperty("href", `${server.pagesUrl}blog/introducing-c2a`);
      for (const image of await page.locator("img").all()) {
        await expect(image).toHaveJSProperty("complete", true);
        assert.ok(await image.evaluate((img: HTMLImageElement) => img.naturalWidth > 0), await image.getAttribute("src") || "image");
      }
      // Crawlers: the home page and the post are real pre-rendered files, with their own head, text and structured data.
      const raw = async (uri: string) => { const r = await fetch(`${server.pagesUrl}${uri}`); return { status: r.status, text: await r.text() }; };
      const home = await raw("");
      assert.match(home.text, /<link rel="canonical" href="[^"]*"/);
      assert.match(home.text, /<h1>C2A: the Context2Agent Benchmark<\/h1>/);
      assert.match(home.text, /"@type":"WebSite"/);
      const post = await raw("blog/introducing-c2a/");
      assert.equal(post.status, 200);
      assert.match(post.text, /<title>C2A: can agents keep up/);
      assert.match(post.text, new RegExp(`<link rel="canonical" href="${server.pagesUrl}blog/introducing-c2a/"`));
      assert.match(post.text, /"@type":"BlogPosting"/);
      assert.match(post.text, /<h2>Inside the benchmark<\/h2>/);
      assert.equal((await raw("blog/introducing-c2a.md")).status, 200);
      const sitemap = (await raw("sitemap.xml")).text;
      assert.match(sitemap, new RegExp(`<loc>${server.pagesUrl}blog/introducing-c2a/</loc>`));
      for (const [, date] of sitemap.matchAll(/<lastmod>([^<]*)<\/lastmod>/g)) assert.match(date, /^\d{4}-\d{2}-\d{2}$/, "sitemap lastmod must be a date");
      assert.match((await raw("robots.txt")).text, /Sitemap: /);
      assert.equal((await raw("llms.txt")).status, 200);
      // The app takes over at the post's own URL, replaces the pre-rendered text, and sets its title.
      await page.goto(`${server.pagesUrl}blog/introducing-c2a/`);
      await expect(page.locator("article h1")).toBeVisible();
      await expect(page.locator("#static")).toHaveCount(0);
      await expect(page).toHaveTitle(/^C2A: can agents keep up/);
      // Old hash links move to the real URL; /blog goes to the post; an unknown path is a real 404 that still shows the app's not-found page.
      await page.goto(`${server.pagesUrl}#/blog`);
      await expect(page).toHaveURL(`${server.pagesUrl}blog/introducing-c2a`);
      await page.goto(`${server.pagesUrl}blog`);
      await expect(page).toHaveURL(new RegExp(`${server.pagesUrl}blog/introducing-c2a/?$`));
      assert.equal((await raw("no-such-page")).status, 404);
      await page.goto(`${server.pagesUrl}no-such-page`);
      await expect(page.getByText("This page could not be found.")).toBeVisible();
      // Deep links + hard refresh rely on Pages' 404.html fallback, which is the app shell.
      const codeStage = base === "/" ? 0 : 1;
      if (base !== "/") {
        await page.goto(`${server.pagesUrl}runs/${runKey}/code?v=s0`);
        await expect(page.getByText("No code files were produced at this stage.")).toBeVisible();
      }
      await page.goto(`${server.pagesUrl}runs/${runKey}/code?v=s${codeStage}&f=agent.py`);
      await expect(page.locator(".monaco-editor").first()).toBeVisible({ timeout: 30_000 });
      await page.getByRole("button", { name: /other\.py/ }).click();
      await expect(page).toHaveURL(new RegExp(`/runs/.+/code\\?v=s${codeStage}&f=other.py`));
      await page.reload();
      await expect(page.locator(".monaco-editor").first()).toBeVisible();
      await expect(page).toHaveURL(/f=other.py/);
      // Stage changes preserve the other query filters.
      await page.goto(`${server.pagesUrl}runs/${runKey}/research/acquisition?stage=0&pick=none`);
      await page.locator("#stage-select").click();
      await page.locator('[data-slot="dropdown-menu-radio-item"][data-value="1"]').click();
      await expect(page).toHaveURL(/stage=1&pick=none/);
      // A blog → landing section link goes to the home page and scrolls to its section.
      await page.goto(`${server.pagesUrl}blog/introducing-c2a`);
      await page.locator("nav[aria-label=Main]").getByRole("link", { name: "Viewer", exact: true }).click();
      await expect(page).toHaveURL(/#environments$/);
      await expect(page.locator("#environments")).toBeAttached();
      await expect.poll(() => page.locator("#environments").evaluate((el) => Math.abs(el.getBoundingClientRect().top))).toBeLessThan(250);
      assert.ok(server.requests.some((uri) => uri.startsWith(`${base}monaco/vs/`)), "Monaco should load under Pages base");
      assert.ok(server.requests.some((uri) => uri.startsWith(`${base}assets/json-worker-`)), "large replay JSON should load through the worker");
      assert.ok(server.dataRequests.some((uri) => uri.endsWith("/code.json")), "worker must fetch data cross-origin with CORS");
      assert.ok(server.requests.every((uri) => uri.startsWith(base)), `Asset escaped base: ${server.requests.join(", ")}`);
      assert.deepEqual(errors, [], "browser runtime errors");
      assert.deepEqual(failed, [], "browser network/CORS failures");
    } finally {
      await browser?.close();
      await server.close();
      await rm(dir, { recursive: true, force: true });
    }
  });
}
