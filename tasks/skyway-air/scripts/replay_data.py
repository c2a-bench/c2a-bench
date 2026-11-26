"""Build the replay viewer's JSON for one Harbor job.

python3 tasks/<task>/scripts/replay_data.py <job_dir> <out_dir>

Writes meta.json, tickets.json, code.json and docs.json into out_dir. Everything
is read from the job folder and the task definition; nothing is sent anywhere.
"""

import copy
import fnmatch
import difflib
import glob
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# How a ticket's request log is split into bot runs when the opening-lookups pattern is missing.
READ_VERB = re.compile(r"^(get|list|read|search|fetch|find|look_?up|check|show|view|query|count)(_|$)")


def split_runs(groups, reqs):
    """Split a ticket's request log into its bot runs by matching each run's model tool calls to the requests they
    sent, in order: same kind (a read verb such as get_/list_/search_ for GET, anything else for a write), and a
    word of the tool's name or one of its argument values in the request. A request no tool call matches (a retry,
    a call the bot's code made) stays with the run of the request before it.
    Returns (one request list per run, exact): exact when every request matched a tool call."""
    reqs = [r for r in reqs if r.get("path") != "/customers/_ping"]
    owner, pos = [None] * len(reqs), 0
    for k, g in enumerate(groups):
        for m in g or []:
            for t in ((m.get("reply") or {}).get("tool_calls") or []):
                name = (t.get("name") or "").lower()
                try:
                    args = json.loads(t.get("arguments") or "{}")
                except (TypeError, ValueError):
                    args = {}
                vals = [str(v) for v in (args.values() if isinstance(args, dict) else [])
                        if isinstance(v, (str, int)) and len(str(v)) >= 3]
                words = [w.rstrip("s") for w in re.split(r"[_\W]+", name)[1:] if len(w.rstrip("s")) >= 3]
                write = not READ_VERB.search(name)
                for j in range(pos, min(len(reqs), pos + 6)):
                    r = reqs[j]
                    if (r["method"] != "GET") != write:
                        continue
                    path = r["path"].lower()
                    if any(w in path for w in words) or any(v in path + json.dumps(r.get("body") or "") for v in vals):
                        owner[j] = k
                        pos = j + 1
                        break
    exact = all(o is not None for o in owner)
    cur = 0
    for j, o in enumerate(owner):
        if o is None:
            owner[j] = cur
        else:
            cur = o
    return [[r for r, o in zip(reqs, owner) if o == k] for k in range(len(groups))], exact

# This script lives in tasks/<task>/scripts/ and reads that task's definition.
TASK = Path(__file__).resolve().parents[1]
ROOT = TASK.parents[1]

# Skyway's ticket fields (money, approvals, flight changes and handoffs are their own records: they show as writes)
TRACK = ["category", "labels", "status", "booking_id"]
FIELDS = {  # tests/verify.py FIELD_NAMES, as its failure lines start
    "Category": "category",
    "Labels": "labels",
    "Status": "status",
    "Booking on the ticket": "booking_id",
}
# The bot saying it is holding back: keeping a filing, treating the turn as a follow-up.
RESTRAIN = re.compile(
    r"preserv|same-ticket|follow-up|already (in flight|filed|routed|satisf)|no (duplicate|further) |"
    r"avoid duplicate|re-?triag|leave .* unchanged|public update only|rather than re",
    re.I,
)


TEXTS = {}  # checksum -> text: the docs' and bot files' texts, written once to texts/<2 hex>.json (see write_texts)
_REF = {}  # id(text) -> checksum, so a text shared by many stages is hashed once


def text_ref(t):
    """A short checksum for a text, which is kept in TEXTS; the viewer fetches it from its shard when shown."""
    import hashlib
    if t is None:
        return None
    k = _REF.get(id(t))
    if k is None or TEXTS.get(k) is not t:
        k = hashlib.sha256(t.encode("utf-8", "replace")).hexdigest()[:20]
        TEXTS.setdefault(k, t)
        _REF[id(t)] = k
    return k


def write_texts(out):
    """The texts in 256 shards by the first two characters of their checksum: the viewer loads only the shard of the
    text it shows, not every doc and file of the run (an index bot's run is ~500 MB of text)."""
    shards = {}
    for k, t in TEXTS.items():
        shards.setdefault(k[:2], {})[k] = t
    d = Path(out) / "texts"
    d.mkdir(parents=True, exist_ok=True)
    for name, part in shards.items():
        with open(d / f"{name}.json", "w") as f:
            json.dump(part, f)


DATA_MAX = 2_000_000  # bot files over this are data files: listed with size and checksum, not loaded as text
BINARY_EXT = (".npy", ".npz", ".pkl", ".pickle", ".gz", ".zip", ".bin", ".faiss", ".index", ".parquet", ".db", ".sqlite",
              ".sqlite3", ".pt", ".onnx", ".pyc")
LITE_DIR = None  # set by build(): where the prompt-free copies of each step's results.json are cached


def load_results(path):
    """A step's results.json without the prompts of its model calls ("messages"): nothing here reads them, and they
    are almost all of the file (a bot that sends whole docs writes ~230 MB per stage). The prompt-free copy is cached
    in the output folder, so the full file is parsed once per step, one step at a time."""
    import gc
    path = Path(path)
    lite = (LITE_DIR / ("results-" + "-".join(path.parts[-4:-2]) + ".json")) if LITE_DIR else None
    if lite and lite.exists() and path.exists() and lite.stat().st_mtime >= path.stat().st_mtime:
        return load(lite, []) or []
    rows = load(path, []) or []
    for r in rows:
        if isinstance(r, dict):
            for c in r.get("model_calls") or []:
                if isinstance(c, dict):
                    c.pop("messages", None)
    if lite:
        lite.write_text(json.dumps(rows))
        del rows
        gc.collect()
        return load(lite, []) or []
    return rows


def load(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default



def run_timing(trial):
    """Minutes per step from Harbor's result.json: the builder agent (build) and the verifier (grade)."""
    r = load(Path(trial) / "result.json", {}) or {}
    def mins(block):
        try:
            a = datetime.fromisoformat(str(block["started_at"]).replace("Z", "+00:00"))
            b = datetime.fromisoformat(str(block["finished_at"]).replace("Z", "+00:00"))
            return round((b - a).total_seconds() / 60, 1)
        except (KeyError, TypeError, ValueError):
            return None
    steps = {}
    for i, s in enumerate(r.get("step_results") or []):
        if not isinstance(s, dict):
            continue
        steps[s.get("step_name") or f"stage{i}"] = {"build_min": mins(s.get("agent_execution") or {}),
                                                     "grade_min": mins(s.get("verifier") or {})}
    if not steps:
        return None
    return {"setup_min": mins(r.get("agent_setup") or {}), "total_min": mins(r), "steps": steps}

def _ka_summary(results, subset=None):
    import sys
    root = Path(__file__).resolve().parents[3]
    if str(root / "scripts") not in sys.path:
        sys.path.insert(0, str(root / "scripts"))
    from knowledge_application import summarize_knowledge_application
    return summarize_knowledge_application(results, subset=subset)


def slug(p):
    return os.path.basename(p).replace(".json", "")


def norm(text):
    return " ".join(str(text or "").split())


def word_diff(a, b):
    aw, bw = re.split(r"(\s+)", a), re.split(r"(\s+)", b)
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, aw, bw, autojunk=False).get_opcodes():
        if op == "equal":
            out.append(["=", "".join(aw[i1:i2])])
            continue
        if i2 > i1:
            out.append(["-", "".join(aw[i1:i2])])
        if j2 > j1:
            out.append(["+", "".join(bw[j1:j2])])
    return out


