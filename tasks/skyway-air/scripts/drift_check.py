"""Ask a cheap model whether each generated doc states or shows customer policy it should not.

    python drift_check.py --stage 0 [--sources tools/doc-gen/generated_data/sources] [--limit N] [--dry-run]

Run with EnterpriseRAG's venv (it has the openai package) and LLM_API_KEY set, as for its steps. Planned docs may state
their own sentences (docs_build/stage<N>/manifest.json) and nothing else; background docs may state no customer policy
at all. Keyword checks miss scenes such as staff arranging a hotel after a storm; this catches them.

Answers are cached in docs_build/drift_cache.json by doc text, so a re-run only pays for new or changed docs.
Writes docs_build/stage<N>/drift.json and prints the docs to read. Cost is logged to $USAGE_LOG (default usage.jsonl).
"""
import argparse
import hashlib
import json
import os
import sys
import threading
import time
from erb_paths import SOURCES  # noqa: E402
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_docs import text_of  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "docs_build" / "drift_cache.json"
MODEL = os.environ.get("CHEAP_LLM_MODEL_NAME", "gpt-5.6-luna")
VERSION = "drift-v1"  # change when the question changes, so old answers are not reused

QUESTION = """You check documents from an airline's internal wiki and Slack for customer-policy content.

Customer-policy content means any of:
- a rule, amount, limit, fee, deadline or eligibility condition for refunds, travel credit, vouchers, compensation,
  goodwill, meals, hotels, ground transport, reimbursements, bag claims, booking changes, cancellations, pets,
  special assistance, unaccompanied minors, loyalty benefits or who may ask for these;
- a scene where staff give, arrange, promise, approve or refuse any of those to a customer (for example booking a hotel
  for stranded passengers, handing out meal vouchers, approving goodwill, refusing a refund);
- a statement that a policy or document is outdated, replaced, wrong or in conflict with another.

{allowed}

Answer with JSON only: {{"drift": true or false, "quote": "the shortest passage that shows it, or empty", "why": "a few words"}}.
"drift" is true only if the document contains customer-policy content beyond what is allowed above.

Document:
{doc}"""
ALLOWED_PLANNED = ("This document is allowed to contain exactly these policy sentences, and situations that do nothing "
                   "more than illustrate them:\n{sentences}\nAnything else that is customer-policy content counts.")
ALLOWED_BACKGROUND = "This document is allowed to contain no customer-policy content at all."
PRICES = {"gpt-5.6-terra": (2.00, 0.20, 12.00), "gpt-5.6-luna": (0.20, 0.02, 1.20)}
_lock = threading.Lock()


def prompt_for(body, sentences):
    allowed = ALLOWED_PLANNED.format(sentences="\n".join(f"- {s}" for s in sentences)) if sentences is not None else ALLOWED_BACKGROUND
    return QUESTION.format(allowed=allowed, doc=body[:12000])


def key_for(prompt):
    return hashlib.sha256((VERSION + MODEL + prompt).encode()).hexdigest()


def ask(client, prompt, usage_log):
    for attempt in range(4):
        try:
            r = client.responses.create(model=MODEL, input=prompt)
            u = getattr(r, "usage", None)
            if u is not None:
                with _lock, open(usage_log, "a") as f:
                    cached = getattr(getattr(u, "input_tokens_details", None), "cached_tokens", 0) or 0
                    f.write(json.dumps({"ts": time.time(), "step": "drift_check", "model": MODEL, "input": u.input_tokens,
                                        "cached": cached, "output": u.output_tokens}) + "\n")
            text = r.output_text.strip()
            text = text[text.find("{"): text.rfind("}") + 1]
            ans = json.loads(text)
            return {"drift": bool(ans.get("drift")), "quote": str(ans.get("quote", ""))[:300], "why": str(ans.get("why", ""))[:120]}
        except Exception as e:  # rate limit, timeout or a malformed answer: wait and try again
            last = e
            time.sleep(2 * (attempt + 1))
    return {"drift": None, "quote": "", "why": f"no answer: {last}"[:200]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", type=int, required=True)
    ap.add_argument("--sources", default=str(SOURCES))
    ap.add_argument("--limit", type=int, default=None, help="only this many docs (to try it)")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--dry-run", action="store_true", help="print one prompt and the number of docs; call nothing")
    args = ap.parse_args()
    out = ROOT / "docs_build" / f"stage{args.stage}"
    manifest = json.loads((out / "manifest.json").read_text())["docs"]
    sources = Path(args.sources)

    jobs = []
    for f in sorted(sources.rglob("*.json")):
        path = "sources/" + str(f.relative_to(sources))
        try:
            body = text_of(json.loads(f.read_text()))
        except json.JSONDecodeError:
            continue
        sentences = manifest[path]["must_contain"] if path in manifest else None
        jobs.append((path, prompt_for(body, sentences)))
    if args.limit:
        jobs = jobs[: args.limit]
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    todo = [(p, q) for p, q in jobs if key_for(q) not in cache]
    est = sum(len(q) for _, q in todo) / 4 / 1e6 * PRICES[MODEL][0] + len(todo) * 60 / 1e6 * PRICES[MODEL][2]
    print(f"{len(jobs)} docs, {len(jobs) - len(todo)} already answered, {len(todo)} to ask {MODEL} (about ${est:.2f})")
    if args.dry_run:
        if jobs:
            print("\n--- example prompt ---\n" + jobs[0][1][:2500])
        return

    from openai import OpenAI
    client = OpenAI(api_key=os.environ.get("LLM_API_KEY") or os.environ["OPENAI_API_KEY"])
    usage_log = os.environ.get("USAGE_LOG", "usage.jsonl")
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(ask, client, q, usage_log): (p, q) for p, q in todo}
        for fut in as_completed(futures):
            p, q = futures[fut]
            cache[key_for(q)] = fut.result()
            done += 1
            if done % 100 == 0:
                CACHE.write_text(json.dumps(cache) + "\n")
                print(f"  {done}/{len(todo)}")
    CACHE.write_text(json.dumps(cache) + "\n")

    results = {p: dict(cache[key_for(q)], planned=p in manifest) for p, q in jobs}
    (out / "drift.json").write_text(json.dumps(results, indent=2) + "\n")
    flagged = {p: r for p, r in results.items() if r["drift"]}
    unanswered = [p for p, r in results.items() if r["drift"] is None]
    print(f"stage {args.stage}: {len(flagged)} docs to read ({sum(r['planned'] for r in flagged.values())} planned), "
          f"{len(unanswered)} without an answer")
    for p, r in list(flagged.items())[:40]:
        print(f"  {'PLANNED ' if r['planned'] else ''}{p}\n     {r['why']}: {r['quote'][:160]}")
    print(f"details: {out / 'drift.json'}")


if __name__ == "__main__":
    main()
