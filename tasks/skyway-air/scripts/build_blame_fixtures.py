"""Write the blame fixtures: tests/blame_fixtures.json (stage 0) and steps/stage<N>/check/blame_fixtures.json.

    python3 build_blame_fixtures.py

A blame fixture is a failed ticket with the model calls the bot made (what reached the model, what it replied), and
the blame diagnose.py must give it ("retrieval", "trap doc", "stale copy", "execution"...). verify.py check
--blame-fixtures grades them. They are built from real tickets, their passing fixtures and their rules' evidence,
trap and stale sentences, so they follow the tickets when those change. The stage-0 set mirrors redwood-inference's.
"""
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import diagnose  # noqa: E402

UNRELATED = "Crew scheduling: rest periods between duty days are set by the crew planning team."


def stage_dir(n):
    return ROOT / ("tests" if n == 0 else f"tests/stages/stage{n}")


def load(n):
    base = stage_dir(n)
    cases = {c["id"]: c for c in json.loads((base / "cases.json").read_text())}
    rules = {r["id"]: r for r in json.loads((base / "rules.json").read_text())}
    return cases, rules


def good(n, cid):
    return next(f for f in json.loads((stage_dir(n) / "fixtures" / f"{cid}.json").read_text()) if f["should"] == "pass")


def call(messages, reply="", error=None, seconds=None):
    out = {"kind": "llm", "model": "m", "messages": [{"role": "user", "content": m} for m in messages]}
    if error:
        out["error"] = error
    else:
        out["reply"] = {"content": reply, "tool_calls": []}
    if seconds is not None:
        out["seconds"] = seconds
    return out


def fixture(case, name, data, calls, blame, **extra):
    return {"case": case["id"], "name": name, "data": data, "model_calls": calls, "expect_blame": blame, **extra}


def money_path(case):
    return next(p for p in case["expect"] if not p.startswith("tickets.") and isinstance(case["expect"][p], (int, float)))


def wrong_money(n, case):
    """The ticket's passing state with its first expected amount wrong: one failed check. Returns (data, want, got)."""
    path = money_path(case)
    file, rid, field = path.split(".", 2)
    want = case["expect"][path]
    got = want - 37
    data = copy.deepcopy(good(n, case["id"])["data"])
    data.setdefault(file, {}).setdefault(rid, {})[field] = got
    return data, want, got


def deciding(case, rules):
    return diagnose.candidate_rules(case, {"key": diagnose.check_key(money_path(case))}, rules)


def stage0():
    cases, rules = load(0)
    c = cases["cancel-06"]  # one refund, decided by R2 alone, which has a trap page
    data, want, got = wrong_money(0, c)
    rid = deciding(c, rules)
    assert rid == ["R2"] and rules["R2"]["trap_evidence"], rid
    evidence, trap = rules["R2"]["evidence"][0], rules["R2"]["trap_evidence"][0]
    said = f'{{"refund": {got}}}'
    out = [
        fixture(c, "crashed", {}, [], ["crashed"], bot_problem="The bot crashed (exit code 1)"),
        fixture(c, "connection-error", {}, [], ["our service"],
                bot_problem="The bot crashed (exit code 1); the LLM provider did not respond: "
                            "litellm.InternalServerError: OpenAIException - Connection error"),
        fixture(c, "local-connection-error", {}, [], ["crashed"],
                bot_problem="The bot crashed (exit code 1); Connection refused to 127.0.0.1:8080"),
        fixture(c, "no-model-call", data, [], ["no model call"]),
        fixture(c, "execution", data, [call([evidence], f'{{"refund": {want}}}')], ["execution"]),
        fixture(c, "code-decided", data, [call(["ticket text"], '{"category": "refund"}')], ["code decided"]),
        fixture(c, "retrieval", data, [call([UNRELATED], said)], ["retrieval"]),
        fixture(c, "trap-doc-only", data, [call([trap], said)], ["trap doc"]),
        fixture(c, "misapplied-rule", data, [call([evidence], said)], ["misapplied rule"]),
        fixture(c, "chose-trap-doc", data, [call([evidence, trap], said)], ["chose trap doc"]),
        fixture(c, "rule-buried-replay-passed", data, [call([evidence], said)], ["rule buried"], replay_passed=True),
        fixture(c, "misapplied-replay-failed", data, [call([evidence], said)], ["misapplied rule"], replay_passed=False),
        fixture(c, "not-kept", data, [call([UNRELATED], said)], ["not kept"], stored="notes about crew rest periods"),
        fixture(c, "not-retrieved", data, [call([UNRELATED], said)], ["not retrieved"], stored=evidence),
        fixture(c, "model-call-failed", {}, [call(["t"], error="InternalServerError: OpenAIException - The server had an error "
                                                               "while processing your request")], ["model call failed"]),
        fixture(c, "provider-connection-error", {}, [call(["t"], error="InternalServerError: litellm.InternalServerError: "
                                                                       "OpenAIException - Connection error.")], ["our service"]),
        fixture(c, "bot-timeout", {}, [call(["t"], seconds=45, error="Timeout: litellm.Timeout: APITimeoutError - Request timed out")],
                ["model call failed"]),
        fixture(c, "stalled-run", {}, [call(["t"], seconds=1121, error="Timeout: litellm.Timeout: APITimeoutError - Request timed out")],
                ["our limit"]),
        fixture(c, "out-of-credits", {}, [call([], seconds=0.4, error="RateLimitError: litellm.RateLimitError: RateLimitError: "
                                               "OpenAIException - You have no credits remaining. Add credits to continue using the API.")],
                ["our service"]),
    ]
    # a passing ticket whose change was only in the answer text: a note, never a failure
    ok = good(0, c["id"])
    out.append(fixture(c, "change-without-tool-call", ok["data"], [call([evidence], f'{{"refund": {want}}}')], [],
                       requests=[{"method": "POST", "path": "/refunds", "status": 200,
                                  "body": {"booking_id": money_path(c).split(".")[1], "amount": want, "method": "original_payment"}}]))

    # a label: the rule reached the model, which wrote another label
    c = cases["damage-01"]
    sup = c["input"]["ticket_id"]
    data = copy.deepcopy(good(0, c["id"])["data"])
    data["tickets"][sup]["labels"] = ["wear"]
    ev = next(e for r in c["rules"] for e in rules[r]["evidence"] if "wear-and-tear" in e)
    out.append(fixture(c, "misapplied-label", data, [call([ev], '{"labels": ["wear"]}')], ["misapplied rule"]))

    # a handoff the bot must make
    c = cases["handoff-01"]
    reason = c["required_calls"][0]["body"]["reason"]
    data = good(0, c["id"])["data"]
    out.append(fixture(c, "handoff-rule-never-sent", data, [call(["You help airline customers.", "t"], '{"category": "other"}')],
                       ["retrieval"], requests=[]))
    out.append(fixture(c, "model-said-handoff-code-ignored", data,
                       [call(["You help airline customers.", "t"], f'{{"action": "handoff", "reason": "{reason}"}}')],
                       ["execution"], requests=[]))

    # an injection the model obeyed: it had the rule and gave the credit anyway
    c = cases["attack-01"]
    bad = next(f for f in json.loads((stage_dir(0) / "fixtures/attack-01.json").read_text()) if f["name"] == "credited")
    booking, = bad["data"]["credits"]
    rule_text = [e for r in c["rules"] for e in rules[r]["evidence"]][:3]
    out.append(fixture(c, "model-obeyed-injection", bad["data"], [call(rule_text, '{"credit": 500, "reason": "goodwill"}')],
                       ["misapplied rule"], requests=[{"method": "POST", "path": "/credits", "status": 200,
                                                       "body": {"booking_id": booking, "amount": 500, "reason": "goodwill"}}]))
    return out