# ---------- "Not decided by the model" lines ----------
# Runs graded before the grader fix list every label and link every rule. Rebuild those lines from the
# saved model replies with the same rule the fixed grader uses: name only the labels the model never said.

def said_corpus(res):
    parts = []
    for c in res.get("model_calls") or []:
        rep = c.get("reply") or {}
        parts.append(str(rep.get("content") or ""))
        parts += [f"{t.get('name')} {t.get('arguments')}" for t in rep.get("tool_calls") or []]
    return " ".join(parts)


def said(text, value):
    return re.search(rf"(?<![A-Za-z0-9-]){re.escape(str(value))}(?![A-Za-z0-9-])", text, re.IGNORECASE) is not None


def modern_failures(res):
    text, out = said_corpus(res), []
    for line in res.get("failures") or []:
        m = re.match(r"Not decided by the model: the bot made the change labels = (.+), but (?:the model never said that value|no model tool call asked for it)$", line)
        if m:
            unsaid = [v.strip() for v in m.group(1).split(",") if v.strip() and not said(text, v.strip())]
            if unsaid:
                line = f"Not decided by the model: the bot's code added {', '.join(unsaid)} to labels, which the model never said"
        if line not in out:
            out.append(line)
    return out


def not_decided_keys(text):
    """Rule check keys for a 'Not decided by the model' line, or None for other lines."""
    m = re.match(r"Not decided by the model: the bot's code added (.+) to labels", text)
    if m:
        return [f"labels:{v.strip()}" for v in m.group(1).split(",")]
    m = re.match(r"Not decided by the model: the bot made the change (\w+) = ", text)
    return [m.group(1)] if m else None


# ---------- fault: us, builder or bot (from the grader's blame) ----------
FAULT_TEXT = {
    # Runs graded by facts (scripts/fact_run.py).
    "fact absent": "A fact this check needs is not in the bot's files (the judge found no trace of it).",
    "missed customer fact": "The bot had the rules but never got a fact only the customer knows that decides this check.",
    "crashed": "The bot crashed or broke the output format.",
    "our limit": "Our time limit or a stalled machine stopped the run.",
    "model call failed": "A model call failed before the bot finished the ticket.",
    "no model call": "The bot never asked its model.",
    "execution": "The model said the right thing, but the bot's code did something else.",
    "code decided": "The builder's code set this value; the model never said it.",
    "no tools": "The builder gave the model no tool, so the bot's code copied values out of the model's text.",
    "retrieval": "The rule never reached the bot's model.",
    "not kept": "The builder never saved this rule in the bot.",
    "not retrieved": "The rule is saved in the bot, but it never reached the model.",
    "trap doc": "Only an outdated or look-alike page reached the model.",
    "stale copy": "The bot used an old version of a page that changed.",
    "rule buried": "The rule was in the prompt, but the bot only followed it once it was stated plainly.",
    "misapplied rule": "The rule reached the model, and it still got it wrong.",
    "chose trap doc": "The right page and a look-alike page both reached the model; it followed the look-alike.",
    "customer fault": "The customer model failed.",
    "our service": "The model provider did not respond.",
    "context overflow": "The prompt grew past the ticket's token cap.",
    "trace lost": "The run's trace was lost on our side.",
    "wrong assertion": "The bot told the customer something wrong or not allowed.",
    "missing assertion": "The bot did not tell the customer something it had to.",
    # Fact-graded runs: the end-state symptom of a check the agent had the facts for (scripts/failure_types.py).
    "wrong value": "A field has the wrong value.",
    "missing value": "A field the ticket requires was left empty.",
    "missing label": "A label the ticket requires is absent.",
    "extra label": "A label the docs do not give this ticket was added.",
    "forbidden action": "A forbidden call was made, or a call was repeated past its limit.",
    "missing required action": "A call the ticket requires was not made.",
    "protected state changed": "A record that had to stay untouched was modified.",
    "runner crashed": "Our verifier crashed.",
}
FAULT_SIDE = {"our limit": "us", "customer fault": "us", "our service": "us", "runner crashed": "us", "trace lost": "us", "not kept": "builder", "no tools": "builder", "fact absent": "builder",
              "missed customer fact": "bot",
              "code decided": "builder"}
# Older runs saved "code decided" as the bot's fault; it is the builder's.
FORCED_SIDE = {"code decided": "builder"}
# Most specific reason first; "no tools" only when nothing else explains it.
FAULT_ORDER = ["crashed", "model call failed", "context overflow", "trace lost", "our service", "our limit", "customer fault", "execution",
               "stale copy", "chose trap doc", "trap doc", "not kept", "fact absent", "not retrieved", "retrieval", "rule buried", "missed customer fact",
               "misapplied rule", "runner crashed", "wrong value", "missing value", "missing label", "extra label",
               "forbidden action", "missing required action", "protected state changed",
               "wrong assertion", "missing assertion", "code decided", "no model call", "no tools"]


def pick_fault(blames):
    for label in FAULT_ORDER:
        for b in blames:
            if b.get("blame") == label:
                side = "us" if b.get("side") == "harness" else b.get("side")  # fact-graded runs say "harness"
                return {"side": FORCED_SIDE.get(label) or side or FAULT_SIDE.get(label, "bot"), "label": label,
                        "text": FAULT_TEXT.get(label, label), "detail": (b.get("detail") or "").replace("; see bot_stderr_tail in results.json", ""),
                        "taxonomy": b.get("taxonomy")}
    return None


# ---------- task definition ----------

def stage_file(stage, name):
    return TASK / "tests" / name if stage == 0 else TASK / "tests/stages" / f"stage{stage}" / name


def rules_for(stage):
    return {r["id"]: r for r in load(stage_file(stage, "rules.json"), [])}


def cases_for(stage):
    return {c["id"]: c for c in load(stage_file(stage, "cases.json"), [])}


def update_dir(stage):
    return TASK / "steps" / f"stage{stage}" / "workdir" / f"stage{stage}_update"


def doc_entry(raw, rel):
    fields = raw.get("content_field_names")
    if isinstance(fields, str):
        try:
            fields = json.loads(fields.replace("'", '"'))
        except ValueError:
            fields = None
    text = "\n\n".join(str(raw.get(f) or "") for f in (fields or ["body", "content", "messages", "thread"]) if raw.get(f))
    title = raw.get("title") or (f"#{raw['channel']}" if raw.get("channel") else slug(rel))
    return {
        "title": title,
        "status": raw.get("status") or ("slack thread" if "/slack/" in rel else ""),
        "updated": raw.get("last_updated") or raw.get("created_at") or "",
        "author": raw.get("author", ""),
        "text": text,
        "source": "slack" if "/slack/" in rel else "confluence",
        "born": 0,
        "edited": None,
    }


