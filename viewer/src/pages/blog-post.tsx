/**
 * The blog: the one post, rendered from its Markdown (src/blog). Two comments in the Markdown become figures:
 * `<!-- figure:<name> -->` draws that landing chart from live data, and
 * `<!-- shot:<file> | <caption> | <link> -->` shows a run-page screenshot from public/blog (light and dark versions).
 */
import { Suspense, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router";
import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { ArrowRight, ChevronsRight, List } from "lucide-react";
import { Nav, RepoLinks } from "@/landing/nav";
import { publicAsset } from "@/lib/assets";
import { POSTS, postDate } from "@/blog/posts";
import { LandingFigure, Seg, type FigureEnv, type FigureName } from "@/pages/home";
import { TicketViewer, BehaviourViewer, CustomerTypeViewer } from "@/blog/viewers";
import "@/landing/landing.css";

/** `skyway` (with its own caption) gives the figure a Redwood / Skyway toggle; the figure opens on Redwood. */
const FIGURES: Record<FigureName, { title: string; from: string; caption: string; href: string; skyway?: string }> = {
  results: {
    title: "Pass rate by builder",
    from: "Redwood Inference",
    caption: "Each column is one builder, every one run with high reasoning effort.",
    skyway: "Each column is one builder, pooled over the six architectures it was assigned, every one run with high reasoning effort.",
    href: "/#results",
  },
  failures: {
    title: "Why tickets failed",
    from: "Redwood Inference",
    caption: "Each bar splits a builder's failure reasons: warm colours are the builder's fault, blue ones the agent's. Every builder ran with high reasoning effort. Hover a segment for its share.",
    skyway: "Each bar splits a builder's failure reasons over all six architectures it built: warm colours are the builder's fault, blue ones the agent's. Every builder ran with high reasoning effort. Hover a segment for its share.",
    href: "/#failures",
  },
  architecture: {
    title: "Pass rate by architecture",
    from: "Skyway Air",
    caption: "Six builders (high reasoning effort), each building all six assigned architectures; each bar pools their runs, and the dashed line is the average. Hover a row for its numbers.",
    href: "/#architecture",
  },
  packs: {
    title: "How changed docs move the score",
    from: "Knowledge perturbations",
    caption: "Each bar is one builder's gain or loss on a changed pack against its own complete-docs score; the big number is the typical change. Every builder ran with high reasoning effort.",
    href: "/#packs",
  },
};

const VIEWERS: Record<string, { kicker: string; title: string; caption?: string; href?: string; link?: string; View: () => ReactNode }> = {
  ticket: {
    kicker: "One ticket, six stages",
    title: "How a ticket changes",
    caption: "A simplified demo of one ticket, based on a real Skyway Air ticket and run (knowledge-graph design) where the agent really did fail at stage 3. Click a stage to replay it.",
    href: "/#environments",
    link: "See the environments",
    View: TicketViewer,
  },
  behaviours: {
    kicker: "The simulated customer",
    title: "Customer behaviors",
    caption: "Each ticket gives the customer one of these behaviors. It changes how the customer shares the facts, never the facts themselves or the right answer. Each example is a real exchange from a run, trimmed.",
    href: "/#environments",
    link: "See the environments",
    View: BehaviourViewer,
  },
  "customer-types": {
    kicker: "Across every run",
    title: "Pass rate and customer recall by customer behavior",
    caption: "Pooled over every Redwood Inference and Skyway Air run. Pass rate is the share of tickets passed; customer recall is the share of the customer's facts the agent got them to share. Switch between them above the chart.",
    href: "/#environments",
    link: "See the environments",
    View: CustomerTypeViewer,
  },
};

function Frame({ kicker, title, note, caption, href, link, right, children }: { kicker: string; title?: string; note?: string; caption?: string; href?: string; link?: string; right?: ReactNode; children: ReactNode }) {
  const inner = !href ? null : <Link to={href}>{link} <ArrowRight className="inline size-3.5" /></Link>;
  return (
    <figure className="lp-figure">
      {right ? (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="caps muted">{kicker}</div>
          {right}
        </div>
      ) : (
        <div className="caps muted">{kicker}</div>
      )}
      {title && <div className="lp-figure-title">{title}</div>}
      {note && <div className="lp-figure-note"><span aria-hidden="true">★</span> {note}</div>}
      <div className="lp-figure-body">{children}</div>
      {(caption || inner) && (
        <figcaption>
          {caption} {inner && <span className="lp-figure-link">{inner}</span>}
        </figcaption>
      )}
    </figure>
  );
}

/** A Markdown link to `#tip` is a hover note, not a link: `[668 test cases](#tip "how it adds up")`. */
const MD: Components = {
  h2: ({ children }) => <h2 id={headingId(plain(children))}>{children}</h2>,
  h3: ({ children }) => <h3 id={headingId(plain(children))}>{children}</h3>,
  a: ({ href, title, children, ...rest }) =>
    href === "#tip" ? (
      <span className="lp-tip" tabIndex={0} data-tip={title ?? ""} aria-label={title ?? undefined}>{children}</span>
    ) : href?.startsWith("/") && !href.startsWith("//") ? (
      <Link to={href} title={title} {...rest}>{children}</Link>
    ) : (
      <a href={href} title={title} {...rest}>{children}</a>
    ),
};

/** The text of a rendered heading, so the id the page puts on it matches the one the contents list links to. */
function plain(node: ReactNode): string {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(plain).join("");
  if (typeof node === "object" && "props" in node) return plain((node.props as { children?: ReactNode }).children);
  return "";
}
const headingId = (text: string) => text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

type TocItem = { id: string; text: string; level: 2 | 3 };
/** The post's `##` and `###` headings, in order. Inline Markdown (code, bold, links) is reduced to its text. */
function headingsOf(md: string): TocItem[] {
  return [...md.matchAll(/^(#{2,3})\s+(.+?)\s*$/gm)].map((m) => {
    const text = m[2].replace(/`([^`]*)`/g, "$1").replace(/\*+/g, "").replace(/\[([^\]]*)\]\([^)]*\)/g, "$1");
    return { id: headingId(text), text, level: m[1].length as 2 | 3 };
  });
}

const TOC_KEY = "c2a-blog-toc";
const WIDE = "(min-width: 1280px)";

/**
 * Contents rail. Wide screens dock it to the right of the article; narrower ones float it as a button that opens a panel.
 * It highlights the section being read, opens a section's subsections only while you are in it, and collapses to one button
 * (the choice is remembered on wide screens).
 */
function TocRail({ items }: { items: TocItem[] }) {
  const [open, setOpen] = useState(() => {
    try {
      const saved = localStorage.getItem(TOC_KEY);
      if (saved && matchMedia(WIDE).matches) return saved === "1";
    } catch { /* storage can be blocked */ }
    return matchMedia(WIDE).matches;
  });
  const [active, setActive] = useState(items[0]?.id ?? "");
  const raf = useRef(0);

  // The section being read: the last heading that has reached the top of the page.
  useEffect(() => {
    const update = () => {
      raf.current = 0;
      const line = 120;
      let current = items[0]?.id ?? "";
      for (const it of items) {
        const el = document.getElementById(it.id);
        if (el && el.getBoundingClientRect().top <= line) current = it.id;
      }
      setActive(current);
    };
    const onScroll = () => (raf.current ||= requestAnimationFrame(update));
    update();
    addEventListener("scroll", onScroll, { passive: true });
    addEventListener("resize", onScroll);
    return () => {
      removeEventListener("scroll", onScroll);
      removeEventListener("resize", onScroll);
      cancelAnimationFrame(raf.current);
    };
  }, [items]);

  const toggle = (next: boolean) => {
    setOpen(next);
    try {
      if (matchMedia(WIDE).matches) localStorage.setItem(TOC_KEY, next ? "1" : "0");
    } catch { /* ignore */ }
  };
  const go = (id: string) => {
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    document.getElementById(id)?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
    if (!matchMedia(WIDE).matches) setOpen(false);
  };

  // The section the reader is in: the active h2, or the h2 above the active h3.
  const section = useMemo(() => {
    const i = items.findIndex((it) => it.id === active);
    for (let k = i; k >= 0; k--) if (items[k].level === 2) return items[k].id;
    return "";
  }, [items, active]);

  if (!open) {
    return (
      <nav className="lp-toc lp-toc--closed" aria-label="Contents">
        <button type="button" className="lp-toc-btn" onClick={() => toggle(true)} aria-expanded="false" aria-controls="lp-toc-panel">
          <List className="size-4" aria-hidden /> Contents
        </button>
      </nav>
    );
  }
  let parent = "";
  return (
    <nav className="lp-toc" aria-label="Contents">
      <div className="lp-toc-panel" id="lp-toc-panel">
        <div className="lp-toc-head">
          <span className="caps muted">Contents</span>
          <button type="button" className="lp-toc-collapse" onClick={() => toggle(false)} aria-label="Collapse contents" aria-expanded="true" aria-controls="lp-toc-panel">
            <ChevronsRight className="size-4" aria-hidden />
          </button>
        </div>
        <ol>
          {items.map((it) => {
            if (it.level === 2) parent = it.id;
            if (it.level === 3 && parent !== section) return null;
            return (
              <li key={it.id} className={it.level === 3 ? "lp-toc-sub" : undefined}>
                <a href={`#${it.id}`} data-active={it.id === active || undefined} aria-current={it.id === active ? "location" : undefined}
                  onClick={(e) => { e.preventDefault(); go(it.id); }}>
                  {it.text}
                </a>
              </li>
            );
          })}
        </ol>
      </div>
    </nav>
  );
}

