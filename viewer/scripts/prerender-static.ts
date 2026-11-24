// After `vite build`: make the home page and the blog post readable to crawlers that don't run JavaScript.
//
// Each page is the app's own shell (so the app boots and takes over at that URL) with its own <head> (title, description,
// canonical, Open Graph, JSON-LD) and its text as plain HTML in a `hidden` block that React replaces on first render; with
// JavaScript off, a <noscript> rule shows it. Also written: 404.html (the app shell, the Pages fallback for every other
// route), blog/index.html (redirect to the post), sitemap.xml, robots.txt, llms.txt and a Markdown copy of the post.
//
//   SITE_URL=https://example.com/base/ npm run prerender -- [--out-dir dist]
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { parseArgs } from "node:util";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { createServer } from "vite";

const { values } = parseArgs({ options: { "out-dir": { type: "string", default: "dist" } } });
const out = values["out-dir"]!;
const site = (process.env.SITE_URL || "https://c2abench.com/").replace(/\/?$/, "/");
const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const ld = (data: object) => `<script type="application/ld+json">${JSON.stringify(data).replace(/</g, "\\u003c")}</script>`;
const write = async (file: string, body: string) => { await mkdir(path.dirname(path.join(out, file)), { recursive: true }); await writeFile(path.join(out, file), body); };

// posts.ts and data.ts import through Vite (`?raw`, the "@" alias), so load them through Vite rather than plain Node.
const vite = await createServer({ server: { middlewareMode: true }, appType: "custom", logLevel: "error" });
const { POSTS } = (await vite.ssrLoadModule("/src/blog/posts.ts")) as typeof import("../src/blog/posts");
const { latestByBuilder, latestByArchitecture, pooled, shortModel, SKYWAY_ARCH } = (await vite.ssrLoadModule("/src/landing/data.ts")) as typeof import("../src/landing/data");
await vite.close();

