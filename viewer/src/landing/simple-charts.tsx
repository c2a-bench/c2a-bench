/**
 * Plain replacements for the landing charts: bars with the number written on them, sorted, one idea per chart, no
 * hover needed to read them. Shown side by side with the current charts on /draft-charts until approved.
 */
import { useRef, useState, type ReactNode } from "react";
import { BuilderLegend, Mark, frontier, useWidth, worseRegion } from "./charts";
import type { Shape } from "./data";

const pct = (v: number) => `${Math.round(100 * v)}%`;

export type BarRow = { label: string; sub?: string; value: number; text?: string; star?: boolean };

export type SplitRow = { label: string; sub?: string; parts: number[]; total: number };

export type PairRow = { label: string; a: number; b: number };

// ---------------- hover ----------------

type TipData = { x: number; y: number; w: number; body: ReactNode };

/** One tooltip per chart: it shows at once, glides to the item under the pointer, and fades out when the pointer leaves
 *  the chart (not each item), so moving across items does not flicker. The other items dim a little. */
function useHover() {
  const ref = useRef<HTMLDivElement>(null);
  const [tip, setTip] = useState<TipData | null>(null);
  const [on, setOn] = useState<string | null>(null);
  const show = (e: React.PointerEvent<Element>, key: string, body: ReactNode, follow = false) => {
    const box = ref.current?.getBoundingClientRect();
    if (!box) return;
    const el = (e.currentTarget as Element).getBoundingClientRect();
    setOn(key);
    setTip({ x: follow ? e.clientX - box.left : el.left - box.left + el.width / 2, y: el.top - box.top, w: box.width, body });
  };
  const hide = () => { setOn(null); setTip(null); };
  return { ref, tip, on, show, hide };
}

function HoverTip({ tip }: { tip: TipData | null }) {
  const last = useRef<TipData | null>(null);
  if (tip) last.current = tip;
  const t = tip ?? last.current;
  if (!t) return null;
  const W = 250;
  return (
    <div className="sc-tip" aria-hidden style={{ left: Math.max(0, Math.min(t.x - W / 2, t.w - W)), top: t.y, width: W, opacity: tip ? 1 : 0 }}>
      {t.body}
    </div>
  );
}

const TipHead = ({ children }: { children: ReactNode }) => <div className="font-semibold">{children}</div>;
const TipLine = ({ children, muted }: { children: ReactNode; muted?: boolean }) => <div className={muted ? "muted mt-0.5" : "mt-0.5"}>{children}</div>;
const Swatch = ({ color }: { color: string }) => <span className="mr-1.5 inline-block size-2.5 rounded-[2px] align-[-1px]" style={{ background: color }} />;

// ---------------- benchmark-style forms ----------------

export type Col = { label: string; sub?: string; value: number; color?: string; tip?: ReactNode };

