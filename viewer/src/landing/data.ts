/**
 * Data for the landing page: the latest finished run of every builder model on the current ticket version,
 * plus the per-run meta.json of the Redwood runs (ticket types, failure groups, rule recall, architecture,
 * latency and tokens are not in the catalog).
 */
import { olderThan } from "@/lib/leaderboard";
import { getLandingMeta, listJobs, listTasks, type JobSummary } from "@/lib/data";

export const ENV = { redwood: "redwood-inference", packs: "support-agent-knowledge", skyway: "skyway-air", skywayArch: "skyway-air" } as const;

/** Skyway with the architecture fixed per run: tasks/skyway-air/architectures/<id>.md, by its heading. */
export const SKYWAY_ARCH: Record<string, string> = {
  "graph-query": "Knowledge graph + graph queries",
  "prompt-workflows": "Prompts and workflows, no retrieval",
  "raw-index": "Raw docs + retrieval index",
  "raw-terminal": "Raw docs + terminal tools",
  "wiki-index": "LLM wiki + retrieval index",
  "wiki-terminal": "LLM wiki + terminal tools",
};

/** The latest finished run of each architecture (the catalog lists newest first). */
/** Skyway: each builder model's newest finished run of each architecture (jobs come newest first). */
export function latestByArchitecture(jobs: JobSummary[]) {
  const seen = new Set<string>();
  return jobs.filter((j) => {
    const key = `${(j.builder.model ?? "").split("/").pop()}|${j.architecture}`;
    return j.finished && j.scores.length && j.architecture && !seen.has(key) && seen.add(key);
  });
}
/** Runs started before this date are on an older version of the tickets and are left out. */
export const CURRENT = "2026-10-15";
/** gpt-5.6-sol is also the agent and the customer model in every run. */
export const CONFOUND = "gpt-5.6-sol";
export const CONDITIONS = ["R-complete", "R-fragmented", "R-incomplete", "R-conflicting", "R-noisy"];

export type Shape = "square" | "circle" | "triangle" | "diamond" | "plus" | "cross";
/** Hue by provider, a distinct shade per model, a marker per model. Colours are CSS variables (landing.css). */
const STYLE: Record<string, { color: string; shape: Shape }> = {
  "gpt-6.1-sol": { color: "var(--b-gpt61)", shape: "square" },
  "gpt-6-astra": { color: "var(--b-astra)", shape: "triangle" },
  "gpt-5.6-sol": { color: "var(--b-gpt56)", shape: "circle" },
  "claude-opus-5-5": { color: "var(--b-opus)", shape: "square" },
  "claude-sonnet-5-5": { color: "var(--b-sonnet)", shape: "circle" },
  "gemini-4-argon": { color: "var(--b-gemini)", shape: "diamond" },
  "glm-5.3": { color: "var(--b-glm)", shape: "plus" },
  "deepseek-v4.1-flash-1017": { color: "var(--b-deepseek)", shape: "cross" },
};
const FALLBACK = ["var(--b-x1)", "var(--b-x2)", "var(--b-x3)"];
export function style(model: string) {
  return STYLE[model] ?? { color: FALLBACK[model.length % FALLBACK.length], shape: "circle" as Shape };
}

const HARNESS: Record<string, string> = { "gemini_no_web:GeminiCliNoWeb": "gemini-cli" };
export const shortModel = (m: string | null | undefined) => (m ? m.split("/").pop()! : "unknown");
export const harnessName = (a: string | null | undefined) => (a ? HARNESS[a] ?? a : "");

/** The agent the builder made never ran: 0 passed (always 0 model calls in the published runs). */
export const crashed = (s: { passed: number | null }) => (s.passed ?? 0) === 0;

export type Builder = { model: string; harness: string; job: JobSummary };

/** Latest finished run per builder model on the current ticket version (jobs come newest first). */
export function latestByBuilder(jobs: JobSummary[]): Builder[] {
  const seen = new Set<string>();
  const out: Builder[] = [];
  for (const j of jobs) {
    const model = shortModel(j.builder.model);
    if (!j.finished || !j.scores.length || olderThan(j, CURRENT) || seen.has(model)) continue;
    seen.add(model);
    out.push({ model, harness: harnessName(j.builder.agent), job: j });
  }
  return out;
}

/** Tickets passed ÷ all tickets of the run; a crashed stage counts as failed, as on the run pages. */
export function pooled(j: JobSummary) {
  const p = j.scores.reduce((a, s) => a + (s.passed ?? 0), 0);
  const n = j.scores.reduce((a, s) => a + (s.total ?? 0), 0);
  return n ? p / n : 0;
}

