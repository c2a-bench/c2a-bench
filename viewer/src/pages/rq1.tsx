import { use } from "react";
import { TextLink } from "@/components/link";
import { ChartCard, Defined, How, GroupedBarsLine, Legend, VIZ, type LineSeries } from "@/components/charts";
import { useRunSummary } from "@/pages/research";
import { useJob } from "@/lib/route";
import { getMeta } from "@/lib/data";
import { evolutionForStage, type CriterionScore } from "@/lib/knowledge-evolution";
import { TICKET_TYPES, TICKET_TYPE_DEFS, TICKET_TYPE_LABEL, ticketTypes } from "@/lib/ticket-types";
import type { FactsScore, Meta } from "@/lib/types";

// What each series means, for a reader who has not seen the benchmark before.
export const EVOLUTION_DEFS = {
  all: "Share of all tickets in the stage the agent got fully right.",
  update: "Tickets that test a rule that is new or changed in this stage's docs. Higher means the builder picked up the change.",
  staleness: "The changed-rule tickets alone: the old version of the rule would now be wrong. Higher means the agent dropped the outdated version.",
  regression: "Tickets on rules that did not change. Higher means the agent kept what it already got right; lower means the rebuild broke it.",
};

const KNOWLEDGE_DEFS = {
  recall: "Of the facts the tickets need, the share that is in the agent's files. A low score is what causes “Missing knowledge” failures.",
  precision: "Of the facts the agent holds from the stage's list (needed facts and their outdated or look-alike versions), the share that are the needed ones. A low score means the agent's files also hold wrong versions. It is a score, not a failure type: holding a wrong version does not show it caused a failure.",
  customer: "Of the facts only the customer knows and the tickets need, the share the agent got. A low score is what causes “Missing customer info” failures.",
};

const pctv = (v: number | null | undefined) => (v == null ? "—" : `${Math.round(100 * v)}%`);

