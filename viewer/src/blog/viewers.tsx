/**
 * Interactive viewers for the blog post, placed with `<!-- figure:ticket -->`, `<!-- figure:behaviours -->` and `<!-- figure:customer-types -->`.
 *  - TicketViewer: an animated diagram of how the bench works, one ticket through the six stages (based on Skyway service-02, Nov 6).
 *  - BehaviourViewer: the 14 customer behaviours, each with a short real exchange (Redwood runs) and what it tests.
 * The numbers are fixed here (from the published runs), not loaded.
 */
import { useEffect, useRef, useState } from "react";
import { Pause, Play, RotateCcw } from "lucide-react";

/** How the bench works, as a small animated diagram: the docs (and what changed), the builder building or updating the
 *  support agent, a customer writing in, the agent looking up its knowledge and calling the support desk, and the check.
 *  A simplified demo based on a real Skyway Air ticket and run (knowledge-graph design, Nov 6), where the agent really
 *  failed at stage 3. */
type DemoStage = {
  docs: [string, string]; changed?: number; was?: string; docsNote: string;
  built: string; customer: [string, string]; lookup: [string, string]; desk: [string, string, string]; pass: boolean; why: string;
};
const DEMO: DemoStage[] = [
  { docs: ["Delay 4h+: $150", "Missed meal: $50"], docsNote: "Stage 0: the company's docs. A 4-hour delay earns $150; a missed meal, $50.",
    built: "Builds", customer: ["“Meal missing,", "landed 4h late.”"], lookup: ["delay → $150", "meal → $50"],
    desk: ["credit $150", "credit $50", "ticket resolved"], pass: true, why: "Resolved: the desk ends in exactly the right state." },
  { docs: ["Delay 4h+: $150", "Missed meal: $50"], docsNote: "Stage 1: the docs change, but nothing this ticket needs.",
    built: "Updates", customer: ["“Meal missing,", "landed 4h late.”"], lookup: ["delay → $150", "meal → $50"],
    desk: ["credit $150", "credit $50", "ticket resolved"], pass: true, why: "Resolved: the update didn't break this ticket." },
  { docs: ["Delay 4h+: $175", "Missed meal: $50"], changed: 0, was: "was $150", docsNote: "Stage 2: compensation goes up from $150 to $175. An outdated draft still says $200.",
    built: "Updates", customer: ["“Meal missing,", "landed 4h late.”"], lookup: ["delay → $175", "meal → $50"],
    desk: ["credit $175", "credit $50", "ticket resolved"], pass: true, why: "Resolved: it used the new amount and ignored the outdated draft." },
  { docs: ["Delay 4h+: $175", "Missed meal: $50"], docsNote: "Stage 3: the docs change again, but nothing this ticket needs.",
    built: "Updates", customer: ["“Not sure which", "flight it was.”"], lookup: ["one trip found…", "waits to confirm"],
    desk: ["label unverified", "no credits", "ticket closed"], pass: false, why: "Failed: the agent had both rules and the account has one trip, but it closed the claim unpaid. An agent failure." },
  { docs: ["Delay 4h+: $175", "Missed meal: $60"], changed: 1, was: "was $50", docsNote: "Stage 4: goodwill for a missed meal goes up from $50 to $60.",
    built: "Updates", customer: ["“Meal missing,", "landed 4h late.”"], lookup: ["delay → $175", "meal → $60"],
    desk: ["credit $175", "credit $60", "ticket resolved"], pass: true, why: "Resolved: back on track, with the new amount." },
  { docs: ["Delay 3h+ from Dec 1", "Missed meal: $60"], changed: 0, was: "flight: Nov 28", docsNote: "Stage 5: from December 1, compensation starts at 3 hours. This flight was on November 28.",
    built: "Updates", customer: ["“Meal missing,", "landed 4h late.”"], lookup: ["4h late: $175", "meal → $60"],
    desk: ["credit $175", "credit $60", "ticket resolved"], pass: true, why: "Resolved: 4 hours late qualifies under either rule." },
];
/** Beats: 0 docs, 1 docs → builder, 2 builder → agent, 3 customer → agent, 4 agent looks up, 5 agent → desk, 6 desk → check, 7 verdict. */
const NARRATE = (d: DemoStage, i: number): string[] => [
  d.docsNote,
  "The builder, a coding agent, reads the docs.",
  `${d.built === "Builds" ? "It builds the support agent" : "It updates the support agent it built"}, with the rules in a knowledge graph. The docs are then taken away.`,
  i === 3 ? "A customer writes in, but isn't sure which flight it was." : "A customer writes in: their meal was missing and the flight landed 4 hours late.",
  i === 3 ? "The agent finds one trip on the account, but waits for the customer to confirm." : `The agent looks up its knowledge: ${d.lookup[0]}, ${d.lookup[1]}.`,
  i === 3 ? "It calls the support desk: labels the claim unverified and closes it, with no credits." : "It calls the support desk: two credits, then it closes the ticket.",
  "We check the desk's end state against the right answer.",
  d.why,
];
const BEAT = 1500;
const N = { docs: [4, 20], builder: [194, 20], agent: [384, 20], customer: [574, 20], desk: [384, 186], check: [574, 186] } as const;
const W = 152, H = 106;
const STAGE_NAME = ["First build", "Docs update", "Docs update", "Docs update", "Docs update", "Docs update"];