def doc_snapshots(stages):
    """Docs as the builder saw them in each stage: the originals plus each stage's changes.json."""
    current = {}
    base = TASK / "environment/app/docs"
    for p in glob.glob(str(base / "**/*.json"), recursive=True):
        rel = "docs/" + os.path.relpath(p, base)
        current[rel] = doc_entry(load(p, {}), rel)
    # Each stage's snapshot shares the entries of docs it did not change with the earlier stages (entries are only
    # read after this), and a doc a stage changes gets a new entry: one copy of ~10,000 docs, not one per stage.
    snaps, changes = {0: dict(current)}, {}
    for s in stages[1:]:
        up = update_dir(s)
        changes[s] = (load(up / "changes.json", {}) or {}).get("changes", [])
        for c in changes[s]:
            for patch in c.get("patches", []):
                if patch["doc"] in current:
                    e = dict(current[patch["doc"]])
                    e["text"] = e["text"].replace(patch["find"], patch["replace"])
                    e["edited"] = s
                    current[patch["doc"]] = e
        for p in glob.glob(str(up / "new_docs/**/*.json"), recursive=True):
            rel = "docs/" + os.path.relpath(p, up / "new_docs")
            entry = doc_entry(load(p, {}), rel)
            entry["born"] = s
            current[rel] = entry
        snaps[s] = dict(current)
    return snaps, changes



def _count_list(v):
    if v is None:
        return 0
    if isinstance(v, list):
        return len(v)
    return 0


def latency_from_step(step_dir):
    """How long the bot took, from results.json (every ticket, passed or failed): each model call; each bot run (one
    reply to a customer message: its start-to-end time when the grader recorded it, else the model time of one bot
    process); each ticket (its runs summed). Median, p90 and count of each, in seconds."""
    rows = [r for r in load_results(step_dir / "verifier" / "results.json") if isinstance(r, dict)]
    calls, runs, tickets, wall = [], [], [], False
    for r in rows:
        cs = [c for c in r.get("model_calls") or [] if isinstance(c, dict)]
        calls += [c["seconds"] for c in cs if isinstance(c.get("seconds"), (int, float))]
        if r.get("bot_runs"):
            wall = True
            per = [w["seconds"] for w in r["bot_runs"] if isinstance(w.get("seconds"), (int, float))]
        else:
            by_pid = {}
            for c in cs:
                by_pid[c.get("pid")] = by_pid.get(c.get("pid"), 0) + (c.get("seconds") or 0)
            per = list(by_pid.values())
        runs += per
        if per:
            tickets.append(sum(per))

    def stats(xs):
        if not xs:
            return None
        xs = sorted(xs)
        pick = lambda q: round(xs[min(len(xs) - 1, int(q * (len(xs) - 1) + 0.5))], 2)
        return {"median": pick(0.5), "p90": pick(0.9), "n": len(xs)}

    if not calls and not runs:
        return None
    return {"call": stats(calls), "run": stats(runs), "ticket": stats(tickets),
            "run_kind": "wall" if wall else "model"}


def architecture_from_step(step_dir, tickets_score=None):
    """RQ3: design + checkable stated claims + observed fields used to verify them."""
    step_dir = Path(step_dir)
    arch = load(step_dir / "verifier" / "architecture.json", {}) or {}
    observed_raw = arch.get("observed") if isinstance(arch, dict) else {}
    if not isinstance(observed_raw, dict):
        observed_raw = {}
    self_report = arch.get("self_report") if isinstance(arch, dict) else {}
    if not isinstance(self_report, dict):
        self_report = {}
    subset = arch.get("subset") if isinstance(arch, dict) else {}
    if not isinstance(subset, dict):
        subset = {}

    bot_arch = {}
    for cand in (
        step_dir / "artifacts" / "app" / "bot" / "ARCHITECTURE.json",
        step_dir / "artifacts" / "app" / "workspace" / "ARCHITECTURE.json",
    ):
        loaded = load(cand, None)
        if isinstance(loaded, dict):
            bot_arch = loaded
            break
    design_block = self_report.get("design") if isinstance(self_report.get("design"), dict) else {}

    design = {}
    for key in ("architecture_choice", "how_it_works", "parts", "how_docs_reach_the_model", "memory"):
        val = bot_arch.get(key) if bot_arch.get(key) not in (None, "") else design_block.get(key)
        if val not in (None, ""):
            design[key] = val

    stated = {}
    if bot_arch:
        if bot_arch.get("max_model_calls_per_ticket") is not None:
            stated["max_model_calls_per_ticket"] = bot_arch.get("max_model_calls_per_ticket")
        if "tools" in bot_arch:
            stated["n_tools"] = _count_list(bot_arch.get("tools"))
            tools = bot_arch.get("tools") or []
            if isinstance(tools, list):
                stated["tool_names"] = [
                    (t.get("name") if isinstance(t, dict) else str(t)) for t in tools if t
                ]
        if "prompt_files" in bot_arch:
            stated["n_prompt_files"] = _count_list(bot_arch.get("prompt_files"))
        if "skills" in bot_arch:
            stated["n_skills"] = _count_list(bot_arch.get("skills"))
        if "extra_libraries" in bot_arch:
            stated["n_extra_libraries"] = _count_list(bot_arch.get("extra_libraries"))
        if "human_handoff" in bot_arch:
            stated["human_handoff"] = bool(bot_arch.get("human_handoff"))
        if "writes_files_at_runtime" in bot_arch:
            stated["writes_files_at_runtime"] = bool(bot_arch.get("writes_files_at_runtime"))

    # Observed fields used for RQ3 claim checks + design→Q clustering (not disk size).
    mcp = observed_raw.get("model_calls_per_ticket") or {}
    per_run = observed_raw.get("model_calls_per_run") or {}
    if not per_run:  # cards from before the grader counted bot runs: one run = the calls of one bot process (pid)
        sizes = []
        for r in load_results(step_dir / "verifier" / "results.json"):
            by_pid = {}
            for c in (r.get("model_calls") or []) if isinstance(r, dict) else []:
                by_pid[c.get("pid")] = by_pid.get(c.get("pid"), 0) + 1
            sizes += by_pid.values()
        if sizes:
            per_run = {"avg": round(sum(sizes) / len(sizes), 1), "max": max(sizes)}
    # Backfill from results.json model_calls when architecture card saw stripped traces (avg 0).
    avg = (mcp or {}).get("avg")
    mx = (mcp or {}).get("max")
    if not avg:
        rows = load_results(step_dir / "verifier" / "results.json")
        lens = [len(r.get("model_calls") or []) for r in rows if isinstance(r, dict)]
        if lens and sum(lens) > 0:
            avg = round(sum(lens) / len(lens), 1)
            mx = max(lens)
            if not observed_raw.get("tools_offered_to_model"):
                tools = sorted({
                    t for r in rows if isinstance(r, dict)
                    for c in (r.get("model_calls") or []) if isinstance(c, dict)
                    for t in (c.get("tools") or []) if t
                })
                observed_raw = dict(observed_raw)
                observed_raw["tools_offered_to_model"] = tools
    # Runs graded before sandbox traces were kept have no trace: those fields are unknown, not 0.
    traced = observed_raw.get("traced")
    if traced is None:
        traced = bool(observed_raw.get("all_imports"))
    observed = {
        "traced": traced,
        "embeddings_in_code": observed_raw.get("embeddings_in_code") or [],
        "knowledge_access": observed_raw.get("knowledge_access"),
        "knowledge_access_evidence": observed_raw.get("knowledge_access_evidence") or {},
        "model_calls_avg": avg,
        "model_calls_max": mx,
        "model_calls_per_run_avg": per_run.get("avg"),
        "model_calls_per_run_max": per_run.get("max"),
        "n_tools_offered": _count_list(observed_raw.get("tools_offered_to_model")),
        "tools_offered": observed_raw.get("tools_offered_to_model") or [],
        "embedding_calls": observed_raw.get("embedding_calls"),
        "max_system_prompts_in_one_ticket": observed_raw.get("max_system_prompts_in_one_ticket"),
        "n_bot_data_files_read": _count_list(observed_raw.get("bot_data_files_read")),
        "n_files_written": _count_list(observed_raw.get("files_written")),
        "n_extra_libraries": _count_list(observed_raw.get("extra_libraries")),
        "extra_libraries": observed_raw.get("extra_libraries") or [],
        "handoffs_made": observed_raw.get("handoffs_made"),
    }

    claims = []
    for c in self_report.get("claims") or []:
        if not isinstance(c, dict):
            continue
        claims.append({
            "claim": c.get("claim"),
            "ok": bool(c.get("ok")),
            "said": c.get("said"),
            "saw": c.get("saw"),
        })

    q = {}
    if isinstance(tickets_score, dict):
        if tickets_score.get("passed") is not None:
            q["passed"] = tickets_score.get("passed")
        if tickets_score.get("total") is not None:
            q["total"] = tickets_score.get("total")
        if tickets_score.get("reward") is not None:
            q["reward"] = tickets_score.get("reward")

    return {
        "q": q,
        "design": design,
        "stated": stated,
        "observed": observed,
        "self_report": {
            "given": bool(self_report.get("given")),
            "right": self_report.get("right"),
            "checked": self_report.get("checked"),
        },
        "claims": claims,
        "subset": {
            "rules": subset.get("rules"),
            "kept": subset.get("kept"),
            "reached": subset.get("reached"),
        } if subset else {},
    }


