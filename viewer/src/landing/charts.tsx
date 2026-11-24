import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { CONFOUND, type Shape } from "./data";

// ---------------- shared ----------------

export function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [w, setW] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setW(el.clientWidth));
    ro.observe(el);
    setW(el.clientWidth);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

export function Mark({ shape, x, y, r = 5, color }: { shape: Shape; x: number; y: number; r?: number; color: string }) {
  const s = { fill: color, stroke: "var(--bg)", strokeWidth: 1.2 } as const;
  switch (shape) {
    case "square":
      return <rect x={x - r} y={y - r} width={2 * r} height={2 * r} {...s} />;
    case "triangle":
      return <path d={`M${x},${y - r * 1.15} L${x + r * 1.1},${y + r * 0.85} L${x - r * 1.1},${y + r * 0.85} Z`} {...s} />;
    case "diamond":
      return <path d={`M${x},${y - r * 1.25} L${x + r * 1.15},${y} L${x},${y + r * 1.25} L${x - r * 1.15},${y} Z`} {...s} />;
    case "plus":
      return <path d={`M${x - r},${y} H${x + r} M${x},${y - r} V${y + r}`} stroke={color} strokeWidth={r * 0.75} fill="none" />;
    case "cross":
      return <path d={`M${x - r * 0.8},${y - r * 0.8} L${x + r * 0.8},${y + r * 0.8} M${x + r * 0.8},${y - r * 0.8} L${x - r * 0.8},${y + r * 0.8}`} stroke={color} strokeWidth={r * 0.7} fill="none" />;
    default:
      return <circle cx={x} cy={y} r={r} {...s} />;
  }
}

function MarkIcon({ shape, color, size = 14 }: { shape: Shape; color: string; size?: number }) {
  return (
    <svg width={size} height={size} className="shrink-0" aria-hidden>
      <Mark shape={shape} x={size / 2} y={size / 2} r={size * 0.34} color={color} />
    </svg>
  );
}

const pct = (x: number) => `${Math.round(100 * x)}%`;
const star = (m: string) => (m === CONFOUND ? `${m} *` : m);


export function BuilderLegend({ items }: { items: { model: string; color: string; shape: Shape }[] }) {
  return (
    <ul className="mt-4 flex flex-wrap gap-x-5 gap-y-2">
      {items.map((b) => (
        <li key={b.model} className="flex items-center gap-1.5 text-[13px]">
          <MarkIcon shape={b.shape} color={b.color} />
          {star(b.model)}
        </li>
      ))}
    </ul>
  );
}

// ---------------- plot 1: pass rate per stage ----------------

export type StagePoint = { passed: number; total: number; crashed: boolean; types: [string, string, number, number][] };
/** One architecture behind a pooled line. Drawn, in a lighter shade, while that line is hovered. */
export type StagePart = { name: string; stages: { passed: number; total: number; crashed: boolean }[] };
/** `band`, when set, is the lowest-to-highest architecture at each stage (Skyway). `parts` are those architectures. */
export type StageRow = { model: string; harness: string; color: string; shape: Shape; rate: number; passed: number; total: number; stages: StagePoint[]; band?: { lo: number; hi: number; loName: string; hiName: string }[]; parts?: StagePart[] };

// ---------------- plot 2: where failed checks come from ----------------

/** One builder's failed tickets, split by group as on the run viewer's Failure analysis page: a failed ticket counts once,
 *  split evenly between the parties blamed for it, then between that party's groups. Keys are "Builder|group", "Agent|group". */
export type FailureRow = { model: string; harness: string; failed: number; total: number; rate: number; groups: Map<string, number>; crashedStages: number };

export type RecallPoint = { model: string; color: string; shape: Shape; stage: number; recall: number; precision: number | null; pass: number };
export type RuleMeasure = "f1" | "recall" | "precision";
const MEASURE_NAME: Record<RuleMeasure, string> = { f1: "Rule F1", recall: "Rule recall", precision: "Rule precision" };
/** One mark's value on the chosen measure; null when the run has no precision score. */
const measureOf = (p: RecallPoint, m: RuleMeasure): number | null =>
  m === "recall" ? p.recall : p.precision == null ? null : m === "precision" ? p.precision : p.recall + p.precision === 0 ? 0 : (2 * p.recall * p.precision) / (p.recall + p.precision);

// ---------------- plot 3: architecture ----------------

