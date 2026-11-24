// The failure names shown in the viewer (research_notes/failure-nomenclature.md): party, group, type.
// Fact-graded runs carry these names on every blame record (scripts/failure_types.py, which defines them); this file
// adds the definitions and the order, and maps older runs' types onto the names.
import { BLAME_TYPES, partyOf, SYMPTOM_NOT_RECORDED, TYPE_LABEL } from "./knowledge-application";
import type { Ticket } from "./types";

/** The grader's parties: "Bot" is the agent on screen. */
export type Party = "Builder" | "Bot" | "Harness";
export const PARTIES: Party[] = ["Builder", "Bot", "Harness"];

/** scripts/failure_types.py names the agent's party "Agent"; the viewer keys it "Bot". */
export const asParty = (p: string | null | undefined): Party | undefined => (p === "Agent" ? "Bot" : (p as Party | null | undefined) ?? undefined);

type Spec = { party: Party; group: string; def: string; types: { type: string; def: string; old: string[] }[] };

export const FAILURE_SPEC: Spec[] = [
  {
    party: "Builder",
    group: "Missing knowledge (rule recall)",
    def: "A fact the ticket needs is not in the agent's files, so the agent could not use it. The Scores by stage page shows rule recall for every ticket.",
    types: [{ type: "Fact missing from the agent's files", old: ["fact absent"], def: "The judge found no trace of a fact deciding this check in the agent's files." }],
  },
  {
    party: "Builder",
    group: "Build spec failure",
    def: "The agent's build broke a rule of the test.",
    types: [
      { type: "Prompt over the size cap", old: ["context budget exceeded"], def: "The agent's prompt grew past the ticket's token cap, so its model call was refused. The ticket is graded as failed." },
      { type: "Agent never started", old: [], def: "The agent's run program never got to a model call on any ticket of the stage: it is missing, or fails on start (a syntax error). Every ticket of the stage is graded as failed." },
    ],
  },
  {
    party: "Bot",
    group: "Wrong end state (database check)",
    def: "The agent had the knowledge, but the ticket's data ended up wrong.",
    types: [
      { type: "Wrong value", old: ["wrong value", SYMPTOM_NOT_RECORDED], def: "A field was set, to the wrong value." },
      { type: "Value not set", old: ["missing value"], def: "A field the ticket requires was left empty." },
      { type: "Missing label", old: ["missing label"], def: "A label the ticket requires is absent." },
      { type: "Extra label", old: ["extra label or write"], def: "A label the docs do not give this ticket was added." },
      { type: "Forbidden action taken", old: ["forbidden action"], def: "A forbidden call was made, or a call was repeated past its limit." },
      { type: "Required action skipped", old: ["missing required action"], def: "A call the ticket requires was not made." },
      { type: "Protected record changed", old: ["protected state changed"], def: "A record that had to stay untouched was modified." },
    ],
  },
  {
    party: "Bot",
    group: "Wrong reply (reply check)",
    def: "What the agent told the customer broke a reply check. Hidden when zero.",
    types: [
      { type: "Told the customer something wrong", old: ["wrong or prohibited assertion"], def: "A reply check found a wrong or prohibited statement." },
      { type: "Didn't tell the customer something required", old: ["missing assertion"], def: "A reply check found a required statement missing." },
    ],
  },
  {
    party: "Bot",
    group: "Missing customer info (customer recall)",
    def: "A fact only the customer knows, and the ticket needs, never reached the agent. The Scores by stage page shows customer facts recall for every ticket.",
    types: [{ type: "Key fact never obtained from the customer", old: ["decisive fact not obtained"], def: "A decisive customer fact for this check was never told in the conversation." }],
  },
  {
    party: "Bot",
    group: "Agent crash",
    def: "The agent never answered the ticket. Hidden when zero.",
    types: [
      { type: "Agent crashed", old: ["crash"], def: "The agent crashed or broke the output contract." },
      { type: "Model call failed", old: ["model call failed"], def: "A model call failed before the agent finished the ticket." },
      { type: "Never called the model", old: ["no model call"], def: "The agent never asked the model." },
    ],
  },
  {
    party: "Harness",
    group: "Our side",
    def: "Our test setup failed, not the agent or the builder.",
    types: [
      { type: "Time limit", old: ["time limit"], def: "The agent did not finish within our time limit." },
      { type: "Runner crash", old: ["our runner crashed"], def: "Our verifier crashed." },
      { type: "Model provider down", old: ["provider failure"], def: "The language-model provider failed." },
      { type: "Customer simulator failed", old: ["customer model failure"], def: "The simulated customer's model failed." },
      { type: "Trace lost", old: ["trace lost"], def: "The grader could not see the agent's model calls." },
    ],
  },
];

export const OTHER_GROUP = "Other (older runs)";
export const NONE = "none";

export type Leaf = { key: string; party: Party | typeof NONE; group: string; type: string };

const byOld = new Map<string, Leaf>();
const byName = new Map<string, Leaf>();
for (const g of FAILURE_SPEC)
  for (const t of g.types) {
    const leaf = { key: `${g.party}|${g.group}|${t.type}`, party: g.party, group: g.group, type: t.type };
    byName.set(leaf.key, leaf);
    for (const o of t.old) byOld.set(o, leaf);
  }