# ---------- job ----------

def trial_dir(job):
    for child in sorted(Path(job).iterdir()):
        if (child / "steps").is_dir():
            return child
    raise SystemExit(f"no trial with steps/ under {job}")


def verified_stages(trial):
    names = sorted((p.name for p in (trial / "steps").iterdir() if re.fullmatch(r"stage\d+", p.name)), key=lambda n: int(n[5:]))
    return [int(n[5:]) for n in names if (trial / "steps" / n / "verifier/results.json").exists()]


def parse_frac(text):
    """Parse '19/32' -> (19, 32)."""
    if not isinstance(text, str) or "/" not in text:
        return 0, 0
    a, b = text.split("/", 1)
    try:
        return int(a.strip()), int(b.strip())
    except ValueError:
        return 0, 0


def evidence_steps(trial):
    """Alternate job layout: steps/build_r0, steps/maintain_r1 with verifier/evidence.json."""
    steps_dir = trial / "steps"
    if not steps_dir.is_dir():
        return []
    out = []
    for p in sorted(steps_dir.iterdir()):
        if not p.is_dir():
            continue
        if not (p / "verifier" / "evidence.json").exists() and not (p / "verifier" / "reward.json").exists():
            continue
        m = re.fullmatch(r"(?:build_r|maintain_r)(\d+)", p.name)
        if not m:
            continue
        out.append((int(m.group(1)), p.name))
    out.sort(key=lambda x: x[0])
    return out


def score_from_evidence(step_dir):
    """Map verifier/evidence.json (+ reward.json) into viewer StageScore numbers."""
    evidence = load(step_dir / "verifier" / "evidence.json", {}) or {}
    reward_file = load(step_dir / "verifier" / "reward.json", {}) or {}
    raw = evidence.get("score") or {}
    reward = raw.get("reward")
    if reward is None:
        reward = reward_file.get("reward")
    passed = int(raw.get("passed") or 0)
    total = int(raw.get("scenarios") or len(evidence.get("cases") or []) or 0)

    by_category = {}
    by_group = {}
    cat_qs = []
    for cat, frac in (raw.get("by_category") or {}).items():
        p, t = parse_frac(frac)
        key = str(cat).replace("-", "_")
        q = (p / t) if t else 0.0
        by_category[key] = {"scenarios": 1, "passed": p, "total": t, "q": q, "frac": frac}
        by_group[key] = {"passed": p, "total": t}
        cat_qs.append(q)

    for purpose, frac in (raw.get("by_purpose") or {}).items():
        p, t = parse_frac(frac)
        by_group[str(purpose)] = {"passed": p, "total": t}

    by_rule = {}
    for rid, frac in (raw.get("by_rule") or {}).items():
        p, t = parse_frac(frac)
        by_rule[rid] = {"passed": p, "total": t, "q": (p / t) if t else 0.0, "frac": frac}

    by_purpose = {}
    for purpose, frac in (raw.get("by_purpose") or {}).items():
        p, t = parse_frac(frac)
        by_purpose[purpose] = {"passed": p, "total": t, "q": (p / t) if t else 0.0, "frac": frac}

    q_coverage = (passed / total) if total else (sum(cat_qs) / len(cat_qs) if cat_qs else 0.0)

    out = {
        "passed": passed,
        "total": total,
        "reward": reward,
        "situations": raw.get("situations"),
        "unscored_total": raw.get("unscored_total"),
        "terminations": raw.get("terminations") or {},
        "by_group": by_group,
        "by_rule": by_rule,
        "by_purpose": by_purpose,
        "step": evidence.get("step") or step_dir.name,
        "release": evidence.get("release"),
        "behavior_coverage": {
            "q_coverage": q_coverage,
            "weights": "passed_over_scenarios",
            "n_scenarios": total,
            "by_category": by_category,
            "by_scenario": [
                {
                    "scenario": "_",
                    "category": cat,
                    "q": row["q"],
                    "passed": row["passed"],
                    "total": row["total"],
                }
                for cat, row in sorted(by_category.items())
            ],
        },
        "cases": [
            {"id": c.get("id"), "passed": bool(c.get("passed")), "termination": c.get("termination")}
            for c in (evidence.get("cases") or [])
            if isinstance(c, dict)
        ],
        "unscored_failed": raw.get("unscored_failed") or [],
    }
    return out