/** Leaderboard columns: one per entry, best first, the value on top, the name under it. Hover a column for its details. */
export function Columns({ cols, highlight, height = 320 }: { cols: Col[]; highlight?: number; height?: number }) {
  const [ref, w] = useWidth<HTMLDivElement>();
  const h = useHover();
  const small = w < 640;
  const m = { l: 36, r: 4, t: 26, b: small ? 78 : 64 };
  const n = cols.length;
  const band = (w - m.l - m.r) / Math.max(1, n);
  const bw = Math.min(64, band * 0.62);
  const y = (v: number) => m.t + (1 - v) * (height - m.t - m.b);
  const words = (s: string) => {
    const parts = s.split("-");
    const half = Math.ceil(parts.length / 2);
    return parts.length > 2 ? [parts.slice(0, half).join("-"), parts.slice(half).join("-")] : [s];
  };
  // On a phone nine long names can't sit under columns: the same data turns sideways, one row per entry.
  if (w > 0 && w < 520) {
    return (
      <div ref={h.ref} className={h.on ? "relative sc-hov" : "relative"} onPointerLeave={h.hide}>
        <div ref={ref}>
          <ul className="sc-cl">
            {cols.map((c, i) => {
              const body = (
                <>
                  <TipHead>{c.label}</TipHead>
                  {c.sub && <TipLine muted>{c.sub}</TipLine>}
                  <TipLine><span className="num font-semibold">{pct(c.value)}</span> of tickets passed · #{i + 1} of {n}</TipLine>
                  {c.tip}
                </>
              );
              return (
                <li key={c.label} className={h.on === c.label ? "sc-cl-row sc-item sc-on" : "sc-cl-row sc-item"} onPointerDown={(e) => h.show(e, c.label, body)} onPointerEnter={(e) => h.show(e, c.label, body)}>
                  <div className="sc-cl-name"><span className="font-medium">{c.label}</span>{c.sub && <span className="label muted"> {c.sub}</span>}</div>
                  <div className="sc-cl-track">
                    <div className="sc-cl-bar" style={{ width: `${(100 * c.value) / Math.max(...cols.map((x) => x.value), 0.01) * 0.82}%`, background: c.color ?? "var(--ink)" }} />
                    <span className="num font-semibold">{pct(c.value)}</span>
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
        <HoverTip tip={h.tip} />
      </div>
    );
  }
  return (
    <div ref={h.ref} className={h.on ? "relative sc-hov" : "relative"} onPointerLeave={h.hide}>
      <div ref={ref}>
        {w > 0 && (
          <svg width={w} height={height} role="img" aria-label={`Pass rate, best first: ${cols.map((c, i) => `${i + 1}. ${c.label}${c.sub ? ` (${c.sub})` : ""} ${pct(c.value)}`).join("; ")}`}>
            {[0, 0.25, 0.5, 0.75, 1].map((v) => (
              <g key={v}>
                <line x1={m.l} x2={w - m.r} y1={y(v)} y2={y(v)} stroke="var(--line)" />
                <text x={m.l - 6} y={y(v) + 4} textAnchor="end" fontSize={11} fill="var(--muted)">{v * 100}%</text>
              </g>
            ))}
            {cols.map((c, i) => {
              const cx = m.l + band * (i + 0.5);
              const hi = i === highlight;
              const body = (
                <>
                  <TipHead>{c.label}</TipHead>
                  {c.sub && <TipLine muted>{c.sub}</TipLine>}
                  <TipLine><span className="num font-semibold">{pct(c.value)}</span> of tickets passed · #{i + 1} of {n}</TipLine>
                  {c.tip}
                </>
              );
              return (
                <g key={c.label} className={h.on === c.label ? "sc-item sc-on" : "sc-item"} onPointerEnter={(e) => h.show(e, c.label, body)} onPointerDown={(e) => h.show(e, c.label, body)}>
                  <rect x={cx - band / 2} y={m.t - 20} width={band} height={height - m.t + 20} fill="transparent" />
                  <rect x={cx - bw / 2} y={y(c.value)} width={bw} height={y(0) - y(c.value)} rx={4} className={hi ? "sc-hi-svg" : undefined} fill={hi ? undefined : c.color ?? "var(--ink)"} />
                  <rect x={cx - bw / 2} y={y(0) - 4} width={bw} height={4} fill={hi ? "var(--action)" : c.color ?? "var(--ink)"} />
                  <text x={cx} y={y(c.value) - 7} textAnchor="middle" fontSize={small ? 12 : 14} fontWeight={600} fill="var(--ink)">{pct(c.value)}</text>
                  {words(c.label).map((t, k) => (
                    <text key={k} x={cx} y={y(0) + 16 + k * 13} textAnchor="middle" fontSize={small ? 10 : 12} fontWeight={500} fill="var(--ink)">{t}</text>
                  ))}
                  {c.sub && <text x={cx} y={y(0) + 16 + words(c.label).length * 13} textAnchor="middle" fontSize={small ? 9.5 : 11} fill="var(--muted)">{c.sub}</text>}
                </g>
              );
            })}
          </svg>
        )}
      </div>
      <HoverTip tip={h.tip && { ...h.tip, y: Math.max(0, h.tip.y) }} />
    </div>
  );
}

export type Dot = { label: string; x: number; y: number; color: string };

/** Two values per row as dots on one 0–100% line, joined, so the gap between them is the thing you see. Hover a row to read it. */
export function Dumbbell({ rows, names }: { rows: { label: string; a: number; b: number; color: string }[]; names: [string, string] }) {
  const h = useHover();
  return (
    <div>
      <ul className="flex flex-wrap gap-x-5 gap-y-1.5 text-[13px]">
        <li className="flex items-center gap-2"><span className="size-3 rounded-full" style={{ border: "2px solid var(--ink)" }} />{names[0]}</li>
        <li className="flex items-center gap-2"><span className="size-3 rounded-full" style={{ background: "var(--ink)" }} />{names[1]}</li>
      </ul>
      <div ref={h.ref} className={h.on ? "relative sc-hov" : "relative"} onPointerLeave={h.hide}>
        <ul className="sc-rows mt-4">
          {rows.map((r) => {
            const gap = Math.round(100 * (r.a - r.b));
            const body = (
              <>
                <TipHead>{r.label}</TipHead>
                <TipLine>{names[0]}: <span className="num font-semibold">{pct(r.a)}</span></TipLine>
                <TipLine>{names[1]}: <span className="num font-semibold">{pct(r.b)}</span></TipLine>
                <TipLine muted>The two numbers are counted differently (rules over a whole stage, tickets one by one), so read the gap as a comparison, not as tickets lost.</TipLine>
              </>
            );
            return (
              <li key={r.label} className={h.on === r.label ? "sc-row sc-item sc-on" : "sc-row sc-item"} onPointerEnter={(e) => h.show(e, r.label, body, true)} onPointerMove={(e) => h.show(e, r.label, body, true)} onPointerDown={(e) => h.show(e, r.label, body, true)}>
                <div className="sc-name"><span className="font-medium">{r.label}</span></div>
                <div className="sc-db">
                  <div className="sc-db-axis" />
                  <div className="sc-db-gap" style={{ left: `${100 * Math.min(r.a, r.b)}%`, width: `${100 * Math.abs(r.a - r.b)}%`, background: r.color }} />
                  <span className="sc-db-dot sc-db-dot--open" style={{ left: `${100 * r.a}%` }} />
                  <span className="sc-db-dot" style={{ left: `${100 * r.b}%`, background: r.color }} />
                  <span className="sc-db-lab num" style={{ left: `${100 * r.b}%`, transform: "translateX(-110%)" }}>{pct(r.b)}</span>
                  <span className="label num muted sc-db-gaplab" style={{ left: `${100 * Math.max(r.a, r.b)}%` }}>{r.a >= r.b ? "−" : "+"}{Math.abs(gap)} pts</span>
                </div>
              </li>
            );
          })}
        </ul>
        <HoverTip tip={h.tip} />
      </div>
      <div className="sc-db-ticks label muted"><span>0%</span><span>50%</span><span>100%</span></div>
    </div>
  );
}

/** Why failed tickets failed: five plain reasons, builder's (warm, left) then agent's (cool, right). */
export const REASONS = [
  { key: "recall", side: "Builder", name: "Missing a rule", long: "the agent was built without a rule it needed", color: "var(--f-recall)", text: "#fff" },
  { key: "spec", side: "Builder", name: "Built wrong", long: "the agent ignored the build instructions, or never started", color: "var(--f-spec)", text: "#000" },
  { key: "state", side: "Agent", name: "Wrong action", long: "it left the support system in the wrong state", color: "var(--f-state)", text: "#fff" },
  { key: "customer", side: "Agent", name: "Missed customer info", long: "it missed something the customer told it", color: "var(--f-customer)", text: "#000" },
  { key: "crash", side: "Agent", name: "Crashed", long: "it crashed mid-ticket", color: "var(--f-crash)", text: "#000" },
] as const;
export type ReasonKey = (typeof REASONS)[number]["key"];
export type ReasonRow = { label: string; sub?: string; parts: Record<ReasonKey, number>; bold?: boolean };

export function ReasonBars({ rows, focus }: { rows: ReasonRow[]; focus?: ReasonKey | null }) {
  const h = useHover();
  return (
    <div>
      <div className="grid gap-x-10 gap-y-3 sm:grid-cols-2">
        {(["Builder", "Agent"] as const).map((side) => (
          <div key={side}>
            <div className="label muted">{side === "Builder" ? "Builder's fault" : "Agent's fault"}</div>
            <ul className="mt-1.5 grid gap-1 text-[13.5px]">
              {REASONS.filter((r) => r.side === side).map((r) => (
                <li key={r.key} className="flex items-baseline gap-2" style={{ opacity: focus && focus !== r.key ? 0.45 : 1 }}>
                  <span className="size-3 shrink-0 translate-y-[1px] rounded-[2px]" style={{ background: r.color }} />
                  <span><span className="font-medium">{r.name}</span><span className="muted">: {r.long}</span></span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <div ref={h.ref} className={h.on ? "relative sc-hov" : "relative"} onPointerLeave={h.hide}>
        <ul className="sc-rows mt-6">
          {rows.map((row) => {
            const sum = REASONS.reduce((a, r) => a + row.parts[r.key], 0) || 1;
            const side = (s: string) => REASONS.filter((r) => r.side === s).reduce((a, r) => a + row.parts[r.key], 0) / sum;
            return (
              <li key={row.label} className="sc-row" style={row.bold ? { paddingBottom: 10, marginBottom: 4, borderBottom: "1px solid var(--line)" } : undefined}>
                <div className="sc-name">
                  <span className={row.bold ? "font-semibold" : "font-medium"}>{row.label}</span>
                  {row.sub && <div className="label muted">{row.sub}</div>}
                </div>
                <div className="sc-split" style={row.bold ? { height: 32 } : undefined}>
                  {REASONS.map((r) => {
                    const v = row.parts[r.key];
                    const key = `${row.label}|${r.key}`;
                    const body = (
                      <>
                        <TipHead>{row.label}</TipHead>
                        <TipLine><Swatch color={r.color} /><span className="font-medium">{r.name}</span> · {r.side}&apos;s fault</TipLine>
                        <TipLine muted>{r.long[0].toUpperCase() + r.long.slice(1)}.</TipLine>
                        <TipLine><span className="num font-semibold">{pct(v / sum)}</span> of {row.bold ? "all" : "this model's"} failure reasons</TipLine>
                        <TipLine muted>Builder&apos;s fault {pct(side("Builder"))} · agent&apos;s fault {pct(side("Agent"))}</TipLine>
                      </>
                    );
                    return v > 0 ? (
                      <div
                        key={r.key}
                        className={h.on === key ? "sc-seg sc-item sc-on" : "sc-seg sc-item"}
                        onPointerEnter={(e) => h.show(e, key, body)}
                        onPointerDown={(e) => h.show(e, key, body)}
                        style={{ flexGrow: v, background: r.color, color: r.text, opacity: focus && focus !== r.key ? 0.2 : undefined }}
                      >
                        {v / sum >= 0.07 && <span>{pct(v / sum)}</span>}
                      </div>
                    ) : null;
                  })}
                </div>
              </li>
            );
          })}
        </ul>
        <HoverTip tip={h.tip} />
      </div>
    </div>
  );
}

const median = (xs: number[]) => {
  const v = [...xs].sort((a, b) => a - b);
  return v.length ? (v.length % 2 ? v[(v.length - 1) / 2] : (v[v.length / 2 - 1] + v[v.length / 2]) / 2) : 0;
};

/** One small panel per change: the middle builder's change on top (the median, so one extreme build can't swing it) and a
 *  sorted bar per builder, left for a loss, right for a gain. Hover a row for its two scores. */
export function ChangePanels({ panels }: { panels: { title: string; term?: string; about?: string; rows: { label: string; d: number | null; base?: number | null; v?: number | null }[] }[] }) {
  const max = Math.max(0.1, ...panels.flatMap((p) => p.rows.map((r) => Math.abs(r.d ?? 0))));
  const pts = (d: number) => (Math.abs(d) < 0.005 ? "0" : `${d > 0 ? "+" : "−"}${Math.abs(Math.round(100 * d))}`);
  return (
    <div className="grid gap-x-10 gap-y-12 md:grid-cols-2">
      {panels.map((p) => <Panel key={p.title} p={p} max={max} pts={pts} />)}
    </div>
  );
}

function Panel({ p, max, pts }: { p: Parameters<typeof ChangePanels>[0]["panels"][number]; max: number; pts: (d: number) => string }) {
  const h = useHover();
  const ds = p.rows.flatMap((r) => (r.d == null ? [] : [r.d]));
  const typ = median(ds);
  const tone = (d: number) => (d < 0 ? "var(--f-recall)" : "var(--f-state)");
  return (
    <div>
      <div className="flex items-end justify-between gap-3 border-b pb-2" style={{ borderColor: "var(--ink)" }}>
        <div>
          <h3 className="text-[17px] font-medium leading-tight">
            {p.title}
            {p.about && <span className="lp-tip lp-info" tabIndex={0} role="note" aria-label={p.about} data-tip={p.about}>i</span>}
          </h3>
          {p.term && <div className="label muted mt-0.5">{p.term}</div>}
        </div>
        <div className="num shrink-0 text-[26px] font-semibold leading-none" style={{ color: tone(typ) }}>{pts(typ)}<span className="label muted"> pts</span></div>
      </div>
      <div ref={h.ref} className={h.on ? "relative sc-hov" : "relative"} onPointerLeave={h.hide}>
        <ul className="mt-3 grid gap-1.5">
          {[...p.rows].sort((a, b) => (b.d ?? -9) - (a.d ?? -9)).map((r) => {
            const w = r.d == null ? 0 : (36 * Math.abs(r.d)) / max;
            const down = (r.d ?? 0) < 0;
            const body = r.d == null ? (
              <>
                <TipHead>{r.label}</TipHead>
                <TipLine muted>The agent never started for this pack, so there is no score to compare.</TipLine>
              </>
            ) : (
              <>
                <TipHead>{r.label}</TipHead>
                {r.base != null && <TipLine>Complete docs: <span className="num font-semibold">{pct(r.base)}</span></TipLine>}
                {r.v != null && <TipLine>{p.title}: <span className="num font-semibold">{pct(r.v)}</span></TipLine>}
                <TipLine>
                  <span className="num font-semibold" style={{ color: tone(r.d) }}>{pts(r.d)} pts</span>
                  <span className="muted"> {Math.abs(r.d) < 0.005 ? "no change" : down ? "lost" : "gained"}</span>
                </TipLine>
              </>
            );
            const color = down ? "var(--f-recall)" : "var(--f-state)";
            return (
              <li key={r.label} className={h.on === r.label ? "sc-item sc-on grid grid-cols-[minmax(120px,190px)_1fr] items-center gap-2 text-[13px]" : "sc-item grid grid-cols-[minmax(120px,190px)_1fr] items-center gap-2 text-[13px]"} onPointerEnter={(e) => h.show(e, r.label, body)} onPointerDown={(e) => h.show(e, r.label, body)}>
                <span className="truncate">{r.label}</span>
                <div className="relative h-[18px]">
                  <div className="absolute inset-y-[-3px] left-1/2 w-px" style={{ background: "var(--line)" }} />
                  {r.d == null ? (
                    <span className="label muted absolute left-1/2 top-0 pl-2">never started</span>
                  ) : (
                    <>
                      <div
                        className="absolute inset-y-0"
                        style={{
                          width: `${w}%`, [down ? "right" : "left"]: "50%", borderRadius: down ? "3px 0 0 3px" : "0 3px 3px 0",
                          background: color,
                        }}
                      />
                      <span className="num absolute top-0 text-[12px]" style={{ [down ? "right" : "left"]: `calc(50% + ${w}% + 5px)` }}>{pts(r.d)}</span>
                    </>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
        <HoverTip tip={h.tip} />
      </div>
    </div>
  );
}

export type CostDot = { label: string; sub?: string; cost: number; rate: number; color: string; tip?: ReactNode };

/** Pass rate against what the builder spent (log scale: costs span about 100×). Every dot is named; up and to the left is
 *  better. The dashed line is the Pareto frontier; the tint is what it beats (dearer and passing fewer). Hover a dot for its numbers. */
export function CostScatter({ dots, height = 340, title = "Tickets passed vs what the builder spent on the whole run", axis = "builder cost, log scale", spent = "Builder spent" }: { dots: CostDot[]; height?: number; title?: string; axis?: string; spent?: string }) {
  const [ref, w] = useWidth<HTMLDivElement>();
  const h = useHover();
  const m = { l: 44, r: 16, t: 30, b: 40 }; // the top band holds the "better" hint
  const pos = dots.map((d) => d.cost).filter((c) => c > 0);
  const lo = Math.log10(Math.min(...pos) / 1.5), hi = Math.log10(Math.max(...pos) * 1.5);
  // on a phone the chart keeps a readable width (names beside the dots) and scrolls sideways in its frame
  const narrow = w > 0 && w < 520;
  const cw = narrow ? 640 : w;
  const x = (v: number) => m.l + ((Math.log10(Math.max(v, 1e-6)) - lo) / (hi - lo)) * (cw - m.l - m.r);
  const yLo = Math.max(0, Math.floor(10 * Math.min(...dots.map((d) => d.rate))) / 10 - 0.1);
  const yHi = Math.min(1, Math.ceil(10 * Math.max(...dots.map((d) => d.rate))) / 10 + 0.05);
  const y = (v: number) => m.t + (1 - (v - yLo) / (yHi - yLo)) * (height - m.t - m.b);
  const xt = [0.25, 0.5, 1, 2, 4, 8, 16, 32, 64].filter((t) => Math.log10(t) >= lo && Math.log10(t) <= hi);
  const yt = Array.from({ length: 11 }, (_, i) => i / 10).filter((v) => v >= yLo - 1e-9 && v <= yHi + 1e-9);
  const front = frontier(dots.map((d) => [d.cost, d.rate] as [number, number]));
  // names sit to the right of the dot (left near the right edge); a name that would overlap one already placed moves down
  const placed: { x0: number; x1: number; y: number }[] = [];
  const named = [...dots].sort((a, b) => b.rate - a.rate).map((d) => {
    const cx = x(d.cost), cy = y(d.rate);
    const wTxt = d.label.length * 6.6;
    const right = cx + 12 + wTxt < cw - 4;
    const x0 = right ? cx + 11 : cx - 11 - wTxt, x1 = x0 + wTxt;
    let ly = cy + 4;
    while (placed.some((p) => p.x0 < x1 && x0 < p.x1 && Math.abs(p.y - ly) < 14)) ly += 14;
    placed.push({ x0, x1, y: ly });
    return { d, cx, cy, ly, right };
  });
  return (
    <div>
      <div className="label muted mb-3">{title}</div>
      <div ref={h.ref} className={h.on ? "relative sc-hov" : "relative"} onPointerLeave={h.hide}>
        <div ref={ref} className={narrow ? "sc-swipe" : undefined}>
          {w > 0 && (
            <svg width={cw} height={height} role="img" aria-label={`Pass rate against builder cost: ${dots.map((d) => `${d.label} ${pct(d.rate)} for $${d.cost.toFixed(2)}`).join("; ")}`}>
              {yt.map((v) => (
                <g key={v}>
                  <line x1={m.l} x2={cw - m.r} y1={y(v)} y2={y(v)} stroke="var(--line)" />
                  <text x={m.l - 8} y={y(v) + 4} textAnchor="end" fontSize={11} fill="var(--muted)">{Math.round(v * 100)}%</text>
                </g>
              ))}
              {xt.map((t) => (
                <text key={t} x={x(t)} y={height - m.b + 18} textAnchor="middle" fontSize={11} fill="var(--muted)">${t < 1 ? t.toFixed(2) : t}</text>
              ))}
              <text x={(m.l + cw - m.r) / 2} y={height - 4} textAnchor="middle" fontSize={11} fill="var(--muted)">{axis}</text>
              <text x={m.l} y={14} fontSize={11} fill="var(--muted)">↖ better: more passed for less</text>
              <path d={worseRegion(front, x, y, cw - m.r, height - m.b)} fill="var(--ink)" opacity={0.12} />
              <path d={front.map(([fx, fy], i) => `${i ? "L" : "M"}${x(fx)},${y(fy)}`).join("")} fill="none" stroke="var(--ink)" strokeWidth={1.2} strokeDasharray="4 4" opacity={0.6} />
              {named.map(({ d, cx, cy, ly, right }) => {
                const body = (
                  <>
                    <TipHead>{d.label}</TipHead>
                    {d.sub && <TipLine muted>{d.sub}</TipLine>}
                    <TipLine>Passed <span className="num font-semibold">{pct(d.rate)}</span> of tickets</TipLine>
                    <TipLine>{spent} <span className="num font-semibold">${d.cost.toFixed(2)}</span></TipLine>
                    {d.tip}
                  </>
                );
                return (
                  <g key={d.label} className={h.on === d.label ? "sc-item sc-on" : "sc-item"} onPointerEnter={(e) => h.show(e, d.label, body)} onPointerDown={(e) => h.show(e, d.label, body)}>
                    <circle cx={cx} cy={cy} r={14} fill="transparent" />
                    <circle cx={cx} cy={cy} r={7} fill={d.color} stroke="var(--bg)" strokeWidth={2} />
                    {Math.abs(ly - (cy + 4)) > 2 && <line x1={cx + (right ? 7 : -7)} y1={cy} x2={cx + (right ? 10 : -10)} y2={ly - 4} stroke="var(--muted)" strokeWidth={0.75} />}
                    <text x={right ? cx + 11 : cx - 11} y={ly} textAnchor={right ? "start" : "end"} fontSize={12} fontWeight={500} fill="var(--ink)">{d.label}</text>
                  </g>
                );
              })}
            </svg>
          )}
        </div>
        <HoverTip tip={h.tip} />
      </div>
      <p className="label muted mt-2">The tint is what the dashed frontier beats: a builder there cost more and passed fewer tickets than one on the line.</p>
      {narrow && <p className="label muted mt-2">Swipe the chart sideways to see all of it.</p>}
    </div>
  );
}

export type StageLine = { label: string; sub?: string; color: string; shape: Shape; values: (number | null)[]; counts?: string[]; /** Lower and upper edge at each stage (e.g. mean ± 1 SD across builders), drawn as a shaded band. */ band?: ([number, number] | null)[] };

/** Pass rate at each stage, one line per builder. Hover a point for the builder and stage; the other lines dim. */
export function StageLines({ lines, height = 340 }: { lines: StageLine[]; height?: number }) {
  const [ref, w] = useWidth<HTMLDivElement>();
  const h = useHover();
  const m = { l: 40, r: 18, t: 14, b: 34 };
  const n = Math.max(...lines.map((l) => l.values.length));
  const all = lines.flatMap((l) => [...l.values.filter((v): v is number => v != null), ...(l.band ?? []).flatMap((b) => b ?? [])]);
  const yLo = Math.max(0, Math.floor(10 * Math.min(...all)) / 10 - 0.1), yHi = Math.min(1, Math.ceil(10 * Math.max(...all)) / 10 + 0.05);
  const x = (i: number) => m.l + (n > 1 ? (i / (n - 1)) * (w - m.l - m.r) : 0);
  const y = (v: number) => m.t + (1 - (v - yLo) / (yHi - yLo)) * (height - m.t - m.b);
  const yt = Array.from({ length: 11 }, (_, i) => i / 10).filter((v) => v >= yLo - 1e-9 && v <= yHi + 1e-9);
  return (
    <div>
      <div ref={h.ref} className={h.on ? "relative sc-hov" : "relative"} onPointerLeave={h.hide}>
        <div ref={ref}>
          {w > 0 && (
            <svg width={w} height={height} role="img" aria-label={`Pass rate at each stage: ${lines.map((l) => `${l.label} ${l.values.map((v) => (v == null ? "–" : pct(v))).join(", ")}`).join("; ")}`}>
              {yt.map((v) => (
                <g key={v}>
                  <line x1={m.l} x2={w - m.r} y1={y(v)} y2={y(v)} stroke="var(--line)" />
                  <text x={m.l - 6} y={y(v) + 4} textAnchor="end" fontSize={11} fill="var(--muted)">{Math.round(v * 100)}%</text>
                </g>
              ))}
              {Array.from({ length: n }, (_, i) => <text key={i} x={x(i)} y={height - m.b + 20} textAnchor="middle" fontSize={11} fill="var(--muted)">Stage {i}</text>)}
              {lines.map((l) => (
                <g key={l.label} className={h.on === l.label ? "sc-item sc-on" : "sc-item"}>
                  {l.band && l.band.every((b) => b) && (
                    <path d={`${l.band.map((b, i) => `${i ? "L" : "M"}${x(i)},${y(b![1])}`).join("")}${[...l.band].reverse().map((b, i) => `L${x(l.band!.length - 1 - i)},${y(b![0])}`).join("")}Z`} fill={l.color} fillOpacity={h.on === l.label ? 0.25 : 0} stroke="none" pointerEvents="none" />
                  )}
                  <path d={l.values.flatMap((v, i) => (v == null ? [] : [`${i ? "L" : "M"}${x(i)},${y(v)}`])).join("")} fill="none" stroke={l.color} strokeWidth={2} />
                  {l.values.map((v, i) => v == null ? null : (
                    <g key={i}
                      onPointerEnter={(e) => h.show(e, l.label, <><TipHead>{l.label}</TipHead>{l.sub && <TipLine muted>{l.sub}</TipLine>}<TipLine>Stage {i}: <span className="num font-semibold">{pct(v)}</span> passed{l.counts?.[i] ? ` · ${l.counts[i]}` : ""}</TipLine>{l.band?.[i] && <TipLine muted>Across builders (±1 SD): {pct(l.band[i]![0])} to {pct(l.band[i]![1])}</TipLine>}</>)}
                      onPointerDown={(e) => h.show(e, l.label, <><TipHead>{l.label}</TipHead>{l.sub && <TipLine muted>{l.sub}</TipLine>}<TipLine>Stage {i}: <span className="num font-semibold">{pct(v)}</span> passed{l.counts?.[i] ? ` · ${l.counts[i]}` : ""}</TipLine>{l.band?.[i] && <TipLine muted>Across builders (±1 SD): {pct(l.band[i]![0])} to {pct(l.band[i]![1])}</TipLine>}</>)}>
                      <circle cx={x(i)} cy={y(v)} r={12} fill="transparent" />
                      <Mark shape={l.shape} x={x(i)} y={y(v)} r={4.5} color={l.color} />
                    </g>
                  ))}
                </g>
              ))}
            </svg>
          )}
        </div>
        <HoverTip tip={h.tip} />
      </div>
      <BuilderLegend items={lines.map((l) => ({ model: l.label, color: l.color, shape: l.shape }))} />
    </div>
  );
}

/** Benchmark bars: one horizontal bar per row, best first, its % at the end, and a dashed line for the average of all rows;
 *  beside each, how far it sits above (blue) or below (red) that average. Hover a row for its details. */
export function BenchmarkBars({ rows }: { rows: { label: string; sub?: string; value: number; tip?: ReactNode }[] }) {
  const h = useHover();
  const avgV = rows.reduce((a, r) => a + r.value, 0) / (rows.length || 1);
  // scale to the data (up to the next tenth above the best), so the longest bar reaches across the row
  const top = Math.min(1, Math.ceil(10 * Math.max(...rows.map((r) => r.value), 0.1)) / 10 + 0.1);
  const at = (v: number) => `${((100 * v) / top).toFixed(2)}%`;
  const pts = (d: number) => `${d >= 0 ? "+" : "−"}${Math.abs(Math.round(100 * d))}`;
  return (
    <div ref={h.ref} className={h.on ? "relative sc-hov" : "relative"} onPointerLeave={h.hide}>
      <ul className="sc-rows">
        <li className="sc-row" aria-hidden>
          <div />
          <div className="sc-bench-head"><span className="label muted" style={{ left: at(avgV) }}>average {pct(avgV)}</span></div>
        </li>
        {rows.map((r) => {
          const d = r.value - avgV;
          const body = (
            <>
              <TipHead>{r.sub ?? r.label}</TipHead>
              <TipLine>Passed <span className="num font-semibold">{pct(r.value)}</span> of tickets</TipLine>
              <TipLine><span className="num font-semibold" style={{ color: d < 0 ? "var(--f-recall)" : "var(--f-state)" }}>{pts(d)} pts</span><span className="muted"> {d < 0 ? "below" : "above"} the average of all designs ({pct(avgV)})</span></TipLine>
              {r.tip}
            </>
          );
          return (
            <li key={r.label} className={h.on === r.label ? "sc-row sc-item sc-on" : "sc-row sc-item"} onPointerEnter={(e) => h.show(e, r.label, body, true)} onPointerMove={(e) => h.show(e, r.label, body, true)} onPointerDown={(e) => h.show(e, r.label, body, true)}>
              <div className="sc-name">
                <div className="font-medium">{r.sub ?? r.label}</div>
                {r.sub && <div className="sc-bench-id">{r.label}</div>}
              </div>
              <div className="sc-bench">
                <div className="sc-bench-bar" style={{ width: at(r.value) }} />
                <div className="sc-bench-avg" style={{ left: at(avgV) }} />
                <span className="sc-bench-val num" style={{ left: `calc(${at(r.value)} + 10px)` }}>
                  <span className="font-semibold">{pct(r.value)}</span>
                  <span style={{ color: d < 0 ? "var(--f-recall)" : "var(--f-state)" }}> {pts(d)}</span>
                </span>
              </div>
            </li>
          );
        })}
      </ul>
      <HoverTip tip={h.tip} />
    </div>
  );
}
