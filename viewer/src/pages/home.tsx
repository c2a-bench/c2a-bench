/*
 * Landing page. Hero, then the journey (one figure morphing doc → prompt → agent → chat → checklist as the steps scroll by), then the
 * four cross-builder charts, environments, grading and the closing. Normal scroll; only the nav and the journey figure are pinned.
 */
import { Suspense, use, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { publicAsset } from "@/lib/assets";
import { ArrowRight } from "lucide-react";
import { CONTRIBUTING, Nav, RepoLinks } from "@/landing/nav";
import { Journey } from "@/landing/journey";
import { ArchTradeoff, ArchTypes, RecallScatter, type ArchRun, type TicketType, type RecallPoint, type StageRow, type StagePoint } from "@/landing/charts";
import { CONDITIONS, CONFOUND, ENV, SKYWAY_ARCH, catalog, crashed, harnessName, loadMetas, pooled, shortModel, stagesOf, style, type Builder, type FailureGroup, type Shape } from "@/landing/data";
import type { JobSummary } from "@/lib/data";
import { FIRST_POST } from "@/blog/first";
import { SITE_TITLE, usePageTitle } from "@/lib/title";
import { BenchmarkBars, ChangePanels, Columns, CostScatter, StageLines, REASONS, ReasonBars, type ReasonKey, type ReasonRow } from "@/landing/simple-charts";
import "@/landing/landing.css";


const day = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" }) : "");
const fmt = (n: number) => n.toLocaleString("en-US");

/**
 * One title that travels. The hero's h1 keeps its place in the layout (invisible); a fixed copy is drawn over it and,
 * as the page scrolls, it shrinks and slides into the nav's slot, reaching it exactly when the h1 would pass under the
 * nav, and stays docked there. Scrolling back reverses it. Positions are measured, so it fits any width.
 */
function useDockedTitle(hero: React.RefObject<HTMLElement | null>, slot: React.RefObject<HTMLElement | null>, title: React.RefObject<HTMLAnchorElement | null>, divider: React.RefObject<HTMLElement | null>) {
  useLayoutEffect(() => {
    const h = hero.current, n = slot.current, t = title.current, d = divider.current;
    if (!h || !n || !t || !d) return;
    let m = { left: 0, top: 0, size: 0, toLeft: 0, toTop: 0, toSize: 0, cw: [] as number[], rh: 0, rw: 0 };
    const parts = () => [...t.querySelectorAll<HTMLElement>("[data-c]")];
    const rest = t.querySelector<HTMLElement>("[data-r]")!;
    const measure = () => {
      const hr = h.getBoundingClientRect(), nr = n.getBoundingClientRect();
      t.style.fontSize = `${parseFloat(getComputedStyle(h).fontSize)}px`;
      parts().forEach((e) => (e.style.width = ""));
      rest.style.height = rest.style.width = "";
      // natural (unscaled) sizes of the letters that fold away, so the name can shrink to C2A smoothly
      m = { left: hr.left, top: hr.top + scrollY, size: parseFloat(getComputedStyle(h).fontSize), toLeft: nr.left, toTop: nr.top, toSize: parseFloat(getComputedStyle(n).fontSize), cw: parts().map((e) => e.offsetWidth), rh: rest.offsetHeight, rw: rest.offsetWidth };
      draw();
    };
    const draw = () => {
      const travel = Math.max(1, m.top - m.toTop);
      const p = Math.min(1, Math.max(0, scrollY / travel));
      const e = p * p * (3 - 2 * p);
      const x = m.left + (m.toLeft - m.left) * e;
      const y = p < 1 ? m.top - scrollY : m.toTop;
      const sc = 1 + (m.toSize / m.size - 1) * e;
      t.style.transform = `translate(${x}px, ${y}px) scale(${sc})`;
      t.style.pointerEvents = p >= 1 ? "auto" : "none";
      d.style.opacity = String(Math.max(0, (p - 0.8) / 0.2));
      // the rest of the name folds away on the way up, leaving the bold C, 2 and A
      const k = Math.min(1, Math.max(0, (p - 0.05) / 0.6)), q = 1 - k * k * (3 - 2 * k);
      parts().forEach((e, i) => ((e.style.width = `${m.cw[i] * q}px`), (e.style.opacity = String(q * q))));
      rest.style.height = `${m.rh * q}px`;
      rest.style.width = `${m.rw * q}px`;
      rest.style.opacity = String(q * q);
    };
    let raf = 0;
    const onScroll = () => (raf ||= requestAnimationFrame(() => ((raf = 0), draw())));
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(document.documentElement);
    ro.observe(n.parentElement!); // the logo next to the slot loads late and shifts it; re-measure so the title never lands on the logo
    addEventListener("scroll", onScroll, { passive: true });
    document.fonts?.ready.then(measure);
    return () => {
      ro.disconnect();
      removeEventListener("scroll", onScroll);
      cancelAnimationFrame(raf);
    };
  }, [hero, slot, title, divider]);
}

/** The benchmark's full name with the C, 2 and A that spell C2A in bold. The hero h1 and its travelling copy both use it so they wrap alike. */
const FullName = () => (
  <>
    <span><b>C</b><span data-c>ontext</span><b>2</b><b>A</b><span data-c>gent</span></span>
    <span data-r style={{ display: "block" }}>Benchmark</span>
  </>
);

function SectionHead({ id, title, lead, from, right }: { id?: string; title: string; lead?: ReactNode; from: string; right?: ReactNode }) {
  return (
    <div className="mb-8 flex flex-wrap items-end justify-between gap-x-8 gap-y-4 sm:mb-10">
      <div className="max-w-[62ch]">
        <span className="chip">From: {from}</span>
        <h2 id={id} className="mt-4">{title}</h2>
        {lead && <p className="lead muted mt-4">{lead}</p>}
      </div>
      {right}
    </div>
  );
}

/** A landing section, or with `bare` only its figure (the blog post embeds the figures). */
function Sec({ bare, id, className, head, children }: { bare?: boolean; id: string; className: string; head: ReactNode; children: ReactNode }) {
  if (bare) return <>{children}</>;
  return (
    <section id={id} className={className}>
      <div className="lp-wrap">
        {head}
        {children}
      </div>
    </section>
  );
}

/** Chart panels: one frame per section; each row puts a chart beside its explanation, alternating sides row by row. */
type ZigRow = { title: string; body: ReactNode; points?: ReactNode[]; note?: ReactNode; chart: ReactNode; wide?: boolean };
function Zig({ rows }: { rows: ZigRow[] }) {
  return (
    <div className="lp-zig">
      {rows.map((r, i) => (
        <div key={r.title} className={`lp-zig-row${i % 2 ? " lp-zig-row--flip" : ""}${r.wide ? " lp-zig-row--wide" : ""}`}>
          <div className="lp-zig-text">
            <h3>{r.title}</h3>
            <p className="muted mt-2">{r.body}</p>
            {r.points && r.points.length > 0 && <ul className="lp-zig-points">{r.points.map((p, k) => <li key={k}>{p}</li>)}</ul>}
            {r.note && <p className="label muted mt-4">{r.note}</p>}
          </div>
          <div className="lp-zig-chart">{r.chart}</div>
        </div>
      ))}
    </div>
  );
}

function SkywayEmpty({ what }: { what: string }) {
  return (
    <div className="card flex min-h-[300px] flex-col justify-center p-8 sm:p-12">
      <h3>No Skyway runs yet</h3>
      <p className="muted mt-3 max-w-[56ch]">
        In Skyway every builder uses the same set architectures, so {what} compares the architectures themselves. It fills in
        once we publish the first runs.
      </p>
    </div>
  );
}

// ---------------- sections ----------------

const TYPE_NAMES = [
  ["New tickets, new facts", "discovery"],
  ["Old tickets, old facts", "regression"],
  ["Old tickets, new facts", "adaptability"],
] as const;
const stagePoints = (meta: Awaited<ReturnType<typeof loadMetas>>[number]): StagePoint[] =>
  stagesOf(meta).map((s) => ({
    passed: s.passed,
    total: s.total,
    crashed: crashed(s),
    types: TYPE_NAMES.flatMap(([plain, term]) => {
      const c = s.ticket_types?.[term];
      return c ? [[plain, term, c.passed, c.total] as [string, string, number, number]] : [];
    }),
  }));
const sum = (j: JobSummary, k: "passed" | "total") => j.scores.reduce((a, s) => a + (s[k] ?? 0), 0);

export function Seg<T extends string>({ value, options, onChange }: { value: T; options: [T, string][]; onChange: (v: T) => void }) {
  return (
    <div className="seg" role="group">
      {options.map(([v, label]) => (
        <button key={v} type="button" aria-pressed={v === value} onClick={() => onChange(v)}>{label}</button>
      ))}
    </div>
  );
}

/** Pass rate by stage, comparing builder models and harnesses. Redwood: one line per builder.
 *  Skyway: one line per model, pooled over the prescribed architectures; hover draws those architectures. */
function Results({ redwood, metas, skyway, skywayMetas, bare, compact, env: fixedEnv }: { compact?: boolean; redwood: Builder[]; metas: Awaited<ReturnType<typeof loadMetas>>; skyway?: JobSummary[]; skywayMetas?: Awaited<ReturnType<typeof loadMetas>>; bare?: boolean; env?: FigureEnv }) {
  const [ownEnv, setEnvRaw] = useState<FigureEnv>(skyway?.length ? "skyway" : "redwood");
  const env = fixedEnv ?? ownEnv;
  const setEnv = (e: "redwood" | "skyway") => setEnvRaw(e);
  const [view, setView] = useState<"overall" | "stage">("overall");
  const sky = env === "skyway" && skyway?.length && skywayMetas;
  const rows: StageRow[] = sky
    ? [...new Set(skyway.map((j) => shortModel(j.builder.model)))]
        .map((model) => {
          const runs = skyway.flatMap((j, i) => (shortModel(j.builder.model) === model ? [{ j, st: stagePoints(skywayMetas[i]) }] : []));
          const n = Math.max(...runs.map((r) => r.st.length));
          const stages: StagePoint[] = Array.from({ length: n }, (_, k) => {
            const at = runs.flatMap((r) => (r.st[k] ? [r.st[k]] : []));
            const types = TYPE_NAMES.flatMap(([plain, term]) => {
              const c = at.flatMap((s) => s.types.filter((t) => t[1] === term));
              return c.length ? [[plain, term, c.reduce((a, t) => a + t[2], 0), c.reduce((a, t) => a + t[3], 0)] as [string, string, number, number]] : [];
            });
            return { passed: at.reduce((a, s) => a + (s.crashed ? 0 : s.passed), 0), total: at.reduce((a, s) => a + s.total, 0), crashed: at.every((s) => s.crashed), types };
          });
          const band = Array.from({ length: n }, (_, k) => {
            const v = runs.flatMap((r) => {
              const s = r.st[k];
              return s && s.total ? [{ name: r.j.architecture!, rate: s.crashed ? 0 : s.passed / s.total }] : [];
            });
            if (!v.length) return { lo: 0, hi: 0, loName: "", hiName: "" };
            const lo = v.reduce((a, b) => (b.rate < a.rate ? b : a)), hi = v.reduce((a, b) => (b.rate > a.rate ? b : a));
            return { lo: lo.rate, hi: hi.rate, loName: lo.name, hiName: hi.name };
          });
          const passed = runs.reduce((a, r) => a + sum(r.j, "passed"), 0), total = runs.reduce((a, r) => a + sum(r.j, "total"), 0);
          return {
            model, harness: harnessName(runs[0].j.builder.agent), ...style(model), rate: passed / total, passed, total, stages, band,
            parts: runs.map((r) => ({ name: SKYWAY_ARCH[r.j.architecture!] ?? r.j.architecture!, stages: r.st })),
          };
        })
        .sort((a, b) => b.rate - a.rate)
    : redwood
        .map((b, i) => ({ model: b.model, harness: b.harness, ...style(b.model), rate: pooled(b.job), passed: sum(b.job, "passed"), total: sum(b.job, "total"), stages: stagePoints(metas[i]) }))
        .sort((a, b) => b.rate - a.rate);
  // Skyway: one dot per builder, its pooled pass rate against what one build cost it, averaged over its architectures.
  const costs = sky
    ? rows.flatMap((r) => {
        const c = skyway.filter((j) => shortModel(j.builder.model) === r.model && j.cost != null).map((j) => j.cost!);
        return c.length ? [{ model: r.model, harness: r.harness, color: r.color, shape: r.shape, rate: r.rate, cost: c.reduce((a, x) => a + x, 0) / c.length }] : [];
      })
    : redwood.filter((b) => b.job.cost != null).map((b) => ({ model: b.model, harness: b.harness, ...style(b.model), rate: pooled(b.job), cost: b.job.cost! }));
  const toggle = skyway?.length ? <Seg value={env} onChange={setEnv} options={[["skyway", "Skyway Air"], ["redwood", "Redwood Inference"]]} /> : undefined;
  return (
    <Sec bare={bare} id="results" className="lp-sec" head={
          <SectionHead
            from={sky ? "Skyway Air" : "Redwood Inference"}
            title="Pass rate by model and harness"
            right={toggle}
          />
        }>
        {!bare && <div className="lp-figure-note mb-6"><span aria-hidden="true">★</span> All runs at high reasoning effort</div>}
        {bare ? (
          // The blog's column is narrow: under each Skyway column, just the harness (the caption says it pools six architectures).
          <Columns cols={rows.map((r) => ({ label: r.model === CONFOUND ? `${r.model} *` : r.model, sub: compact ? r.harness.split(" · ")[0] : r.harness, value: r.rate, color: r.color, tip: <div className="muted mt-0.5">{fmt(r.passed)} of {fmt(r.total)} tickets</div> }))} height={compact ? 280 : 340} />
        ) : (() => {
          const zig: ZigRow[] = [{
            title: "Which builder makes the best agent",
            body: sky
              ? "Share of all Skyway tickets each builder's agents passed."
              : "Share of all Redwood tickets each builder's agent passed, over the six stages. Every agent runs on the same model; only the builder differs.",
            points: sky ? [
              <><b>Failed builds hurt the overall score.</b> Gemini ranked second on stages where its agent ran, but failed builds dropped it to fourth overall.</>,
              <><b>Asking the customer for missing details matters.</b> The weakest builder&apos;s agents collected only 48% of the facts that only the customer knew, compared with 61% to 74% for the other builders.</>,
            ] : [
              <><b>Updates separate the builders more than the first build.</b> One builder checked file dates instead of file contents, missed newly added pages, and stayed in last place for three stages.</>,
              <><b>Testing new limits prevents failures.</b> When a prompt size limit was added in stage 4, two builders missed it completely and failed 21% of the stage, and a third still failed 8% on the same limit.</>,
            ],
            chart: (
              <>
                <div className="mb-4"><Seg value={view} onChange={setView} options={[["overall", "Overall"], ["stage", "By stage"]]} /></div>
                {view === "stage" ? (
                  <StageLines lines={rows.map((r) => ({
                    label: r.model === CONFOUND ? `${r.model} *` : r.model, sub: r.harness, color: r.color, shape: r.shape,
                    values: r.stages.map((s) => (s.total ? (s.crashed ? 0 : s.passed / s.total) : null)),
                    counts: r.stages.map((s) => `${fmt(s.crashed ? 0 : s.passed)} of ${fmt(s.total)} tickets`),
                  }))} />
                ) : (
                  <Columns cols={rows.map((r) => ({ label: r.model === CONFOUND ? `${r.model} *` : r.model, sub: r.harness, value: r.rate, color: r.color, tip: <div className="muted mt-0.5">{fmt(r.passed)} of {fmt(r.total)} tickets</div> }))} height={compact ? 280 : 340} />
                )}
              </>
            ),
          }];
          if (costs.length > 1) zig.push({
            title: "What it cost to build",
            body: sky
              ? "Cost is what one build cost the builder, averaged over its architectures."
              : "Cost is what the builder spent on the whole run.",
            points: sky ? [
              <><b>Spending more to build does not guarantee a better agent.</b> Two builders spent almost the same amount per build and finished 17 percentage points apart.</>,
              <><b>On a large doc set, build spend starts to matter.</b> Unlike on Redwood, the highest spender finishes first and the lowest spender finishes last.</>,
            ] : [
              <><b>A more expensive build does not mean a better agent.</b> The cheapest builder finishes near the top.</>,
              <><b>A cheap build can create an expensive agent.</b> Two builders with almost the same score built agents that differ by 3× in model calls per ticket.</>,
            ],
            chart: (
              <CostScatter
                dots={costs.map((c) => ({ label: c.model === CONFOUND ? `${c.model} *` : c.model, sub: c.harness, cost: c.cost, rate: c.rate, color: c.color }))}
                {...(sky ? { title: "Tickets passed vs what the builder spent per build", axis: "builder cost per architecture, log scale", spent: "Builder spent per build" } : {})}
              />
            ),
          });
          return <div className="lp-top"><Zig rows={zig} /></div>;
        })()}
    </Sec>
  );
}

type Focus = { focus: FailureGroup | null; onFocus: (g: FailureGroup | null) => void };

type Metas = Awaited<ReturnType<typeof loadMetas>>;
const recallPoints = (model: string, meta: Metas[number]): RecallPoint[] =>
  stagesOf(meta).flatMap((s, i) => (!crashed(s) && s.facts?.rule_recall != null ? [{ model, ...style(model), stage: i, recall: s.facts.rule_recall, pass: s.passed / s.total }] : []));

// The grader's failure groups (per-stage failure_taxonomy.by_group) under the chart's plain reasons.
const GROUP_REASON: Record<string, ReasonKey> = {
  "Builder / Missing knowledge (rule recall)": "recall",
  "Builder / Build spec failure": "spec",
  "Agent / Wrong end state (database check)": "state",
  "Agent / Missing customer info (customer recall)": "customer",
  "Agent / Agent crash": "crash",
};
const FOCUS_REASON: Record<FailureGroup, ReasonKey> = {
  "Missing knowledge (rule recall)": "recall",
  "Build spec failure": "spec",
  "Wrong end state (database check)": "state",
  "Missing customer info (customer recall)": "customer",
  "Agent crash": "crash",
};
const noReasons = (): Record<ReasonKey, number> => ({ recall: 0, spec: 0, state: 0, customer: 0, crash: 0 });
/** Failure reasons over a run's stages, plus its failed and total tickets. A stage whose agent never started counts all
 *  its tickets as built wrong. */
function runReasons(meta: Metas[number], into = noReasons()) {
  let failed = 0, total = 0;
  for (const st of stagesOf(meta)) {
    total += st.total;
    failed += st.total - st.passed;
    if (crashed(st)) { into.spec += st.total; continue; }
    for (const [g, v] of Object.entries(st.failure_taxonomy?.by_group ?? {})) if (GROUP_REASON[g]) into[GROUP_REASON[g]] += v;
  }
  return { parts: into, failed, total };
}

/** Why tickets failed. Redwood: one row per builder. Skyway: one row per builder too, either pooled over its runs with
 *  the prescribed architectures ("Overall") or for one architecture. An "All builders" row on top. */
function Failures({ redwood, metas, skyway, skywayMetas, focus, bare, compact, env: fixedEnv }: { compact?: boolean; redwood: Builder[]; metas: Metas; skyway?: JobSummary[]; skywayMetas?: Metas; bare?: boolean; env?: FigureEnv } & Focus) {
  const [ownEnv, setEnv] = useState<FigureEnv>(skyway?.length ? "skyway" : "redwood");
  const env = fixedEnv ?? ownEnv;
  const [arch, setArch] = useState("overall");
  const sky = env === "skyway" && !!skyway?.length && !!skywayMetas;
  const rows: (ReasonRow & { rate: number })[] = [];
  const points: RecallPoint[] = [];
  const sub = (failed: number, total: number) => `${fmt(Math.round(failed))} of ${fmt(total)} tickets failed`;
  if (sky) {
    const picked = skyway!.flatMap((j, i) => (arch === "overall" || j.architecture === arch ? [{ j, meta: skywayMetas![i] }] : []));
    for (const model of [...new Set(picked.map((r) => shortModel(r.j.builder.model)))]) {
      const mine = picked.filter((r) => shortModel(r.j.builder.model) === model);
      const parts = noReasons();
      let failed = 0, total = 0;
      for (const r of mine) { const x = runReasons(r.meta, parts); failed += x.failed; total += x.total; }
      rows.push({ label: model, sub: sub(failed, total), parts, rate: total ? (total - failed) / total : 0 });
      for (const r of mine) points.push(...recallPoints(model, r.meta));
    }
  } else {
    redwood.forEach((b, i) => {
      points.push(...recallPoints(b.model, metas[i]));
      const x = runReasons(metas[i]);
      rows.push({ label: b.model === CONFOUND ? `${b.model} *` : b.model, sub: sub(x.failed, x.total), parts: x.parts, rate: pooled(b.job) });
    });
  }
  rows.sort((a, b) => b.rate - a.rate);
  const all = noReasons();
  for (const r of rows) for (const k of Object.keys(all) as ReasonKey[]) all[k] += r.parts[k];
  return (
    <Sec bare={bare} id="failures" className="lp-sec lp-alt" head={
          <SectionHead
            from={sky ? `Skyway Air${arch === "overall" ? "" : ` · ${SKYWAY_ARCH[arch]}`}` : "Redwood Inference"}
            title="Why tickets failed"
            right={skyway?.length ? <Seg value={env} onChange={setEnv} options={[["skyway", "Skyway Air"], ["redwood", "Redwood Inference"]]} /> : undefined}
          />
        }>
        {/* The architecture picker sits here, not in the header, so the header (and its Redwood/Skyway toggle) is the same
            in both views; it is always rendered (hidden on Redwood) so its row, even when it wraps, keeps its height and nothing below moves. */}
        {!bare && skyway?.length ? (
          <div className="mb-6" style={{ visibility: sky ? "visible" : "hidden" }} aria-hidden={!sky}>
            <Seg value={arch} onChange={setArch} options={[["overall", "Overall"], ...Object.keys(SKYWAY_ARCH).filter((a) => skyway.some((j) => j.architecture === a)).map((a) => [a, a] as [string, string])]} />
          </div>
        ) : null}
        {rows.length > 0 && Object.values(all).every((v) => v === 0) && (
          <p className="muted mb-5">These runs were graded before the current failure names, so they have no breakdown to show.</p>
        )}
        {bare ? (
          <ReasonBars rows={[{ label: sky ? "All runs" : "All builders", parts: all, bold: true }, ...rows]} focus={focus ? FOCUS_REASON[focus] : null} />
        ) : (() => {
          const zig: ZigRow[] = [{
            title: "Who caused the failures",
            body: "Every failed ticket is traced to a cause, and every cause to the builder or the agent.",
            points: !Object.values(all).some((v) => v > 0) ? [] : sky ? [
              <><b>Large doc sets cause more build failures.</b> With over 10,000 pages, builders lose more rule details before the agent ever sees a ticket.</>,
              <><b>Agents act before asking.</b> Failing to ask the customer for missing details is one of the main reasons tickets fail.</>,
            ] : [
              <><b>Finding the rule is easier than using it.</b> Most failed tickets happen even when the right rule is already in the agent&apos;s files.</>,
              <><b>When a ticket is unclear, agents guess instead of asking.</b> Instead of asking a follow-up question, they pick a default value, close the ticket early, or hand it off.</>,
            ],
            note: "A failed ticket can have more than one reason, so bars show each reason's share of all reasons found. A stage where the agent never started counts all its tickets as built wrong.",
            chart: <ReasonBars rows={[{ label: sky ? "All runs" : "All builders", parts: all, bold: true }, ...rows]} focus={focus ? FOCUS_REASON[focus] : null} />,
          }];
          if (points.length > 0) zig.push({
            title: "Rule recall vs pass rate",
            body: "An agent built with all the rules can still fail to apply them to a ticket. Each mark is one builder's agent at one stage: how many of the rules its tickets needed were in the agent's files, against the share of tickets it passed.",
            points: sky ? [
              <><b>Finding the right rule at runtime is harder than storing it.</b> Keeping every document gives high rule recall, but it does not produce correct answers on its own.</>,
              <><b>Keeping the most rules does not mean the highest score.</b> The builder whose agents kept 99% of the rules still scored lower overall than two builders whose agents kept 88%.</>,
            ] : [
              <><b>Having the rule does not mean using it.</b> Even with nearly 100% rule recall, agents still fail about 25% of tickets.</>,
              <><b>Having the rules does not separate the builders.</b> Six builders kept 98% to 100% of the rules their completed stages needed, yet their overall pass rates still ranged from 60% to 80%.</>,
            ],
            note: "The shaded band is rule recall below 0.9.",
            chart: <RecallScatter points={points} height={340} />,
          });
          return <div className="lp-top"><Zig rows={zig} /></div>;
        })()}
    </Sec>
  );
}

/** The cost/time tradeoff: one mark per design, pooled over every builder's run of it (tickets passed over tickets,
 *  cost per ticket weighted by tickets, each run's median ticket time averaged); the hover lists each builder. */
function pooledDesigns(arch: ArchRun[], order: string[]): ArchRun[] {
  return order.map((a) => {
    const rs = arch.filter((r) => r.arch === a);
    const total = rs.reduce((x, r) => x + r.total, 0);
    const types: ArchRun["types"] = {};
    for (const r of rs) for (const [k, v] of Object.entries(r.types) as [TicketType, [number, number]][]) { const t = (types[k] ??= [0, 0]); t[0] += v[0]; t[1] += v[1]; }
    const n = Math.max(...rs.map((r) => r.stages.length));
    return {
      arch: a, name: rs[0].name, model: `${rs.length} builders`, harness: "pooled", color: "#8fa3bf", shape: "square",
      passed: rs.reduce((x, r) => x + r.passed, 0), total,
      stages: Array.from({ length: n }, (_, i) => rs.reduce((x, r) => x + (r.stages[i] ?? 0), 0) / rs.length),
      usd: rs.reduce((x, r) => x + r.usd * r.total, 0) / total,
      time: rs.reduce((x, r) => x + r.time, 0) / rs.length,
      tok: rs.reduce((x, r) => x + r.tok * r.total, 0) / total,
      types,
      parts: rs.map((r) => ({ model: r.model, passed: r.passed, total: r.total, usd: r.usd, time: r.time })).sort((p, q) => q.passed / q.total - p.passed / p.total),
    };
  });
}

/** One colour and marker per design, borrowed from the builder palette in landing.css. */
const DESIGN_STYLE: Record<string, { color: string; shape: Shape }> = {
  "wiki-terminal": { color: "var(--b-gemini)", shape: "square" },
  "wiki-index": { color: "var(--b-x2)", shape: "diamond" },
  "graph-query": { color: "var(--b-opus)", shape: "circle" },
  "prompt-workflows": { color: "var(--b-glm)", shape: "triangle" },
  "raw-terminal": { color: "var(--b-x1)", shape: "plus" },
  "raw-index": { color: "var(--b-deepseek)", shape: "cross" },
};

function Architecture({ runs, metas, bare, compact }: { runs: JobSummary[]; metas: Awaited<ReturnType<typeof loadMetas>>; bare?: boolean; compact?: boolean }) {
  const arch: ArchRun[] = runs.map((j, i) => {
    const st = stagesOf(metas[i]);
    const ok = st.filter((s) => !crashed(s));
    const total = st.reduce((a, s) => a + s.total, 0);
    const types: ArchRun["types"] = {};
    for (const s of st)
      for (const [t, c] of Object.entries(s.ticket_types ?? {}) as [TicketType, { passed: number; total: number }][]) {
        const v = (types[t] ??= [0, 0]);
        v[0] += c.passed;
        v[1] += c.total;
      }
    const model = shortModel(j.builder.model);
    return {
      arch: j.architecture!,
      name: SKYWAY_ARCH[j.architecture!] ?? j.architecture!,
      model,
      harness: harnessName(j.builder.agent),
      ...style(model),
      passed: st.reduce((a, s) => a + s.passed, 0),
      total,
      stages: st.map((s) => s.passed / s.total),
      usd: st.reduce((a, s) => a + (s.cost?.bot?.usd ?? 0), 0) / total,
      time: ok.reduce((a, s) => a + (s.latency?.ticket?.median ?? 0), 0) / Math.max(1, ok.length),
      tok: st.reduce((a, s) => a + (s.cost?.bot?.in ?? 0), 0) / total / 1000,
      types,
    };
  });
  const mean = (a: string) => { const rs = arch.filter((r) => r.arch === a); return rs.reduce((x, r) => x + r.passed / r.total, 0) / rs.length; };
  const order = [...new Set(arch.map((r) => r.arch))].sort((a, b) => mean(b) - mean(a));
  const builders = [...new Map(arch.map((r) => [r.model, { model: r.model, color: r.color, shape: r.shape }])).values()];
  return (
    <Sec bare={bare} id="architecture" className="lp-sec" head={
          <SectionHead
            from="Skyway Air"
            title="Pass rate by architecture"
          />
        }>
        {order.length ? (
          <>
            {(() => {
              const bars = order.map((a) => {
                const rs = arch.filter((r) => r.arch === a);
                const passed = rs.reduce((x, r) => x + r.passed, 0), total = rs.reduce((x, r) => x + r.total, 0);
                return {
                  label: a, sub: rs[0].name, value: passed / (total || 1),
                  tip: <div className="muted mt-0.5">{fmt(passed)} of {fmt(total)} tickets · built by {[...new Set(rs.map((r) => r.model))].join(", ")}</div>,
                };
              });
              const lastStage = Math.max(...arch.map((r) => r.stages.length)) - 1;
              const barsChart = <BenchmarkBars rows={bars} />;
              if (bare) return barsChart;
              return (
                <Zig rows={[
                  {
                    title: "Which design passes most",
                    body: <>The share of Skyway tickets each design passed, combined over the {builders.length} builders. The dashed line is the average.</>,
                    points: [
                      <><b>Three designs lead, and raw docs + retrieval index trails.</b> The knowledge graph, LLM wiki + terminal and prompts and workflows are within one point of each other (56%), and the last needs no retrieval at all. Raw docs + retrieval index passes 43%. Choose among the leaders on cost and upkeep.</>,
                      <><b>A terminal beats a retrieval index.</b> On the same docs, the terminal design passes about 10 points more with raw docs and 9 more with a wiki. Try a terminal before building an index.</>,
                      <><b>A wiki helps a little.</b> With the same retrieval, a wiki passes 3 to 5 points more than raw docs: 56% against 53% with a terminal, 48% against 43% with a retrieval index. The bigger gains are on cost and on changed rules.</>,
                    ],
                    chart: barsChart,
                  },
                  {
                    title: "What each design costs",
                    body: <>Pass rate against what a ticket costs the agent, or how long it takes: one mark per design, pooled over the {builders.length} builders that built it. The dashed line is the Pareto frontier.</>,
                    points: [
                      <><b>A wiki makes the agent cheaper to run.</b> Wiki agents cost $0.11 to $0.12 per ticket, less than half the $0.26 to $0.27 of raw docs, because they read short notes. LLM wiki + terminal is on the frontier at every stage.</>,
                      <><b>Prompt caching keeps prompts and workflows affordable.</b> It sends the most text per ticket, but 91% is the same prompt every call, billed at about a twelfth of the usual price. Without caching it would cost the most.</>,
                      <><b>The wiki&apos;s saving is paid for up front.</b> Wiki designs cost the builder the most to build, and each update costs about three-quarters of the first build again. For an agent that answers few tickets, that may not pay back.</>,
                    ],
                    note: "Cost is the agent's model spend per ticket; time is the median time to finish a ticket, over the stages where the agent ran.",
                    chart: <ArchTradeoff runs={pooledDesigns(arch, order)} order={order} />,
                    wide: true,
                  },
                  {
                    title: "Which designs hold up as the docs change",
                    body: <>Pass rate for each design at every stage, averaged over the {builders.length} builders that built it, through {lastStage} rounds of doc changes. The shaded band is one standard deviation either side of the average across builders; hover a design to bring it out.</>,
                    points: [
                      <><b>Designs hold their score as the docs change.</b> Every design finishes within about five points of where it started, and every one dips at stage 2. The small rises in prompts and workflows and raw docs + terminal come from two builders and are within the stage-to-stage swings.</>,
                    ],
                    chart: (
                      <StageLines lines={order.map((a) => {
                        const rs = arch.filter((r) => r.arch === a);
                        const n = Math.max(...rs.map((r) => r.stages.length));
                        const at = (i: number) => rs.map((r) => r.stages[i] ?? 0);
                        return {
                          label: rs[0].name, color: (DESIGN_STYLE[a] ?? { color: "var(--b-x3)" }).color, shape: (DESIGN_STYLE[a] ?? { shape: "circle" as Shape }).shape,
                          values: Array.from({ length: n }, (_, i) => at(i).reduce((x, v) => x + v, 0) / rs.length),
                          band: Array.from({ length: n }, (_, i) => {
                            const v = at(i), m = v.reduce((x, y) => x + y, 0) / v.length, sd = Math.sqrt(v.reduce((x, y) => x + (y - m) ** 2, 0) / Math.max(1, v.length - 1));
                            return [Math.max(0, m - sd), Math.min(1, m + sd)] as [number, number];
                          }),
                        };
                      })} height={380} />
                    ),
                  },
                  {
                    title: "Which tickets each design gets right",
                    body: "Tickets split by what they test: a rule that is new at that stage, a rule from before that didn't change, or one that changed.",
                    points: [
                      <><b>Changed rules are usually the hardest tickets.</b> Four of the six designs score lower on changed rules than on both new and unchanged rules.</>,
                      <><b>Compiled notes handle rule changes better than raw documents.</b> Designs that read the raw documents drop 11 to 13 points on changed rules compared with new rules; the graph, wiki and prompt designs drop 3 to 7. A wiki beats raw docs on changed rules by 6 points with a terminal and 13 with a retrieval index.</>,
                    ],
                    chart: <ArchTypes runs={arch} order={order} />,
                  },
                ]} />
              );
            })()}
          </>
        ) : (
          <SkywayEmpty what="this chart" />
        )}
    </Sec>
  );
}

/** What each change to the docs did: one panel per pack, a bar per builder for the points it gained or lost against its own
 *  R-complete score (so a weak complete-docs build does not skew the rest), and the mean of those changes on top. */
function Packs({ packs, bare }: { packs: Builder[]; bare?: boolean }) {
  const PANEL: [string, string, string][] = [
    ["Rules split up", "R-fragmented", "The same docs, but some sections are moved word for word onto other pages, so the parts of a rule sit on separate pages. Nothing is added or reworded."],
    ["Facts removed", "R-incomplete", "Some facts the tickets need are deleted from the docs. The agent can't know them, so it should leave those fields alone or hand the ticket to a person rather than guess."],
    ["Contradictions added", "R-conflicting", "The complete docs plus older and draft pages that state some rules differently. The current pages are the ones to follow."],
    ["Noise added", "R-noisy", "The complete docs plus look-alike pages from the same company that answer none of the tickets."],
  ];
  const rows = packs.map((b) => ({
    label: b.model === CONFOUND ? `${b.model} *` : b.model,
    pass: CONDITIONS.map((_, i) => {
      const s = b.job.scores[i];
      return !s || crashed({ passed: s.passed ?? 0 }) ? null : (s.passed ?? 0) / (s.total || 1);
    }),
  }));
  const panels = PANEL.map(([title, term, about], k) => {
    const deltas = rows.map((r) => ({ label: r.label, base: r.pass[0], v: r.pass[k + 1], d: r.pass[0] == null || r.pass[k + 1] == null ? null : r.pass[k + 1]! - r.pass[0]! }));
    return { title, term, about, rows: deltas };
  });
  return (
    <Sec bare={bare} id="packs" className="lp-sec lp-alt" head={
          <SectionHead
            from="Knowledge perturbations"
            title="How changed docs move the score"
          />
        }>
        {bare ? <ChangePanels panels={panels} /> : (() => {
          return (
            <Zig rows={[{
              title: "How changed docs move the score",
              body: "Each bar shows how one builder's score changed on that version of the docs, compared with its score on the complete docs. The large number is the typical change across builders.",
              points: [
                <><b>Missing facts cause the biggest drop.</b> With facts removed, agents pass 14 points fewer tickets, in all seven builders, because they guess instead of leaving the field alone or handing the ticket to a person. Gaps in the docs cost more than messy pages.</>,
                <><b>Contradicting and noisy pages do not hurt.</b> Pass rates stay within a few points of the complete docs (79% and 81% against 78%), as builders leave out old pages and skip unrelated ones. Clearly marked old pages do little harm.</>,
              ],
              note: "Same tickets in every pack; only the docs change.",
              chart: <ChangePanels panels={panels} />,
              wide: true,
            }]} />
          );
        })()}
    </Sec>
  );
}

/** The hero's way in: each environment as one row, with its current leader and that leader's pass rate per stage. */
type Pick = { name: string; word: string; href?: string; cases: string; best: string; rate: number; bars: number[] };

function Spark({ bars, label }: { bars: number[]; label: string }) {
  const w = 5, gap = 3, h = 26;
  return (
    <svg width={bars.length * (w + gap) - gap} height={h} role="img" aria-label={label} className="shrink-0">
      <title>{label}</title>
      {bars.map((v, i) => (
        <g key={i}>
          <rect x={i * (w + gap)} y={0} width={w} height={h} rx={1} fill="currentColor" opacity={0.1} />
          <rect x={i * (w + gap)} y={h - Math.max(2, v * h)} width={w} height={Math.max(2, v * h)} rx={1} fill="currentColor" />
        </g>
      ))}
    </svg>
  );
}

function HeroEnvs({ picks, cases }: { picks: Pick[]; cases: string }) {
  return (
    <div className="lp-picks">
      <div className="flex items-baseline justify-between gap-4 pb-3">
        <span className="caps muted">Environments</span>
        <span className="text-[13px] muted"><span className="num font-medium" style={{ color: "var(--ink)" }}>{cases}</span> test cases</span>
      </div>
      {picks.map((p) => {
        const body = (
          <>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
                <span className="text-[17px] font-medium">{p.name}</span>
                <span className="caps muted">{p.word}</span>
              </div>
              <div className="mt-1 text-[13px] muted">
                {p.cases}
                {p.href && <> · <span className="whitespace-nowrap">Best: <span style={{ color: "var(--ink)" }}>{p.best}</span> <span className="num font-medium" style={{ color: "var(--ink)" }}>{Math.round(p.rate * 100)}%</span></span></>}
              </div>
            </div>
            {p.href ? (
              <>
                <Spark bars={p.bars} label={`${p.best}: pass rate by ${p.name === "Knowledge perturbations" ? "pack" : "stage"}, ${p.bars.map((v) => Math.round(v * 100) + "%").join(", ")}`} />
                <ArrowRight className="lp-pick-arrow size-4 shrink-0" />
              </>
            ) : (
              <span className="text-[13px] muted">First runs coming</span>
            )}
          </>
        );
        return p.href ? (
          <Link key={p.name} to={p.href} className="lp-pick">{body}</Link>
        ) : (
          <div key={p.name} className="lp-pick">{body}</div>
        );
      })}
    </div>
  );
}

type Env = { name: string; word: string; line: string; rows: [string, string][]; href?: string; foot: string };

function Environments({ envs }: { envs: Env[] }) {
  return (
    <section id="environments" className="lp-sec lp-alt">
      <div className="lp-wrap">
        <h2>Environments</h2>
        <div className="mt-10 grid gap-6 lg:grid-cols-3">
          {envs.map((e) => {
            const body = (
              <>
                <div className="caps muted">{e.word}</div>
                <h3 className="mt-1 text-[24px]">{e.name}</h3>
                <p className="mt-3 text-[16px]">{e.line}</p>
                <dl className="mt-6">
                  {e.rows.map(([k, v]) => (
                    <div key={k} className="flex justify-between gap-4 border-t py-2.5 text-[15px]" style={{ borderColor: "var(--line)" }}>
                      <dt className="muted">{k}</dt>
                      <dd className="m-0 text-right font-medium">{v}</dd>
                    </div>
                  ))}
                </dl>
                <div className="mt-auto pt-6">
                  {e.href ? (
                    <span className="btn btn--secondary btn--sm">
                      {e.foot}
                      <ArrowRight className="size-4" />
                    </span>
                  ) : (
                    <span className="text-[15px] font-medium">{e.foot}</span>
                  )}
                </div>
              </>
            );
            return e.href ? (
              <Link key={e.name} to={e.href} className="card flex flex-col p-6 sm:p-8">{body}</Link>
            ) : (
              <div key={e.name} className="card flex flex-col p-6 sm:p-8">{body}</div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

function Closing({ last, skywayTask }: { last: string | null; skywayTask: string }) {
  return (
    <footer className="lp-sec lp-foot flex flex-col" style={{ background: "var(--ink)", color: "var(--bg)" }}>
      <div className="lp-wrap flex flex-1 flex-col">
        <div>
          <h2>Resolve customer requests with Observe.AI</h2>
          <p className="lead mt-4 max-w-[56ch]" style={{ opacity: 0.75 }}>
            A business never stops changing, and its AI agents have to keep up. Observe.AI builds AI agents that resolve
            customer requests across voice and chat, with full visibility on one CX platform.
          </p>
        </div>
        <div className="mt-14 sm:mt-16">
          <div className="grid gap-8 border-t pt-8 text-[15px] sm:grid-cols-2" style={{ borderColor: "color-mix(in srgb, var(--bg) 20%, transparent)" }}>
            <div>
              <div className="label" style={{ opacity: 0.6 }}>Environments</div>
              <ul className="mt-2 space-y-1.5">
                <li><Link className="link" to={`/t/${skywayTask}`}>Skyway Air</Link></li>
                <li><Link className="link" to={`/t/${ENV.redwood}`}>Redwood Inference</Link></li>
                <li><Link className="link" to={`/t/${ENV.packs}`}>Knowledge perturbations</Link></li>
                <li><a className="link" href={CONTRIBUTING} target="_blank" rel="noreferrer">Submit results</a></li>
              </ul>
            </div>
            <div>
              <div className="label" style={{ opacity: 0.6 }}>Code and data</div>
              <RepoLinks className="mt-2 !flex-col !gap-1.5 text-[14px]" />
              <ul className="mt-3 space-y-1.5 text-[14px]" style={{ opacity: 0.75 }}>
                {last && <li>Updated {day(last)}</li>}
                <li className="flex items-center gap-2">
                  <span>Built with</span>
                  <a href="https://newmeasure.ai" target="_blank" rel="noreferrer" className="flex items-center">
                    <img src={publicAsset("new-measure.png")} alt="New Measure" width={600} height={87} className="block h-[0.8rem] w-auto -translate-y-[2px] invert dark:invert-0" />
                  </a>
                </li>
              </ul>
            </div>
          </div>
        </div>
        <div className="lp-wordmark lp-wordmark--ghost lp-wordmark--long" aria-hidden>Context2Agent Benchmark</div>
      </div>
    </footer>
  );
}

/** One landing figure on its own, from live data, for the blog post. */
export type FigureName = "results" | "failures" | "architecture" | "packs";
/** Which environment a figure that has both shows; the blog's figure frame holds the toggle. */
export type FigureEnv = "redwood" | "skyway";
/** compact (the blog): shorter versions of the same charts, for its narrow column. */
export function LandingFigure({ name, compact, env = "redwood" }: { name: FigureName; compact?: boolean; env?: FigureEnv }) {
  const c = use(catalog());
  const metas = use(loadMetas(c.redwood.map((b) => b.job.key)));
  const archMetas = use(loadMetas(c.skywayArch.map((j) => j.key)));
  const [focus, setFocus] = useState<FailureGroup | null>(null);
  if (name === "results") return <Results bare compact={compact} env={env} redwood={c.redwood} metas={metas} skyway={c.skywayArch} skywayMetas={archMetas} />;
  if (name === "failures") return <Failures bare compact={compact} env={env} redwood={c.redwood} metas={metas} skyway={c.skywayArch} skywayMetas={archMetas} focus={focus} onFocus={setFocus} />;
  if (name === "architecture") return <Architecture bare runs={c.skywayArch} metas={archMetas} />;
  return <Packs bare packs={c.packs} />;
}

// ---------------- page ----------------

function Charts({ redwood, packs, skywayArch, focus, onFocus }: { redwood: Builder[]; packs: Builder[]; skywayArch: JobSummary[] } & Focus) {
  const metas = use(loadMetas(redwood.map((b) => b.job.key)));
  const archMetas = use(loadMetas(skywayArch.map((j) => j.key)));
  return (
    <>
      <Results redwood={redwood} metas={metas} skyway={skywayArch} skywayMetas={archMetas} />
      <Failures redwood={redwood} metas={metas} skyway={skywayArch} skywayMetas={archMetas} focus={focus} onFocus={onFocus} />
      <Architecture runs={skywayArch} metas={archMetas} />
      <Packs packs={packs} />
    </>
  );
}

export default function Home() {
  usePageTitle(SITE_TITLE);
  const c = use(catalog());
  const [failFocus, setFailFocus] = useState<FailureGroup | null>(null);
  const heroName = useRef<HTMLHeadingElement>(null);
  const navSlot = useRef<HTMLSpanElement>(null);
  const navDivider = useRef<HTMLSpanElement>(null);
  const flyTitle = useRef<HTMLAnchorElement>(null);
  useDockedTitle(heroName, navSlot, flyTitle, navDivider);
  const showFailure = (g: FailureGroup) => {
    setFailFocus(g);
    document.getElementById("failures")?.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  };

  // Test cases: Redwood's and Skyway's tickets, plus the knowledge packs' own set (the same tickets in every pack, so
  // counted once; 28 of them also appear in Redwood's first stage). 290 + 311 + 67 = 668, as in the blog.
  const tickets = (j?: JobSummary) => (j ? j.scores.reduce((a, s) => a + (s.total ?? 0), 0) : 0);
  const packTickets = c.packs[0]?.job.scores[0]?.total ?? 67;
  const facts = [
    { value: fmt(tickets(c.redwood[0]?.job) + tickets(c.skywayArch[0]) + packTickets), label: "test cases" },
    { value: "3", label: "environments" },
  ];
  // Docs at stage 0, counted from tasks/<env>/environment/app/docs (Confluence pages + Slack files) and tasks/support-agent-knowledge/packs.
  const envs: Env[] = [
    {
      name: "Skyway Air",
      word: "Fixed architecture",
      line: "An airline. Each run uses one of six set agent architectures.",
      rows: [["Stages", "6"], ["Docs", "9,999"], ["Test cases", c.skywayArch[0] ? fmt(tickets(c.skywayArch[0])) : "–"]],
      ...(c.skywayArch.length ? { href: `/t/${c.skywayArchTask}`, foot: "See the runs" } : { foot: "First runs coming" }),
    },
    {
      name: "Redwood Inference",
      word: "Free architecture",
      line: "An AI inference company. The builder picks the agent architecture.",
      rows: [["Stages", "6"], ["Docs", "26"], ["Test cases", c.redwood[0] ? fmt(tickets(c.redwood[0].job)) : "–"]],
      href: `/t/${ENV.redwood}`,
      foot: "See the runs",
    },
    {
      name: "Knowledge perturbations",
      word: "Changed docs",
      line: "A separate set of Redwood Inference tickets, with the docs rewritten five ways.",
      rows: [["Stages", "1 per pack, 5 packs"], ["Docs", "22 to 60 per pack"], ["Test cases", String(c.packs[0]?.job.scores[0]?.total ?? 67)]],
      href: `/t/${ENV.packs}`,
      foot: "See the runs",
    },
  ];
  const stageRates = (j: JobSummary) => j.scores.map((x) => (x.passed ?? 0) / (x.total || 1));
  const bestOf = <T,>(xs: T[], job: (x: T) => JobSummary) => xs.reduce<T | undefined>((a, x) => (!a || pooled(job(x)) > pooled(job(a)) ? x : a), undefined);
  const bestArch = bestOf(c.skywayArch, (j) => j);
  const bestRed = bestOf(c.redwood, (b) => b.job);
  const bestPack = bestOf(c.packs, (b) => b.job);
  const picks: Pick[] = [
    { name: envs[0].name, word: envs[0].word, href: envs[0].href, cases: `${envs[0].rows[2][1]} cases · 6 stages`, best: bestArch?.architecture ?? "", rate: bestArch ? pooled(bestArch) : 0, bars: bestArch ? stageRates(bestArch) : [] },
    { name: envs[1].name, word: envs[1].word, href: envs[1].href, cases: `${envs[1].rows[2][1]} cases · 6 stages`, best: bestRed?.model ?? "", rate: bestRed ? pooled(bestRed.job) : 0, bars: bestRed ? stageRates(bestRed.job) : [] },
    { name: envs[2].name, word: envs[2].word, href: envs[2].href, cases: `${envs[2].rows[2][1]} cases · 5 packs`, best: bestPack?.model ?? "", rate: bestPack ? pooled(bestPack.job) : 0, bars: bestPack ? stageRates(bestPack.job) : [] },
  ];
  return (
    <div className="lp min-h-screen">
      <Nav slotRef={navSlot} dividerRef={navDivider} />
      <Link ref={flyTitle} to="/#top" className="lp-title lp-fly" aria-hidden tabIndex={-1}><FullName /></Link>
      <main>
        <section id="top" className="lp-hero">
          <div className="lp-wrap">
            <div className="grid gap-x-12 gap-y-12 lg:grid-cols-12 lg:items-center">
              <div className="lg:col-span-7">
                <h1 ref={heroName} className="lp-title" style={{ opacity: 0 }}><FullName /></h1>
                <p className="lead muted mt-5 max-w-[40ch]" style={{ fontSize: "clamp(20px, 0.8vw + 16px, 26px)", lineHeight: 1.35 }}>
                  Can an AI agent learn and adapt to changing business context to resolve customer issues?
                </p>
                <div className="mt-9 flex flex-wrap items-center gap-3">
                  <Link to="/#results" className="btn btn--primary">See the results</Link>
                  <Link to={`/blog/${FIRST_POST}`} className="btn btn--secondary">Read the blog</Link>
                </div>
                <RepoLinks runs={false} className="muted mt-6" />
              </div>
              <div className="lg:col-span-5"><HeroEnvs picks={picks} cases={facts[0].value} /></div>
            </div>
          </div>
        </section>
        <section id="how" className="pb-16">
          <div className="lp-wrap">
            <h2 className="max-w-[24ch]">Can the agent keep up with the business?</h2>
            <p className="lead muted mt-4 max-w-[62ch]">Policies and procedures keep changing, and a support agent has to keep up. Each step below shows how we test that, and where it can go wrong.</p>
            <div className="mt-8"><Journey onFailure={showFailure} /></div>
          </div>
        </section>
        <Environments envs={envs} />
        <Suspense fallback={<div className="lp-sec" />}>
          <Charts redwood={c.redwood} packs={c.packs} skywayArch={c.skywayArch} focus={failFocus} onFocus={setFailFocus} />
        </Suspense>
      </main>
      <Closing last={c.last} skywayTask={c.skywayArchTask} />
    </div>
  );
}
