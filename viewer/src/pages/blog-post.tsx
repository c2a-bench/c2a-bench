/**
 * The blog: the one post, rendered from its Markdown (src/blog). Two comments in the Markdown become figures:
 * `<!-- figure:<name> -->` draws that landing chart from live data, and
 * `<!-- shot:<file> | <caption> | <link> -->` shows a run-page screenshot from public/blog (light and dark versions).
 */
import { Suspense, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router";
import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { ArrowRight, ChevronRight, ChevronsRight, List } from "lucide-react";
import { Nav, RepoLinks } from "@/landing/nav";
import { publicAsset } from "@/lib/assets";
import { POSTS, postDate, type Post } from "@/blog/posts";
import { NotFound } from "@/pages/not-found";
import { usePageTitle } from "@/lib/title";
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
    title: "Failure reasons by builder",
    from: "Redwood Inference",
    caption: "Each bar splits a builder's failure reasons: warm colours are the builder's fault, blue ones the agent's. Every builder ran with high reasoning effort. Hover a segment for its share.",
    skyway: "Each bar splits a builder's failure reasons over all six architectures it built: warm colours are the builder's fault, blue ones the agent's. Every builder ran with high reasoning effort. Hover a segment for its share.",
    href: "/#failures",
  },
  architecture: {
    title: "Share of tickets passed, by architecture",
    from: "Skyway Air",
    caption: "Six builders (high reasoning effort), each building all six assigned architectures; each bar pools their runs, and the dashed line is the average. Hover a row for its numbers.",
    href: "/#architecture",
  },
  packs: {
    title: "Pass rate change on each changed pack",
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
  a: ({ href, title, children, ...rest }) =>
    href === "#tip" ? (
      <span className="lp-tip" tabIndex={0} data-tip={title ?? ""} aria-label={title ?? undefined}>{children}</span>
    ) : href?.startsWith("/") && !href.startsWith("//") ? (
      <Link to={href} title={title} {...rest}>{children}</Link>
    ) : (
      <a href={href} title={title} {...rest}>{children}</a>
    ),
};

const SHOT_SIZE: Record<string, [number, number]> = { "run-customers": [2112, 1064], "run-stages": [2112, 1058], "run-ticket": [2880, 1720] };

const slug = (text: string) => text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

type TocItem = { id: string; text: string; level: 2 | 3 };
/**
 * The post's `##` and `###` headings, read from the rendered page so the list can never disagree with it: whatever the
 * Markdown holds (emphasis, code, links, a repeated title, a new section) gets an id here, unique, and an entry in the list.
 */
function useHeadings(body: React.RefObject<HTMLElement | null>, source: string): TocItem[] {
  const [items, setItems] = useState<TocItem[]>([]);
  useLayoutEffect(() => {
    const used = new Set<string>();
    const list: TocItem[] = [];
    body.current?.querySelectorAll<HTMLElement>(":scope > h2, :scope > h3").forEach((h, i) => {
      const text = (h.textContent ?? "").trim();
      const base = slug(text) || `section-${i + 1}`;
      let id = base;
      for (let n = 2; used.has(id); n++) id = `${base}-${n}`;
      used.add(id);
      h.id = id;
      list.push({ id, text, level: h.tagName === "H2" ? 2 : 3 });
    });
    setItems(list);
  }, [body, source]);
  return items;
}

const TOC_KEY = "c2a-blog-toc";
const WIDE = "(min-width: 960px)";

type TocGroup = { head: TocItem; kids: TocItem[] };
const groupsOf = (items: TocItem[]): TocGroup[] => {
  const groups: TocGroup[] = [];
  for (const it of items) {
    if (it.level === 2 || !groups.length) groups.push({ head: it, kids: [] });
    else groups[groups.length - 1].kids.push(it);
  }
  return groups;
};