/** The viewer's leaf for one blame record: its own names when the grader gave a group (fact-graded runs), else the
 *  older type mapped; types no longer named go to "Other (older runs)" under their party. */
export function leafOf(party: Party, oldType: string, group?: string | null): Leaf {
  if (group) return byName.get(`${party}|${group}|${oldType}`) ?? { key: `${party}|${group}|${oldType}`, party, group, type: oldType };
  const hit = byOld.get(oldType);
  if (hit) return hit;
  const type = TYPE_LABEL[oldType] ?? oldType;
  return { key: `${party}|${OTHER_GROUP}|${type}`, party, group: OTHER_GROUP, type };
}

export const NONE_LEAF: Leaf = { key: NONE, party: NONE, group: "No blame recorded", type: "No blame recorded" };

/** The distinct leaves of one failed ticket (one per kind of failed check), or the "no blame" leaf. */
export function ticketLeaves(t: Ticket): Leaf[] {
  const recs: [Party, string, string | null | undefined][] = t.blames
    ? t.blames.map((b) => [asParty(b.party) ?? partyOf(b.label), b.type ?? BLAME_TYPES[b.label]?.[2] ?? SYMPTOM_NOT_RECORDED, b.group])
    : t.failures.flatMap((f) => (f.fault ? [[asParty(f.fault.taxonomy?.party) ?? partyOf(f.fault.label), f.fault.taxonomy?.type ?? BLAME_TYPES[f.fault.label]?.[2] ?? SYMPTOM_NOT_RECORDED, f.fault.taxonomy?.group] as [Party, string, string | undefined]] : []));
  const seen = new Map<string, Leaf>();
  for (const [p, ty, g] of recs) {
    const l = leafOf(p, ty, g);
    seen.set(l.key, l);
  }
  return seen.size ? [...seen.values()] : [NONE_LEAF];
}

export type Rollup = {
  failed: number;
  parties: Record<string, number>;
  groups: Record<string, number>;
  leaves: Record<string, number>;
  info: Record<string, Leaf>;
};

/** Failed tickets by party, group and type. A failed ticket counts once: split evenly between the parties it is blamed on
 *  (the same split as the Overview), then evenly between that party's types. A group is the sum of its types. */
export function rollup(tickets: Ticket[]): Rollup {
  const r: Rollup = { failed: 0, parties: {}, groups: {}, leaves: {}, info: {} };
  const add = (m: Record<string, number>, k: string, n: number) => (m[k] = (m[k] ?? 0) + n);
  for (const t of tickets) {
    if (t.passed) continue;
    const leaves = ticketLeaves(t);
    const parties = [...new Set(leaves.map((l) => l.party))];
    r.failed += 1;
    for (const p of parties) {
      const mine = leaves.filter((l) => l.party === p);
      for (const l of mine) {
        const w = 1 / parties.length / mine.length;
        r.info[l.key] = l;
        add(r.parties, p, w);
        add(r.groups, `${l.party}|${l.group}`, w);
        add(r.leaves, l.key, w);
      }
    }
  }
  return r;
}

/** The small summary kept next to tickets.json: the landing chart's split, without the tickets. */
export function failureSummary(tickets: Ticket[], failedInScore: number, total: number) {
  const r = withGap(rollup(tickets), failedInScore);
  const round = (m: Record<string, number>) => Object.fromEntries(Object.entries(m).map(([k, v]) => [k, Math.round(v * 100) / 100]));
  return { failed: r.failed, total, parties: round(r.parties), groups: round(r.groups) };
}

/** Add failures the score counts but no ticket carries blame for (older publications) as "no blame recorded". */
export function withGap(r: Rollup, failedInScore: number): Rollup {
  const gap = failedInScore - Object.values(r.parties).reduce((a, n) => a + n, 0);
  if (gap <= 0.01) return r;
  const out = { ...r, parties: { ...r.parties }, groups: { ...r.groups }, leaves: { ...r.leaves }, info: { ...r.info } };
  out.parties[NONE] = (out.parties[NONE] ?? 0) + gap;
  out.groups[NONE] = (out.groups[NONE] ?? 0) + gap;
  out.leaves[NONE] = (out.leaves[NONE] ?? 0) + gap;
  out.info[NONE] = NONE_LEAF;
  out.failed = Math.max(out.failed, failedInScore);
  return out;
}

/** Does a leaf fall under a pick ("Builder", "Builder|Group" or "Builder|Group|Type")? */
export const under = (leafKey: string, pick: string) => leafKey === pick || leafKey.startsWith(`${pick}|`);

/** Order the spec gives groups and types; anything else sorts last. */
export function specRank(leaf: Leaf): number {
  let i = 0;
  for (const g of FAILURE_SPEC) for (const t of g.types) { if (g.party === leaf.party && g.group === leaf.group && t.type === leaf.type) return i; i++; }
  return 99;
}

export const defOf = (leaf: Leaf): string | undefined => FAILURE_SPEC.find((g) => g.group === leaf.group)?.types.find((t) => t.type === leaf.type)?.def;
export const groupDef = (group: string): string | undefined => FAILURE_SPEC.find((g) => g.group === group)?.def;