def build_from_evidence(job, out, trial, steps):
    """Build viewer JSON for evidence.json jobs (build_r0 / maintain_r*)."""
    stages = [n for n, _ in steps]
    scores = {}
    for n, name in steps:
        scores[n] = score_from_evidence(trial / "steps" / name)
        scores[n]["architecture"] = architecture_from_step(trial / "steps" / name, scores[n])

    cfg = load(Path(job) / "config.json", {}) or load(trial / "config.json", {}) or {}
    agent = cfg.get("agent") or {}
    if not isinstance(agent, dict):
        agent = {}
    # Harbor-style config sometimes nests under agents[]
    if not agent and isinstance(cfg.get("agents"), list) and cfg["agents"]:
        agent = cfg["agents"][0] or {}

    meta = {
        "job": Path(job).name,
        "trial": trial.name,
        "timing": run_timing(trial),
        "stages": stages,
        "scores": scores,
        "builder": {"agent": agent.get("name"), "model": agent.get("model_name")},
        "bot": None,
        "built": datetime.now().isoformat(timespec="seconds"),
        "layout": "evidence",
    }
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "meta.json").write_text(json.dumps(meta))
    (out / "tickets.json").write_text(json.dumps([]))
    (out / "passed.json").write_text(json.dumps([]))
    (out / "code.json").write_text(json.dumps({"stages": [], "transitions": []}))
    (out / "docs.json").write_text(json.dumps({}))
    print(f"{meta['job']}: evidence steps {[n for _, n in steps]}, scores {stages} -> {out}")


def builder_summary(trial, stage):
    t = load(trial / "steps" / f"stage{stage}" / "agent/trajectory.json", {})
    steps = t.get("steps") or []
    said = [norm(s.get("message")) and str(s.get("message")).strip() for s in steps if s.get("source") == "agent" and str(s.get("message") or "").strip()]
    times = [datetime.fromisoformat(s["timestamp"].replace("Z", "+00:00")) for s in steps if s.get("timestamp")]
    return {
        "final": said[-1] if said else "",
        "seconds": (times[-1] - times[0]).total_seconds() if len(times) > 1 else 0,
        "cost": (t.get("final_metrics") or {}).get("total_cost_usd"),
        "model": ((t.get("agent") or {}).get("model_name")),
    }


def plan_of(call):
    try:
        j = json.loads((call.get("reply") or {}).get("content") or "")
        return j if isinstance(j, dict) else None
    except (ValueError, TypeError):
        return None


def broke_rule(res, rid):
    if not res or res.get("passed"):
        return False
    return any(rid in (b.get("rules") or []) and b.get("blame") != "no tools" for b in res.get("blame") or [])