/** Every section, with its subsections under it: open for the section being read (or by its chevron), closed otherwise. */
function TocTree({ groups, active, section, manual, onToggle, onGo }: {
  groups: TocGroup[]; active: string; section: string; manual: Record<string, boolean>;
  onToggle: (id: string, open: boolean) => void; onGo: (id: string) => void;
}) {
  const link = (it: TocItem, tab: boolean) => (
    <a href={`#${it.id}`} data-active={it.id === active || undefined} aria-current={it.id === active ? "location" : undefined}
      tabIndex={tab ? undefined : -1} onClick={(e) => { e.preventDefault(); onGo(it.id); }}>
      {it.text}
    </a>
  );
  return (
    <ul className="lp-toc-tree">
      {groups.map((g) => {
        const open = manual[g.head.id] ?? g.head.id === section;
        const subId = `lp-toc-${g.head.id}`;
        return (
          <li key={g.head.id} data-section={g.head.id === section || undefined}>
            <div className="lp-toc-row">
              {link(g.head, true)}
              {g.kids.length > 0 && (
                <button type="button" className="lp-toc-chev" aria-expanded={open} aria-controls={subId}
                  aria-label={`Subsections of ${g.head.text}`} onClick={() => onToggle(g.head.id, !open)}>
                  <ChevronRight className="size-3.5" aria-hidden />
                </button>
              )}
            </div>
            {g.kids.length > 0 && (
              <div className="lp-toc-subwrap" data-open={open || undefined}>
                <ul className="lp-toc-sub" id={subId} aria-hidden={!open}>
                  {g.kids.map((k) => <li key={k.id}>{link(k, open)}</li>)}
                </ul>
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

/**
 * Contents. From 960px up a rail sits beside the article, level with where the text starts, rides up with the page and then stays
 * on screen (wide screens centre the article, middling ones shift it left); narrower ones get a bar under the nav that shows the
 * section being read, a reading-progress line, and a sheet with the whole list. Either way the section being read is
 * highlighted and its subsections open as you enter it and close as you leave. The rail collapses to one button
 * (remembered on wide screens).
 */
function TocRail({ items }: { items: TocItem[] }) {
  const groups = useMemo(() => groupsOf(items), [items]);
  const [open, setOpen] = useState(() => {
    try {
      const saved = localStorage.getItem(TOC_KEY);
      if (saved && matchMedia(WIDE).matches) return saved === "1";
    } catch { /* storage can be blocked */ }
    return true;
  });
  const [sheet, setSheet] = useState(false);
  const [active, setActive] = useState(items[0]?.id ?? "");
  const [progress, setProgress] = useState(0);
  const [manual, setManual] = useState<Record<string, boolean>>({});
  const raf = useRef(0);

  // The section being read: the last heading that has reached the top of the page.
  useEffect(() => {
    const update = () => {
      raf.current = 0;
      const line = matchMedia(WIDE).matches ? 120 : 160;
      let current = items[0]?.id ?? "";
      for (const it of items) {
        const el = document.getElementById(it.id);
        if (el && el.getBoundingClientRect().top <= line) current = it.id;
      }
      setActive(current);
      const max = document.documentElement.scrollHeight - innerHeight;
      setProgress(max > 0 ? Math.min(1, Math.max(0, scrollY / max)) : 0);
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

  const section = useMemo(() => groups.find((g) => g.head.id === active || g.kids.some((k) => k.id === active))?.head.id ?? "", [groups, active]);
  const current = items.find((it) => it.id === active)?.text ?? "";
  // Moving to another section lets it decide what is open again.
  useEffect(() => setManual({}), [section]);
  useEffect(() => {
    if (!sheet) return;
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setSheet(false);
    addEventListener("keydown", esc);
    return () => removeEventListener("keydown", esc);
  }, [sheet]);

  const toggleRail = (next: boolean) => {
    setOpen(next);
    try { localStorage.setItem(TOC_KEY, next ? "1" : "0"); } catch { /* ignore */ }
  };
  const go = (id: string) => {
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    document.getElementById(id)?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
    setSheet(false);
  };
  // keep the active entry in view when the list is longer than the panel
  useEffect(() => {
    const link = document.querySelector<HTMLElement>(".lp-toc--rail a[data-active]");
    const panel = link?.closest<HTMLElement>(".lp-toc-panel");
    if (!link || !panel) return;
    const l = link.getBoundingClientRect(), p = panel.getBoundingClientRect();
    if (l.top < p.top) panel.scrollTop -= p.top - l.top + 8;
    else if (l.bottom > p.bottom) panel.scrollTop += l.bottom - p.bottom + 8;
  }, [active, manual, open]);
  const tree = (
    <TocTree groups={groups} active={active} section={section} manual={manual} onToggle={(id, o) => setManual((m) => ({ ...m, [id]: o }))} onGo={go} />
  );

  if (!items.length) return null;
  return (
    <div className="lp-toc-root">
      <nav className="lp-toc lp-toc--rail" aria-label="Contents" data-open={open || undefined}>
        <div className="lp-toc-sticky">
          <div className="lp-toc-panel" inert={!open}>
            <div className="lp-toc-head">
              <span className="lp-toc-label">Contents</span>
              <button type="button" className="lp-toc-collapse" onClick={() => toggleRail(false)} aria-label="Hide contents" aria-expanded={open}>
                <ChevronsRight className="size-4" aria-hidden />
              </button>
            </div>
            {tree}
          </div>
        </div>
      </nav>
      {!open && <button type="button" className="lp-toc-edge" onClick={() => toggleRail(true)} aria-label="Show contents" aria-expanded="false" />}
      <div className="lp-toc-bar" data-open={sheet || undefined}>
        <button type="button" className="lp-toc-bar-btn" aria-expanded={sheet} aria-controls="lp-toc-sheet" onClick={() => setSheet((v) => !v)}>
          <List className="size-4 shrink-0" aria-hidden />
          <span className="lp-toc-bar-cur">{current}</span>
          <ChevronRight className="lp-toc-bar-chev size-4 shrink-0" aria-hidden />
        </button>
        <div className="lp-toc-bar-progress" aria-hidden><span style={{ transform: `scaleX(${progress})` }} /></div>
        {sheet && <nav className="lp-toc-sheet" id="lp-toc-sheet" aria-label="Contents">{tree}</nav>}
      </div>
    </div>
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
      const [width, height] = SHOT_SIZE[name] ?? [2112, 1064]; // the files' own sizes, so the page does not jump as they load
      out.push(
        <Frame key={name} kicker="From a run page" caption={caption} href={href} link="Open this run">
          <img src={publicAsset(`blog/${name}-light.jpg`)} alt={caption} width={width} height={height} className="lp-shot dark:hidden" loading="lazy" />
          <img src={publicAsset(`blog/${name}-dark.jpg`)} alt={caption} width={width} height={height} className="lp-shot hidden dark:block" loading="lazy" />
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
  const post = POSTS.find((p) => p.slug === useParams().slug);
  return post ? <PostPage post={post} /> : <NotFound />;
}

function PostPage({ post }: { post: Post }) {
  usePageTitle(post.title);
  const prose = useRef<HTMLDivElement>(null);
  const items = useHeadings(prose, post.body);
  return (
    <div className="lp min-h-screen">
      <Nav />
      <main className="lp-wrap" style={{ paddingTop: "calc(var(--nav) + clamp(56px, 9vh, 112px))", paddingBottom: 140 }}>
        <article className="lp-article">
          <div className="caps muted">
            <time dateTime={post.date}>{postDate(post.date)}</time>
            {post.updated && <> · Updated <time dateTime={post.updated}>{postDate(post.updated)}</time></>}
          </div>
          <h1 style={{ marginTop: 16, fontSize: "clamp(36px, 2.6vw + 22px, 64px)", lineHeight: 1.08 }}>{post.title}</h1>
          <RepoLinks className="muted mt-5" />
          <div className="lp-prose" style={{ marginTop: 40 }} ref={prose}>
            <TocRail items={items} />
            <Body md={post.body} />
          </div>
        </article>
      </main>
    </div>
  );
}