/** What the agent's files hold, scored over every ticket of a stage (passed and failed). Fact-graded runs only. */
function KnowledgeScores({ meta, stages, name, job }: { meta: Meta; stages: number[]; name: (s: number) => string; job: string }) {
  const facts = (s: number) => meta.scores[String(s)]?.facts;
  const graded = stages.filter((s) => facts(s));
  if (!graded.length) return null;
  const bar = (key: string, label: string, color: string, pick: (f: FactsScore) => number | null): LineSeries => ({
    key,
    label,
    color,
    points: stages.map((s) => {
      const v = facts(s) ? pick(facts(s)!) : null;
      return v == null ? { value: null } : { value: v, note: pctv(v) };
    }),
  });
  const bars = [
    bar("recall", "Rule recall", VIZ[3], (f) => f.rule_recall),
    bar("precision", "Rule precision", VIZ[1], (f) => f.rule_precision),
    bar("customer", "Customer facts recall", VIZ[4], (f) => f.customer_recall),
  ];
  const rows = graded
    .flatMap((s) => (facts(s)!.rows ?? []).map((x) => ({ ...x, stage: s })))
    .sort((a, b) => Number(a.passed) - Number(b.passed) || a.recall - b.recall);
  return (
    <ChartCard
      className="mt-10"
      title="Knowledge in the agent's files"
      scope={{ label: "All stages" }}
      how="One judge call per stage reads the agent's files and marks each fact the tickets need as present or absent, quoting the agent's own text; a quote not found in the files counts as absent. Each score is computed over every ticket of the stage, passed and failed. The table lists every ticket, failed first."
      subtitle="How much of what the tickets need is in the agent's files, scored over all tickets, passed or failed. The failure analysis shows why tickets failed; these scores are not failure rates."
      table={
        <div className="space-y-6">
          <table className="w-full text-sm">
            <thead className="border-b text-left text-xs text-muted-foreground">
              <tr>
                <th className="py-2 pr-3 font-medium">stage</th>
                <th className="py-2 pr-3 font-medium">rule recall</th>
                <th className="py-2 pr-3 font-medium">rule precision</th>
                <th className="py-2 font-medium">customer facts recall</th>
              </tr>
            </thead>
            <tbody>
              {graded.map((s) => (
                <tr key={s} className="border-b border-border/60">
                  <td className="py-2 pr-3">{name(s)}</td>
                  <td className="py-2 pr-3 tabular-nums">{pctv(facts(s)!.rule_recall)}</td>
                  <td className="py-2 pr-3 tabular-nums">{pctv(facts(s)!.rule_precision)}</td>
                  <td className="py-2 tabular-nums">{pctv(facts(s)!.customer_recall)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <table className="w-full text-sm">
            <thead className="border-b text-left text-xs text-muted-foreground">
              <tr>
                <th className="py-2 pr-3 font-medium">ticket</th>
                <th className="py-2 pr-3 font-medium">stage</th>
                <th className="py-2 pr-3 font-medium">passed</th>
                <th className="py-2 pr-3 font-medium">rule recall</th>
                <th className="py-2 pr-3 font-medium">facts in the agent's files</th>
                <th className="py-2 pr-3 font-medium">facts missing</th>
                <th className="py-2 font-medium">wrong versions held</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((x) => (
                <tr key={`${x.stage}-${x.id}`} className="border-b border-border/60 align-top">
                  <td className="py-2 pr-3">{x.passed ? x.id : <TextLink href={`/runs/${job}/tickets?stage=${x.stage}&t=${encodeURIComponent(x.id)}`}>{x.id}</TextLink>}</td>
                  <td className="py-2 pr-3">{name(x.stage)}</td>
                  <td className="py-2 pr-3 tabular-nums">{x.passed ? "yes" : "no"}</td>
                  <td className="py-2 pr-3 tabular-nums">{pctv(x.recall)}</td>
                  <td className="py-2 pr-3 text-xs">{x.right.join(", ")}</td>
                  <td className="py-2 pr-3 text-xs">{x.absent.join(", ")}</td>
                  <td className="py-2 text-xs">{x.traps.join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      }
    >
      <GroupedBarsLine xLabels={stages.map(name)} bars={bars} format={pctv} axisFormat={pctv} showValues />
      <Legend items={bars.map((b) => ({ key: b.key, label: b.label, value: 0, color: b.color, def: KNOWLEDGE_DEFS[b.key as keyof typeof KNOWLEDGE_DEFS] }))} counts={false} />
    </ChartCard>
  );
}

/** RQ1 · end-to-end effectiveness, with RQ6 (knowledge evolution) folded in: how the agent does at each stage. */
export default function Rq1Page() {
  const job = useJob();
  const meta = use(getMeta(job));
  const { stages, name, e2e, allPassed, allAnswerable, costRow, parts } = useRunSummary();
  const evo = stages.map((s) => evolutionForStage(s, meta.scores[String(s)]));
  // Discovery / regression / adaptability when the run's data has ticket types (they add up to every ticket);
  // older data falls back to update / staleness / regression.
  const types = stages.map((s) => ticketTypes(meta.scores[String(s)]));
  const typed = types.some((t) => !!t);
  const evolves = typed || evo.some((r) => !r.update.empty || !r.staleness.empty);
  const point = (c: CriterionScore) => (c.empty || !c.total ? { value: null } : { value: c.passed / c.total, note: `${c.passed}/${c.total}` });
  const line: LineSeries = {
    key: "all",
    label: "all tickets",
    color: VIZ[1],
    points: e2e.map((r) => ({ value: r.answerable ? r.passed / r.answerable : null, note: `${r.passed}/${r.answerable}` })),
  };
  const typeColor = { discovery: VIZ[0], regression: VIZ[4], adaptability: VIZ[2] } as const;
  const bars: LineSeries[] = typed
    ? TICKET_TYPES.map((k) => ({
        key: k,
        label: TICKET_TYPE_LABEL[k],
        color: typeColor[k],
        points: types.map((t) => {
          const c = t?.[k];
          const n = t ? TICKET_TYPES.reduce((a, x) => a + t[x].total, 0) : 0;
          return !c || !c.total ? { value: null } : { value: c.passed / c.total, note: `${c.passed}/${c.total} · ${Math.round((100 * c.total) / n)}% of the stage` };
        }),
      }))
    : evolves
    ? [
        { key: "update", label: "update", color: VIZ[0], points: evo.map((r) => point(r.update)) },
        { key: "staleness", label: "staleness", color: VIZ[2], points: evo.map((r) => point(r.staleness)) },
        { key: "regression", label: "regression", color: VIZ[4], points: evo.map((r) => point(r.regression)) },
      ]
    : [];
  return (
    <div className="mx-auto max-w-5xl px-6 py-12">
      <h1 className="font-heading text-3xl font-normal tracking-tight">Scores by stage</h1>
      <p className="mt-2 max-w-3xl text-sm text-muted-foreground">How many tickets the agent gets right after each build, and whether it keeps up when the docs change.</p>
      <ChartCard
        className="mt-10"
        title="Tickets passed at each stage"
        scope={{ label: "All stages" }}
        how={
          typed
            ? "Line: tickets passed ÷ tickets in the stage. Each bar: tickets passed ÷ tickets of that kind in the stage. Every ticket is exactly one kind, so the kinds add up to the stage: new = a ticket no earlier stage had; old tickets, old facts (regression) = an earlier stage's ticket whose expected answer did not change; old tickets, new facts (adaptability) = an earlier stage's ticket whose expected answer changed with the docs. Stage 0 is all new. Hover a bar for its counts and its share of the stage."
            : evolves
            ? "Line: tickets passed ÷ tickets in the stage. Each bar: tickets passed ÷ tickets of that kind in the stage. A ticket is update when its rule is new or changed in this stage's docs, staleness when the old version of that rule would now give the wrong answer, regression when its rule did not change. Hover a point or bar for its counts."
            : "Tickets passed ÷ tickets at each step. Hover a point for its counts."
        }
        subtitle={
          typed
            ? "Each stage changes the docs and the builder updates the agent. The line is the share of all of the stage's tickets the agent got right; the bars split them into new tickets, old tickets whose answer is unchanged, and old tickets whose answer changed."
            : evolves
            ? "Each stage changes the docs and the builder updates the agent. The line is the share of all tickets right; the bars split out the tickets that test a change."
            : "Each step builds a new agent. The line is the share of tickets right at each step."
        }
        table={
          <table className="w-full text-sm">
            <thead className="border-b text-left text-xs text-muted-foreground">
              <tr>
                <th className="py-2 pr-3 font-medium">step</th>
                <th className="py-2 pr-3 font-medium">all tickets</th>
                {bars.map((b) => (
                  <th key={b.key} className="py-2 pr-3 font-medium">{b.label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {stages.map((s, i) => (
                <tr key={s} className="border-b border-border/60">
                  <td className="py-2 pr-3">{name(s)}</td>
                  <td className="py-2 pr-3 tabular-nums">{line.points[i].note ?? "—"}</td>
                  {bars.map((b) => (
                    <td key={b.key} className="py-2 pr-3 tabular-nums">{b.points[i].note ?? "—"}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        }
      >
        <GroupedBarsLine
          xLabels={stages.map(name)}
          bars={bars}
          line={line}
          format={(v) => `${Math.round(100 * v)}%`}
          axisFormat={(v) => `${Math.round(100 * v)}%`}
          showValues
          callout={{ index: 0, label: "First build" }}
        />
        {bars.length > 0 && (
          <Legend items={bars.map((b) => ({ key: b.key, label: b.label, value: 0, color: b.color, def: typed ? TICKET_TYPE_DEFS[b.key as keyof typeof TICKET_TYPE_DEFS] : EVOLUTION_DEFS[b.key as keyof typeof EVOLUTION_DEFS] }))} counts={false} />
        )}
        <div className="mt-1.5 flex items-center gap-1.5 font-sans text-xs">
          <span className="h-0.5 w-3.5 rounded-full" style={{ background: line.color }} />
          <Defined def={EVOLUTION_DEFS.all}>all tickets</Defined>
        </div>
      </ChartCard>
      <p className="mt-6 font-sans text-sm">
        <TextLink href={`/runs/${job}/tickets?view=case&from=rq1`}>See the test cases behind these numbers</TextLink>
      </p>
      <KnowledgeScores meta={meta} stages={stages} name={name} job={job} />
      {parts.time}
    </div>
  );
}
