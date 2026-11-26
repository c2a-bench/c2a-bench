"""Write plan.json: each ticket's correct calls, from the tickets of every stage. Run after any ticket change.

    python3 scripts/e2e/make_plan.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import server_selftest  # noqa: E402  (booking_for: the booking a ticket is about)

plan = {}
for n in range(6):
    base = ROOT / ("tests" if n == 0 else f"tests/stages/stage{n}")
    for c in json.loads((base / "cases.json").read_text()):
        sup = c["input"]["ticket_id"]
        patch, money = {}, {}
        for path, want in c["expect"].items():
            f, rid, field = path.split(".", 2)
            if f == "tickets":
                patch[field] = want
            else:
                money.setdefault(f + "|" + rid, {})[field] = want
        labels = c["contains"].get(f"tickets.{sup}.labels")
        if labels:
            patch["labels"] = labels
        plan[f"{n}|{sup}"] = {"patch": patch, "money": money, "required": c.get("required_calls", []),
                              "attempt": c.get("require_attempt"), "after": c.get("after"),
                              "booking": server_selftest.booking_for(c)}
(Path(__file__).parent / "plan.json").write_text(json.dumps(plan, indent=1))
print(f"plan.json: {len(plan)} tickets")
