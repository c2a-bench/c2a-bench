"""Sum token usage from usage.jsonl and estimate cost per step and model."""
import json
import sys
from collections import defaultdict

# USD per million tokens: (input, cached input, output). Check against OpenAI's pricing page.
PRICES = {
    "gpt-5.6-terra": (2.00, 0.20, 12.00),
    "gpt-5.6-luna": (0.20, 0.02, 1.20),
}

path = sys.argv[1] if len(sys.argv) > 1 else "usage.jsonl"
totals = defaultdict(lambda: defaultdict(int))
for line in open(path):
    row = json.loads(line)
    t = totals[(row["step"], row["model"])]
    t["calls"] += 1
    for k in ("input", "cached", "output"):
        t[k] += row[k]


def cost(model, t):
    if model not in PRICES:
        return None
    pi, pc, po = PRICES[model]
    return ((t["input"] - t["cached"]) * pi + t["cached"] * pc + t["output"] * po) / 1e6


grand = 0.0
print(f"{'step':<50} {'model':<15} {'calls':>6} {'input':>11} {'output':>10} {'cost $':>8}")
for (step, model), t in sorted(totals.items()):
    c = cost(model, t)
    grand += c or 0
    shown = f"{c:8.2f}" if c is not None else "  no price"
    print(f"{step:<50} {model:<15} {t['calls']:>6} {t['input']:>11,} {t['output']:>10,} {shown}")
print(f"{'TOTAL':<50} {'':<15} {'':>6} {'':>11} {'':>10} {grand:8.2f}")