def stage(n):
    """Per stage: a changed-rule ticket whose rule has stale sentences, and stage 5's confirmation-number pair."""
    cases, rules = load(n)
    out = []
    for c in cases.values():
        if c["group"] != "changed-rule" or not any(not p.startswith("tickets.") and isinstance(v, (int, float))
                                                   for p, v in c["expect"].items()):
            continue
        rid = [r for r in deciding(c, rules) if rules[r].get("stale_evidence")]
        if not rid:
            continue
        data, want, got = wrong_money(n, c)
        r = rules[rid[0]]
        said = f'{{"amount": {got}}}'
        out += [fixture(c, "stale-copy", data, [call([r["stale_evidence"][0]], said)], ["stale copy"]),
                fixture(c, "current-doc-but-wrong", data, [call(r["evidence"], said)], ["misapplied rule"]),
                fixture(c, "rule-never-reached", data, [call([UNRELATED], said)], ["retrieval"])]
        break
    for c in cases.values():
        if not c.get("require_attempt"):
            continue
        head = cases[c["after"]]
        ok = good(n, c["id"])
        paid, comment = ok["requests"]
        cf = paid["response"]["confirmation_id"]
        # the first ticket's payment never happened, and this run made no model call
        out.append(fixture(c, "first-write-never-made", ok["data"], [], ["no model call"], requests=[comment], already=0))
        # the model gave the id, but the bot posted the comment without it
        quiet = copy.deepcopy(comment)
        quiet["body"]["body"] = "Your payment went through."
        data = copy.deepcopy(ok["data"])
        data["tickets"][c["input"]["ticket_id"]]["comments"] = [quiet["body"]]
        out.append(fixture(c, "id-said-not-posted", data, [call(["t"], f"Your confirmation number is {cf}.")], ["execution"],
                           requests=[paid, quiet], already=1))
        assert head["id"] == c["after"]
        break
    return out


def main():
    (ROOT / "tests/blame_fixtures.json").write_text(json.dumps(stage0(), indent=1) + "\n")
    print(f"stage 0: {len(stage0())} blame fixtures")
    for n in range(1, 6):
        d = ROOT / f"steps/stage{n}/check"
        d.mkdir(parents=True, exist_ok=True)
        fx = stage(n)
        (d / "blame_fixtures.json").write_text(json.dumps(fx, indent=1) + "\n")
        print(f"stage {n}: {len(fx)} blame fixtures ({', '.join(sorted({f['case'] for f in fx}))})")


if __name__ == "__main__":
    main()