const shell = await readFile(path.join(out, "index.html"), "utf8");
if (!shell.includes('<div id="root" class="contents"></div>')) throw new Error("index.html root element not found; update prerender-static.ts");
const meta = (re: RegExp) => shell.match(re)?.[1] ?? "";
const siteTitle = meta(/<title>([^<]*)<\/title>/);
const siteDescription = meta(/<meta name="description" content="([^"]*)"/);
// The shell names its own domain in the image tags; point them at this deploy.
const own = (s: string) => s.replace(/https:\/\/c2abench\.com\//g, site);

// The Pages fallback for every route that has no file of its own: the shell as built, with no page's text in it.
await write("404.html", shell);

/** The shell with this page's head tags and text. The title, description, canonical, og:* and twitter:* tags it owns are replaced. */
function page(p: { title: string; description: string; url: string; type: "website" | "article"; extraHead?: string; text: string }) {
  const owns = /^\s*(<title>|<meta name="description"|<link rel="canonical"|<meta property="og:(type|title|description|url)"|<meta name="twitter:(title|description)")/;
  const head = `<title>${esc(p.title)}</title>
    <meta name="description" content="${esc(p.description)}" />
    <link rel="canonical" href="${p.url}" />
    <meta name="robots" content="index, follow, max-image-preview:large" />
    <meta property="og:type" content="${p.type}" />
    <meta property="og:title" content="${esc(p.title)}" />
    <meta property="og:description" content="${esc(p.description)}" />
    <meta property="og:url" content="${p.url}" />
    <meta name="twitter:title" content="${esc(p.title)}" />
    <meta name="twitter:description" content="${esc(p.description)}" />
    ${p.extraHead ?? ""}
    <noscript><style>#static[hidden]{display:block}</style></noscript>`;
  const lines = own(shell).split("\n");
  const at = lines.findIndex((l) => l.includes('name="viewport"'));
  return [...lines.slice(0, at + 1), `    ${head}`, ...lines.slice(at + 1).filter((l) => !owns.test(l))].join("\n")
    .replace('<div id="root" class="contents"></div>', `<div id="root" class="contents"><div id="static" hidden>${p.text}</div></div>`);
}

// ---- what the pages say ----

const pct = (x: number) => `${Math.round(x * 100)}%`;
const table = (head: string, rows: [string, number][]) =>
  `<table><thead><tr><th>${head}</th><th>Pass rate</th></tr></thead><tbody>${[...rows].sort((x, y) => y[1] - x[1]).map(([k, v]) => `<tr><td>${esc(k)}</td><td>${pct(v)}</td></tr>`).join("")}</tbody></table>`;
type Job = Parameters<typeof pooled>[0];
const landing = JSON.parse(await readFile(path.join(out, "landing.json"), "utf8")) as { index: { updatedAt?: string; tasks: { id: string; name: string; description: string; jobs: Job[] }[] } };
const jobsOf = (id: string) => (landing.index.tasks.find((t) => t.id === id)?.jobs ?? []) as never;
const redwood = latestByBuilder(jobsOf("redwood-inference"));
const byArch = new Map<string, number[]>();
for (const j of latestByArchitecture(jobsOf("skyway-air"))) byArch.set(j.architecture!, [...(byArch.get(j.architecture!) ?? []), pooled(j)]);
/** The headline numbers behind the charts, from the same data and helpers as the landing page. */
const results = `<h2>Results at a glance</h2>
<p>Pass rate is the share of customer tickets resolved. Each builder's latest finished run.</p>
${table("Builder model, Redwood Inference", redwood.map((b) => [shortModel(b.model), pooled(b.job)]))}
${table("Architecture, Skyway Air (average over builders)", [...byArch].map(([k, v]) => [SKYWAY_ARCH[k] ?? k, v.reduce((a, b) => a + b, 0) / v.length]))}`;

const latest = POSTS[0];
const urlOf = (slug: string) => `${site}blog/${slug}/`;
const publisher = { "@type": "Organization", name: "Observe.AI", url: "https://www.observe.ai/" };
const image = `${site}og.png`;

// Markdown as plain HTML: internal links become real URLs, `[text](#tip "note")` hover notes become their text.
const a = ({ href, children }: { href?: string; children?: unknown }) =>
  href === "#tip" ? createElement("span", null, children as never) : createElement("a", { href: href?.startsWith("/") ? `${site}${href.slice(1)}` : href }, children as never);
const html = (md: string) => renderToStaticMarkup(createElement(Markdown, { remarkPlugins: [remarkGfm], components: { a } }, md));

// ---- home ----

await write("index.html", page({
  title: siteTitle, description: siteDescription, url: site, type: "website",
  extraHead: ld({
    "@context": "https://schema.org",
    "@graph": [
      { "@type": "WebSite", "@id": `${site}#website`, url: site, name: "C2A Bench", alternateName: ["C2A", "Context2Agent Benchmark"], description: siteDescription, publisher: { "@id": `${site}#org` } },
      { ...publisher, "@id": `${site}#org`, sameAs: ["https://github.com/c2a-bench/c2a-bench", "https://huggingface.co/datasets/observeai/c2a-bench"] },
    ],
  }),
  text: `<h1>C2A: the Context2Agent Benchmark</h1>
<p>${esc(siteDescription)} Policies and procedures keep changing, and a support agent has to keep up. A coding agent (the builder) builds a customer support agent from a company's docs, then updates it as the docs change, and the agent is graded ticket by ticket against a simulated customer.</p>
${POSTS.map((p) => `<p><a href="${urlOf(p.slug)}">Read the blog post: ${esc(p.title)}</a></p>`).join("\n")}
<h2>Environments</h2>
<ul>${landing.index.tasks.map((t) => `<li><b>${esc(t.name)}</b>: ${esc(t.description)}</li>`).join("")}</ul>
${results}`,
}));

// ---- blog ----

for (const post of POSTS) {
const postUrl = urlOf(post.slug);
await write(`blog/${post.slug}/index.html`, page({
  title: post.title, description: post.description, url: postUrl, type: "article",
  extraHead: `<meta property="article:published_time" content="${post.date}" />
    <meta property="article:modified_time" content="${post.updated ?? post.date}" />
    <link rel="alternate" type="text/markdown" href="${site}blog/${post.slug}.md" />
    ${ld({
      "@context": "https://schema.org",
      "@graph": [
        { "@type": "BlogPosting", "@id": `${postUrl}#post`, headline: post.title, description: post.description, datePublished: post.date, dateModified: post.updated ?? post.date, image, url: postUrl, mainEntityOfPage: postUrl, isPartOf: { "@id": `${site}#website` }, publisher },
        { "@type": "BreadcrumbList", itemListElement: [{ "@type": "ListItem", position: 1, name: "C2A Bench", item: site }, { "@type": "ListItem", position: 2, name: post.title, item: postUrl }] },
      ],
    })}`,
  text: `<p><a href="${site}">C2A Bench</a></p>
<article>
<h1>${esc(post.title)}</h1>
<p><time datetime="${post.date}">${post.date}</time></p>
${html(post.body)}
${results}
</article>`,
}));

// The post as Markdown, for readers that prefer it.
await write(`blog/${post.slug}.md`, `# ${post.title}\n\n${post.body
  .replace(/<!--[\s\S]*?-->\n?/g, "")
  .replace(/\[([^\]]+)\]\(#tip "([^"]*)"\)/g, "$1 ($2)")
  .replace(/\]\(\/([^)]*)\)/g, `](${site}$1)`)}\n`);
}

// /blog goes to the newest post (client-side the app does the same).
await write("blog/index.html", `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>${esc(latest.title)}</title>
<link rel="icon" href="${site}favicon.svg" type="image/svg+xml">
<link rel="canonical" href="${urlOf(latest.slug)}"><meta http-equiv="refresh" content="0; url=${urlOf(latest.slug)}"></head>
<body><a href="${urlOf(latest.slug)}">${esc(latest.title)}</a></body></html>
`);


// ---- crawler files ----

const day = (iso?: string) => (iso ? `<lastmod>${iso.slice(0, 10)}</lastmod>` : "");
await write("sitemap.xml", `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>${site}</loc>${day(landing.index.updatedAt)}</url>
${POSTS.map((p) => `<url><loc>${urlOf(p.slug)}</loc>${day(p.updated ?? p.date)}</url>`).join("\n")}
</urlset>
`);
// robots.txt is only honoured at the host root; harmless (and still correct) when the site lives under a path.
await write("robots.txt", `User-agent: *\nAllow: /\n\nSitemap: ${site}sitemap.xml\n`);
await write("llms.txt", `# C2A Bench

> ${siteDescription}

## Read

${POSTS.map((p) => `- [${p.title}](${urlOf(p.slug)}): ${p.description}\n- [The same post as Markdown](${site}blog/${p.slug}.md)`).join("\n")}
- [Home page: leaderboard and charts](${site})

## Code and data

- [GitHub: c2a-bench](https://github.com/c2a-bench/c2a-bench)
- [Benchmark dataset on Hugging Face](https://huggingface.co/datasets/observeai/c2a-bench)
- [Run results on Hugging Face](https://huggingface.co/datasets/observeai/c2a-bench-runs)
`);
console.log(`prerendered home, ${POSTS.length} post(s), 404.html, sitemap.xml, robots.txt, llms.txt in ${out} for ${site}`);