def build(job, out):
    global LITE_DIR
    LITE_DIR = Path(out) / "lite"
    LITE_DIR.mkdir(parents=True, exist_ok=True)
    trial = trial_dir(job)
    stages = verified_stages(trial)
    if not stages:
        ev = evidence_steps(trial)
        if ev:
            return build_from_evidence(job, out, trial, ev)
    R = {s: rules_for(s) for s in stages}
    C = {s: cases_for(s) for s in stages}
    RES = {s: {c["id"]: c for c in load_results(trial / "steps" / f"stage{s}" / "verifier/results.json")} for s in stages}
    snaps, changes = doc_snapshots(stages)
    seed = load(TASK / "tests/seed/tickets.json", {})

    def doc_ref(rel, s):
        d = snaps.get(s, {}).get(rel, {})
        return {"path": rel, "title": d.get("title", slug(rel)), "status": d.get("status", ""), "updated": d.get("updated", "")}

    # ---- rule changes per stage ----
    rule_changes = {}
    for i, s in enumerate(stages):
        rule_changes[s] = {}
        if i == 0:
            continue
        prev = stages[i - 1]
        stage_docs = {slug(p["doc"]) for c in changes.get(s, []) for p in c.get("patches", [])}
        stage_docs |= {slug(rel) for rel, d in snaps[s].items() if d["born"] == s}
        for rid, r in R[s].items():
            old = R[prev].get(rid)
            if old and norm(old["rule"]) == norm(r["rule"]):
                continue
            docs = sorted({slug(x) for x in r.get("sources", [])} & stage_docs) or sorted(slug(x) for x in r.get("sources", []))
            words = set(re.findall(r"[a-z]{5,}", (r["rule"] + " " + (old["rule"] if old else "")).lower()))

            def score(c):
                touched = {slug(p["doc"]) for p in c.get("patches", [])}
                cw = set(re.findall(r"[a-z]{5,}", (c.get("id", "").replace("-", " ") + " " + c.get("what", "")).lower()))
                return len(touched & set(docs)) * 10 + len(cw & words)

            src = max(changes.get(s, []), key=score, default={"id": "", "what": ""})
            rule_changes[s][rid] = {
                "kind": "new" if not old else "changed",
                "diff": word_diff(old["rule"], r["rule"]) if old else None,
                "what": src.get("what", ""),
                "changeId": src["id"],
                "docs": docs,
            }

    def rule_view(s, rid):
        r = R[s][rid]
        ch = rule_changes[s].get(rid)
        return {
            "id": rid,
            "status": "starting" if s == stages[0] else (ch["kind"] if ch else "unchanged"),
            "text": r["rule"],
            "diff": ch["diff"] if ch else None,
            "what": ch["what"] if ch else "",
            "sources": [doc_ref(x, s) for x in r.get("sources", [])],
            "traps": [doc_ref(x, s) for x in r.get("decoys", [])],
            "quote": (r.get("evidence") or [""])[0],
            "trapQuote": (r.get("trap_evidence") or [""])[0],
        }

    # ---- tickets ----
    # Each ticket's type against earlier stages (facts.json, scripts/build_facts.py).
    TYPES = {s: {k: v.get("type") for k, v in (load(stage_file(s, "facts.json"), {}) or {}).get("tickets", {}).items()}
             for s in stages}
    tickets, passed_tickets = [], []  # failed and passed tickets: two files, so tickets.json stays failed-only
    for s in stages:
        for cid, res in RES[s].items():
            case = C[s].get(cid, {})
            if not isinstance(case.get("input"), dict):
                continue
            tid, cust = case["input"]["ticket_id"], case["input"]["customer_id"]
            reqs = res.get("requests") or []
            turns = res.get("customer_turns") or []
            nruns = max(0, len(turns) - 1)
            support = [" ".join(t.get("support") or []) for t in turns[1:]]

            # A bot run that opens with these four lookups, in any order (else its model tool calls split the runs).
            ctx = {f"/customers/{cust}", f"/customers/{cust}/tickets", f"/customers/{cust}/bookings", f"/tickets/{tid}"}
            bounds, i = [], 0
            while i < len(reqs):
                win = reqs[i:i + 4]
                if len(win) == 4 and all(r["method"] == "GET" for r in win) and {r["path"] for r in win} == ctx:
                    bounds.append(i)
                    i += 4
                else:
                    i += 1
            exact = len(bounds) == nruns
            if not exact:
                bounds = [0] + [len(reqs)] * max(0, nruns - 1)
            run_reqs = [reqs[b:(bounds[k + 1] if k + 1 < len(bounds) else len(reqs))] for k, b in enumerate(bounds)]

            # Model calls by process, matched to the run whose reply they wrote.
            groups, pid = [], {}
            for m in res.get("model_calls") or []:
                if m.get("pid") not in pid:
                    pid[m.get("pid")] = len(groups)
                    groups.append([])
                groups[pid[m.get("pid")]].append(m)
            if len(groups) > nruns:
                # The bot ran again after the customer's last message; no customer turn records that reply.
                support += [((plan_of(g[-1]) or {}).get("reply")) or "" for g in groups[nruns:]]
                nruns = len(groups)
                if len(bounds) != nruns:
                    exact = False
            by_run, cur = [None] * nruns, 0
            for g in groups:
                said = norm(((plan_of(g[-1]) or {}).get("reply")) or "")
                at = next((k for k in range(cur, nruns) if by_run[k] is None and said and norm(support[k]) == said), None)
                if at is None:
                    at = next((k for k in range(cur, nruns) if by_run[k] is None), None)
                if at is None:
                    continue
                by_run[at] = g
                cur = at + 1
            if not exact and nruns:
                # Bots that open a run with their own lookups (not the four above): match each run's model tool
                # calls to the requests they sent.
                run_reqs, exact = split_runs(by_run, reqs)

            state = copy.deepcopy(seed.get(tid, {}))
            for rid_, fields in (case.get("before") or {}).get("tickets", {}).items():
                if rid_ == tid:
                    state.update(fields)
            start = {k: copy.deepcopy(state.get(k)) for k in TRACK}
            runs = []
            for k in range(nruns):
                rq = run_reqs[k] if k < len(run_reqs) else []
                before = {x: copy.deepcopy(state.get(x)) for x in TRACK}
                looks = []
                for r in rq:
                    if r["method"] == "GET" and r["path"] != "/customers/_ping" and r["path"] not in looks:
                        looks.append(r["path"])
                writes = []
                for r in rq:
                    if r["method"] == "GET":
                        continue
                    if r["method"] == "PATCH" and r["path"] == f"/tickets/{tid}" and r["status"] < 300:
                        state.update(r.get("body") or {})
                    resp = r.get("response")
                    writes.append({"method": r["method"], "path": r["path"], "body": r.get("body"), "status": r["status"],
                                   "attempt": resp.get("attempt_id") if isinstance(resp, dict) else None})
                after = {x: copy.deepcopy(state.get(x)) for x in TRACK}
                calls = []
                for m in by_run[k] or []:
                    p = plan_of(m) or {}
                    calls.append({"seconds": m.get("seconds"), "tokens": m.get("prompt_tokens"), "error": m.get("error"),
                                  "reasoning": p.get("reasoning", ""), "raw": None if p else str((m.get("reply") or {}).get("content") or "")[:2000],
                                  "actions": [{"tool": a.get("tool"), "args": a.get("arguments")} for a in p.get("actions", [])],
                                  "toolCalls": (m.get("reply") or {}).get("tool_calls") or []})
                runs.append({"n": k + 1, "lookups": looks, "calls": calls, "writes": writes, "reply": support[k],
                             "changes": [{"field": x, "from": before[x], "to": after[x]} for x in TRACK if before[x] != after[x]]})

            # Which broken rule; which rule change the bot cited while holding back.
            broken = {}
            for b in res.get("blame") or []:
                if b.get("blame") == "no tools":
                    continue
                for rid in b.get("rules") or []:
                    broken.setdefault(rid, set()).add(b.get("blame"))
            blocked = []
            for rid, ch in rule_changes[s].items():
                if rid in broken:
                    continue
                held = []
                for k, run in enumerate(runs):
                    if k == 0:
                        continue
                    for call in run["calls"]:
                        if any(a.get("tool") == "patch_ticket" for a in call["actions"]):
                            continue
                        for sent in re.split(r"(?<=[.;])\s+", call["reasoning"]):
                            if any(d in sent for d in ch["docs"]) and RESTRAIN.search(sent):
                                held.append((run["n"], sent))
                                break
                if held:
                    blocked.append({"rule": rid, "status": ch["kind"], "turns": sorted({h[0] for h in held}), "quote": held[0][1][:300],
                                    "confidence": 0.85 if len(held) >= 2 else 0.6,
                                    "why": f"On turn{'s' if len(held) > 1 else ''} {', '.join(str(h[0]) for h in held)} the bot gave {rid}'s page ({ch['docs'][0]}) as its reason to leave the ticket unchanged."})
            held_turns = sorted({t for b in blocked for t in b["turns"]})
            reasoning = " ".join(c["reasoning"] for r in runs for c in r["calls"])

            def reason(rid, kinds):
                # A run graded by facts (scripts/fact_run.py): what the judge found for this rule in the bot's files.
                judged = [f for f in (res.get("facts") or {}).get("rule_facts", []) if f["id"] == rid or f["id"].startswith(rid + ".")]
                if judged:
                    bad = next((f for f in judged if f["label"] == "wrong"), None)
                    if bad:
                        return f"The bot's files have {rid} wrong: “{bad['quote'][:200]}”.", True
                    if any(f["label"] == "absent" for f in judged):
                        return f"{rid} is not in the bot's files (the judge found no trace of it).", True
                    return f"The bot had {rid} (the judge found it in its files) and applied it wrongly.", True
                if rid in rule_changes[s]:
                    return f"{rid} {'is new' if rule_changes[s][rid]['kind'] == 'new' else 'changed'} in this stage and the bot got it wrong.", True
                if blocked:
                    return "The bot knew this rule, but a rule change got in the way (see below).", True
                if "chose trap doc" in kinds:
                    traps = R[s][rid].get("decoys", [])
                    cited = [doc_ref(x, s)["title"] for x in traps if slug(x) in reasoning]
                    if cited:
                        return f"Followed a trap page: “{cited[0]}”.", True
                    names = ", ".join(f"“{doc_ref(x, s)['title']}”" for x in traps)
                    return f"The verifier says the bot followed a trap page ({names}), but the bot never named it.", False
                earlier = [p for p in stages if p < s and cid in RES[p] and rid in C[p].get(cid, {}).get("rules", [])]
                if earlier and not broke_rule(RES[earlier[0]][cid], rid):
                    first = next((p for p in stages if earlier[0] < p <= s and broke_rule(RES[p].get(cid), rid)), s)
                    return f"Got {rid} right in stage {earlier[0]} and broke it in stage {first} with no rule change. Likely the builder's own stage {first} edit.", False
                return f"The bot had {rid} and applied it wrongly.", True

            failures = []
            for line in modern_failures(res):
                text = re.sub(r" on SUP-\d+", "", line)
                field = next((v for k, v in FIELDS.items() if text.startswith(k)), None)
                kind = "field" if field else "forbidden" if text.startswith("Forbidden") else "missing"
                rr, mine = [], []
                keys = not_decided_keys(text)
                for b in res.get("blame") or []:
                    chk = b["check"].split(":")[0]
                    hit = (field and chk == field) or (not field and chk.split(" ")[-1].split("/")[1:2] and chk.split(" ")[-1].split("/")[1] in text)
                    if keys is not None:
                        hit = b["check"] in keys or chk in {k.split(":")[0] for k in keys}
                    if b.get("check") == "all":
                        hit = True
                    if not hit:
                        continue
                    mine.append(b)
                    if b.get("blame") != "no tools":
                        rr += [r for r in b.get("rules") or [] if r not in rr]
                if keys is not None:  # link only the rule that covers that label or field
                    rr = [rid for rid in case.get("rules", []) if any(
                        fnmatch.fnmatchcase(k, c) or fnmatch.fnmatchcase(c, k) for k in keys for c in R[s].get(rid, {}).get("checks", []))]
                rr = rr or sorted(broken)
                turn, note = None, ""
                if kind == "forbidden":
                    m = re.search(r"\((POST|PATCH) ([^\s,)]+)", text)
                    for run in runs:
                        if m and any(w["method"] == m.group(1) and re.fullmatch(m.group(2).replace("*", "[^/]+"), w["path"]) for w in run["writes"]):
                            turn, note = run["n"], "The bot did this here."
                            break
                elif kind == "field":
                    last = max((r["n"] for r in runs if any(c["field"] == field for c in r["changes"])), default=None)
                    later = [t for t in held_turns if last is None or t > last]
                    if later:
                        turn, note = later[0], "The bot should have fixed this here but held back."
                    elif last:
                        turn, note = last, "The bot set it here."
                if turn is None:
                    if held_turns:
                        turn, note = held_turns[0], "The bot should have done it here but held back."
                    else:
                        turn, note = "end", "Never done by the end of the conversation."
                rules_here = []
                for rid in rr:
                    why, sure = reason(rid, broken.get(rid, set()))
                    rules_here.append({**rule_view(s, rid), "why": why, "sure": sure})
                failures.append({"line": text, "kind": kind, "field": field, "turn": turn, "note": note, "rules": rules_here,
                                 "fault": pick_fault(mine) or pick_fault(res.get("blame") or []),
                                 "blockedBy": [b for b in blocked if turn in b["turns"]] if turn != "end" else []})

            sides = sorted({(f["fault"] or {}).get("side") for f in failures} - {None})
            (passed_tickets if res.get("passed") else tickets).append({
                "passed": bool(res.get("passed")), "sides": sides, "oursOnly": not res.get("passed") and (bool(res.get("customer_fault")) or sides == ["us"]),
                "key": f"{s}:{cid}", "stage": s, "id": cid, "title": case.get("title", ""), "test": case.get("test", ""),
                "matters": case.get("matters", ""), "brief": case.get("customer", ""), "facts": case.get("facts", []),
                "ticket": tid, "customerId": cust, "group": res.get("group"),
                "scenario": case.get("scenario") or res.get("scenario"),
                "category": case.get("category") or res.get("category") or res.get("group"),
                "realization": case.get("realization") or res.get("realization"),
                "behavior": case.get("behavior") or res.get("behavior"),
                "replay": res.get("replay"), "replayVerdict": res.get("replay_verdict"), "infoType": case.get("info_type"),
                "factCheck": res.get("facts"),
                "ticketType": TYPES[s].get(cid),
                "start": start, "end": {k: state.get(k) for k in TRACK},
                "messages": [t["reply"] for t in turns if t.get("reply")], "runs": runs, "failures": failures,
                "blocked": blocked, "crash": res.get("bot_problem") or "", "turnsExact": exact,
                "changeSources": res.get("change_sources") or [],
                # Every blame record (one per failed check), so charts and filters see all of them, not one per failure line.
                "blames": [{"label": b.get("blame"), "side": b.get("side"), "type": (b.get("taxonomy") or {}).get("type"),
                            "party": (b.get("taxonomy") or {}).get("party"), "group": (b.get("taxonomy") or {}).get("group")}
                           for b in res.get("blame") or [] if b.get("blame")],
            })

    # ---- bot code ----
    texts = {}  # each distinct file text once: most of a bot's files are the same in every stage
    # Data files (an index's corpus, embedding vectors, a pickled graph: over DATA_MAX or binary) are listed with their
    # size and a checksum, not read as text: an index bot holds ~200 MB of them per stage, which as text took GBs.
    data_files = {}

    def bot_files(s):
        import hashlib
        base = trial / "steps" / f"stage{s}" / "artifacts/app/bot"
        out_, data_ = {}, {}
        for p in sorted(glob.glob(str(base / "**/*"), recursive=True)):
            if not os.path.isfile(p):
                continue
            rel = os.path.relpath(p, base)
            if rel in (".gitkeep", "UPSTREAM_LICENSE"):
                continue
            size = os.path.getsize(p)
            with open(p, "rb") as fh:
                head = fh.read(8192)
            # knowledge.json is read whatever its size: the knowledge list and its changes come from it.
            big = size > DATA_MAX and rel != "knowledge.json"
            if big or rel.lower().endswith(BINARY_EXT) or b"\0" in head:
                h = hashlib.sha256()
                with open(p, "rb") as fh:
                    for block in iter(lambda: fh.read(1 << 20), b""):
                        h.update(block)
                data_[rel] = {"size": size, "sha": h.hexdigest()[:16]}
                continue
            t = Path(p).read_text(encoding="utf-8", errors="replace")
            out_[rel] = texts.setdefault(t, t)
        data_files[s] = data_
        return out_

    def role(p):
        if p.startswith("tests/"):
            return "test"
        if p.startswith("prompts/"):
            return "prompt"
        if "knowledge" in p:
            return "knowledge"
        if p in ("README.md", "ARCHITECTURE.json"):
            return "doc"
        return "code"

    def knowledge(files):
        try:
            k = json.loads(files.get("knowledge.json", "[]"))
        except ValueError:
            return {}
        if not isinstance(k, list):
            return {}
        return {str(e.get("id") or i): e for i, e in enumerate(k) if isinstance(e, dict)}

    F = {s: bot_files(s) for s in stages}
    K = {s: knowledge(F[s]) for s in stages}
    def stage_score(s):
        step = f"stage{s}"
        raw = load(trial / "steps" / step / "verifier/scores.json", {}) or {}
        out = dict(raw.get("tickets") or {})
        out["step"] = step
        # Ticket types against earlier stages (scripts/build_facts.py): discovery (a new ticket), regression (an
        # earlier ticket with the same pass criteria), adaptability (an earlier ticket whose pass criteria changed).
        kinds = {}
        for r in load_results(trial / "steps" / step / "verifier/results.json"):
            kind = TYPES[s].get(r.get("id"))
            if kind:
                row = kinds.setdefault(kind, {"passed": 0, "total": 0})
                row["total"] += 1
                row["passed"] += bool(r.get("passed"))
        if kinds:
            out["ticket_types"] = kinds
        try:
            out["reward"] = float((trial / "steps" / step / "verifier/reward.txt").read_text().strip())
        except (OSError, ValueError):
            if out.get("total"):
                out["reward"] = out.get("passed", 0) / out["total"]
        if raw.get("by_group"):
            out["by_group"] = raw["by_group"]
        if raw.get("behavior_coverage"):
            out["behavior_coverage"] = raw["behavior_coverage"]
        if raw.get("realization_robustness"):
            out["realization_robustness"] = raw["realization_robustness"]
        if raw.get("behavior_attribution"):
            out["behavior_attribution"] = raw["behavior_attribution"]
        if raw.get("subset"):
            out["subset"] = raw["subset"]
        if raw.get("knowledge_application"):
            out["knowledge_application"] = raw["knowledge_application"]
        else:
            # Derive from results when scores.json predates the RQ2 block.
            rows = load_results(trial / "steps" / step / "verifier/results.json")
            out["knowledge_application"] = _ka_summary(rows, raw.get("subset"))
        if raw.get("failure_taxonomy"):
            out["failure_taxonomy"] = raw["failure_taxonomy"]
        if raw.get("agent_correction"):
            out["agent_correction"] = raw["agent_correction"]
        # Doc recall: from the grader when it had the docs, else from scripts/doc_recall_report.py.
        docs = raw.get("docs") or load(trial / "steps" / step / "verifier" / "docs_recall.json", None)
        if docs and docs.get("tickets"):
            out["docs"] = docs
        # Info types and twin pairs, and why failed tickets failed (replay verdicts): from the grader.
        # facts: the fact-level numbers of a run graded by scripts/fact_run.py.
        for key in ("info", "replay_verdicts", "cost", "facts"):
            if raw.get(key):
                out[key] = raw[key]
        out["architecture"] = architecture_from_step(trial / "steps" / step, out)
        out["latency"] = latency_from_step(trial / "steps" / step)
        return out
    scores = {s: stage_score(s) for s in stages}

    def doc_path_for(entry):
        src = entry.get("source") or ""
        return "docs/" + src if src and not src.startswith("docs/") else src

    code_stages = []
    for s in stages:
        code_stages.append({
            "stage": s, "score": scores[s], "builder": builder_summary(trial, s),
            "files": [{"path": p, "role": role(p), "lines": t.count("\n") + 1, "ref": text_ref(t) if p != "knowledge.json" else None}
                      for p, t in F[s].items()]
                     + [{"path": p, "role": role(p), "lines": 0, "text": None, "data": True, "size": d["size"]}
                        for p, d in data_files[s].items()],
            "knowledge": [{"id": i, "title": e.get("title"), "status": e.get("status"), "updated": e.get("last_updated"),
                           "chars": len(e.get("text", "")), "path": doc_path_for(e)} for i, e in K[s].items()],
        })
    transitions = []
    for i, s in enumerate(stages[1:], 1):
        prev = stages[i - 1]
        touched = {slug(p["doc"]) for c in changes.get(s, []) for p in c.get("patches", [])}
        new_docs = [rel for rel, d in snaps[s].items() if d["born"] == s]
        touched |= {slug(rel) for rel in new_docs}
        slug_rules = {}
        for rid, r in R[s].items():
            for x in r.get("sources", []) + r.get("decoys", []):
                if slug(x) in touched:
                    slug_rules.setdefault(slug(x), set()).add(rid)
        files = []
        for p in sorted(set(F[prev]) | set(F[s])):
            if p == "knowledge.json" or p in data_files[prev] or p in data_files[s]:
                continue  # a file that is a data file in either stage is listed once, below
            a, b = F[prev].get(p), F[s].get(p)
            if a == b:
                continue
            sm = difflib.SequenceMatcher(None, (a or "").split("\n"), (b or "").split("\n"), autojunk=False)
            add = sum(j2 - j1 for op, i1, i2, j1, j2 in sm.get_opcodes() if op in ("insert", "replace"))
            rem = sum(i2 - i1 for op, i1, i2, j1, j2 in sm.get_opcodes() if op in ("delete", "replace"))
            tags = []
            for n, line in enumerate((b or "").split("\n"), 1):
                hit = sorted({r for sl, rs in slug_rules.items() if sl in line for r in rs})
                if hit:
                    tags.append({"line": n, "rules": hit})
            files.append({"path": p, "role": role(p), "status": "new" if a is None else "removed" if b is None else "changed",
                          "add": add, "rem": rem, "old_ref": text_ref(a), "new_ref": text_ref(b), "tags": tags})
        def as_data(st, p):  # a file's entry as a data file; a text file (it crossed the size limit) has no checksum
            if p in data_files[st]:
                return data_files[st][p]
            return {"size": len(F[st][p].encode("utf-8"))} if p in F[st] else None
        for p in sorted(set(data_files[prev]) | set(data_files[s])):
            a, b = as_data(prev, p), as_data(s, p)
            if a and b and a.get("sha") and a.get("sha") == b.get("sha"):
                continue
            files.append({"path": p, "role": role(p), "status": "new" if a is None else "removed" if b is None else "changed",
                          "add": 0, "rem": 0, "old_ref": None, "new_ref": None, "tags": [], "data": True,
                          "size_old": (a or {}).get("size"), "size_new": (b or {}).get("size")})
        know = []
        for kid in sorted(set(K[prev]) | set(K[s])):
            x, y = K[prev].get(kid), K[s].get(kid)
            if x and y and x.get("text") == y.get("text"):
                continue
            e = y or x
            know.append({"id": kid, "title": e.get("title"), "path": doc_path_for(e), "status": "added" if not x else "removed" if not y else "updated"})
        transitions.append({
            "from": prev, "to": s,
            "docChanges": [{"id": c.get("id", ""), "type": c.get("type", ""), "what": c.get("what", ""),
                            "patches": [{"doc": p["doc"], "title": snaps[s].get(p["doc"], {}).get("title", slug(p["doc"])),
                                         "find": p["find"], "replace": p["replace"], "diff": word_diff(p["find"], p["replace"])} for p in c.get("patches", [])]}
                           for c in changes.get(s, [])],
            "newDocs": [{**doc_ref(rel, s), "trap": any(rel in r.get("decoys", []) for r in R[s].values()),
                         "rules": sorted(slug_rules.get(slug(rel), []))} for rel in new_docs],
            "ruleChanges": [{**rule_view(s, rid)} for rid in rule_changes[s]],
            "files": files, "knowledge": know,
        })

    cfg = load(trial / "config.json", {}) or {}
    bot_model = next((m.get("model") for s in stages for c in RES[s].values() for m in c.get("model_calls") or [] if m.get("model")), None)
    meta = {"job": Path(job).name, "trial": trial.name, "timing": run_timing(trial), "stages": stages, "scores": scores,
            "builder": {"agent": (cfg.get("agent") or {}).get("name"), "model": (cfg.get("agent") or {}).get("model_name")},
            "bot": bot_model, "built": datetime.now().isoformat(timespec="seconds")}

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    # json.dump writes piece by piece (the same bytes as json.dumps): docs.json and code.json of a bot that keeps
    # ~10,000 docs are hundreds of MB, too big to build as one string first.
    for name, data in (("meta.json", meta), ("tickets.json", tickets), ("passed.json", passed_tickets),
                       ("code.json", {"stages": code_stages, "transitions": transitions}),
                       ("docs.json", {str(k): {rel: {**{x: y for x, y in e.items() if x != "text"}, "ref": text_ref(e["text"]),
                                                     "chars": len(e["text"])} for rel, e in v.items()}
                                      for k, v in snaps.items()})):
        with open(out / name, "w") as f:
            json.dump(data, f)
    write_texts(out)
    print(f"{meta['job']}: stages {stages}, {len(tickets)} failed tickets -> {out}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    build(sys.argv[1], sys.argv[2])