/** Every graded customer conversation in the catalog, each run once (a "-facts" or "-relabel" copy re-grades the same run). */
export function countConversations(jobsByTask: JobSummary[][]) {
  let n = 0;
  for (const jobs of jobsByTask) {
    const seen = new Set<string>();
    for (const j of jobs) {
      const base = j.id.replace(/-(facts|relabel)$/, "");
      if (seen.has(base)) continue;
      seen.add(base);
      n += j.scores.reduce((a, s) => a + (s.total ?? 0), 0);
    }
  }
  return n;
}

// ---- meta.json fields the landing page reads ----

type Count = { passed: number; total: number };
export type MetaStage = {
  passed: number;
  total: number;
  ticket_types?: Partial<Record<"discovery" | "regression" | "adaptability", Count>>;
  behavior_coverage?: { n_behaviors?: number } | null;
  facts?: { rule_recall?: number | null; rule_precision?: number | null } | null;
  failure_taxonomy?: { by_group?: Record<string, number>; by_type?: Record<string, { party?: string | null; group?: string | null; count: number }> } | null;
  architecture?: { observed?: { knowledge_access?: string[]; model_calls_avg?: number | null } | null } | null;
  latency?: { ticket?: { median?: number | null } | null } | null;
  cost?: { bot?: { in?: number | null; usd?: number | null } | null } | null;
};
/** Failed tickets by who was to blame (lib/failure-types.ts failureSummary). The runs dataset has it on every run. */
export type FailureSummary = { failed: number; total: number; parties: Record<string, number>; groups: Record<string, number> };
type LooseMeta = { scores: Record<string, MetaStage>; failure_summary?: FailureSummary };

const metaCache = new Map<string, Promise<LooseMeta[]>>();
/** One promise per set of runs, so React's use() can read it across renders. */
export function loadMetas(keys: string[]) {
  const id = keys.join("|");
  let p = metaCache.get(id);
  if (!p) {
    // Start the fetches after render: getMeta reports to the top loader, which must not update while Home renders.
    p = Promise.resolve().then(() => Promise.all(keys.map((k) => getLandingMeta(k) as unknown as Promise<LooseMeta>)));
    metaCache.set(id, p);
  }
  return p;
}

export const stagesOf = (m: LooseMeta) =>
  Object.keys(m.scores)
    .sort((a, b) => Number(a) - Number(b))
    .map((k) => m.scores[k]);

// Failure groups, as in research_notes/failure-nomenclature.md. Runs graded before the rename carry old labels with
// no group; each maps to exactly one new group.
export const GROUPS = [
  { party: "Builder", group: "Missing knowledge (rule recall)", term: "Rule recall", color: "var(--f-recall)" },
  { party: "Builder", group: "Build spec failure", term: "Build spec failure", color: "var(--f-spec)" },
  { party: "Agent", group: "Wrong end state (database check)", term: "Database check", color: "var(--f-state)" },
  { party: "Agent", group: "Missing customer info (customer recall)", term: "Customer facts recall", color: "var(--f-customer)" },
  { party: "Agent", group: "Agent crash", term: "Agent crash", color: "var(--f-crash)" },
] as const;
export type FailureGroup = (typeof GROUPS)[number]["group"];
const PART: Record<string, [string, string]> = {
  llm_wiki: ["notes", "LLM wiki"],
  sparse_retrieval: ["keyword search", "BM25"],
  dense_retrieval: ["vector search", "embeddings"],
};
/** "llm_wiki+sparse_retrieval" → ["notes + keyword search", "LLM wiki + BM25"]. */
export function archName(cls: string): [string, string] {
  const parts = cls.split("+");
  return [parts.map((p) => PART[p]?.[0] ?? p).join(" + "), parts.map((p) => PART[p]?.[1] ?? p).join(" + ")];
}

/** Everything the landing page needs from the catalog, read with use(). */
export async function loadCatalog() {
  const tasks = await listTasks();
  const all = await Promise.all(tasks.map((t) => listJobs(t.id)));
  const byId = Object.fromEntries(tasks.map((t, i) => [t.id, all[i]]));
  const redwood = latestByBuilder(byId[ENV.redwood] ?? []);
  const packs = latestByBuilder(byId[ENV.packs] ?? []);
  const skyway = latestByBuilder(byId[ENV.skyway] ?? []);
  const skywayArchTask = ENV.skywayArch;
  const skywayArch = latestByArchitecture(byId[skywayArchTask] ?? []);
  const builders = new Set([...redwood, ...packs, ...skyway].map((b) => b.model));
  const last = all.flat().map((j) => j.started ?? "").sort().pop() ?? null;
  return {
    tasks,
    redwood,
    packs,
    skyway,
    skywayArch,
    skywayArchTask,
    conversations: countConversations(all),
    builderCount: builders.size,
    last,
    runCount: (id: string) => new Set((byId[id] ?? []).map((j) => j.id.replace(/-(facts|relabel)$/, ""))).size,
  };
}

let catalogPromise: ReturnType<typeof loadCatalog> | null = null;
export const catalog = () => (catalogPromise ??= Promise.resolve().then(loadCatalog));