function Node({ at, title, lines, on, tone, hi }: { at: readonly [number, number]; title: string; lines: string[]; on: boolean; tone?: "good" | "bad"; hi?: number }) {
  const [x, y] = at;
  return (
    <g className={`bd-node${on ? " on" : ""}${tone ? ` bd-${tone}` : ""}`}>
      <rect x={x} y={y} width={W} height={H} rx={12} />
      <text x={x + 12} y={y + 22} className="bd-title">{title}</text>
      {lines.map((l, k) => (
        <text key={k} x={x + 12} y={y + 46 + k * 18} className={k === hi ? "bd-line bd-hi" : "bd-line"}>{l}</text>
      ))}
    </g>
  );
}

function Edge({ d, on }: { d: string; on: boolean }) {
  return <path d={d} className={`bd-edge${on ? " on" : ""}`} markerEnd={on ? "url(#bd-arrow-on)" : "url(#bd-arrow)"} />;
}

export function TicketViewer() {
  const reduce = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  const [i, setI] = useState(0);
  const [beat, setBeat] = useState(0);
  // It starts at stage 0, step one, and plays only once it is on screen (not from page load, which would leave it
  // finished by the time a reader scrolls to it). With reduced motion it waits for the play button.
  const [playing, setPlaying] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (reduce || !box.current || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(([e]) => {
      // The first report can say "intersecting" for any overlap, below the threshold: wait for half on screen.
      if (e.isIntersecting && e.intersectionRatio >= 0.5) { setPlaying(true); io.disconnect(); }
    }, { threshold: 0.5 });
    io.observe(box.current);
    return () => io.disconnect();
  }, [reduce]);
  const d = DEMO[i];
  const end = i === DEMO.length - 1 && beat === 7;
  useEffect(() => {
    if (!playing) return;
    if (end) { setPlaying(false); return; }
    const t = setTimeout(() => {
      if (beat < 7) setBeat(beat + 1);
      else { setI(i + 1); setBeat(0); }
    }, beat === 7 ? BEAT * 2 : BEAT);
    return () => clearTimeout(t);
  }, [playing, beat, i, end]);
  const toggle = () => {
    if (end) { setI(0); setBeat(0); setPlaying(true); }
    else setPlaying(!playing);
  };
  const b = beat;
  return (
    <div className="bv bd" ref={box}>
      <div className="bd-scroll">
      <svg viewBox="0 0 730 304" className="bd-svg" role="img" aria-label={NARRATE(d, i)[b]}>
        <defs>
          <marker id="bd-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" className="bd-arrowhead" /></marker>
          <marker id="bd-arrow-on" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" className="bd-arrowhead on" /></marker>
        </defs>
        <Edge d="M158 73 H190" on={b === 1} />
        <Edge d="M348 73 H380" on={b === 2} />
        <Edge d="M572 73 H540" on={b === 3} />
        <Edge d="M460 128 V182" on={b === 5} />
        <Edge d="M538 239 H570" on={b === 6} />
        <text x="468" y="160" className="bd-edge-label">calls</text>
        <text x="8" y="232" className="bd-stage">Stage {i}</text>
        <text x="8" y="258" className="bd-stage-sub">{STAGE_NAME[i]}</text>
        <Node at={N.docs} title={i === 0 ? "COMPANY DOCS" : "DOCS CHANGE"} lines={[...d.docs, d.was ?? ""]} hi={d.changed} on={b === 0 || b === 1} />
        <Node at={N.builder} title="BUILDER" lines={b >= 1 ? [b === 1 ? "Reading docs…" : `${d.built} the`, b === 1 ? "" : "support agent"] : ["", ""]} on={b === 1 || b === 2} />
        <Node at={N.agent} title="SUPPORT AGENT" lines={b >= 4 ? ["Looks up:", ...d.lookup] : ["Knowledge graph", b >= 2 ? (d.built === "Builds" ? "built" : "updated") : ""]} on={b >= 2 && b <= 5} />
        <Node at={N.customer} title="CUSTOMER" lines={b >= 3 ? d.customer : ["", ""]} on={b === 3} />
        <Node at={N.desk} title="SUPPORT DESK" lines={b >= 5 ? d.desk : ["", "", ""]} on={b === 5 || b === 6} tone={b >= 5 && !d.pass ? "bad" : undefined} />
        <Node at={N.check} title="CHECK" lines={b >= 7 ? [d.pass ? "✓ Resolved" : "✗ Failed"] : [b === 6 ? "Comparing…" : ""]} on={b >= 6} tone={b >= 7 ? (d.pass ? "good" : "bad") : undefined} />
      </svg>
      </div>
      <p className="bd-say" aria-live="polite">{NARRATE(d, i)[b]}</p>
      <div className="bp-controls">
        <button type="button" className="bp-play" onClick={toggle} aria-label={end ? "Replay" : playing ? "Pause" : "Play"}>
          {end ? <RotateCcw className="size-4" /> : playing ? <Pause className="size-4" /> : <Play className="size-4" />}
        </button>
        <div className="bp-track" role="group" aria-label="Stage">
          {DEMO.map((st, k) => {
            const shown = k < i || (k === i && beat === 7);
            return (
              <button key={k} type="button" aria-pressed={k === i} onClick={() => { setI(k); setBeat(0); setPlaying(true); }}
                className={`bp-seg${shown ? (st.pass ? " is-pass" : " is-fail") : ""}`} title={`Stage ${k}`}>
                {shown ? (st.pass ? "✓" : "✗") : ""} <span className="bp-seg-word">Stage </span>{k}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

type Turn = ["c" | "a", string];
/** name, what the customer does, a short real exchange (trimmed with …), what the agent has to get right */
const BEHAVIOURS: [string, string, Turn[], string][] = [
  ["Baseline", "Plain: answers what is asked.", [
    ["c", "Please revoke a leaked API key."],
    ["a", "Please confirm the exact key name: “ci-runner” is already disabled, while “prod-web” is active."],
    ["c", "The key name is “ci-runner.” I don’t know the key ID; please ensure it is fully revoked."],
  ], "Nothing is hidden. This is the control: every other behavior is measured against it."],
  ["On request", "Says as little as possible; one fact per question.", [
    ["c", "We need to rotate one of our keys."],
    ["a", "Which key should be rotated: ci-runner or prod-web? Also, is it suspected to be exposed, or is this a routine rotation?"],
    ["c", "The key is prod-web."],
    ["a", "Thanks. Is it suspected to be exposed, or is this a routine rotation? We won’t disable it until you confirm."],
  ], "Two questions, one answer. The agent has to notice what is still missing and ask again."],
  ["Incremental", "Volunteers one or two facts each message.", [
    ["c", "Every request is failing."],
    ["a", "Which region is affected, and what error are the failed requests returning?"],
    ["c", "The affected region is us-east. Requests to the dedicated pool hang and then fail with a 504."],
    ["c", "Production is down, and we don’t have a workaround."],
  ], "The facts arrive over several messages, and the most important one (production is down) comes last. The agent has to keep listening, not act on the first message."],
  ["Underspecified", "Names the area, not the problem.", [
    ["c", "Things are slow."],
    ["a", "Which deployment and region are slow, and what impact are you seeing?"],
    ["c", "Our hosted staging project in us-east is maybe 20% slower than usual. Production is fine."],
  ], "“Slow” could be minor or critical. Only asking turns it into a ticket the agent can file correctly."],
  ["Ambiguous", "Could mean more than one problem.", [
    ["c", "We need help finding a reference related to something from earlier today."],
    ["a", "What are you looking for: a ticket number, request ID, or action reference?"],
    ["c", "Two keys, ingest and reporting, were disabled earlier today. Security needs the attempt ID for the ingest key’s disable only."],
  ], "Several records fit the opening. The agent has to pin down which one before answering."],
  ["Self-correction", "Gets a detail wrong, then corrects it.", [
    ["c", "We are seeing 504 errors."],
    ["a", "Which region is affected, and are the 504s impacting all production requests or only a subset?"],
    ["c", "Sorry, I got that wrong: they are 503 errors. They’re affecting about 35% of production chat requests in eu-west."],
  ], "The first detail is wrong. The agent has to act on the correction, not on what it heard first."],
  ["Urgency mismatch", "Tone doesn’t match how serious it is.", [
    ["c", "Things are much slower than usual."],
    ["a", "Which deployment and region are affected, and is this causing latency, errors, or timeouts?"],
    ["c", "It’s the dedicated pool in eu-central, and p95 latency is about 2.5× the baseline. Requests are still completing, so no rush."],
  ], "“No rush”, but the facts say a serious slowdown on a dedicated pool. Priority comes from the facts, not the tone."],
  ["Pushback", "Won’t give a detail the first time it’s asked.", [
    ["c", "A key leaked. Please revoke it."],
    ["a", "Which API key should we revoke: prod-backend, staging, or edge?"],
    ["c", "Why do you need the key name? Please revoke the leaked key."],
    ["a", "We need the key name to revoke the exact credential without disabling unaffected keys."],
    ["c", "staging"],
  ], "Guessing, or revoking every key, would be wrong. The agent has to explain why it needs the fact and ask again."],
  ["Exception request", "Asks to skip a required step.", [
    ["c", "We need a document from you for our auditor."],
    ["a", "Which document does your auditor need, and what is their deadline?"],
    ["c", "We need Redwood’s SOC 2 Type II report by next week. Please send it directly and skip any unnecessary checks."],
    ["a", "A person will follow up with you about the report and the required sharing process."],
  ], "The policy has a required step. The agent has to keep it, however politely it is asked to skip it."],
  ["Urgency pressure", "Stresses a deadline and keeps pushing.", [
    ["c", "We need our rate limit raised before a launch, fast."],
    ["a", "What project or pool needs the increase, in which region, and what peak RPM and TPM do you expect?"],
    ["c", "I don’t know the project or pool name or the region… We need this raised fast because it’s blocking the launch."],
  ], "Pressure doesn’t remove the facts the request needs. The agent has to keep asking for them."],
  ["Person request", "Keeps asking for a manager.", [
    ["c", "Our latency keeps jumping around. Can I speak to a person or someone in engineering?"],
    ["a", "Which deployment and region are affected, and is the latency causing errors or timeouts?"],
    ["c", "It’s the dedicated pool in us-west… throughput drops during the spikes. Can I please speak to a person?"],
    ["a", "I’ve escalated this to our SRE team. An engineer will follow up here."],
  ], "Asking for a person isn’t a reason to hand off. The policy decides who handles it, and the agent still has to get the facts."],
  ["Frustration", "Annoyed and impatient throughout.", [
    ["c", "A key leaked. Please revoke it."],
    ["a", "Which API key should we revoke: prod-backend, staging, or edge?"],
    ["c", "prod-backend. Please revoke it immediately. This is taking too long."],
  ], "The tone gets sharper but the facts don’t change. The agent has to stay on task and not over-apologize into the wrong action."],
  ["Goal change", "Opens with a different request, then switches.", [
    ["c", "We need audit logs exported before an audit."],
    ["a", "Please provide the affected deployment and region, the desired sink, bucket and prefix…"],
    ["c", "Sorry, ignore the audit log request; that’s fine now. Production is down."],
    ["a", "Which deployment and region are affected, and are all production requests failing?"],
  ], "The ticket that matters is the second one. The agent has to drop the first request and resolve the outage, not export logs."],
  ["Disfluency", "Types in a hurry: typos, fillers, broken sentences.", [
    ["c", "um we need to talk about our account"],
    ["a", "Could you briefly describe what you need help with regarding your account?"],
    ["c", "we're thinking about moving to another provider before renewal next month, havent decided yet tho and i wanna talk to a person"],
  ], "Messy writing hides a clear request: a customer thinking of leaving, who wants a person. The agent has to read past the typing."],
];

export function BehaviourViewer() {
  const [i, setI] = useState(12);
  const [name, does, turns, tests] = BEHAVIOURS[i];
  return (
    <div className="bv bv-beh">
      <div className="bv-beh-list" role="group" aria-label="Customer behaviors">
        {BEHAVIOURS.map(([n], k) => (
          <button key={n} type="button" aria-pressed={k === i} onClick={() => setI(k)}>{n}</button>
        ))}
      </div>
      <div className="bv-beh-detail">
        <div className="caps muted">{name}</div>
        <p className="bv-lead" style={{ marginTop: 8 }}>{does}</p>
        <div className="bv-convo">
          {turns.map(([who, text], k) => (
            <div key={k} className={who === "c" ? "bv-turn" : "bv-turn bv-agent"}>
              <div className="caps muted">{who === "c" ? "Customer" : "Support agent"}</div>
              <div className="bv-bubble">{text}</div>
            </div>
          ))}
        </div>
        <div className="bv-tests"><span className="caps muted">What it tests</span><p>{tests}</p></div>
      </div>
    </div>
  );
}



/** Pass rate and customer facts recall per customer behavior, one bar chart with a toggle between the two, over every published
 *  run with customer types (Redwood Inference and Skyway Air). Plain numbers, no adjustment; from `npm run customer-types`
 *  on the pinned runs. [tickets, attempts, pass %, customer facts recall %]. */
const CUSTOMER_TYPES = {"baseline": [57, 921, 66.2, 74.8], "exception_request": [27, 624, 64.1, 69.8], "disfluency": [26, 617, 61.9, 67.3], "underspecified": [44, 1004, 60.6, 60.4], "incremental": [56, 1320, 60, 81.8], "urgency_pressure": [48, 858, 60, 59], "on_request": [63, 1485, 59.7, 49.9], "pushback": [50, 1075, 58.6, 72.5], "frustration": [64, 1434, 56.4, 73.2], "goal_change": [14, 301, 55.1, 40.3], "ambiguous": [43, 939, 51.5, 75], "urgency_mismatch": [39, 882, 47.3, 74.8], "person_request": [32, 833, 40.6, 58.4], "self_correction": [38, 933, 28.9, 49.2]} as Record<string, [number, number, number, number]>;
const typeName = (k: string) => (k === "baseline" ? "Baseline (plain customer)" : k.replace(/^./, (c) => c.toUpperCase()).replace(/_/g, " "));
const MEASURE = { pass: { label: "Pass rate", at: 2, color: "var(--f-state)" }, recall: { label: "Customer facts recall", at: 3, color: "var(--f-customer)" } } as const;

export function CustomerTypeViewer() {
  const [m, setM] = useState<"pass" | "recall">("pass");
  const { at, color } = MEASURE[m];
  const rows = Object.entries(CUSTOMER_TYPES).sort((x, y) => y[1][at] - x[1][at]); // highest first
  const base = CUSTOMER_TYPES.baseline[at]; // the comparison: what a plain customer gets
  return (
    <div className="ct">
      <div className="ct-top">
        <div className="seg" role="group" aria-label="Measure">
          {(Object.keys(MEASURE) as (keyof typeof MEASURE)[]).map((k) => (
            <button key={k} type="button" aria-pressed={m === k} onClick={() => setM(k)}>{MEASURE[k].label}</button>
          ))}
        </div>
        <span className="muted ct-avg-note"><i className="ct-key-avg" aria-hidden /> baseline customer: {Math.round(base)}%</span>
      </div>
      <div className="ct-row ct-axis-row" aria-hidden>
        <span />
        <div className="ct-track ct-axis">{[0, 25, 50, 75, 100].map((v) => <span key={v} style={{ left: `${v}%` }}>{v}%</span>)}</div>
        <span />
      </div>
      <ul className="ct-rows">
        {rows.map(([k, v]) => (
          <li key={k} className="ct-row" aria-label={`${typeName(k)}: ${MEASURE[m].label.toLowerCase()} ${Math.round(v[at])}%, ${v[0]} tickets`}
            title={`${typeName(k)}\npass rate ${v[2].toFixed(0)}%\ncustomer facts recall ${v[3].toFixed(0)}%\n${v[0]} tickets, ${v[1].toLocaleString()} attempts`}>
            <span className="ct-name">{typeName(k)}</span>
            <div className="ct-track"><span className="ct-avg" style={{ left: `${base}%` }} /><span className="ct-bar" style={{ width: `${v[at]}%`, background: color }} /></div>
            <b className="ct-val num">{Math.round(v[at])}%</b>
          </li>
        ))}
      </ul>
      <p className="muted ct-foot">Each ticket always has the same customer behavior, so a behavior's rate also reflects the tickets it was given. The dashed line marks the baseline customer.</p>
    </div>
  );
}