export type TicketType = "discovery" | "regression" | "adaptability";
/** One builder's run of one prescribed architecture, summed over its stages. */
export type ArchRun = {
  arch: string;
  name: string;
  model: string;
  harness: string;
  color: string;
  shape: Shape;
  passed: number;
  total: number;
  stages: number[];
  usd: number;
  time: number;
  tok: number;
  types: Partial<Record<TicketType, [number, number]>>;
  /** A pooled mark's builders, one line each in its hover card. */
  parts?: { model: string; passed: number; total: number; usd: number; time: number }[];
};

const avg = (v: number[]) => v.reduce((a, b) => a + b, 0) / v.length;

const TYPES: [TicketType, string][] = [
  ["discovery", "New rule"],
  ["regression", "Rule that didn't change"],
  ["adaptability", "Rule that changed"],
];

/** Pass rate per ticket type and architecture (rows in the shared order), averaged over builders. */
export function ArchTypes({ runs, order }: { runs: ArchRun[]; order: string[] }) {
  const cells = order.map((arch) => {
    const rs = runs.filter((r) => r.arch === arch);
    return { arch, name: rs[0]?.name ?? arch, v: TYPES.map(([t]) => { const c = rs.flatMap((r) => (r.types[t] ? [r.types[t]!] : [])); return c.length ? { rate: avg(c.map(([p, n]) => p / n)), n: c.reduce((a, [, n]) => a + n, 0) } : null; }) };
  });
  const all = cells.flatMap((c) => c.v.flatMap((v) => (v ? [v.rate] : [])));
  const [lo, hi] = [Math.min(...all), Math.max(...all)];
  const shade = (v: number) => 12 + (78 * (v - lo)) / Math.max(0.01, hi - lo);
  return (
    <div>
      <table className="w-full border-separate" style={{ borderSpacing: 3 }}>
        <thead>
          <tr>
            <th />
            {TYPES.map(([t, plain]) => (
              <th key={t} className="pb-1 text-left align-bottom text-[13px] font-medium">{plain}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {cells.map((c) => (
            <tr key={c.arch}>
              <td className="pr-2 text-[13px] leading-tight">{c.name}</td>
              {c.v.map((v, i) => (
                <td key={i} className="num h-9 rounded-[3px] px-2 text-[13px]" title={v ? `${c.name}, ${TYPES[i][1]}: ${pct(v.rate)} of ${v.n} tickets` : ""}
                  style={v ? { background: `color-mix(in oklab, var(--heat) ${shade(v.rate)}%, var(--bg))`, color: shade(v.rate) > 55 ? "#fff" : "var(--ink)" } : undefined}>
                  {v ? pct(v.rate) : "–"}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------- plot 4: doc perturbations ----------------

export type PackBuilder = { model: string; color: string; shape: Shape; pass: (number | null)[] };

// ---------------- restored: rule recall scatter, architecture cost/time tradeoff ----------------

type TipState = { x: number; y: number; body: ReactNode } | null;

/** A chart frame that owns one tooltip; hover on desktop, tap on a phone. The tooltip stays mounted with the last thing it
 *  showed, so it fades out instead of vanishing and glides from item to item instead of jumping. */
function TipFrame({ tip, w, onDismiss, children }: { tip: TipState; w: number; onDismiss?: () => void; children: ReactNode }) {
  const frameRef = useRef<HTMLDivElement>(null);
  const last = useRef<TipState>(null);
  if (tip) last.current = tip;
  const t = tip ?? last.current;
  useEffect(() => {
    if (!tip || !onDismiss) return;
    const away = (ev: PointerEvent) => {
      if (frameRef.current && !frameRef.current.contains(ev.target as Node)) onDismiss();
    };
    document.addEventListener("pointerdown", away, { passive: true });
    return () => document.removeEventListener("pointerdown", away);
  }, [tip, onDismiss]);
  return (
    <div ref={frameRef} className="relative">
      {children}
      {t && (
        <div className="tip tip--smooth" aria-hidden={!tip} style={{ left: Math.max(0, Math.min(t.x + 14, w - 250)), top: Math.max(0, t.y + 14), opacity: tip ? 1 : 0 }}>
          {t.body}
        </div>
      )}
    </div>
  );
}

export function RecallScatter({ points: all, measure = "recall", height = 300 }: { points: RecallPoint[]; measure?: RuleMeasure; height?: number }) {
  const points = all.filter((p) => measureOf(p, measure) != null);
  const val = (p: RecallPoint) => measureOf(p, measure) as number;
  const [ref, w] = useWidth<HTMLDivElement>();
  const [tip, setTip] = useState<TipState>(null);
  const h = height;
  const m = { l: 38, r: 18, t: 10, b: 40 };
  const lo = Math.min(0.4, ...points.map(val)) - 0.02;
  const x = (v: number) => m.l + ((v - lo) / (1.02 - lo)) * (w - m.l - m.r);
  const y = (v: number) => m.t + (1 - v) * (h - m.t - m.b);
  const pick = (clientX: number, clientY: number, rect: DOMRect) => {
    const mx = clientX - rect.left, my = clientY - rect.top;
    let best: RecallPoint | null = null, d = 24 * 24;
    for (const p of points) {
      const dd = (x(val(p)) - mx) ** 2 + (y(p.pass) - my) ** 2;
      if (dd < d) (d = dd), (best = p);
    }
    setTip(best && { x: x(val(best)), y: y(best.pass), body: <><div className="font-medium">{star(best.model)} · stage {best.stage}</div><div className="num">{MEASURE_NAME[measure]} {val(best).toFixed(2)} · passed {pct(best.pass)}</div></> });
  };
  const near = (ev: React.PointerEvent<SVGSVGElement>) => {
    if (ev.pointerType === "touch") return;
    pick(ev.clientX, ev.clientY, ev.currentTarget.getBoundingClientRect());
  };
  const ticks = [0.4, 0.6, 0.8, 1].filter((t) => t >= lo);
  return (
    <div ref={ref}>
      {w > 0 && (
        <TipFrame tip={tip} w={w} onDismiss={() => setTip(null)}>
          <svg width={w} height={h} onPointerMove={near} onClick={(ev) => pick(ev.clientX, ev.clientY, ev.currentTarget.getBoundingClientRect())} onPointerLeave={(ev) => ev.pointerType !== "touch" && setTip(null)} role="img" aria-label={`${MEASURE_NAME[measure]} against stage pass rate`}>
            <rect x={x(lo)} y={m.t} width={x(0.9) - x(lo)} height={h - m.t - m.b} fill="color-mix(in srgb, var(--ink) 5%, transparent)" />
            {[0, 0.25, 0.5, 0.75, 1].map((v) => (
              <g key={v}>
                <line x1={m.l} x2={w - m.r} y1={y(v)} y2={y(v)} stroke="var(--line)" />
                <text x={m.l - 6} y={y(v) + 4} textAnchor="end" fontSize={12} fill="var(--muted)">{v * 100}%</text>
              </g>
            ))}
            {ticks.map((t) => (
              <text key={t} x={x(t)} y={h - 22} textAnchor="middle" fontSize={12} fill="var(--muted)">{t.toFixed(1)}</text>
            ))}
            <text x={(m.l + w - m.r) / 2} y={h - 4} textAnchor="middle" fontSize={12} fill="var(--muted)">{MEASURE_NAME[measure]}</text>
            {points.map((p, i) => (
              <Mark key={i} shape={p.shape} x={x(val(p))} y={y(p.pass)} r={4.2} color={p.color} />
            ))}
          </svg>
        </TipFrame>
      )}
    </div>
  );
}

/** Wilson 95% interval for a pass rate of p/n. */
export function wilson(p: number, n: number): [number, number] {
  if (!n) return [0, 1];
  const z = 1.96;
  const f = p / n;
  const d = 1 + (z * z) / n;
  const c = (f + (z * z) / (2 * n)) / d;
  const h = (z * Math.sqrt((f * (1 - f)) / n + (z * z) / (4 * n * n))) / d;
  return [c - h, c + h];
}
const rate = (r: ArchRun) => r.passed / r.total;
/** Pass-rate axis shared by the dot plot and the scatter: whole tens around every interval. */
function passDomain(runs: ArchRun[]): [number, number] {
  const ci = runs.map((r) => wilson(r.passed, r.total));
  return [Math.max(0, Math.floor(Math.min(...ci.map((c) => c[0])) * 10) / 10), Math.min(1, Math.ceil(Math.max(...ci.map((c) => c[1])) * 10) / 10)];
}
function runTip(r: ArchRun) {
  const [lo, hi] = wilson(r.passed, r.total);
  return (
    <>
      <div className="font-medium">{r.name}</div>
      <div className="muted">{r.model} · {r.harness}</div>
      <div className="mt-1 num">Passed {r.passed}/{r.total} = {pct(rate(r))} <span className="muted">(95% interval {pct(lo)} to {pct(hi)})</span></div>
      <div className="num muted">By stage: {r.stages.map((x) => pct(x)).join(" · ")}</div>
      <div className="num muted">${r.usd.toFixed(2)} a ticket · {Math.round(r.time)} s median · {Math.round(r.tok)}k input tokens</div>
      {r.parts && (
        <div className="mt-1.5 border-t pt-1.5" style={{ borderColor: "var(--line)" }}>
          {r.parts.map((b) => (
            <div key={b.model} className="num muted">{b.model}: {pct(b.passed / b.total)} · ${b.usd.toFixed(2)} · {Math.round(b.time)} s</div>
          ))}
        </div>
      )}
    </>
  );
}

/** The price of a pass rate: pass rate against cost per ticket or ticket time, one point per builder and architecture. */
export function ArchTradeoff({ runs, order }: { runs: ArchRun[]; order: string[] }) {
  const [ref, w] = useWidth<HTMLDivElement>();
  const [tip, setTip] = useState<TipState>(null);
  const [axis, setAxis] = useState<"usd" | "time">("usd");
  const h = 320;
  const m = { l: 40, r: 22, t: 16, b: 40 };
  const [lo, hi] = passDomain(runs);
  const xs = runs.map((r) => r[axis]);
  const xmax = Math.max(...xs) * 1.15;
  const xmin = axis === "time" ? Math.max(0, Math.min(...xs) * 0.8) : 0;
  const X = (v: number) => m.l + ((v - xmin) / (xmax - xmin)) * (w - m.l - m.r);
  const Y = (v: number) => m.t + (1 - (v - lo) / (hi - lo)) * (h - m.t - m.b);
  const yt = Array.from({ length: Math.round((hi - lo) * 10) + 1 }, (_, i) => lo + i / 10);
  const narrow = w < 560;
  const step = axis === "usd" ? (xmax > 0.6 ? 0.2 : 0.1) : narrow ? 20 : 10;
  const xt = Array.from({ length: Math.floor((xmax - xmin) / step) + 1 }, (_, i) => Math.ceil(xmin / step) * step + i * step).filter((v) => v <= xmax);
  const fmt = (v: number) => (axis === "usd" ? `$${v.toFixed(2)}` : `${Math.round(v)} s`);
  const frontPts = frontier(order.map((a) => { const rs = runs.filter((r) => r.arch === a); return [avg(rs.map((r) => r[axis])), avg(rs.map(rate))] as [number, number]; }));
  return (
    <div ref={ref}>
      <div className="mb-4">
        <div className="seg" role="group">
          {(["usd", "time"] as const).map((k) => (
            <button key={k} type="button" aria-pressed={axis === k} onClick={() => setAxis(k)}>{k === "usd" ? "Cost per ticket" : "Ticket time"}</button>
          ))}
        </div>
      </div>
      <TipFrame tip={tip} w={w} onDismiss={() => setTip(null)}>
        {w > 0 && (
          <svg width={w} height={h} onPointerLeave={(ev) => ev.pointerType !== "touch" && setTip(null)} role="img" aria-label="Pass rate against cost per ticket by architecture">
            {yt.map((t) => (
              <g key={t}>
                <line x1={m.l} x2={w - m.r} y1={Y(t)} y2={Y(t)} stroke="var(--line)" />
                <text x={m.l - 8} y={Y(t) + 4} textAnchor="end" fontSize={12} className="num" fill="var(--muted)">{pct(t)}</text>
              </g>
            ))}
            {xt.map((t) => <text key={t} x={X(t)} y={h - m.b + 18} textAnchor="middle" fontSize={12} className="num" fill="var(--muted)">{fmt(t)}</text>)}
            <text x={m.l + 4} y={m.t + 12} fontSize={11} fill="var(--muted)">↖ better: more passed and {axis === "usd" ? "cheaper" : "faster"}</text>
            <path d={worseRegion(frontPts, X, Y, w - m.r, h - m.b)} fill="var(--ink)" opacity={0.12} />
            <path d={frontPts.map(([cx, cy], i) => `${i ? "L" : "M"}${X(cx)},${Y(cy)}`).join("")} fill="none" stroke="var(--ink)" strokeWidth={1.2} strokeDasharray="4 4" opacity={0.6} />
            {placeLabels(
              order.map((arch) => {
                const rs = runs.filter((r) => r.arch === arch);
                const cx = X(avg(rs.map((r) => r[axis])));
                return { arch, rs, cx, cy: Y(avg(rs.map(rate))), left: cx > w * 0.7 };
              }),
            ).map(({ arch, rs, cx, cy, left, ly }) => (
              <g key={arch}>
                {rs.length > 1 && <circle cx={cx} cy={cy} r={11} fill="none" stroke="var(--ink)" strokeWidth={1} opacity={0.5} />}
                {rs.map((r) => (
                  <g key={r.model} onPointerEnter={(e) => e.pointerType !== "touch" && setTip({ x: X(r[axis]), y: Y(rate(r)), body: runTip(r) })} onClick={() => setTip({ x: X(r[axis]), y: Y(rate(r)), body: runTip(r) })}>
                    <Mark shape={r.shape} x={X(r[axis])} y={Y(rate(r))} r={6} color={r.color} />
                  </g>
                ))}
                {!narrow && Math.abs(ly - (cy + 4)) > 2 && <line x1={cx + (left ? -7 : 7)} y1={cy} x2={cx + (left ? -11 : 11)} y2={ly - 4} stroke="var(--muted)" strokeWidth={0.75} />}
                {narrow ? (
                  <text x={cx} y={cy - 10} textAnchor="middle" fontSize={11} fontWeight={600} className="num" fill="var(--ink)">{order.indexOf(arch) + 1}</text>
                ) : (
                  <text x={cx + (left ? -12 : 12)} y={ly} textAnchor={left ? "end" : "start"} fontSize={12} className="mono" fill="var(--ink)">{arch}</text>
                )}
              </g>
            ))}
          </svg>
        )}
      </TipFrame>
      {narrow && (
        <ol className="mt-2 grid grid-cols-2 gap-x-4 gap-y-0.5 text-[12px]">
          {order.map((a, i) => <li key={a}><span className="num font-semibold">{i + 1}</span> <span className="mono">{a}</span></li>)}
        </ol>
      )}
    </div>
  );
}

/** Push labels apart vertically where their boxes would overlap (labels are short ids, about 7 px a character). */
function placeLabels<T extends { arch: string; cx: number; cy: number; left: boolean }>(items: T[]): (T & { ly: number })[] {
  const box = (t: T) => (t.left ? [t.cx - 12 - t.arch.length * 7.2, t.cx - 12] : [t.cx + 12, t.cx + 12 + t.arch.length * 7.2]);
  const placed: (T & { ly: number })[] = [];
  for (const t of [...items].sort((a, b) => a.cy - b.cy)) {
    let ly = t.cy + 4;
    const [a, b] = box(t);
    for (const p of placed) {
      const [c, d] = box(p);
      if (a < d && c < b && Math.abs(ly - p.ly) < 15) ly = p.ly + 15;
    }
    placed.push({ ...t, ly });
  }
  return placed;
}

/** The Pareto frontier of [cost, score] points: cheapest first, each one passing more than every cheaper point. */
export function frontier(points: [number, number][]): [number, number][] {
  const out: [number, number][] = [];
  for (const p of [...points].sort((a, b) => a[0] - b[0] || b[1] - a[1])) if (!out.length || p[1] > out[out.length - 1][1]) out.push(p);
  return out;
}

/** The region a frontier point already beats: higher cost, lower pass rate. Dominated on a builder chart; the feasible-but-worse set on a tradeoff chart. */
export function worseRegion(front: [number, number][], X: (v: number) => number, Y: (v: number) => number, right: number, bottom: number) {
  if (!front.length) return "";
  const d = [`M${X(front[0][0])},${bottom}`, `L${X(front[0][0])},${Y(front[0][1])}`];
  for (let i = 1; i < front.length; i++) d.push(`L${X(front[i][0])},${Y(front[i - 1][1])}`, `L${X(front[i][0])},${Y(front[i][1])}`);
  const last = front[front.length - 1];
  d.push(`L${right},${Y(last[1])}`, `L${right},${bottom}`, "Z");
  return d.join("");
}