/** A landing chart in the post; one that has Skyway Air data too gets a Redwood / Skyway toggle above it. */
function ChartFigure({ name }: { name: FigureName }) {
  const f = FIGURES[name];
  const [env, setEnv] = useState<FigureEnv>("redwood");
  const sky = env === "skyway" && !!f.skyway;
  const toggle = f.skyway ? <Seg value={env} onChange={setEnv} options={[["redwood", "Redwood Inference"], ["skyway", "Skyway Air"]]} /> : undefined;
  return (
    <Frame kicker={`From: ${sky ? "Skyway Air" : f.from}`} title={f.title} note="All runs at high reasoning effort" caption={sky ? f.skyway : f.caption} href={f.href} link="See it on the results page" right={toggle}>
      <Suspense fallback={<div className="lp-figure-wait muted">Loading the latest runs…</div>}>
        <LandingFigure name={name} env={sky ? "skyway" : "redwood"} compact />
      </Suspense>
    </Frame>
  );
}

const PART = /<!--\s*(figure|shot):\s*([\w-]+)\s*(?:\|\s*([\s\S]*?)\s*\|\s*(\S+)\s*)?-->/g;

function Body({ md }: { md: string }) {
  const out: ReactNode[] = [];
  let last = 0;
  for (const m of md.matchAll(PART)) {
    const text = md.slice(last, m.index);
    if (text.trim()) out.push(<Markdown key={`t${last}`} remarkPlugins={[remarkGfm]} components={MD}>{text}</Markdown>);
    const [, kind, name, caption = "", href = "/"] = m;
    if (kind === "figure" && name in VIEWERS) {
      const v = VIEWERS[name];
      out.push(
        <Frame key={name} kicker={v.kicker} title={v.title} caption={v.caption} href={v.href} link={v.link}>
          <v.View />
        </Frame>,
      );
    } else if (kind === "figure" && name in FIGURES) {
      out.push(<ChartFigure key={name} name={name as FigureName} />);
    } else if (kind === "shot") {
      out.push(
        <Frame key={name} kicker="From a run page" caption={caption} href={href} link="Open this run">
          <img src={publicAsset(`blog/${name}-light.jpg`)} alt={caption} className="lp-shot dark:hidden" loading="lazy" />
          <img src={publicAsset(`blog/${name}-dark.jpg`)} alt={caption} className="lp-shot hidden dark:block" loading="lazy" />
        </Frame>,
      );
    }
    last = m.index! + m[0].length;
  }
  const rest = md.slice(last);
  if (rest.trim()) out.push(<Markdown key={`t${last}`} remarkPlugins={[remarkGfm]} components={MD}>{rest}</Markdown>);
  return <>{out}</>;
}

export default function BlogPost() {
  const post = POSTS[0];
  const items = useMemo(() => headingsOf(post.body), [post.body]);
  return (
    <div className="lp min-h-screen">
      <Nav />
      <TocRail items={items} />
      <main className="lp-wrap" style={{ paddingTop: "calc(var(--nav) + clamp(56px, 9vh, 112px))", paddingBottom: 140 }}>
        <article className="lp-article">
          <div className="caps muted">{postDate(post.date)}</div>
          <h1 style={{ marginTop: 16, fontSize: "clamp(36px, 2.6vw + 22px, 64px)", lineHeight: 1.08 }}>{post.title}</h1>
          <RepoLinks className="muted mt-5" />
          <div className="lp-prose" style={{ marginTop: 40 }}>
            <Body md={post.body} />
          </div>
        </article>
      </main>
    </div>
  );
}
