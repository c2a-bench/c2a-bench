"""Build stages 1-5 for skyway-air: per-stage rules, planned doc changes, records and tickets.

Run from tasks/skyway-air after build_stage0_tickets.py. Idempotent.

Each stage happens on a later Wednesday. Its records are the earlier records moved forward by whole weeks, so every
"how long ago" (24-hour window, claim deadlines, notice periods) and every weekday stays the same, and only a rule
change can change a ticket's answer. Stage texts that name a date are moved the same way.

A stage changes rules (changes.json: what the docs must say after the change), re-asks earlier tickets
(changed-rule: they use a changed rule; unchanged: they use none) and adds tickets on new rules (new-rule).
Amounts come from the stage-0 rule functions with this stage's values; check_stage() refuses to save a stage that
breaks the review rules.
"""
import copy
import json
import re
import sys
from collections import Counter
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_stage0_tickets as b0  # noqa: E402  (builds the stage-0 tickets on import; does not save)
import rule_keywords  # noqa: E402

TESTS = b0.TESTS
DATES = {0: "2026-05-20T10:00:00Z", 1: "2026-07-01T10:00:00Z", 2: "2026-08-19T10:00:00Z",
         3: "2026-09-02T10:00:00Z", 4: "2026-11-04T10:00:00Z", 5: "2026-12-02T10:00:00Z"}
TARGET = {1: 58, 2: 52, 3: 49, 4: 40, 5: 42}  # redwood-inference's 56/47/45/38/38 plus the many-bookings and decoy-flight tickets
EFFECTIVE = {1: "July 1", 2: "August 15", 3: "September 1", 4: "November 1", 5: "December 1"}
APPLIES = "This applies to every request handled from {}, whatever the date of the flight."
NEW_DOCS = 40  # new docs per stage: rule docs first, background docs make up the rest
APPLIED_THREADS = 3  # Slack threads applying each changed or new rule
CHANGE_LOG = "docs/confluence/policy-and-compliance/change-log/"
TRAP_MARKS = {" (lookalike)": "a lookalike page: same words, a different situation", " (outdated)": "an outdated draft"}
CUSTOMER, API, BOTH = b0.CUSTOMER, b0.API, b0.BOTH
CP, PB, SL = b0.CP, b0.PB, b0.SL

# A wrong version of each rule a later stage adds: a team note from before the policy, so the policy is newer and wins.
WRONG_LATER = {
    "R22": (SL + "support-team/assistance-not-provided-credit-question.json",
            "When booked assistance isn't provided, give $50 goodwill credit."),
    "R23": (SL + "refunds-desk/schedule-change-refund-threshold.json",
            "Customers can cancel for a full refund if the flight moves by 4 hours or more."),
    "R24": (SL + "support-policy-questions/travel-manager-booking-requests.json",
            "Travel managers can only ask about bookings they made themselves."),
    "R25": (SL + "support-team/illness-cancellation-refund-question.json",
            "Illness cancellations get a full refund with a doctor's note."),
    "R26": (SL + "irregular-ops/hotel-taxi-receipts-limit.json", "Taxis to and from the hotel are covered up to $60 per booking."),
    "R27": (SL + "irregular-ops/missed-connection-same-day-rebooking.json",
            "A missed connection is rebooked free only if the next flight leaves the same day."),
    "R28": (SL + "refunds-desk/repeat-claim-follow-up.json",
            "On a follow-up, pay the claim again if the customer says they never got it."),
    "R29": (SL + "support-team/failed-refund-retry-question.json", "If a refund fails, send it again up to three times."),
    "R30": (SL + "refunds-desk/child-seat-fee-age-question.json", "Children under 15 sit with their adult for free."),
    "R31": (PB + "case-handling/unaccompanied-minor-fee-quick-guide.json", "The unaccompanied-minor service costs $125 per flight."),
    "R32": (SL + "support-team/confirmation-number-lookup.json",
            "The confirmation number shows on the ticket when you read it later."),
}


def days(n):
    return (b0.ts(DATES[n]) - b0.ts(DATES[0])).days


assert all(days(n) % 7 == 0 for n in DATES), "stages must be whole weeks apart (weekdays in texts)"

# ---------------------------------------------------------------- moving records and texts in time

ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
MONTH_DAY = re.compile(rf"\b({MONTHS}) (\d{{1,2}})\b")
BARE_MONTH = re.compile(rf"\b({MONTHS})\b(?![ \u00a0]\d)")
# Policy dates (when a rule changed) never move; they are written with a no-break space so shift_text skips them.
POLICY_DATES = ["June 30", "July 1", "August 12", "August 14", "August 15", "September 1", "November 1", "December 1"]


def pin(s):
    for d in POLICY_DATES:
        s = re.sub(rf"\b{d}\b", d.replace(" ", "\u00a0"), s)
    return s


def pin_case(case, keys=("title", "test", "matters", "customer", "facts", "first_goal")):
    for k in keys:
        if isinstance(case.get(k), str):
            case[k] = pin(case[k])
        elif isinstance(case.get(k), list):
            case[k] = [pin(x) for x in case[k]]
    case["input"]["message"] = pin(case["input"]["message"])


def shift(v, d):
    if isinstance(v, dict):
        return {k: shift(x, d) for k, x in v.items()}
    if isinstance(v, list):
        return [shift(x, d) for x in v]
    if isinstance(v, str) and ISO.match(v):
        return (b0.ts(v) + timedelta(days=d)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return v


def shift_text(s, d):
    def one(m):
        when = b0.ts(f"2026-{MONTHS.split('|').index(m.group(1)) + 1:02d}-{int(m.group(2)):02d}T12:00:00Z") + timedelta(days=d)
        return f"{when.strftime('%B')} {when.day}"
    return MONTH_DAY.sub(one, s) if d else s


TEXT_KEYS = ("title", "test", "matters", "customer", "facts", "first_goal")


def shift_case_text(case, d):
    for k in TEXT_KEYS:
        if isinstance(case.get(k), str):
            case[k] = shift_text(case[k], d)
        elif isinstance(case.get(k), list):
            case[k] = [shift_text(x, d) for x in case[k]]
    case["input"]["message"] = shift_text(case["input"]["message"], d)


# ---------------------------------------------------------------- records: every record keeps the stage it was made in

KINDS = {"customers": "CUSTOMERS", "bookings": "BOOKINGS", "flights": "FLIGHTS", "bag_reports": "BAGS",
         "refunds": "REFUNDS", "credits": "CREDITS", "reimbursements": "REIMBURSEMENTS", "approvals": "APPROVALS",
         "changes": "CHANGES"}
REC = {k: {i: (0, copy.deepcopy(r)) for i, r in getattr(b0, g).items()} for k, g in KINDS.items()}


def enter(n):
    """Point the stage-0 helpers and rule functions at stage n's world: all records so far, moved to stage n."""
    world = {k: {i: shift(copy.deepcopy(r), days(n) - days(o)) for i, (o, r) in REC[k].items()} for k in KINDS}
    for c in world["customers"].values():
        c.setdefault("authorized_agents", [])
    for f in world["flights"].values():
        f.setdefault("retimed_by_min", 0)
        f.setdefault("original_departure", None)
    for b in world["bookings"].values():
        b.setdefault("assistance", [])
    for k, g in KINDS.items():
        setattr(b0, g, world[k])
    b0.NOW = DATES[n]
    return world


def commit(n):
    """Records first made in stage n keep stage n as their origin."""
    for k, g in KINDS.items():
        for i, r in getattr(b0, g).items():
            if i not in REC[k]:
                REC[k][i] = (n, copy.deepcopy(r))


def world_seed(n, tickets):
    seed = {k: copy.deepcopy(getattr(b0, g)) for k, g in KINDS.items()}
    for cid, c in seed["customers"].items():
        c["bookings"] = [bid for bid, b in seed["bookings"].items() if b["customer_id"] == cid]
    seed["tickets"] = tickets
    seed["handoffs"] = {}
    return seed


def retimed(fid, route, original, minutes, fares):
    f = b0.flight(route, (b0.ts(original) + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ"), "retimed",
                  fares=fares)
    f["retimed_by_min"], f["original_departure"] = minutes, original
    b0.FLIGHTS[fid] = f


# ---------------------------------------------------------------- stages

ALL_LABELS = list(b0.LABELS)
LATEST = {cid: (0, spec["case"], spec["bad"]) for cid, spec in b0.T.items()}  # id -> (stage, case, bad fixtures)
REQUESTER = {cid: spec["requester"] for cid, spec in b0.T.items()}
RULES = {0: {r[0]: {"id": r[0], "rule": r[1], "sources": r[2], "decoys": r[3], "checks": r[4], "evidence": r[5],
                    "trap_evidence": [b0.TRAPS[d][1] for d in r[3] if d in b0.TRAPS]} for r in b0.RULES}}
LABELS = {0: list(b0.LABELS)}
PLAN = {0: b0.doc_plan()}
RENAMES = {}  # stage -> {old label: new label}
STAGES = {}


# Where a ticket's answer comes from, when the fact tags show the customer's facts decide nothing (the opening and the
# support API settle it): API only. A later version whose answer does need the customer again says so.
WHERE_FROM = {
    1: {"late-claim-03": (1, {}), "late-claim-04": (1, {})},  # late by the bag report's dates
    2: {"pet-01": (1, {}), "pet-02": (1, {})},  # Basic gets nothing / fare minus $75; no pet fee on own cancellation
    3: {"fam-03": (1, {}), "fam-04": (1, {}),  # the child's age and the seat or infant fee are on the booking
        "late-claim-03": (2, {"reimbursements": "customer + api", "category": "customer"}),  # 30 days: now paid
        "late-claim-04": (2, {"reimbursements": "customer + api", "category": "customer"})},
    4: {"um-07": (1, {}), "um-08": (1, {}), "um-10": (1, {})},  # age, escort fee and agency are on the booking
    5: {"rcpt-02b": (1, {})},  # only one earlier payment to quote
}


class Stage:
    def __init__(self, n):
        self.n = n
        self.cases, self.bad, self.changes, self.twins = {}, {}, [], []
        self.rules = copy.deepcopy(RULES[n - 1])
        self.plan = copy.deepcopy(PLAN[n - 1])
        self.splits = {}
        self.labels = list(LABELS[n - 1])
        self.changed, self.added = set(), set()
        self.reused_from = {}
        self.sup = 0
        RULES[n], LABELS[n], PLAN[n] = self.rules, self.labels, self.plan
        STAGES[n] = self
        enter(n)

    # -- rules and the doc changes that carry them
    def rule(self, rid, text, sources, decoys=(), checks=(), evidence=(), split=None):
        """split: {doc: sentences} when the rule's pieces sit on different new docs (fragmented); otherwise every
        new doc of the rule states all its evidence."""
        if split is not None:
            self.splits[rid] = split
        new = rid not in self.rules
        old = self.rules.get(rid, {})
        # a split home of the rule (b0.SPLIT, or this rule's split at an earlier stage) stays a source
        homes = set(b0.SPLIT.get(rid, {})) | {d for x in b0.split_plan().get(rid, {}).get("homes", {}) for d in [x]}
        sources = list(sources) + [d for d in old.get("sources", []) if d in homes and d not in sources]
        text = f"{text} {APPLIES.format(EFFECTIVE[self.n])}"
        # a wrong version of the earlier rule stays a wrong version while it still contradicts the new one
        keep_traps = [t for t in old.get("trap_evidence", []) if not any(t in e or e in t for e in evidence)]
        keep_decoys = [d for d in old.get("decoys", []) if d not in sources
                       and (d not in b0.TRAPS or b0.TRAPS[d][1] in keep_traps)]
        self.rules[rid] = {"id": rid, "rule": text, "sources": list(sources),
                           "decoys": list(dict.fromkeys(list(decoys) + keep_decoys)),
                           "checks": list(checks or old.get("checks", [])), "evidence": list(evidence),
                           "trap_evidence": keep_traps}
        (self.added if new else self.changed).add(rid)

    def change(self, cid, rule_change, appearance, rules, what, edit=(), add=(), keep_old=(), log=None):
        """edit: (doc, old text, new text); add: (new doc path, what it says); keep_old: docs left saying the old rule.
        what is our note (hidden); log is the public change-log line (default: the note's first sentence)."""
        self.changes.append({"id": cid, "rule_change": rule_change, "appearance": appearance, "rules": rules,
                             "what": what, "log": log or what.split(". ")[0].rstrip(".") + ".", "patches": [{"doc": d, "find": o, "replace": r} for d, o, r in edit],
                             "add_docs": [{"doc": d, "states": s} for d, s in add], "left_unchanged": list(keep_old)})

    def rename_label(self, old, new):
        RENAMES.setdefault(self.n, {})[old] = new
        self.labels[self.labels.index(old)] = new
        for r in self.rules.values():
            r["checks"] = [c.replace(f"labels:{old}", f"labels:{new}") for c in r["checks"]]
        if new not in ALL_LABELS:
            ALL_LABELS.append(new)

    def add_label(self, label):
        self.labels.append(label)
        if label not in ALL_LABELS:
            ALL_LABELS.append(label)

    # -- tickets
    def finish(self, case):
        sup = case["input"]["ticket_id"]
        if case["id"] in WHERE_FROM.get(self.n, {}):
            case["info_type"], case["sources"] = WHERE_FROM[self.n][case["id"]]
        if f"approvals.{sup}.booking_id" in case["expect"] and f"approvals.{sup}.kind" not in case["expect"]:
            del case["expect"][f"approvals.{sup}.booking_id"]  # a re-asked ticket whose answer no longer asks for approval
        expect = b0.approval_booking(case)["expect"]
        touched = {p.split(".")[0] for p in expect}
        labels = case["contains"].get(f"tickets.{sup}.labels", [])
        case["not_contains"] = {f"tickets.{sup}.labels": [x for x in ALL_LABELS if x not in labels]}
        handoff = bool(case.get("required_calls"))
        case["unchanged"] = [f for f in b0.MONEY if f not in touched]
        case["forbidden_calls"] = [b0.MONEY[f] for f in b0.MONEY if f not in touched] + ([] if handoff else ["POST /handoffs"])
        case["expected_doc_ids"] = sorted({d for r in case["rules"] for d in self.rules[r]["sources"]})
        return case

    def new(self, cid, customer_id, behavior, rules, title, test, matters, brief, facts, message, category,
            money=None, labels=(), handoff=None, info_type=2, sources=None, group="new-rule", change_type="add",
            lookups=(), must_not=None, bad=(), requester=None, extra=None):
        self.sup += 1
        sup = f"SKY-{6 + self.n}{self.sup:03d}"
        expect = {f"tickets.{sup}.category": category}
        expect.update({p.replace("{T}", sup): v for p, v in b0.norm_money(money or {}).items()})
        case = {"id": cid, "title": title, "test": test, "matters": matters, "rules": rules,
                "input": {"ticket_id": sup, "customer_id": customer_id, "message": message}, "expect": expect,
                "contains": {f"tickets.{sup}.labels": list(labels)} if labels else {},
                "group": group, "change_type": change_type, "customer": brief, "facts": facts, "behavior": behavior,
                "info_type": info_type, "sources": sources or {}}
        if handoff:
            case["required_calls"] = [{"call": "POST /handoffs", "body": {"ticket_id": sup, "reason": handoff}}]
        if must_not:
            case["must_not"] = {k.replace("{T}", sup): v for k, v in must_not.items()}
        if lookups:
            case["lookups"] = list(lookups)
        case.update(extra or {})
        pin_case(case)
        self.cases[cid] = self.finish(case)
        self.bad[cid] = [(name, json.loads(json.dumps(data).replace("{T}", sup)), *rest) for name, data, *rest in bad]
        REQUESTER[cid] = requester or b0.CUSTOMERS[customer_id]["email"]
        return sup

    def reuse(self, cid, group, change_type="none", money=None, labels=None, rules=None, test=None, matters=None,
              bad=(), category=None, must_not=None, facts=None):
        """An earlier ticket asked again in this stage. money/labels replace its expected money/labels. New money
        also drops the earlier must_not on money (it was about the old answer); pass must_not to set a new one."""
        st, prev, prev_bad = LATEST[cid]
        case = copy.deepcopy(prev)
        shift_case_text(case, days(self.n) - days(st))
        sup = case["input"]["ticket_id"]
        for old, new in RENAMES.get(self.n, {}).items():
            got = case["contains"].get(f"tickets.{sup}.labels", [])
            if old in got:
                got[got.index(old)] = new
        if money is not None:
            cat = case["expect"][f"tickets.{sup}.category"]
            case["expect"] = {f"tickets.{sup}.category": cat, **{p.replace("{T}", sup): v for p, v in b0.norm_money(money).items()}}
            kept = {p: v for p, v in case.pop("must_not", {}).items() if p.split(".")[0] not in b0.MONEY}
            if kept:
                case["must_not"] = kept
        if facts is not None:  # the customer's facts read differently once the rule changed
            case["facts"] = list(facts)
        if must_not:
            case.setdefault("must_not", {}).update({k.replace("{T}", sup): v for k, v in must_not.items()})
        if category:
            case["expect"][f"tickets.{sup}.category"] = category
        if labels is not None:
            case["contains"] = {f"tickets.{sup}.labels": list(labels)} if labels else {}
        if rules:
            case["rules"] = rules
        if test:
            case["test"] = pin(test)
        if matters:
            case["matters"] = pin(matters)
        case["group"], case["change_type"] = group, change_type
        case.pop("twin", None)
        self.cases[cid] = self.finish(case)
        olds = [] if group == "unchanged" else [("previous-answer", answer_state(prev))]
        self.bad[cid] = [b for b in prev_bad if b[0] != "previous-answer"] + \
            [(n, json.loads(json.dumps(d).replace("{T}", sup)), *r) for n, d, *r in bad]
        if olds and answer_state(prev) != answer_state(case):
            self.bad[cid].append(olds[0])
        self.reused_from[cid] = (st, prev)

    def twin(self, a, b):
        self.twins.append((a, b))


def answer_state(case):
    """The end state a case expects, as fixture data."""
    data = {}
    for path, want in case["expect"].items():
        file, rid, field = path.split(".", 2)
        data.setdefault(file, {}).setdefault(rid, {})[field] = want
    for path, labels in case["contains"].items():
        file, rid, field = path.split(".", 2)
        data.setdefault(file, {}).setdefault(rid, {})[field] = list(labels)
    return data


def outcome(case):
    sup = case["input"]["ticket_id"]
    return json.dumps({k: case.get(k) for k in ("expect", "contains", "required_calls")}, sort_keys=True).replace(sup, "T")


def check_stage(st):
    n, cases = st.n, list(st.cases.values())
    errors = []
    by_id = st.cases
    sups = [c["input"]["ticket_id"] for c in cases]
    if len(set(sups)) != len(sups):
        errors.append("duplicate ticket ids")
    if len(cases) != TARGET[n]:
        errors.append(f"{len(cases)} tickets, want {TARGET[n]}")
    for c in cases:
        cid = c["id"]
        for path, banned in (c.get("must_not") or {}).items():
            if path in c["expect"] and c["expect"][path] in banned:
                errors.append(f"{cid}: must_not bans {c['expect'][path]!r} at {path}, which it also expects")
        if not set(c["rules"]) <= set(st.rules):
            errors.append(f"{cid}: unknown rule {set(c['rules']) - set(st.rules)}")
        used_changed = set(c["rules"]) & st.changed
        used_added = set(c["rules"]) & st.added
        if c["group"] == "unchanged" and (used_changed or used_added or c["change_type"] != "none"):
            errors.append(f"{cid}: unchanged but uses {sorted(used_changed | used_added)}")
        if c["group"] == "changed-rule" and not used_changed:
            errors.append(f"{cid}: changed-rule but uses no changed rule")
        if c["group"] == "new-rule" and not used_added:
            errors.append(f"{cid}: new-rule but uses no new rule")
        if c["group"] == "unchanged":  # no rule it uses may have changed since the version it copies
            since = st.reused_from[cid][0]
            moved = set(c["rules"]) & {r for k in range(since + 1, n + 1) for r in STAGES[k].changed | STAGES[k].added}
            if moved:
                errors.append(f"{cid}: copies its stage-{since} answer, but {sorted(moved)} changed since")
        if c["group"] == "unchanged" and outcome(c) != outcome(st.reused_from[cid][1]):
            errors.append(f"{cid}: unchanged but its answer differs from stage {st.reused_from[cid][0]}")
        if cid in st.reused_from and outcome(c) != outcome(st.reused_from[cid][1]) and c["test"] == st.reused_from[cid][1]["test"]:
            errors.append(f"{cid}: its answer changed since stage {st.reused_from[cid][0]} but its test text did not")
        if c["expect"].get(f"tickets.{c['input']['ticket_id']}.category") not in b0.CATEGORIES:
            errors.append(f"{cid}: category")
        if c["info_type"] != 1 and not any(v in (CUSTOMER, BOTH) for v in c["sources"].values()):
            errors.append(f"{cid}: info_type {c['info_type']} but no field depends on the customer")
        if (c["behavior"] == "goal_change") != bool(c.get("first_goal")):
            errors.append(f"{cid}: goal_change needs first_goal and only then")
        for k in TEXT_KEYS + ("input",):
            v = c.get(k, "")
            v = v["message"] if k == "input" else v
            text = " | ".join(v) if isinstance(v, list) else str(v)
            if BARE_MONTH.search(text):
                errors.append(f"{cid}: {k} names a month without a day (cannot move between stages)")
        trip_text = " ".join([c["input"]["message"], c["customer"], *c["facts"]])
        for d in POLICY_DATES:
            if d.replace(" ", "\u00a0") in trip_text:  # pinned in the customer's words: that trip date would never move
                errors.append(f"{cid}: the customer's words pin the policy date {d}; pick another trip date")
        for label in c["contains"].get(f"tickets.{c['input']['ticket_id']}.labels", []):
            if label not in st.labels:
                errors.append(f"{cid}: label {label} is not in this stage's labels")
        for path in list(c["expect"]) + list(c.get("must_not", {})):
            file, rec, _ = path.split(".", 2)
            if file in ("refunds", "credits", "reimbursements", "changes") and rec not in b0.BOOKINGS:
                errors.append(f"{cid}: {path} names an unknown booking")
            if file in ("tickets", "approvals") and rec != c["input"]["ticket_id"]:
                errors.append(f"{cid}: {path} is not this ticket")
        for g in c.get("lookups", []):
            parts = g.split()[1].split("?")[0].split("/")
            if parts[1] == "bookings" and parts[2] not in b0.BOOKINGS:
                errors.append(f"{cid}: lookup of unknown booking {parts[2]}")
            if parts[1] == "flights" and parts[2] not in b0.FLIGHTS:
                errors.append(f"{cid}: lookup of unknown flight {parts[2]}")
        if c["input"]["customer_id"] not in b0.CUSTOMERS:
            errors.append(f"{cid}: unknown customer")
    for a, b in st.twins:
        x, y = by_id[a], by_id[b]
        if x["customer"] != y["customer"] or x["input"]["customer_id"] != y["input"]["customer_id"]:
            errors.append(f"twins {a}/{b}: different opening or customer")
        if outcome(x) == outcome(y):
            errors.append(f"twins {a}/{b}: same answer")
        if "goal_change" in (x["behavior"], y["behavior"]):
            errors.append(f"twins {a}/{b}: a twin cannot change goal")
    used = Counter(r for c in cases for r in c["rules"])
    for r in st.changed | st.added:
        if used[r] < 2:
            errors.append(f"rule {r} changed/added this stage but used by {used[r]} tickets")
    behaviors = Counter(c["behavior"] for c in cases)
    for bname in b0.BEHAVIORS:
        if not 1 <= behaviors[bname] <= 8:
            errors.append(f"behavior {bname}: {behaviors[bname]} tickets")
    tags = {(ch["rule_change"], ch["appearance"]) for ch in st.changes}
    if not {a for _, a in tags} >= {"clean", "conflicting", "fragmented", "noisy", "incomplete"} and n == 1:
        errors.append(f"stage 1 should show every appearance type, has {sorted(tags)}")
    return errors


def apply_plan(st):
    """This stage's doc changes, applied to the previous stage's plan. Returns what does not fit."""
    errors, plan, n = [], st.plan, st.n
    clause = APPLIES.format(EFFECTIVE[n])
    for rid in sorted(st.added, key=lambda r: int(r[1:])):  # a wrong version of each new rule, from before it existed
        if rid in WRONG_LATER:
            d, sentence = WRONG_LATER[rid]
            plan[d] = {"states": [sentence], "carries": [], "trap": {"for": rid, "why": b0.OLDER_NOTE}, "added_in": n}
            r = st.rules[rid]
            r["decoys"] = r["decoys"] + [d] if d not in r["decoys"] else r["decoys"]
            r["trap_evidence"] = sorted(set(r.get("trap_evidence", [])) | {sentence})
    for ch in st.changes:  # the change log says from when it applies; it is a source of every rule it changes
        log = f"{CHANGE_LOG}{DATES[n][:10]}-{ch['id']}.json"
        plan[log] = {"states": [ch["log"], clause], "carries": [r for r in ch["rules"] if r in st.rules], "trap": None,
                     "added_in": n, "role": "change log"}
        for rid in ch["rules"]:
            r = st.rules[rid]
            r["sources"] = r["sources"] + [log] if log not in r["sources"] else r["sources"]
            r["evidence"] = r["evidence"] + [clause] if clause not in r["evidence"] else r["evidence"]
    before = RULES[n - 1]
    for ch in st.changes:
        for p in ch["patches"]:
            states = plan.get(p["doc"], {}).get("states", [])
            hit = [i for i, x in enumerate(states) if p["find"] in x]
            if not hit:  # the split moved the part: the edit follows it to the one doc that states it now
                srcs = {d for r in {**before, **st.rules}.values() for d in r["sources"]}  # any rule's docs
                homes = [d for d in sorted(srcs) if d in plan and not plan[d].get("trap") and plan[d].get("role") != "change log"
                         and any(p["find"] in y for y in plan[d]["states"])]
                if len(homes) == 1:
                    for r in ch["rules"]:  # a rule this edit writes into follows the edit
                        src = st.rules[r]["sources"] if r in st.rules else []
                        if p["doc"] in src and homes[0] not in src:
                            src[src.index(p["doc"])] = homes[0]
                    p["doc"], states = homes[0], plan[homes[0]]["states"]
                    hit = [i for i, x in enumerate(states) if p["find"] in x]
            if not hit:
                errors.append(f"{ch['id']}: {p['doc']} has no planned sentence containing {p['find']!r}"
                              + (f" (stated in {homes})" if homes else ""))
                continue
            for i in hit:
                states[i] = states[i].replace(p["find"], p["replace"])
            plan[p["doc"]]["carries"] = sorted(set(plan[p["doc"]]["carries"]) | set(ch["rules"]), key=lambda r: int(r[1:]))
        for a in ch["add_docs"]:
            entry = plan.setdefault(a["doc"], {"states": [], "carries": [], "trap": None, "added_in": n})
            text = a["states"]
            for mark, why in TRAP_MARKS.items():
                if text.rstrip(".").endswith(mark):
                    text = text.rstrip(".")[: -len(mark)] + "."
                    entry["trap"] = {"for": ch["rules"][0], "why": why}
            a["states"] = text
            entry["states"].append(text)
    homes = b0.split_plan()
    for rid in sorted(st.changed | st.added, key=lambda r: int(r[1:])):
        rule, split = st.rules[rid], st.splits.get(rid)
        if split is None and homes.get(rid, {}).get("stage") == n:  # a new rule, split by docs_build/split/plan.json
            split = homes[rid]["homes"]
            rule["sources"] += [d for d in split if d not in rule["sources"]]
        elif split is None and rid in st.changed:  # a changed rule: this stage's docs state what changed, nothing more
            changed = [x for x in rule["evidence"] if x not in before[rid]["evidence"]]
            old = set(before[rid]["evidence"]) - set(rule["evidence"])
            for x in rule["evidence"]:  # an unchanged part whose every home keeps an old part (an old copy now)
                where = [d for d in before[rid]["sources"] if any(x in y for y in plan.get(d, {}).get("states", []))]
                if x not in changed and where and all(any(o in y for o in old for y in plan[d]["states"]) for d in where):
                    changed.append(x)
            split = {d: changed for d in rule["sources"] if plan.get(d, {}).get("role") != "change log"}
        for d in rule["sources"]:
            entry = plan.get(d)
            if entry is None and split and d in split:  # a split home this stage adds (a thread written below)
                entry = plan[d] = {"states": [], "carries": [], "trap": None, "added_in": n}
            if entry is None or entry.get("added_in") != n:
                continue  # an older doc changes only through its patches
            for x in (split.get(d, []) if split is not None else rule["evidence"]):
                if x not in entry["states"]:
                    entry["states"].append(x)
            entry["carries"] = sorted(set(entry["carries"]) | {rid}, key=lambda r: int(r[1:]))
        for d in rule["decoys"]:
            if d in plan and plan[d].get("added_in") == n and not plan[d]["carries"] and not plan[d]["trap"]:
                plan[d]["trap"] = {"for": rid, "why": "a lookalike or outdated page for this rule"}
    for ch in st.changes:
        slug, rids = ch["id"], [r for r in ch["rules"] if r in st.rules]
        if ch["appearance"] == "incomplete":
            continue  # nothing more is published about an incomplete rule
        # one piece per thread, so a fragmented rule stays fragmented
        sentences = [x for r in rids for xs in st.splits.get(r, {}).values() for x in xs] \
            or [x for r in rids for x in st.rules[r]["evidence"]]
        channels = ["support-team", "support-policy-questions", "refunds-desk"]
        for k in range(APPLIED_THREADS):
            d = f"{SL}{channels[k % len(channels)]}/{DATES[n][:10]}-{slug}-thread-{k + 1}.json"
            plan.setdefault(d, {"states": [sentences[k % len(sentences)]], "carries": rids, "trap": None, "added_in": n,
                                "role": "applies the rule"})
    for rid in sorted(st.changed, key=lambda r: int(r[1:])):
        old_sentences = {y for y in set(before[rid]["evidence"]) - set(st.rules[rid]["evidence"])
                         if not y.startswith("This applies to every request handled from")}
        print(f"  {rid} no longer true: {sorted(old_sentences)}")
        # what a bot that kept an older version would say (diagnose blames "stale copy"); every older version counts
        st.rules[rid]["stale_evidence"] = sorted(set(before[rid].get("stale_evidence", [])) | old_sentences)
        declared = set(st.rules[rid]["decoys"]) | {d for ch in st.changes if rid in ch["rules"] for d in ch["left_unchanged"]}
        for d, x in plan.items():
            stale = [y for y in x["states"] if y in old_sentences]
            if not stale or (rid not in x["carries"] and d not in declared):
                continue
            # an earlier stage's announcement threads and change logs are history: they keep the old version
            if d in declared or (x.get("added_in", 0) < n and x.get("role") in ("applies the rule", "change log")):
                if not (x.get("trap") and x["trap"].get("for") != rid):
                    x["trap"] = {"for": rid, "why": f"states the rule as it was before {EFFECTIVE[n]}", "stale": stale}
                if d not in declared:  # an earlier stage's page with the old version: on record with this stage's change
                    for ch in st.changes:
                        if rid in ch["rules"] and d not in ch.setdefault("earlier_pages", []):
                            ch["earlier_pages"].append(d)
                if all(y in old_sentences for y in x["states"]):
                    x["carries"] = [r for r in x["carries"] if r != rid]
            elif d not in {p["doc"] for ch in st.changes for p in ch["patches"]}:
                errors.append(f"{rid}: {d.split('docs/')[-1]} still states the old {stale} but is not declared as a trap")
    # Blame matches stale sentences inside the prompt: one that is also inside current text (any rule's evidence, a doc
    # that is not a trap once the stale copies above are marked) would blame a bot that has the right version.
    def flat(t):
        return " ".join(str(t).lower().split())
    current = [flat(e) for r in st.rules.values() for e in r["evidence"]]
    current += [flat(y) for x in plan.values() if not x.get("trap") for y in x["states"]]
    for r in st.rules.values():
        if r.get("stale_evidence"):
            r["stale_evidence"] = [y for y in r["stale_evidence"] if not any(flat(y) in c for c in current)]
    return errors + b0.plan_errors(list(st.rules.values()), plan)


def vocabulary_errors(cases, rules, plan):
    """Labels, categories and handoff reasons a ticket is graded on must be written in a planned doc of its rules."""
    errors = []
    for c in cases:
        said = " ".join(x for r in c["rules"] for d in rules[r]["sources"] for x in plan.get(d, {}).get("states", []))
        sup = c["input"]["ticket_id"]
        words = list(c["contains"].get(f"tickets.{sup}.labels", [])) + [c["expect"].get(f"tickets.{sup}.category")]
        words += [rc["body"]["reason"] for rc in c.get("required_calls", []) if rc.get("body", {}).get("reason")]
        for w in words:
            if w and not re.search(rf"\b{re.escape(w)}\b", said):
                errors.append(f"{c['id']}: expects {w!r} but no planned doc of its rules says it")
    return errors


from erb_paths import STAFF as STAFF_FILE  # noqa: E402


def save_stage(st):
    n = st.n
    errors = apply_plan(st) + check_stage(st)
    if STAFF_FILE.exists():  # a customer named like a staff member would confuse an agent searching the docs
        staff = set(re.findall(r'- name: "?([^"\n]+)"?', STAFF_FILE.read_text()))
        names = {c["name"] for c in b0.CUSTOMERS.values()} | {p["name"] for bk in b0.BOOKINGS.values() for p in bk["passengers"]}
        errors += [f"customer or passenger named like staff: {x}" for x in sorted(names & staff)]
    errors += vocabulary_errors(list(st.cases.values()), st.rules, st.plan)
    cases = list(st.cases.values())
    for a, b in st.twins:
        st.cases[a]["twin"], st.cases[b]["twin"] = b, a
    groups = Counter(c["group"] for c in cases)
    infos = Counter(c["info_type"] for c in cases)
    changed_answers = sum(1 for c in cases if c["group"] == "changed-rule" and c["id"] in st.reused_from
                          and outcome(c) != outcome(st.reused_from[c["id"]][1]))
    print(f"stage {n}: {len(cases)} tickets; groups {dict(groups)}; info types {dict(sorted(infos.items()))}; "
          f"{len(st.twins)} twin pairs; {len(st.rules)} rules ({len(st.changed)} changed, {len(st.added)} new); "
          f"{len(st.changes)} doc changes; {changed_answers} re-asked tickets now have a different answer")
    print("  behaviors", dict(sorted(Counter(c["behavior"] for c in cases).items())))
    if errors:
        print("\n".join(["  NOT SAVED:"] + ["  " + e for e in errors]))
        raise SystemExit(1)
    out = TESTS / "stages" / f"stage{n}"
    tickets = {c["input"]["ticket_id"]: {"customer_id": c["input"]["customer_id"], "requester_email": REQUESTER[c["id"]],
                                         "booking_id": None, "category": None, "labels": [], "status": "open",
                                         "created_at": DATES[n], "comments": []} for c in cases}
    for name, data in world_seed(n, tickets).items():
        b0.save(out / "seed" / f"{name}.json", data)
    for rid, r in st.rules.items():  # a changed rule carries its own keywords (scripts/rule_keywords.py)
        spec = rule_keywords.for_stage(rid, n)
        if spec is not rule_keywords.BASE.get(rid):
            r["keywords"] = spec
        else:
            r.pop("keywords", None)
    b0.save(out / "rules.json", [st.rules[k] for k in sorted(st.rules, key=lambda r: int(r[1:]))])
    b0.save(out / "changes.json", {"stage": n, "date": DATES[n], "labels": st.labels, "changes": st.changes})
    new = [d for d, x in st.plan.items() if x.get("added_in") == n]
    edited = sorted({p["doc"] for ch in st.changes for p in ch["patches"]})
    background = max(0, NEW_DOCS - len(new))
    b0.save(out / "doc_plan.json", {"stage": n, "date": DATES[n], "docs": st.plan, "must_not_mention": b0.MUST_NOT_MENTION,
                                    "new_rule_docs": len(new), "edited_docs": len(edited), "new_background_docs": background})
    print(f"  docs: {len(new)} new rule docs + {background} new background docs = {len(new) + background} new; {len(edited)} edited")
    b0.narrow_expected(cases, list(st.rules.values()), st.plan, f"stage{n}")
    b0.save(out / "cases.json", cases)
    for f in (out / "fixtures").glob("*.json"):
        f.unlink()
    for c in cases:
        good = b0.good_fixture(c)
        extra_bad = []
        if c.get("require_attempt"):  # the id is only in the first ticket's payment response; a comment must quote it
            first = st.cases[c["after"]]
            call = c["require_attempt"]["call"]
            body = {k.split(".", 2)[2]: v for k, v in first["expect"].items() if k.split(".")[0] == call.split("/")[-1]}
            # verify.py grades a follow-up on its own requests (after `already`): the first ticket's payment comes
            # first in the log, then this ticket's comment quoting the id from that payment's response.
            sup = c["input"]["ticket_id"]
            paid = {"method": "POST", "path": call.split()[1], "body": body, "status": 200,
                    "response": {**body, "confirmation_id": "cf_fixture1"}}
            said = "Your confirmation number is cf_fixture1."
            good["requests"] = [paid, {"method": "POST", "path": f"/tickets/{sup}/comments", "status": 200,
                                       "body": {"body": said, "public": True}}]
            good["already"] = 1
            good["data"].setdefault("tickets", {}).setdefault(sup, {})["comments"] = [{"body": said, "public": True}]
            no_id = json.loads(json.dumps(good))
            no_id.update({"name": "id-not-quoted", "should": "fail"})
            no_id["requests"][1]["body"]["body"] = "Your payment went through."
            no_id["data"]["tickets"][sup]["comments"] = [{"body": "Your payment went through.", "public": True}]
            extra_bad.append(no_id)
        bads = list(extra_bad)
        for f in b0.bad_fixtures({"case": c, "bad": st.bad[c["id"]]}):
            if f["data"] == good["data"] and f["requests"] == good["requests"]:
                print(f"  {c['id']}: dropped wrong-answer fixture {f['name']!r}: it is the right answer in stage {n}")
                continue
            bads.append(f)
        st.bad[c["id"]] = [b for b in st.bad[c["id"]] if b[0] in {f["name"] for f in bads}]
        b0.save(out / "fixtures" / f"{c['id']}.json", [good] + bads)
    for cid, c in st.cases.items():
        LATEST[cid] = (n, c, st.bad[cid])
    commit(n)


# ================================================================== stage 1 (2026-07-01)
s1 = Stage(1)

# -- policy changes
b0.BAG_DAY, b0.BAG_CAP = 90, 450
s1.rule("R13", "Delayed bag: $90 for each full 24 hours between arrival and delivery, at most $450 per bag, paid against receipts.",
        [CP + "baggage/delayed-bags.json", SL + "policy-updates/delayed-bag-rate-july.json"],
        [SL + "baggage-desk/summer-peak-100-per-day.json"], evidence=["$90 for each full 24 hours", "up to $450 per bag", "paid against receipts",
                                                                   "count them from the flight's arrival to the bag's delivery"])
s1.change("bag-rate-90", "edit", "clean", ["R13"], "Delayed-bag allowance rises to $90 a day, capped at $450.",
          edit=[(CP + "baggage/delayed-bags.json", "$75 for each full 24 hours", "$90 for each full 24 hours"),
                (CP + "baggage/delayed-bags.json", "up to $375 per bag", "up to $450 per bag")],
          add=[(SL + "policy-updates/delayed-bag-rate-july.json", "From July 1 the delayed-bag allowance is $90 a day, up to $450.")],
          keep_old=[PB + "case-handling/delayed-bag-expenses-quick-reference.json"])

b0.HOTEL_AUTO = 200
s1.rule("R10", "Hotel for a Skyway-controlled overnight: up to $200 per room per night is paid directly. Above $200, do not pay: "
               "request supervisor approval for the room cost, up to $250 per room per night.",
        [PB + "approvals-and-limits/approval-limits.json", SL + "policy-updates/hotel-limit-200.json"],
        [CP + "delays-and-disruptions/hotels-during-disruptions.json"],
        evidence=["Up to $200 a night needs no approval.", "Above $200, ask a supervisor to approve the room cost, up to $250.",
                  "if the room is over $250, ask approval for $250 only; we don't cover the rest"])
s1.change("hotel-limit-200", "edit", "conflicting", ["R10"],
          "Agents may pay hotels up to $200 without approval. The hotel policy page still says $175; the newer approvals page wins.",
          edit=[(PB + "approvals-and-limits/approval-limits.json", "Above $175 a night, ask a supervisor to approve the room cost, up to $250.",
                 "Up to $200 a night needs no approval. Above $200, ask a supervisor to approve the room cost, up to $250.")],
          add=[(SL + "policy-updates/hotel-limit-200.json", "From July 1 agents can pay hotels up to $200 a room without approval.")],
          keep_old=[CP + "delays-and-disruptions/hotels-during-disruptions.json"])

s1.rename_label("receipts-needed", "awaiting-receipts")
s1.rule("R11", "Reimbursements pay the lower of the receipts and the limit. Without receipts pay nothing yet and label awaiting-receipts.",
        [PB + "case-handling/paying-reimbursements.json"], checks=["reimbursements", "labels:awaiting-receipts"], evidence=["the lower of the receipts and the limit", "label it awaiting-receipts",
                                                                                              "if the customer says they kept the receipts, that is enough to pay now"])
s1.change("receipts-label-renamed", "rename", "clean", ["R11"], "The label receipts-needed is now awaiting-receipts.",
          edit=[(PB + "case-handling/paying-reimbursements.json", "receipts-needed", "awaiting-receipts")],
          add=[(PB + "case-handling/ticket-labels-change-log.json", "receipts-needed was renamed awaiting-receipts on July 1.")])

b0.CREDIT_BONUS = 1.0
s1.rule("R3", "Offer travel credit instead of a refund only if the customer asks for credit; the credit equals the refund "
              "(the 10% bonus ended on June 30). Never default to credit.",
        [CP + "cancellations-and-refunds/travel-credit-instead-of-refund.json", SL + "policy-updates/credit-bonus-ends.json"],
        [CP + "loyalty/gift-credit-promotion.json", SL + "refunds-desk/credit-bonus-question.json"],
        evidence=["credit for the same amount as the refund", "only when the customer asks for credit"])
s1.change("credit-bonus-ended", "remove", "noisy", ["R3"],
          "The 10% bonus on credit taken instead of a refund is withdrawn. A new gift-credit promotion page also says '10% extra', "
          "but it is about buying gift credit.",
          edit=[(CP + "cancellations-and-refunds/travel-credit-instead-of-refund.json", "credit worth 110% of the refund",
                 "credit for the same amount as the refund")],
          add=[(SL + "policy-updates/credit-bonus-ends.json", "The 10% bonus on credit instead of a refund ends June 30."),
               (CP + "loyalty/gift-credit-promotion.json", "Buy Skyway gift credit this summer and get 10% extra (lookalike).")])

s1.add_label("assistance-failure")
s1.rule("R22", "If Skyway did not provide wheelchair or other assistance booked on the reservation: $100 travel credit per "
               "affected passenger, no approval, and label assistance-failure. It is not goodwill, so the one-goodwill limit does "
               "not apply. Assistance that was not booked is not covered; help that came late or was rude is a service failure (R16).",
        [CP + "special-assistance/assistance-not-provided.json", PB + "approvals-and-limits/goodwill.json",
         PB + "case-handling/ticket-labels.json"],
        checks=["credits", "labels:assistance-failure"],
        evidence=["assistance that was booked and not provided", "assistance that was not booked is not covered",
                  "help that came late or was rude is a goodwill case", "$100 per affected passenger", "no approval needed",
                  "this is not goodwill, so the one-goodwill limit does not apply", "label assistance-failure"],
        split={CP + "special-assistance/assistance-not-provided.json": ["assistance that was booked and not provided",
                                                                         "assistance that was not booked is not covered",
                                                                         "help that came late or was rude is a goodwill case"],
               PB + "case-handling/ticket-labels.json": ["label assistance-failure"]})
s1.change("assistance-not-provided", "add", "fragmented", ["R22"],
          "New: booked assistance not provided earns $100 credit per passenger. The trigger, the amount and the label are on three pages.",
          log="New policy for booked assistance that was not provided.",
          edit=[(PB + "approvals-and-limits/goodwill.json", "one goodwill credit per booking",
                 "one goodwill credit per booking. Booked assistance that was not provided: $100 per affected passenger, no approval needed; this is not goodwill, so the one-goodwill limit does not apply")],
          add=[(CP + "special-assistance/assistance-not-provided.json", "When assistance booked on the reservation is not provided, the customer is owed travel credit."),
               (PB + "case-handling/ticket-labels.json", "assistance-failure: booked assistance was not provided.")])

s1.rule("R23", "If Skyway moves a flight's departure by 2 hours or more before the trip, the customer may cancel for a full refund "
               "to the original payment (fare and add-ons, any fare, Basic included), or move free (no fee, no fare difference) to "
               "another Skyway flight on the same route within 3 days of the original departure. Otherwise the normal rules apply.",
        [CP + "fares-and-changes/schedule-changes.json", SL + "refunds-desk/schedule-change-refunds.json"],
        [CP + "fares-and-changes/schedule-changes-draft-2025.json"], checks=["refunds", "changes"],
        evidence=["moved by 2 hours or more before the trip", "a full refund of the fare and add-ons to the original payment",
                  "any fare, Basic included", "move free to another Skyway flight on the same route",
                  "within 3 days of the original departure",
                  "a move of less than 2 hours changes nothing: the normal cancel and change rules apply"])
s1.change("schedule-change-rights", "add", "conflicting", ["R23"],
          "New: a departure moved 2+ hours gives a full refund or a free move. An older 2025 draft says 3+ hours.",
          add=[(CP + "fares-and-changes/schedule-changes.json", "Schedule changes of 2 hours or more: a full refund or a free move."),  # the 3 days: the thread
               (SL + "refunds-desk/schedule-change-refunds.json", "A Basic customer whose flight moved 2h gets a full refund."),
               (CP + "fares-and-changes/schedule-changes-draft-2025.json", "DRAFT 2025: schedule changes of 3 hours or more (outdated).")])

s1.rule("R17", "Only the booking's contact (the email on the booking), or a travel manager under R24, may get a refund, change, "
               "credit or reimbursement on it. Anyone else: label not-authorized and change nothing.",
        [PB + "case-handling/who-can-ask.json", PB + "case-handling/travel-managers.json"],
        evidence=["only the booking contact", "travel managers listed on the company account", "label the ticket not-authorized"])
s1.rule("R24", "A travel manager listed on a company account (authorized_agents on the account's customer record) may ask for "
               "refunds, changes, credits and reimbursements on bookings that belong to that account. The older who-can-ask page says only the "
               "contact; the newer travel-manager page wins.",
        [PB + "case-handling/travel-managers.json", SL + "support-team/travel-manager-thread.json"],
        [PB + "case-handling/who-can-ask.json"], checks=["refunds", "changes", "credits", "labels:not-authorized"],
        evidence=["listed travel managers may act for the company's travellers", "only on bookings that belong to that account"])
s1.change("travel-managers", "add", "conflicting", ["R24", "R17"],
          "New: listed travel managers may act on their company's bookings. The older who-can-ask page still says contact only.",
          add=[(PB + "case-handling/travel-managers.json", "Travel managers listed on a company account may act on its bookings."),
               (SL + "support-team/travel-manager-thread.json", "Yes, the listed travel manager can cancel for their traveller.")],
          keep_old=[PB + "case-handling/who-can-ask.json", SL + "support-team/assistant-asking-for-refund.json"])

s1.rule("R25", "Cancellations for illness: the July 1 announcement promises full travel credit with a doctor's note, but no "
               "process is published yet. Hand off (not_covered) and give nothing under it. Only a full refund under another "
               "rule (a Flex fare, or a Skyway cancellation) replaces the handoff; the normal Basic and Standard cancellation "
               "rule (R5) does not, so those are handed off.",
        [SL + "announcements/illness-cancellations.json"], checks=["POST /handoffs", "credits", "refunds"],
        evidence=["full travel credit with a doctor's note", "details to follow",
                  "until the process is published, an illness cancellation is not a safety case: hand it off as not_covered",
                  "a full refund under another rule, a Flex fare or a Skyway cancellation, replaces the handoff"])
s1.change("illness-announcement", "add", "incomplete", ["R25"],
          "An announcement promises full credit for illness cancellations, with 'details to follow'. No page says how.",
          log="Illness cancellations with a doctor's note will get full travel credit; details to follow.",
          add=[(SL + "announcements/illness-cancellations.json", "Illness cancellations with a doctor's note will get full credit. Details to follow.")])

# -- records made in stage 1
b0.FLIGHTS["SW341"] = b0.flight("RDU-BOS", "2026-06-28T23:00:00Z", "cancelled", "mechanical", "2026-06-28T21:30:00Z",
                                overnight=True, replacement="SW343")
b0.FLIGHTS["SW343"] = b0.flight("RDU-BOS", "2026-06-29T12:00:00Z", arrived="2026-06-29T14:05:00Z")
b0.FLIGHTS["SW657"] = b0.flight("RDU-MIA", "2026-06-27T16:30:00Z", arrived="2026-06-27T19:00:00Z")
b0.FLIGHTS["SW606"] = b0.flight("RDU-MIA", "2026-06-29T16:00:00Z", "delayed", "mechanical", dep_delay=200, arr_delay=210,
                                arrived="2026-06-29T22:00:00Z")
b0.FLIGHTS["SW218"] = b0.flight("BNA-DEN", "2026-06-29T12:00:00Z", "cancelled", "crew", "2026-06-29T08:00:00Z",
                                replacement="SW220")
b0.FLIGHTS["SW220"] = b0.flight("BNA-DEN", "2026-06-29T23:40:00Z", arrived="2026-06-30T02:10:00Z")
b0.FLIGHTS["SW224"] = b0.flight("BNA-DEN", "2026-06-28T12:00:00Z", "delayed", "crew", dep_delay=250, arr_delay=260,
                                arrived="2026-06-28T18:50:00Z")
b0.FLIGHTS["SW449"] = b0.flight("BNA-BOS", "2026-06-26T13:00:00Z", arrived="2026-06-26T15:20:00Z")
PHX = {"Basic": 159, "Standard": 214, "Flex": 289}
retimed("SW890", "BNA-PHX", "2026-07-10T14:00:00Z", 150, PHX)
b0.FLIGHTS["SW892"] = b0.flight("BNA-PHX", "2026-07-11T14:00:00Z", fares={"Basic": 179, "Standard": 244, "Flex": 309})
b0.FLIGHTS["SW896"] = b0.flight("BNA-PHX", "2026-07-15T14:00:00Z", fares={"Basic": 169, "Standard": 234, "Flex": 299})
retimed("SW780", "RDU-ATL", "2026-07-08T13:00:00Z", 90, {"Basic": 99, "Standard": 150, "Flex": 205})
retimed("SW530", "BNA-ORD", "2026-07-12T12:00:00Z", 120, {"Basic": 99, "Standard": 159, "Flex": 219})
retimed("SW345", "RDU-BOS", "2026-07-14T15:00:00Z", 180, {"Basic": 139, "Standard": 199, "Flex": 259})
retimed("SW910", "BNA-MIA", "2026-07-09T14:00:00Z", 60, {"Basic": 119, "Standard": 172, "Flex": 239})
b0.FLIGHTS["SW904"] = b0.flight("BNA-MIA", "2026-07-20T14:00:00Z", fares={"Basic": 119, "Standard": 172, "Flex": 239})
b0.FLIGHTS["SW908"] = b0.flight("BNA-MIA", "2026-07-22T14:00:00Z", fares={"Basic": 139, "Standard": 192, "Flex": 259})
b0.FLIGHTS["SW915"] = b0.flight("BNA-MIA", "2026-07-06T14:00:00Z", fares={"Basic": 119, "Standard": 172, "Flex": 239})
b0.FLIGHTS["SW917"] = b0.flight("BNA-MIA", "2026-07-13T14:00:00Z", fares={"Basic": 119, "Standard": 172, "Flex": 239})
b0.FLIGHTS["SW919"] = b0.flight("BNA-MIA", "2026-07-08T14:00:00Z", fares={"Basic": 109, "Standard": 160, "Flex": 225})

b0.customer("cust_amadi", "Chidi Amadi", "chidi.amadi@gmail.com")
b0.booking("SK8101", "cust_amadi", ["SW341"], "Standard", 205, ["Chidi Amadi", "Ngozi Amadi"], "2026-05-30T08:00:00Z")
b0.customer("cust_novak", "Petra Novak", "petra.novak@gmail.com")
b0.booking("SK8110", "cust_novak", ["SW657"], "Standard", 171, ["Petra Novak"], "2026-06-01T08:00:00Z",
           addons=[("checked_bag", 0, "SW657", 35)])
b0.bag("BG-3001", "SK8110", "SW657", "delayed", "2026-06-30T21:00:00Z")
b0.customer("cust_osei", "Ama Osei", "ama.osei@gmail.com")
b0.booking("SK8120", "cust_osei", ["SW606"], "Standard", 164, ["Ama Osei"], "2026-06-02T08:00:00Z")
b0.customer("cust_berg", "Lars Berg", "lars.berg@gmail.com")
b0.booking("SK8130", "cust_berg", ["SW218"], "Standard", 238, ["Lars Berg", "Eva Berg"], "2026-06-03T08:00:00Z",
           addons=[("checked_bag", 0, "SW218", 35), ("checked_bag", 1, "SW218", 35)])
b0.customer("cust_cole", "Martin Cole", "martin.cole@gmail.com")
b0.booking("SK8140", "cust_cole", ["SW449"], "Standard", 199, ["Martin Cole"], "2026-06-04T08:00:00Z")
b0.customer("cust_mendes", "Joana Mendes", "joana.mendes@gmail.com")
b0.booking("SK8141", "cust_mendes", ["SW449"], "Standard", 199, ["Luis Mendes", "Rosa Mendes"], "2026-06-05T08:00:00Z")
b0.customer("cust_alves", "Pedro Alves", "pedro.alves@gmail.com")
b0.booking("SK8142", "cust_alves", ["SW449"], "Standard", 199, ["Pedro Alves"], "2026-06-06T08:00:00Z")
b0.customer("cust_holt", "Mira Holt", "mira.holt@gmail.com")
b0.booking("SK8143", "cust_holt", ["SW449"], "Standard", 199, ["Mira Holt"], "2026-06-07T08:00:00Z")
b0.customer("cust_amylin", "Amy Lin", "amy.lin@gmail.com")
b0.customer("cust_glin", "George Lin", "george.lin@gmail.com")
b0.booking("SK8144", "cust_glin", ["SW449"], "Standard", 199, ["George Lin"], "2026-06-08T08:00:00Z")
for _bid, _pax in (("SK8140", ["P1"]), ("SK8141", ["P1", "P2"]), ("SK8143", ["P1"]), ("SK8144", ["P1"])):
    b0.BOOKINGS[_bid]["assistance"] = [{"passenger": p, "type": "wheelchair", "requested_at": "2026-06-10T08:00:00Z"} for p in _pax]
b0.customer("cust_dawson", "Ruth Dawson", "ruth.dawson@gmail.com")
b0.booking("SK8150", "cust_dawson", ["SW890"], "Basic", 159, ["Ruth Dawson"], "2026-06-01T09:00:00Z")
b0.booking("SK8151", "cust_dawson", ["SW780"], "Standard", 150, ["Ruth Dawson"], "2026-06-02T09:00:00Z")
b0.customer("cust_ellis", "Sam Ellis", "sam.ellis@gmail.com")
b0.booking("SK8152", "cust_ellis", ["SW890"], "Standard", 214, ["Sam Ellis"], "2026-06-03T09:00:00Z")
b0.customer("cust_frost", "Nora Frost", "nora.frost@gmail.com")
b0.booking("SK8153", "cust_frost", ["SW890"], "Standard", 214, ["Nora Frost"], "2026-06-04T09:00:00Z")
b0.customer("cust_gill", "Harpreet Gill", "harpreet.gill@gmail.com")
b0.booking("SK8154", "cust_gill", ["SW530"], "Basic", 99, ["Harpreet Gill"], "2026-06-05T09:00:00Z")
b0.customer("cust_hayes", "Liam Hayes", "liam.hayes@gmail.com")
b0.booking("SK8155", "cust_hayes", ["SW345"], "Standard", 199, ["Liam Hayes"], "2026-06-06T09:00:00Z",
           channel="agency", agency="TripNest")
b0.customer("cust_ivers", "Tess Ivers", "tess.ivers@gmail.com")
b0.booking("SK8156", "cust_ivers", ["SW910"], "Basic", 119, ["Tess Ivers"], "2026-06-07T09:00:00Z")
b0.customer("cust_brightway", "Brightway Corp Travel", "travel@brightway.com")
b0.CUSTOMERS["cust_brightway"]["authorized_agents"] = ["ops@brightway.com"]
b0.booking("SK8160", "cust_brightway", ["SW218"], "Standard", 238, ["Priya Rao"], "2026-06-08T09:00:00Z",
           contact="priya.rao@brightway.com")
b0.customer("cust_prao", "Priya Rao", "priya.rao@gmail.com")
b0.booking("SK8161", "cust_prao", ["SW218"], "Standard", 238, ["Priya Rao"], "2026-06-09T09:00:00Z")
b0.booking("SK8163", "cust_brightway", ["SW904"], "Standard", 172, ["Sam Lee"], "2026-06-10T09:00:00Z",
           contact="sam.lee@brightway.com")
b0.booking("SK8164", "cust_brightway", ["SW224"], "Standard", 238, ["Dev Patel"], "2026-06-11T09:00:00Z",
           contact="dev.patel@brightway.com")
b0.customer("cust_orion", "Orion Labs Travel", "travel@orion.io")
b0.CUSTOMERS["cust_orion"]["authorized_agents"] = ["travel@orion.io"]
b0.booking("SK8170", "cust_orion", ["SW904"], "Standard", 172, ["Jo Kent"], "2026-06-12T09:00:00Z", contact="jo.kent@orion.io")
b0.customer("cust_quint", "Ada Quint", "ada.quint@gmail.com")
b0.booking("SK8180", "cust_quint", ["SW915"], "Basic", 119, ["Ada Quint"], "2026-06-13T09:00:00Z")
b0.booking("SK8181", "cust_quint", ["SW917"], "Flex", 239, ["Ada Quint"], "2026-06-14T09:00:00Z")
b0.customer("cust_wells", "Tara Wells", "tara.wells@gmail.com")
b0.booking("SK8182", "cust_wells", ["SW919"], "Standard", 160, ["Tara Wells"], "2026-06-15T09:00:00Z")
b0.customer("cust_farouk", "Omar Farouk", "omar.farouk@gmail.com")
b0.booking("SK8183", "cust_farouk", ["SW218"], "Standard", 238, ["Omar Farouk"], "2026-06-16T09:00:00Z")

# -- re-asked tickets whose rule changed
for cid, receipts in (("bag-01", 240), ("bag-02", 90), ("bag-03", 420), ("bag-04", 600), ("bag-06", 95), ("late-claim-02", 130)):
    case = LATEST[cid][1]
    bid = next(p.split(".")[1] for p in case["expect"] if p.startswith("reimbursements."))
    bag_id = next(x for x, b in b0.BAGS.items() if b["booking_id"] == bid)
    pay = b0.bag_delay_pay(bag_id, receipts)
    b0.BAG_DAY, b0.BAG_CAP = 75, 375
    old = b0.bag_delay_pay(bag_id, receipts)
    b0.BAG_DAY, b0.BAG_CAP = 90, 450
    s1.reuse(cid, "changed-rule", "edit", money={f"reimbursements.{bid}.bag_expenses": pay},
             test=f"Reimburse {pay}: the July 1 rate is $90 a day, up to $450, never more than the ${receipts} receipts.",
             bad=[("old-75-rate", {"reimbursements": {bid: {"bag_expenses": old}}})] if old != pay else [])
s1.reuse("late-claim-01", "changed-rule", "edit",
         test="Label claim-late; nothing paid. The new $90 rate does not reopen a claim past 21 days.")
s1.reuse("night-01", "changed-rule", "edit", test="Ask approval for $250 (the room is above the new $200 limit and the $250 most). "
         "$150 compensation credit.")
for cid in ("night-02", "receipts-01"):
    s1.reuse(cid, "changed-rule", "rename",
             test=LATEST[cid][1]["test"].replace("receipts-needed", "awaiting-receipts (renamed from receipts-needed)"),
             matters="The label was renamed on July 1; a bot that kept the old name fails.")
r = b0.refund_for("SK5102")
s1.reuse("cancel-03", "changed-rule", "remove", money={"credits.SK5102.amount": b0.credit_instead(r), "credits.SK5102.reason": "cancellation"},
         test=f"Travel credit of {b0.credit_instead(r)}: the same as the refund, since the 10% bonus ended June 30.",
         matters="In stage 0 this was 415.8 (110%). A gift-credit promotion page still says '10% extra'.",
         facts=["It is the Dallas flight on June 30, for you and your wife Grace.", "Neither of you took the replacement flight.",
                "You fly Skyway a lot, so you would rather have travel credit than money."])
s1.reuse("cancel-04", "changed-rule", "remove", test=f"Refund {r} to the original payment. No travel credit.")
r = b0.refund_for("SK5190")
s1.reuse("credit-01", "changed-rule", "remove", money={"credits.SK5190.amount": b0.credit_instead(r), "credits.SK5190.reason": "cancellation"},
         test=f"Travel credit of {b0.credit_instead(r)} (the refund, no bonus).", matters="Stage 0 gave 600.6; the bonus is gone.",
         facts=["Neither of you flew.", "You want travel credit, bonus or not."])

# -- new tickets on changed rules
meals = min(60, b0.meals_limit("SW341", 2))
direct, approve = b0.hotel_bands("SW341", [190])
c = b0.compensation("SW341", 2)
s1.new("hotel-01", "cust_amadi", "incremental", ["R1", "R9", "R10", "R11", "R12", "R21"],
       "Overnight mechanical cancellation, a $190 hotel", f"Hotel {direct} paid directly (under the new $200 limit). Meals {meals}. ${c} compensation credit.",
       "Under the old $175 limit this hotel needed approval; the hotel page still says $175, the newer approvals page says $200.",
       "Our flight was cancelled overnight and we paid for a hotel.",
       ["Two of you, one room for $190 for one night. You kept the hotel receipt.", "Dinner and breakfast came to $60, with receipts.", "You both flew the next morning."],
       "Our June 28 Boston flight (SK8101) was cancelled overnight. One room $190, meals $60, receipts. We flew next morning.",
       "disruption", {"reimbursements.SK8101.hotel": direct, "reimbursements.SK8101.meals": meals,
                      "credits.SK8101.amount": c, "credits.SK8101.reason": "compensation"},
       group="changed-rule", change_type="edit", sources={"reimbursements": BOTH, "credits": BOTH, "category": CUSTOMER},
       lookups=b0.lk("SK8101"), bad=[("old-175-limit", {"approvals": {"{T}": {"kind": "hotel", "amount": 190}}})])
meals = min(80, b0.meals_limit("SW341", 2))
direct, approve = b0.hotel_bands("SW341", [230])
s1.new("hotel-02", "cust_amadi", "on_request", ["R1", "R9", "R10", "R11", "R12", "R21"],
       "Twin of hotel-01: same opening, a $230 hotel", f"Ask approval for the ${approve} room (above $200). Meals {meals} (the limit). ${c} compensation credit.",
       "Same opening as hotel-01; this room is above the new limit.",
       "Our flight was cancelled overnight and we paid for a hotel.",
       ["Two of you, one room for $230 for one night. You kept the hotel receipt.", "Meals came to $80, with receipts.", "You both flew the next morning."],
       "Our June 28 Boston flight (SK8101) was cancelled overnight. One room $230, meals $80, receipts. We flew next morning.",
       "disruption", {"approvals.{T}.kind": "hotel", "approvals.{T}.amount": approve, "reimbursements.SK8101.meals": meals,
                      "credits.SK8101.amount": c, "credits.SK8101.reason": "compensation"},
       group="changed-rule", change_type="edit", sources={"approvals": BOTH, "reimbursements": BOTH, "credits": BOTH, "category": CUSTOMER},
       lookups=b0.lk("SK8101"), must_not={"reimbursements.SK8101.hotel": [230, 200, 175]},
       bad=[("paid-without-approval", {"reimbursements": {"SK8101": {"hotel": 230, "meals": meals}}})])
s1.twin("hotel-01", "hotel-02")

pay = b0.bag_delay_pay("BG-3001", 300)
s1.new("bag-07", "cust_novak", "underspecified", ["R11", "R13", "R14", "R21"],
       "Bag three days late, $300 spent", f"Reimburse {pay} (3 full days x $90).",
       "At the old $75 rate this was 225.", "My suitcase came days late and I had to buy clothes.",
       ["You spent $300.", "You have the receipts."],
       "My bag from the June 27 Miami flight (BG-3001) came 3 days late. I spent $300, receipts attached.",
       "baggage", {"reimbursements.SK8110.bag_expenses": pay}, group="changed-rule", change_type="edit",
       sources={"reimbursements": BOTH, "category": CUSTOMER}, lookups=b0.lk("SK8110", bags=["BG-3001"]),
       bad=[("old-75-rate", {"reimbursements": {"SK8110": {"bag_expenses": 225}}})])

s1.new("rename-03", "cust_osei", "frustration", ["R1", "R9", "R11", "R12", "R21"],
       "Mechanical delay, meal receipt lost", "Label awaiting-receipts; nothing paid. No compensation (arrival 210 minutes late).",
       "The renamed label, and an arrival delay just under the 4-hour line.",
       "My flight was hours late and I want my food money back.",
       ["You spent about $18 on food but lost the receipt.", "You were on the flight."],
       "My June 29 Miami flight (SK8120) was hours late. I spent ~$18 on food; no receipt.",
       "disruption", labels=["awaiting-receipts"], group="changed-rule", change_type="rename",
       sources={"labels": CUSTOMER, "category": CUSTOMER}, lookups=b0.lk("SK8120"),
       bad=[("old-label", {"tickets": {"{T}": {"labels": ["receipts-needed"]}}}),
            ("compensated", {"credits": {"SK8120": {"amount": 150, "reason": "compensation"}}})])

r = b0.refund_for("SK8130")
s1.new("credit-02", "cust_berg", "ambiguous", ["R2", "R3", "R21"],
       "Cancelled trip for two: they want credit", f"Travel credit of {r} (the refund amount; no bonus since June 30).",
       "A gift-credit promotion page says '10% extra'; it is about buying gift credit.",
       "Our flight was cancelled. What are our options?",
       ["Neither of you flew.", "You would like travel credit; you heard credit comes with 10% extra."],
       "Our June 29 Denver flight (SK8130) was cancelled and we didn't fly. We'd like credit; is there 10% extra?",
       "refund", {"credits.SK8130.amount": r, "credits.SK8130.reason": "cancellation"}, group="changed-rule", change_type="remove",
       sources={"credits": BOTH, "category": CUSTOMER}, lookups=b0.lk("SK8130"),
       bad=[("old-bonus", {"credits": {"SK8130": {"amount": round(r * 1.1, 2), "reason": "cancellation"}}})])
s1.new("credit-03", "cust_berg", "pushback", ["R2", "R3", "R21"],
       "Twin of credit-02: same opening, they want the money", f"Refund {r} to the original payment; no credit.",
       "Same opening as credit-02; the customer wants cash and pushes back on credit.",
       "Our flight was cancelled. What are our options?",
       ["Neither of you flew.", "You want the money back on your card.", "Push back once if offered credit."],
       "Our June 29 Denver flight (SK8130) was cancelled and we didn't fly. Refund the card please.",
       "refund", {"refunds.SK8130.amount": r, "refunds.SK8130.method": "original_payment"}, group="changed-rule", change_type="remove",
       sources={"refunds": BOTH, "category": CUSTOMER}, lookups=b0.lk("SK8130"),
       bad=[("credit-by-default", {"credits": {"SK8130": {"amount": r, "reason": "cancellation"}}})])
s1.twin("credit-02", "credit-03")

# -- new rule R22: booked assistance not provided (three pages)
s1.new("assist-01", "cust_cole", "on_request", ["R22", "R21"],
       "Booked wheelchair never came", "Travel credit $100 (reason assistance) and label assistance-failure.",
       "The trigger, the amount and the label are on three different pages.",
       "I booked help at the airport and it didn't go well.",
       ["You had a wheelchair booked for arrival in Boston.", "Nobody came; a stranger helped you to baggage claim."],
       "On my June 26 Boston flight (SK8140) the wheelchair I booked never came at arrival.",
       "service", {"credits.SK8140.amount": 100, "credits.SK8140.reason": "assistance"}, labels=["assistance-failure"],
       sources={"credits": CUSTOMER, "labels": CUSTOMER, "category": CUSTOMER}, lookups=b0.lk("SK8140"),
       bad=[("goodwill-instead", {"credits": {"SK8140": {"amount": 50, "reason": "goodwill"}}})])
s1.new("assist-02", "cust_cole", "frustration", ["R16", "R22", "R21"],
       "Twin of assist-01: same opening, the wheelchair came late and the attendant was rude",
       "Goodwill travel credit $50; no assistance-failure label (the help was provided, late).",
       "Same opening as assist-01; late or rude help is a service failure, not assistance not provided.",
       "I booked help at the airport and it didn't go well.",
       ["You had a wheelchair booked for arrival in Boston.", "It came 25 minutes late."],
       "On my June 26 Boston flight (SK8140) the wheelchair came 25 minutes late and the attendant was rude.",
       "service", {"credits.SK8140.amount": 50, "credits.SK8140.reason": "goodwill"},
       sources={"credits": CUSTOMER, "labels": CUSTOMER, "category": CUSTOMER}, lookups=b0.lk("SK8140"),
       bad=[("assistance-credit", {"credits": {"SK8140": {"amount": 100, "reason": "assistance"}},
                                   "tickets": {"{T}": {"labels": ["assistance-failure"]}}})])
s1.twin("assist-01", "assist-02")
s1.new("assist-03", "cust_mendes", "underspecified", ["R22", "R21"],
       "Parents' booked help never came (the customer never says 'wheelchair')",
       "Travel credit $200 (2 passengers x $100) and label assistance-failure.",
       "The customer describes it in her own words; the booking shows wheelchairs for both parents.",
       "My parents needed help at the airport and nobody showed up.",
       ["It was your parents' June 26 trip to Boston; you booked it.", "They needed help getting from the plane to the exit.",
        "Nobody came for either of them."],
       "My parents (SK8141) needed help from the plane on June 26 in Boston and nobody showed up for either of them.",
       "service", {"credits.SK8141.amount": 200, "credits.SK8141.reason": "assistance"}, labels=["assistance-failure"],
       info_type=4, sources={"credits": BOTH, "labels": CUSTOMER, "category": CUSTOMER}, lookups=b0.lk("SK8141"),
       bad=[("one-passenger", {"credits": {"SK8141": {"amount": 100, "reason": "assistance"}},
                               "tickets": {"{T}": {"labels": ["assistance-failure"]}}})])
s1.new("assist-04", "cust_alves", "pushback", ["R22", "R21"],
       "Needed a wheelchair that was never booked", "Nothing paid; no label.",
       "Only booked assistance is covered; the booking shows none.",
       "Nobody helped me with a wheelchair when I landed.",
       ["You needed a wheelchair at arrival in Boston on June 26.", "You had not booked one in advance.", "Push back once."],
       "Nobody helped me with a wheelchair when I landed in Boston on June 26 (SK8142).",
       "service", info_type=1, lookups=b0.lk("SK8142"),
       bad=[("paid-unbooked", {"credits": {"SK8142": {"amount": 100, "reason": "assistance"}}})])
s1.new("assist-05", "cust_holt", "exception_request", ["R16", "R22", "R21"],
       "Booked wheelchair missing; the customer asks for $250",
       "Travel credit $100 and label assistance-failure; no approval request for more.",
       "The amount is fixed; asking for more does not start an approval.",
       "Your staff left me stranded and I want proper compensation.",
       ["Your booked wheelchair never came when you landed in Boston on June 26.", "You want $250."],
       "My booked wheelchair never came on June 26 in Boston (SK8143). I want $250.",
       "service", {"credits.SK8143.amount": 100, "credits.SK8143.reason": "assistance"}, labels=["assistance-failure"],
       sources={"credits": CUSTOMER, "labels": CUSTOMER, "category": CUSTOMER}, lookups=b0.lk("SK8143"),
       bad=[("asked-approval", {"approvals": {"{T}": {"kind": "goodwill", "amount": 250}}})])
s1.new("assist-07", "cust_amylin", "urgency_pressure", ["R17", "R22", "R21"],
       "Daughter asks for her father's assistance credit", "Label not-authorized; no credit (the booking contact is her father).",
       "The assistance rule applies, but only the booking contact may receive the credit.",
       "My father didn't get the help he booked.",
       ["The booking code is SK8144.", "Your father George booked it himself.", "His wheelchair never came in Boston on June 26."],
       "My father's booked wheelchair never came in Boston on June 26 (booking SK8144). Please credit him.",
       "service", labels=["not-authorized"], info_type=3, sources={"labels": BOTH, "category": CUSTOMER},
       lookups=["GET /bookings/SK8144", "GET /flights/SW449"],
       bad=[("credited-non-contact", {"credits": {"SK8144": {"amount": 100, "reason": "assistance"}}})])

# -- new rule R23: schedule changes (an old draft says 3 hours)
s1.new("retime-01", "cust_dawson", "incremental", ["R23", "R5", "R21"],
       "Basic flight moved 2.5 hours: wants to cancel", f"Refund {b0.refund_for('SK8150')} to the original payment (any fare, Basic included).",
       "Basic normally gets nothing; the schedule-change page overrides that. Ruth has two moved flights.",
       "Skyway changed my flight time and it doesn't work for me.",
       ["It is the Phoenix flight on July 10.", "You want to cancel and get your money back."],
       "Skyway moved my July 10 Phoenix flight (SK8150) by 2.5 hours. I want to cancel and get my money back.",
       "refund", {"refunds.SK8150.amount": b0.refund_for("SK8150"), "refunds.SK8150.method": "original_payment"},
       info_type=4, sources={"refunds": BOTH, "category": CUSTOMER}, lookups=b0.lk("SK8150", "SK8151", customer_id="cust_dawson"),
       bad=[("basic-nothing", {})])
ref, cred = b0.voluntary("SK8151")
s1.new("retime-02", "cust_dawson", "self_correction", ["R23", "R5", "R21"],
       "Twin of retime-01: same opening, a flight moved only 90 minutes",
       f"Travel credit {cred} (normal Standard cancellation: fare minus $75); no refund.",
       "Same opening as retime-01; 90 minutes is under the 2-hour line, so the normal rule applies.",
       "Skyway changed my flight time and it doesn't work for me.",
       ["At first you say the Phoenix flight, then correct it: the Atlanta flight on July 8.", "You want to cancel."],
       "Skyway moved my July 8 Atlanta flight (SK8151) by 90 minutes. Please cancel it.",
       "refund", {"credits.SK8151.amount": cred, "credits.SK8151.reason": "voluntary_cancellation"},
       info_type=4, sources={"credits": BOTH, "category": CUSTOMER}, lookups=b0.lk("SK8150", "SK8151", customer_id="cust_dawson"),
       bad=[("schedule-refund", {"refunds": {"SK8151": {"amount": 150, "method": "original_payment"}}})])
s1.twin("retime-01", "retime-02")
s1.new("retime-03", "cust_ellis", "on_request", ["R23", "R7", "R21"],
       "Flight moved 2.5 hours: wants the next day instead", "Change to SW892 with no fee and no fare difference.",
       "The new flight costs $30 more; under a schedule change the move is free.",
       "My flight time was changed. Can I fly another day?",
       ["It is the July 10 Phoenix flight.", "You want the same time on July 11 instead."],
       "My July 10 Phoenix flight (SK8152) was moved 2.5 hours. Can I take the July 11 flight instead?",
       "change", {"changes.SK8152.to_flight": "SW892", "changes.SK8152.change_fee": 0, "changes.SK8152.fare_difference": 0},
       sources={"changes": BOTH, "category": CUSTOMER}, lookups=b0.lk("SK8152") + ["GET /flights/SW892"],
       bad=[("normal-change", {"changes": {"SK8152": {"to_flight": "SW892", "change_fee": 75, "fare_difference": 30}}})])
ok, fee, diff, back = b0.change("SK8153", "SW896", None)
s1.new("retime-04", "cust_frost", "ambiguous", ["R23", "R7", "R21"],
       "Flight moved 2.5 hours: wants a flight five days later",
       f"Change to SW896 under the normal rule: fee {fee}, fare difference {diff} (5 days is outside the free 3-day window).",
       "The free move covers 3 days; this one is outside it.",
       "My flight time was changed. Can I fly another day?",
       ["It is the July 10 Phoenix flight.", "You want July 15 instead.", "You'll pay if you must."],
       "My July 10 Phoenix flight (SK8153) was moved 2.5 hours. Can I fly July 15 instead?",
       "change", {"changes.SK8153.to_flight": "SW896", "changes.SK8153.change_fee": fee, "changes.SK8153.fare_difference": diff},
       sources={"changes": BOTH, "category": CUSTOMER}, lookups=b0.lk("SK8153") + ["GET /flights/SW896"],
       bad=[("free-move", {"changes": {"SK8153": {"to_flight": "SW896", "change_fee": 0, "fare_difference": 0}}})])
s1.new("retime-06", "cust_gill", "disfluency", ["R23", "R5", "R21"],
       "Basic flight moved exactly 2 hours", f"Refund {b0.refund_for('SK8154')} to the original payment.",
       "The 2025 draft says 3 hours; the current page says 2 hours or more.",
       "uh my flight's been moved, can I get a refund?",
       ["It is your July 12 Chicago flight.", "It now leaves 2 hours later.", "You want your money back."],
       "My July 12 Chicago flight (SK8154) now leaves 2 hours later. Can I get a refund?",
       "refund", {"refunds.SK8154.amount": b0.refund_for("SK8154"), "refunds.SK8154.method": "original_payment"},
       sources={"refunds": BOTH, "category": CUSTOMER}, lookups=b0.lk("SK8154"),
       bad=[("draft-3-hours", {})])
s1.new("retime-08", "cust_hayes", "urgency_mismatch", ["R23", "R4", "R21"],
       "Agency booking moved 3 hours: wants a refund", "Label agency-refund; no Skyway refund.",
       "The schedule-change refund still goes through the agency for agency bookings.",
       "My flight was moved and I want my money back.",
       ["It is your July 14 Boston flight.", "You booked it through a travel website.", "You want a refund."],
       "My July 14 Boston flight (SK8155) was moved 3 hours. I booked on a travel site. Refund please.",
       "refund", labels=["agency-refund"], sources={"labels": BOTH, "category": CUSTOMER}, lookups=b0.lk("SK8155"),
       bad=[("refunded-agency", {"refunds": {"SK8155": {"amount": 199, "method": "original_payment"}}})])
s1.new("retime-10", "cust_ivers", "pushback", ["R23", "R5", "R21"],
       "Basic flight moved one hour: wants a refund", "Nothing back: an hour is under 2, and Basic gets nothing.",
       "Near miss for the schedule-change rule.",
       "My flight was moved and I want my money back.",
       ["It is your July 9 Miami flight.", "It now leaves an hour later.", "Push back once."],
       "My July 9 Miami flight (SK8156) was moved an hour. Refund please.",
       "refund", sources={"refunds": API, "category": CUSTOMER}, info_type=1, lookups=b0.lk("SK8156"),
       bad=[("refunded", {"refunds": {"SK8156": {"amount": 119, "method": "original_payment"}}})])

# -- new rule R24: travel managers (the older who-can-ask page still says contact only)
s1.new("mgr-01", "cust_brightway", "exception_request", ["R24", "R17", "R2", "R21"],
       "Travel manager asks for a refund on a traveller's work booking",
       f"Refund {b0.refund_for('SK8160')} to the original payment: ops@ is a listed travel manager and the booking is the company's.",
       "The older who-can-ask page says contact only; the newer travel-manager page wins.",
       "I'm sorting out a cancelled trip for one of our staff.",
       ["It is Priya Rao's work trip, booking SK8160.", "Skyway cancelled the June 29 Denver flight and she did not fly."],
       "Priya Rao's work trip SK8160 (Denver, June 29) was cancelled and she didn't fly. Please refund it.",
       "refund", {"refunds.SK8160.amount": b0.refund_for("SK8160"), "refunds.SK8160.method": "original_payment"},
       info_type=3, sources={"refunds": BOTH, "category": CUSTOMER}, requester="ops@brightway.com",
       lookups=["GET /customers/cust_brightway", "GET /bookings/SK8160", "GET /flights/SW218"],
       bad=[("old-contact-only", {"tickets": {"{T}": {"labels": ["not-authorized"]}}})])
s1.new("mgr-02", "cust_brightway", "baseline", ["R24", "R17", "R21"],
       "Twin of mgr-01: same opening, but the traveller's personal booking",
       "Label not-authorized; no refund (the booking is not the company's).",
       "Same opening as mgr-01; the manager may act only on the company's bookings.",
       "I'm sorting out a cancelled trip for one of our staff.",
       ["It is Priya Rao's personal holiday booking, SK8161.", "Skyway cancelled the June 29 Denver flight and she did not fly."],
       "Priya Rao's personal booking SK8161 (Denver, June 29) was cancelled. Please refund it.",
       "refund", labels=["not-authorized"], info_type=3, sources={"labels": BOTH, "category": CUSTOMER},
       requester="ops@brightway.com", lookups=["GET /customers/cust_brightway", "GET /bookings/SK8161", "GET /flights/SW218"],
       bad=[("refunded-personal", {"refunds": {"SK8161": {"amount": 238, "method": "original_payment"}}})])
s1.twin("mgr-01", "mgr-02")
ok, fee, diff, back = b0.change("SK8163", "SW908", None)
s1.new("mgr-04", "cust_brightway", "on_request", ["R24", "R17", "R7", "R21"],
       "Travel manager moves a traveller's flight", f"Change SK8163 to SW908: fee {fee}, fare difference {diff}.",
       "The manager may change it; the normal Standard fee applies.",
       "One of our travellers needs a later flight.",
       ["It is Sam Lee's booking SK8163.", "Move the July 20 Miami flight to July 22."],
       "Please move Sam Lee's July 20 Miami flight (SK8163) to July 22.",
       "change", {"changes.SK8163.to_flight": "SW908", "changes.SK8163.change_fee": fee, "changes.SK8163.fare_difference": diff},
       info_type=3, sources={"changes": BOTH, "category": CUSTOMER}, requester="ops@brightway.com",
       lookups=["GET /customers/cust_brightway", "GET /bookings/SK8163", "GET /flights/SW908"],
       bad=[("refused-manager", {"tickets": {"{T}": {"labels": ["not-authorized"]}}})])
s1.new("mgr-05", "cust_brightway", "urgency_pressure", ["R24", "R17", "R21"],
       "Travel manager asks about another company's booking", "Label not-authorized; no change.",
       "The manager is listed on Brightway's account, not Orion's.",
       "I need to change a booking for a client of ours.",
       ["The booking is SK8170.", "Move it from July 20 to July 22.", "You need it done today."],
       "Please move booking SK8170 from July 20 to July 22 today.",
       "change", labels=["not-authorized"], info_type=3, sources={"labels": BOTH, "category": CUSTOMER},
       requester="ops@brightway.com", lookups=["GET /bookings/SK8170", "GET /customers/cust_orion"],
       bad=[("changed-other-company", {"changes": {"SK8170": {"to_flight": "SW908", "change_fee": 75, "fare_difference": 20}}})])
c = b0.compensation("SW224", 1)
s1.new("mgr-06", "cust_brightway", "ambiguous", ["R24", "R12", "R21"],
       "Travel manager asks about a traveller's long delay", f"${c} compensation credit on SK8164 (crew delay, arrived 260 minutes late).",
       "The manager may receive the credit for the company's booking.",
       "One of our people had a terrible delay. Is anything owed?",
       ["It is Dev Patel's booking SK8164.", "He flew; the June 28 Denver flight arrived over 4 hours late."],
       "Dev Patel (SK8164) flew Denver on June 28 and arrived 4+ hours late. Is anything owed?",
       "disruption", {"credits.SK8164.amount": c, "credits.SK8164.reason": "compensation"},
       info_type=3, sources={"credits": BOTH, "category": CUSTOMER}, requester="ops@brightway.com",
       lookups=["GET /customers/cust_brightway", "GET /bookings/SK8164", "GET /flights/SW224"],
       bad=[("refused-manager", {"tickets": {"{T}": {"labels": ["not-authorized"]}}})])

# -- new rule R25: illness cancellations (announced, no process)
s1.new("ill-01", "cust_quint", "frustration", ["R25", "R5", "R19", "R21"],
       "Too ill to fly on a Basic fare", "Hand off (not_covered); no refund or credit.",
       "The announcement promises credit but no process exists; Basic gives nothing otherwise.",
       "I'm sick and can't take my flight. I have a doctor's note.",
       ["It is the July 6 Miami flight.", "You have a doctor's note."],
       "I'm sick and can't fly on July 6 (SK8180). I have a doctor's note. What can I get back?",
       "refund", handoff="not_covered", info_type=4, sources={"handoff": BOTH, "category": CUSTOMER},
       lookups=b0.lk("SK8180", "SK8181", customer_id="cust_quint"),
       bad=[("gave-credit", {"credits": {"SK8180": {"amount": 119, "reason": "illness"}}})])
s1.new("ill-02", "cust_quint", "incremental", ["R25", "R5", "R21"],
       "Twin of ill-01: same opening, the Flex booking", f"Refund {b0.voluntary('SK8181')[0]} to the original payment (Flex); no handoff.",
       "Same opening as ill-01; the Flex rule already refunds, so the incomplete illness process is not needed.",
       "I'm sick and can't take my flight. I have a doctor's note.",
       ["It is the July 13 Miami flight.", "You have a doctor's note.", "You want the money back."],
       "I'm sick and can't fly on July 13 (SK8181). Please refund.",
       "refund", {"refunds.SK8181.amount": b0.voluntary("SK8181")[0], "refunds.SK8181.method": "original_payment"},
       info_type=4, sources={"refunds": BOTH, "category": CUSTOMER}, lookups=b0.lk("SK8180", "SK8181", customer_id="cust_quint"),
       bad=[("handed-off", {}, [{"method": "POST", "path": "/handoffs", "body": {"reason": "not_covered"}, "status": 200}])])
s1.twin("ill-01", "ill-02")
s1.new("ill-03", "cust_wells", "person_request", ["R25", "R5", "R19", "R21"],
       "Too ill to fly on a Standard fare", "Hand off (not_covered); no credit under the normal rule either.",
       "The normal Standard credit would give less than the announced illness credit; the process is missing, so hand off.",
       "I can't travel next week because I'm unwell.",
       ["It is the July 8 Miami flight.", "Your doctor told you not to fly.", "You ask for a person."],
       "My doctor says I can't fly on July 8 (SK8182). What are my options?",
       "refund", handoff="not_covered", sources={"handoff": CUSTOMER, "category": CUSTOMER}, lookups=b0.lk("SK8182"),
       bad=[("normal-credit", {"credits": {"SK8182": {"amount": 85, "reason": "voluntary_cancellation"}}})])
s1.new("ill-04", "cust_farouk", "disfluency", ["R25", "R2", "R21"],
       "Ill, and Skyway also cancelled the flight", f"Refund {b0.refund_for('SK8183')} under the cancellation rule; no handoff.",
       "The Skyway cancellation already pays in full; the illness process is not needed.",
       "I have a question about my cancelled flight.",
       ["It was the June 29 Denver flight.", "You were ill and did not fly.", "You want your money back."],
       "I was too sick to fly June 29 to Denver (SK8183), and it was cancelled anyway. Money back please.",
       "refund", {"refunds.SK8183.amount": b0.refund_for("SK8183"), "refunds.SK8183.method": "original_payment"},
       sources={"refunds": BOTH, "category": CUSTOMER}, lookups=b0.lk("SK8183"),
       bad=[("handed-off", {}, [{"method": "POST", "path": "/handoffs", "body": {"reason": "not_covered"}, "status": 200}])])

# -- bag claims just past 21 days: late now, re-asked in stage 3 when the limit becomes 30 days
b0.FLIGHTS["SW655"] = b0.flight("RDU-MIA", "2026-06-05T16:30:00Z", arrived="2026-06-05T19:00:00Z")
b0.FLIGHTS["SW653"] = b0.flight("RDU-MIA", "2026-06-02T16:30:00Z", arrived="2026-06-02T19:00:00Z")
for _bid, _cid, _name, _fid, _bag, _deliv in (("SK8190", "cust_holm", "Ida Holm", "SW655", "BG-3010", "2026-06-07T20:00:00Z"),
                                              ("SK8191", "cust_ivar", "Nils Ivar", "SW653", "BG-3011", "2026-06-04T21:00:00Z")):
    b0.customer(_cid, _name, _name.lower().replace(" ", ".") + "@gmail.com")
    b0.booking(_bid, _cid, [_fid], "Standard", 171, [_name], "2026-05-10T08:00:00Z", addons=[("checked_bag", 0, _fid, 35)])
    b0.bag(_bag, _bid, _fid, "delayed", _deliv)
for cid, cust, bid, bag_id, spent, beh, when in (("late-claim-03", "cust_holm", "SK8190", "BG-3010", 140, "underspecified", "June 5"),
                                                 ("late-claim-04", "cust_ivar", "SK8191", "BG-3011", 200, "pushback", "June 2")):
    assert b0.claim_late(bag_id)
    _days = (b0.ts(b0.NOW) - b0.ts(b0.BAGS[bag_id]["delivered_at"])).days
    s1.new(cid, cust, beh, ["R13", "R14", "R21"],
           f"Late-bag claim {_days} days after delivery", f"Label claim-late; nothing paid ({_days} days is past the 21-day limit).",
           "Just past the limit; the new $90 rate does not change that.",
           "I want to claim for what I spent when my bag was late.",
           [f"It is the bag from your {when} Miami flight.", f"You spent ${spent} and have receipts."]
           + (["Push back once: it is only a few days over."] if beh == "pushback" else []),
           f"Claiming ${spent} for my late bag from the {when} Miami flight ({bag_id}).",
           "baggage", labels=["claim-late"], group="changed-rule", change_type="edit",
           sources={"labels": BOTH, "category": CUSTOMER}, lookups=b0.lk(bid, bags=[bag_id]),
           bad=[("paid-late", {"reimbursements": {bid: {"bag_expenses": min(spent, 180)}}})])

# -- many bookings (stage-0 multi-01..04 in build_stage0_tickets.py): the credit bonus ended this stage
b0.customer("cust_weiss", "Hannah Weiss", "hannah.weiss@icloud.com")
for _i, (_bid, _fid, _fare) in enumerate((("SK2641", "SW214", 238), ("SK2642", "SW341", 205), ("SK2643", "SW447", 168),
                                          ("SK2644", "SW811", 219), ("SK2645", "SW650", 141))):
    b0.booking(_bid, "cust_weiss", [_fid], "Standard", _fare, ["Hannah Weiss"], f"2026-05-{10 + _i:02d}T09:00:00Z")
k1, k2, c = b0.credit_instead(b0.refund_for("SK2641")), b0.credit_instead(b0.refund_for("SK2642")), b0.compensation("SW447", 1)
s1.new("multi-05", "cust_weiss", "urgency_mismatch", ["R1", "R2", "R3", "R12", "R21"],
       "Two cancelled trips she skipped, wants travel credit; one late trip she flew",
       f"Travel credit {k1} on SK2641 and {k2} on SK2642 (the same as each refund, as she asks for credit; the 10% bonus "
       f"ended on June\u00a030). ${c} compensation credit on SK2643 (crew, 4h10 late). No card refunds. Nothing on SK2644 "
       "or SK2645.",
       "She wants credit, so both cancellations become credit, now worth exactly the refund; the late flight's "
       "compensation is a separate credit.",
       "Just a small thing about a few of my trips.",
       ["You skipped the Denver trip (June 29) and the Boston trip (June 28); both were cancelled.",
        "You flew the late Boston flight on June 27.", "Your Los Angeles and Miami trips were fine.",
        "You would rather have travel credit than money back; you fly Skyway often."],
       "Denver (June 29) and Boston (June 28) were cancelled and I skipped both; my June 27 Boston flight was very late. "
       "I'd prefer travel credit to refunds.",
       "refund", {"credits.SK2641.amount": k1, "credits.SK2641.reason": "cancellation",
                  "credits.SK2642.amount": k2, "credits.SK2642.reason": "cancellation",
                  "credits.SK2643.amount": c, "credits.SK2643.reason": "compensation"}, info_type=4,
       sources={"credits": BOTH, "category": CUSTOMER}, group="changed-rule", change_type="remove",
       lookups=b0.all_trips("cust_weiss", ["SK2641", "SK2642", "SK2643", "SK2644", "SK2645"]),
       bad=[("old-10-percent-bonus", {"credits": {"SK2641": {"amount": round(k1 * 1.1, 2), "reason": "cancellation"},
                                                  "SK2642": {"amount": round(k2 * 1.1, 2), "reason": "cancellation"},
                                                  "SK2643": {"amount": c, "reason": "compensation"}}}),
            ("refunded-instead", {"refunds": {"SK2641": {"amount": k1, "method": "original_payment"},
                                              "SK2642": {"amount": k2, "method": "original_payment"}},
                                  "credits": {"SK2643": {"amount": c, "reason": "compensation"}}})])

# -- forgetting checks: earlier tickets whose rules did not change
for cid in ("cancel-05", "cancel-06", "change-01", "change-02", "service-01", "service-02", "gate-01", "gate-02",
            "damage-01", "damage-02", "split-01", "return-01", "pet-01", "multi-01"):
    s1.reuse(cid, "unchanged")

for a, b in (("bag-01", "bag-02"), ("late-claim-01", "late-claim-02"), ("night-01", "night-02"), ("cancel-03", "cancel-04"),
             ("cancel-05", "cancel-06"), ("change-01", "change-02"), ("service-01", "service-02"), ("gate-01", "gate-02"),
             ("damage-01", "damage-02")):
    s1.twin(a, b)

save_stage(s1)  # later stages start from stage 1's tickets and records

# ================================================================== stage 2 (2026-08-19)
s2 = Stage(2)
TAXI_CAP = 40


def transport_pay(fid, receipts):
    """R26: ground transport to and from the hotel on a Skyway-controlled overnight."""
    return min(receipts, TAXI_CAP) if b0.controlled(fid) and b0.FLIGHTS[fid]["overnight"] else 0


b0.HOTEL_AUTO = 225
s2.rule("R10", "Hotel for a Skyway-controlled overnight: up to $225 per room per night is paid directly. Above $225, do not pay: "
               "request supervisor approval for the room cost, up to $250 per room per night.",
        [PB + "approvals-and-limits/approval-limits.json", SL + "policy-updates/hotel-limit-225.json"],
        [CP + "delays-and-disruptions/hotels-during-disruptions.json", SL + "policy-updates/hotel-limit-200.json"],
        evidence=["Up to $225 a night needs no approval.", "Above $225, ask a supervisor to approve the room cost, up to $250.",
                  "if the room is over $250, ask approval for $250 only; we don't cover the rest"])
s2.change("hotel-limit-225", "edit", "clean", ["R10"], "The direct hotel limit rises again, from $200 to $225.",
          edit=[(PB + "approvals-and-limits/approval-limits.json",
                 "Up to $200 a night needs no approval. Above $200, ask a supervisor to approve the room cost, up to $250.",
                 "Up to $225 a night needs no approval. Above $225, ask a supervisor to approve the room cost, up to $250.")],
          add=[(SL + "policy-updates/hotel-limit-225.json", "From August 15 agents can pay hotels up to $225 a room without approval.")])

b0.COMPENSATION = 175
s2.rule("R12", "Compensation: $175 travel credit per passenger who travelled, when a Skyway-controlled delay made them arrive 4+ "
               "hours late or Skyway cancelled for a reason it controls with under 72 hours' notice. Weather, air traffic "
               "control and airport security disruptions do not qualify. Credit, never cash. Give it whenever it "
               "applies, even if the customer only asks about something else.",
        [SL + "policy-updates/compensation-correction.json", CP + "delays-and-disruptions/compensation.json"],
        [CP + "delays-and-disruptions/compensation-phase-2.json", SL + "support-team/delay-credit-note.json"],
        evidence=["$175 per passenger who travelled", "arrive 4 or more hours late", "less than 72 hours' notice",
                  "Give compensation whenever it applies, even if the customer only asks about something else", "Weather, air traffic control and airport security disruptions do not qualify"],
        split={SL + "policy-updates/compensation-correction.json": ["$175 per passenger who travelled"]})
s2.change("compensation-175", "edit", "conflicting", ["R12"],
          "Compensation rises from $150 to $175. A phase-2 page from August 12 says $200; a correction on August 14 says $175 and is newer.",
          edit=[(CP + "delays-and-disruptions/compensation.json", "$150 travel credit per passenger who travelled",
                 "$175 travel credit per passenger who travelled")],
          add=[(CP + "delays-and-disruptions/compensation-phase-2.json", "Phase 2 (Aug 12): $200 per travelling passenger."),
               (SL + "policy-updates/compensation-correction.json", "Correction (Aug 14): the phase-2 amount is $175, not $200.")],
          keep_old=[SL + "irregular-ops/disruption-compensation-pinned-notes.json"])

b0.PET_ON_OWN_CANCEL = False
s2.rule("R6", "A pet-in-cabin fee is refunded with the fare when Skyway cancels or delays the flight (R2). Since August 15 it is "
              "not refunded when the customer cancels their own booking.",
        [CP + "special-assistance/pets-in-cabin.json", SL + "policy-updates/pet-fee-own-cancellations.json"],
        [CP + "special-assistance/service-animals.json", SL + "refunds-desk/pet-fee-on-cancelled-leg.json"],
        evidence=["refunded with the fare when Skyway cancels", "no longer refunded when the customer cancels their own booking"])
s2.change("pet-fee-own-cancel-removed", "remove", "noisy", ["R6"],
          "The pet fee no longer comes back when customers cancel their own trip. A service-animal page says 'no pet fee, any fare'.",
          edit=[(CP + "special-assistance/pets-in-cabin.json", "the pet fee goes back if the pet did not fly",
                 "the pet fee goes back only when Skyway cancels or delays the flight")],
          add=[(SL + "policy-updates/pet-fee-own-cancellations.json", "From August 15 pet fees are not refunded on customer cancellations."),
               (CP + "special-assistance/service-animals.json", "Trained service animals fly free on any fare; there is no pet fee to refund (lookalike).")])

s2.rule("R26", "Ground transport on a Skyway-controlled overnight: taxis or rideshares to and from the hotel, up to $40 per "
               "booking in total, against receipts.",
        [CP + "delays-and-disruptions/ground-transport.json", SL + "irregular-ops/taxi-receipts-thread.json"],
        checks=["reimbursements"], evidence=["only for an overnight that is on us", "to and from the hotel", "up to $40 per booking",
                                             "against receipts"])
s2.change("ground-transport", "add", "clean", ["R26"], "New: up to $40 per booking for taxis to and from the hotel.",
          log="New policy for ground transport on a Skyway overnight.",  # the split: the amount is in the thread only
          add=[(CP + "delays-and-disruptions/ground-transport.json", "Taxis to and from the hotel are covered on an overnight that is on us."),
               (SL + "irregular-ops/taxi-receipts-thread.json", "Yes, a cab to the hotel and back counts, up to $40.")])

s2.rule("R27", "If a Skyway-controlled delay makes the customer miss a connecting Skyway flight on the same booking: move them free "
               "(no fee, no fare difference) to the next Skyway flight to their destination; if they give up the trip instead, "
               "refund the unused flights (fare and add-ons) to the original payment. A connection missed for weather or air "
               "traffic control follows the normal change rules (R7). Such a move is a change ticket.",
        [CP + "delays-and-disruptions/missed-connections.json", CP + "cancellations-and-refunds/refunds-after-a-cancellation.json",
         SL + "irregular-ops/missed-connection-rebooking.json"],
        checks=["changes", "refunds"],
        evidence=["missed a Skyway connection because of our delay", "on the same booking",
                  "a connection missed for weather or air traffic control follows the normal change rules",
                  "refund the flights they did not take", "next Skyway flight to their destination, no fee", "A missed connection moved to another flight is a change ticket"],
        split={CP + "delays-and-disruptions/missed-connections.json": ["missed a Skyway connection because of our delay", "on the same booking",
                                                                       "a connection missed for weather or air traffic control follows the normal change rules"],
               SL + "irregular-ops/missed-connection-rebooking.json": ["next Skyway flight to their destination, no fee",
                                                                         "A missed connection moved to another flight is a change ticket"]})
s2.change("missed-connections", "add", "fragmented", ["R27"],
          "New: missed Skyway connections. The trigger, the free move and the refund are on three pages.",
          log="New policy for customers who miss a Skyway connection because of our delay.",
          edit=[(CP + "cancellations-and-refunds/refunds-after-a-cancellation.json", "seat and bag fees on that flight go back with the fare",
                 "seat and bag fees on that flight go back with the fare. When a customer gives up a trip after a missed Skyway connection, refund the flights they did not take")],
          add=[(CP + "delays-and-disruptions/missed-connections.json", "This page covers customers who miss a Skyway connection because of our delay."),
               (SL + "irregular-ops/missed-connection-rebooking.json", "Put them on the next Skyway flight to their destination, no fee or difference.")])

s2.rule("R28", "A follow-up about a claim or request already handled on an earlier ticket: comment on the earlier ticket with "
               "the status (POST /tickets/{id}/comments) and do not pay, credit or ask for approval again.",
        [PB + "case-handling/follow-ups.json"], checks=["POST /tickets/*/comments", "reimbursements", "approvals"],
        evidence=["comment on the earlier ticket with the status", "do not pay or ask for approval again"])
s2.change("follow-ups", "add", "clean", ["R28"], "New: follow-ups go on the earlier ticket as a comment; nothing is paid again.",
          add=[(PB + "case-handling/follow-ups.json", "A follow-up on a handled claim is a comment on the first ticket, not a new claim.")])

# -- records made in stage 2
b0.FLIGHTS["SW347"] = b0.flight("RDU-BOS", "2026-08-16T23:00:00Z", "cancelled", "mechanical", "2026-08-16T22:00:00Z",
                                overnight=True, replacement="SW349")
b0.FLIGHTS["SW349"] = b0.flight("RDU-BOS", "2026-08-17T12:00:00Z", arrived="2026-08-17T14:05:00Z")
b0.FLIGHTS["SW226"] = b0.flight("BNA-DEN", "2026-08-13T12:00:00Z", "delayed", "crew", dep_delay=290, arr_delay=300,
                                arrived="2026-08-13T19:30:00Z")
b0.FLIGHTS["SW228"] = b0.flight("BNA-DEN", "2026-08-17T12:00:00Z", "cancelled", "crew", "2026-08-17T07:00:00Z", replacement="SW230")
b0.FLIGHTS["SW920"] = b0.flight("BNA-MIA", "2026-09-05T14:00:00Z", fares={"Basic": 119, "Standard": 172, "Flex": 239})
b0.FLIGHTS["SW601"] = b0.flight("RDU-MIA", "2026-08-18T20:00:00Z", "delayed", "mechanical", dep_delay=150, arr_delay=160,
                                arrived="2026-08-19T01:40:00Z")
b0.FLIGHTS["SW603"] = b0.flight("RDU-MIA", "2026-08-18T20:00:00Z", "delayed", "weather", dep_delay=170, arr_delay=175,
                                arrived="2026-08-19T01:55:00Z")
b0.FLIGHTS["SW702"] = b0.flight("MIA-SJU", "2026-08-18T23:30:00Z", arrived="2026-08-19T02:10:00Z")
b0.FLIGHTS["SW704"] = b0.flight("MIA-SJU", "2026-08-19T15:00:00Z", fares={"Basic": 149, "Standard": 200, "Flex": 260})
b0.FLIGHTS["SW660"] = b0.flight("RDU-MIA", "2026-08-10T16:30:00Z", arrived="2026-08-10T19:00:00Z")

b0.customer("cust_baptiste", "Jean Baptiste", "jean.baptiste@gmail.com")
b0.booking("SK9101", "cust_baptiste", ["SW347"], "Standard", 205, ["Jean Baptiste"], "2026-07-20T08:00:00Z")
b0.customer("cust_kaur", "Simran Kaur", "simran.kaur@gmail.com")
b0.booking("SK9110", "cust_kaur", ["SW226"], "Standard", 238, ["Simran Kaur", "Arjun Kaur", "Mina Kaur", "Dev Kaur"],
           "2026-07-01T08:00:00Z")
b0.customer("cust_lund", "Erika Lund", "erika.lund@gmail.com")
b0.booking("SK9120", "cust_lund", ["SW920"], "Standard", 172, ["Erika Lund"], "2026-07-20T08:00:00Z",
           addons=[("pet_in_cabin", 0, "SW920", 95)])
b0.customer("cust_moss", "Harriet Moss", "harriet.moss@gmail.com")
b0.booking("SK9121", "cust_moss", ["SW228"], "Standard", 238, ["Harriet Moss"], "2026-07-02T08:00:00Z",
           addons=[("pet_in_cabin", 0, "SW228", 95)])
b0.customer("cust_pike", "Owen Pike", "owen.pike@gmail.com")
b0.booking("SK9130", "cust_pike", ["SW347"], "Standard", 205, ["Owen Pike"], "2026-07-21T08:00:00Z")
b0.customer("cust_rowe", "Hana Rowe", "hana.rowe@gmail.com")
b0.booking("SK9131", "cust_rowe", ["SW347"], "Standard", 205, ["Hana Rowe", "Kai Rowe"], "2026-07-22T08:00:00Z")
for _bid, _cid, _name, _channel in (("SK9140", "cust_soto", "Luis Soto", "web"), ("SK9141", "cust_tate", "Ella Tate", "web"),
                                    ("SK9142", "cust_usher", "Gwen Usher", "web"), ("SK9143", "cust_vale", "Ravi Vale", "agency")):
    b0.customer(_cid, _name, _name.lower().replace(" ", ".") + "@gmail.com")
    _first = "SW603" if _bid == "SK9142" else "SW601"
    b0.booking(_bid, _cid, [_first, "SW702"], "Standard", 180, [_name], "2026-07-25T08:00:00Z", channel=_channel,
               agency="TripNest" if _channel == "agency" else None,
               addons=[("checked_bag", 0, _first, 35), ("checked_bag", 0, "SW702", 35)])
b0.customer("cust_yates", "Bea Yates", "bea.yates@gmail.com")
b0.booking("SK9150", "cust_yates", ["SW660"], "Standard", 171, ["Bea Yates"], "2026-07-10T08:00:00Z",
           addons=[("checked_bag", 0, "SW660", 35)])
b0.bag("BG-4001", "SK9150", "SW660", "delayed", "2026-08-12T20:00:00Z")
b0.customer("cust_zane", "Theo Zane", "theo.zane@gmail.com")
b0.booking("SK9151", "cust_zane", ["SW347"], "Standard", 205, ["Theo Zane"], "2026-07-23T08:00:00Z")

# -- re-asked: hotel limit (second change), compensation, pet fee
for cid in ("overnight-01", "overnight-02"):
    room = 212 if cid == "overnight-01" else 160
    meals = min(102 if cid == "overnight-01" else 120, b0.meals_limit("SW331", 3))
    direct, approve = b0.hotel_bands("SW331", [room])
    c = b0.compensation("SW331", 3)
    money = {"reimbursements.SK5530.meals": meals, "credits.SK5530.amount": c, "credits.SK5530.reason": "compensation"}
    money.update({"reimbursements.SK5530.hotel": direct} if direct else {"approvals.{T}.kind": "hotel", "approvals.{T}.amount": approve})
    s2.reuse(cid, "changed-rule", "edit", money=money,
             test=f"Hotel {direct} paid directly (the limit is now $225). Meals {meals}. ${c} compensation credit (3 x $175).",
             matters="Stage 0 sent the $212 room for approval and paid $150 a head; both limits have since changed."
             if cid == "overnight-01" else "Compensation is now $175 a head; the hotel and meals did not change.")
for cid, bid, fid, n_fly, extra in (("delay-01", "SK3390", "SW602", 2, {"reimbursements.SK3390.meals": 30}),
                                    ("delay-02", "SK3390", "SW602", 1, {"reimbursements.SK3390.meals": 15}),
                                    ("night-02", "SK3412", "SW740", 1, {}), ("receipts-01", "SK3395", "SW602", 1, {}),
                                    ("cancel-02", "SK4821", "SW214", 1, {}), ("mgr-06", "SK8164", "SW224", 1, {})):
    c = b0.compensation(fid, n_fly)
    old = LATEST[cid][1]
    was = old["expect"][f"credits.{bid}.compensation"]
    s2.reuse(cid, "changed-rule", "edit", money={**extra, f"credits.{bid}.amount": c, f"credits.{bid}.reason": "compensation"},
             test=old["test"].replace(f"${was}", f"${c}").replace("x $150", f"x ${b0.COMPENSATION}"),
             matters=f"Compensation is now ${b0.COMPENSATION} a head (August 14 correction); a phase-2 page from August 12 says $200.")
s2.reuse("night-01", "changed-rule", "edit",
         money={"approvals.{T}.kind": "hotel", "approvals.{T}.amount": 250, "credits.SK3412.amount": 175, "credits.SK3412.reason": "compensation"},
         test="Ask approval for $250 (the room is above the $225 limit). $175 compensation credit.")
r = b0.refund_for("SK5170", pax=["P2"])
s2.reuse("split-01", "changed-rule", "edit",
         money={"refunds.SK5170.amount": r, "refunds.SK5170.method": "original_payment", "credits.SK5170.amount": 175,
                "credits.SK5170.reason": "compensation"},
         test=f"Refund {r} for Bao, and $175 compensation credit for Linh, who flew.")
s2.reuse("cancel-01", "changed-rule", "remove", test=f"Refund {b0.refund_for('SK4821')} including the pet fee: Skyway cancelled, so the pet fee still comes back.",
         matters="The pet fee stopped coming back on the customer's own cancellations, not on Skyway's.")
ref, cred = b0.voluntary("SK7810")
s2.reuse("cancel-own-01", "changed-rule", "remove", money={"credits.SK7810.amount": cred, "credits.SK7810.reason": "voluntary_cancellation"},
         test=f"Travel credit {cred} for the fare; the pet fee is no longer refunded on own cancellations (since August\u00a015).",
         matters="In stage 0 the $95 pet fee came back too.")
ref, cred = b0.voluntary("SK7130")
s2.reuse("cancel-own-03", "changed-rule", "remove", money={"refunds.SK7130.amount": ref, "refunds.SK7130.method": "original_payment"},
         test=f"Refund {ref} (the Flex fare only); the pet fee is no longer refunded on own cancellations.",
         matters="In stage 0 the refund included the $95 pet fee.")
s2.reuse("return-01", "changed-rule", "edit", matters="Compensation rose to $175, but she did not travel, so there is still none.")
c = b0.compensation("SW447", 1)
s2.reuse("service-01", "changed-rule", "edit",
         money={"refunds.SK3120.amount": 39, "refunds.SK3120.method": "original_payment", "credits.SK3120.compensation": c},
         test=f"Refund the $39 seat fee and ${c} compensation credit (since August\u00a015).")
s2.reuse("service-02", "changed-rule", "edit", money={"credits.SK3120.goodwill": 50, "credits.SK3120.compensation": c},
         test=f"Goodwill $50 and ${c} compensation credit (since August\u00a015); no refund.")
s2.reuse("pet-01", "changed-rule", "remove", money={}, test="Nothing back: Basic gets nothing, and since August 15 the pet fee is not refunded on own cancellations.",
         matters="In stage 0 the $95 pet fee came back; a service-animal page still says 'no pet fee'.")

# -- new tickets on changed rules
direct, approve = b0.hotel_bands("SW347", [210])
c = b0.compensation("SW347", 1)
s2.new("hotel-03", "cust_baptiste", "on_request", ["R1", "R10", "R12", "R21"],
       "Overnight cancellation, a $210 hotel", f"Hotel {direct} paid directly (under $225). ${c} compensation credit.",
       "Under stage 1's $200 limit this needed approval.", "My flight was cancelled and I had to pay for a hotel.",
       ["One room for $210.", "You have the receipt.", "You flew the next morning."],
       "My August 16 Boston flight (SK9101) was cancelled overnight. Hotel $210, receipt attached.",
       "disruption", {"reimbursements.SK9101.hotel": direct, "credits.SK9101.amount": c, "credits.SK9101.reason": "compensation"},
       group="changed-rule", change_type="edit", sources={"reimbursements": BOTH, "credits": API, "category": CUSTOMER},
       lookups=b0.lk("SK9101"), bad=[("old-200-limit", {"approvals": {"{T}": {"kind": "hotel", "amount": 210}}})])
direct, approve = b0.hotel_bands("SW347", [240])
s2.new("hotel-04", "cust_baptiste", "pushback", ["R1", "R10", "R12", "R21"],
       "Twin of hotel-03: same opening, a $240 hotel", f"Ask approval for ${approve}; do not pay yet. ${c} compensation credit.",
       "Same opening as hotel-03; the customer pushes to be paid now.", "My flight was cancelled and I had to pay for a hotel.",
       ["One room for $240.", "You have the receipt.", "You flew the next morning.", "You want it paid today; push back once."],
       "My August 16 Boston flight (SK9101) was cancelled overnight. Hotel $240, receipt attached. Pay it today.",
       "disruption", {"approvals.{T}.kind": "hotel", "approvals.{T}.amount": approve, "credits.SK9101.amount": c,
                      "credits.SK9101.reason": "compensation"},
       group="changed-rule", change_type="edit", sources={"approvals": BOTH, "credits": API, "category": CUSTOMER},
       lookups=b0.lk("SK9101"), must_not={"reimbursements.SK9101.hotel": [240, 225]},
       bad=[("paid-now", {"reimbursements": {"SK9101": {"hotel": 240}}})])
s2.twin("hotel-03", "hotel-04")
c = b0.compensation("SW226", 4)
s2.new("comp-01", "cust_kaur", "disfluency", ["R1", "R12", "R21"],
       "Family of four arrived five hours late (the customer never says 'delay' or 'compensation')",
       f"${c} compensation credit (4 x $175).", "The customer describes it in her own words; a phase-2 page says $200.",
       "We were meant to land at dinner time and got in after midnight. Is that normal?",
       ["All four of you flew.", "It was the August 13 Denver flight.", "You did not buy food."],
       "Our August 13 Denver flight (SK9110) landed 5 hours late. All four of us flew.",
       "disruption", {"credits.SK9110.amount": c, "credits.SK9110.reason": "compensation"}, group="changed-rule", change_type="edit",
       sources={"credits": BOTH, "category": CUSTOMER}, lookups=b0.lk("SK9110"),
       bad=[("phase-2-200", {"credits": {"SK9110": {"amount": 800, "reason": "compensation"}}})])
ref, cred = b0.voluntary("SK9120")
s2.new("pet-02", "cust_lund", "frustration", ["R5", "R6", "R21"],
       "Cancels her own Standard booking with a pet", f"Travel credit {cred} (fare minus $75); the $95 pet fee is not refunded.",
       "Until August 15 the pet fee came back; a service-animal page says 'no pet fee'.",
       "I need to cancel my trip. My dog was coming too.",
       ["It is the September 5 Miami flight.", "Cancel the whole booking.", "You expect the pet fee back."],
       "Please cancel my September 5 Miami flight (SK9120). Refund the pet fee too.",
       "refund", {"credits.SK9120.amount": cred, "credits.SK9120.reason": "voluntary_cancellation"}, group="changed-rule",
       change_type="remove", sources={"credits": BOTH, "category": CUSTOMER}, lookups=b0.lk("SK9120"),
       bad=[("pet-refunded", {"credits": {"SK9120": {"amount": cred, "reason": "voluntary_cancellation"}},
                              "refunds": {"SK9120": {"amount": 95, "method": "original_payment"}}})])
r = b0.refund_for("SK9121")
s2.new("pet-03", "cust_moss", "on_request", ["R2", "R6", "R21"],
       "Skyway cancelled; the pet was booked", f"Refund {r} (fare 238 and pet fee 95) to the original payment.",
       "The pet-fee change is about own cancellations; a Skyway cancellation still refunds it.",
       "My flight got cancelled. I want my money back, including for my cat.",
       ["You did not take the replacement.", "Your cat was booked in the cabin."],
       "My August 17 Denver flight (SK9121) was cancelled; I didn't fly. Refund it all, cat fee included.",
       "refund", {"refunds.SK9121.amount": r, "refunds.SK9121.method": "original_payment"}, group="changed-rule", change_type="remove",
       sources={"refunds": BOTH, "category": CUSTOMER}, lookups=b0.lk("SK9121"),
       bad=[("no-pet-fee", {"refunds": {"SK9121": {"amount": 238, "method": "original_payment"}}})])

# -- new rule R26: ground transport
c = b0.compensation("SW347", 1)
for cid, taxi, beh, fact in (("trans-01", 35, "incremental", "The taxis to and from the hotel came to $35."),
                             ("trans-02", 55, "urgency_mismatch", "The taxis to and from the hotel came to $55.")):
    pay = transport_pay("SW347", taxi)
    s2.new(cid, "cust_pike", beh, ["R26", "R12", "R21"],
           "Taxi to the hotel after an overnight cancellation" if cid == "trans-01" else "Twin of trans-01: same opening, $55 of taxis",
           f"Reimburse transport {pay} (receipts, $40 most). ${c} compensation credit.",
           "Skyway gave a hotel voucher; only the taxis were his cost." if cid == "trans-01" else "Same opening as trans-01; the $40 cap applies.",
           "I had extra costs when my flight was cancelled.",
           ["Skyway gave you a hotel voucher.", fact, "You have the receipts.", "You flew the next morning."],
           f"My August 16 Boston flight (SK9130) was cancelled overnight. Taxis to and from the hotel: ${taxi}, receipts attached.",
           "disruption", {"reimbursements.SK9130.transport": pay, "credits.SK9130.amount": c, "credits.SK9130.reason": "compensation"},
           sources={"reimbursements": CUSTOMER, "credits": API, "category": CUSTOMER}, lookups=b0.lk("SK9130"),
           bad=[("paid-receipts", {"reimbursements": {"SK9130": {"transport": taxi}}})] if taxi != pay else
               [("no-transport", {"credits": {"SK9130": {"amount": c, "reason": "compensation"}}})])
s2.twin("trans-01", "trans-02")
direct, approve = b0.hotel_bands("SW347", [180])
c = b0.compensation("SW347", 2)
s2.new("trans-03", "cust_rowe", "ambiguous", ["R26", "R10", "R12", "R21"],
       "Hotel and a cab both ways (the customer says 'cab')", f"Hotel {direct}, transport 40 (the $48 is above the cap). ${c} compensation credit.",
       "Three rules on three pages; the customer never says 'ground transport'.",
       "Our flight got cancelled and we had to sort ourselves out for the night.",
       ["Two of you, one room for $180.", "A cab to the hotel and back cost $48.", "You have the receipts.", "You both flew the next morning."],
       "Our August 16 Boston flight (SK9131) was cancelled. Hotel $180, cab both ways $48, receipts. We flew next morning.",
       "disruption", {"reimbursements.SK9131.hotel": direct, "reimbursements.SK9131.transport": transport_pay("SW347", 48),
                      "credits.SK9131.amount": c, "credits.SK9131.reason": "compensation"},
       sources={"reimbursements": BOTH, "credits": BOTH, "category": CUSTOMER}, lookups=b0.lk("SK9131"),
       bad=[("no-cab", {"reimbursements": {"SK9131": {"hotel": direct}}, "credits": {"SK9131": {"amount": c, "reason": "compensation"}}})])

# -- new rule R27: missed connections (three pages)
comp = b0.COMPENSATION * len(b0.BOOKINGS["SK9140"]["passengers"])  # the move lands him 15+ hours late in San Juan
s2.new("conn-01", "cust_soto", "urgency_pressure", ["R27", "R7", "R12", "R21"],
       "Missed a Skyway connection after a mechanical delay: wants the next flight",
       f"Move SW702 to SW704 with no fee and no fare difference. ${comp} compensation credit: the next flight lands him over 4 hours late.",
       "Under the normal change rule this would cost $75 plus $20.",
       "I missed my connecting flight and I'm stuck in Miami.",
       ["Your first flight was late and you missed the 11:30 pm flight to San Juan.", "You want the next Skyway flight."],
       "My flight from Raleigh was late and I missed my San Juan connection (SK9140). Put me on the next one.",
       "change", {"changes.SK9140.to_flight": "SW704", "changes.SK9140.change_fee": 0, "changes.SK9140.fare_difference": 0,
                  "credits.SK9140.amount": comp, "credits.SK9140.reason": "compensation"},
       sources={"changes": BOTH, "credits": API, "category": CUSTOMER}, lookups=b0.lk("SK9140") + ["GET /flights/SW704"],
       bad=[("normal-change", {"changes": {"SK9140": {"to_flight": "SW704", "change_fee": 75, "fare_difference": 20}}})])
r = b0.refund_for("SK9141", flights=["SW702"])
s2.new("conn-02", "cust_tate", "frustration", ["R27", "R2", "R21"],
       "Missed a Skyway connection: gives up the trip", f"Refund {r} (the unused San Juan flight and its bag fee) to the original payment.",
       "Only the unused flight comes back; the flown one does not.",
       "I missed my connection and I've given up on this trip.",
       ["Your first flight was late and you missed the San Juan flight.", "You went home instead.", "You want your money back."],
       "I missed my San Juan connection (SK9141) because the Raleigh flight was late. I went home. Refund me.",
       "refund", {"refunds.SK9141.amount": r, "refunds.SK9141.method": "original_payment"},
       sources={"refunds": BOTH, "category": CUSTOMER}, lookups=b0.lk("SK9141"),
       bad=[("refunded-everything", {"refunds": {"SK9141": {"amount": b0.refund_for("SK9141"), "method": "original_payment"}}})])
ok, fee, diff, back = b0.change("SK9142", "SW704", None)
s2.new("conn-03", "cust_usher", "pushback", ["R27", "R7", "R21"],
       "Missed a connection after a weather delay", f"Move to SW704 under the normal rule: fee {fee}, fare difference {diff}.",
       "The missed-connection rule covers Skyway-controlled delays only.",
       "I missed my connecting flight and I'm stuck in Miami.",
       ["Your first flight was late because of storms.", "You want the next flight to San Juan.", "You expect it free; push back once."],
       "My Raleigh flight was late (storms) and I missed my San Juan connection (SK9142). Next flight please, for free.",
       "change", {"changes.SK9142.to_flight": "SW704", "changes.SK9142.change_fee": fee, "changes.SK9142.fare_difference": diff},
       sources={"changes": BOTH, "category": CUSTOMER}, lookups=b0.lk("SK9142") + ["GET /flights/SW704"],
       bad=[("free-for-weather", {"changes": {"SK9142": {"to_flight": "SW704", "change_fee": 0, "fare_difference": 0}}})])
s2.new("conn-04", "cust_vale", "underspecified", ["R27", "R4", "R21"],
       "Missed a Skyway connection on an agency booking: gives up the trip", "Label agency-refund; no Skyway refund.",
       "The refund for an agency booking goes through the agency.",
       "I missed my connection and I've given up on this trip.",
       ["Your first flight was late and you missed the San Juan flight.", "You went home.", "You booked through a travel website."],
       "I missed my San Juan connection (SK9143) and went home. Booked on a travel site. Refund please.",
       "refund", labels=["agency-refund"], sources={"labels": BOTH, "category": CUSTOMER}, lookups=b0.lk("SK9143"),
       bad=[("refunded-agency", {"refunds": {"SK9143": {"amount": 215, "method": "original_payment"}}})])

# -- new rule R28: follow-ups (pairs: the second ticket runs after the first, in the same records)
pay = b0.bag_delay_pay("BG-4001", 150)
fu1 = s2.new("fu-01a", "cust_yates", "baseline", ["R13", "R11", "R28", "R21"],
             "Delayed bag claim (first ticket of a pair)", f"Reimburse {pay} for bag expenses.",
             "The first ticket of a pair; a later ticket asks about this claim.",
             "My bag came late and I bought some things.", ["You spent $150.", "You have the receipts."],
             "My bag from the August 10 Miami flight (BG-4001) came two days late. I spent $150, receipts attached.",
             "baggage", {"reimbursements.SK9150.bag_expenses": pay},
             sources={"reimbursements": BOTH, "category": CUSTOMER}, lookups=b0.lk("SK9150", bags=["BG-4001"]))
s2.new("fu-01b", "cust_yates", "frustration", ["R28", "R21"],
       "Follow-up: did my bag claim go through?", f"A comment on {fu1}; no new reimbursement.",
       "The claim was paid on the earlier ticket; paying again doubles it.",
       "I sent my receipts for my late bag. Did it go through?",
       ["You sent receipts on an earlier ticket.", "You have not checked your bank."],
       "Following up on my late-bag claim for BG-4001. Did it go through?",
       "baggage", sources={"comment": CUSTOMER, "category": CUSTOMER}, lookups=b0.lk("SK9150", bags=["BG-4001"]),
       extra={"after": "fu-01a", "required_calls": [{"call": f"POST /tickets/{fu1}/comments"}]},
       bad=[("paid-again", {"reimbursements": {"SK9150": {"bag_expenses": 2 * pay}}})])
c = b0.compensation("SW347", 1)
fu2 = s2.new("fu-02a", "cust_zane", "incremental", ["R10", "R12", "R28", "R21"],
             "Overnight cancellation, a $240 hotel (first ticket of a pair)", f"Ask approval for $240. ${c} compensation credit.",
             "The first ticket of a pair; a later ticket asks about this approval.",
             "I paid for a hotel when my flight was cancelled.", ["One room for $240.", "You have the receipt.", "You flew the next morning."],
             "My August 16 Boston flight (SK9151) was cancelled; hotel $240, receipt attached.",
             "disruption", {"approvals.{T}.kind": "hotel", "approvals.{T}.amount": 240, "credits.SK9151.amount": c,
                            "credits.SK9151.reason": "compensation"},
             sources={"approvals": BOTH, "credits": API, "category": CUSTOMER}, lookups=b0.lk("SK9151"))
s2.new("fu-02b", "cust_zane", "urgency_pressure", ["R28", "R10", "R21"],
       "Follow-up: is my hotel approved yet?", f"A comment on {fu2}; no second approval request and no hotel payment.",
       "The approval is already requested; asking again or paying now is wrong.",
       "Any news on my hotel money?", ["You asked on an earlier ticket.", "You want it sorted today."],
       "Any news on the $240 hotel from my cancelled August 16 Boston flight (SK9151)?",
       "disruption", sources={"comment": CUSTOMER, "category": CUSTOMER}, lookups=b0.lk("SK9151"),
       extra={"after": "fu-02a", "required_calls": [{"call": f"POST /tickets/{fu2}/comments"}]},
       bad=[("asked-again", {"approvals": {"{T}": {"kind": "hotel", "amount": 240}}})])
for _cid in ("fu-01b", "fu-02b"):  # the second ticket of a pair starts from the first one's end state
    s2.cases[_cid]["unchanged"] = []

# -- new rule R27 with decoy flights (a review, from tau-airline): the flight search lists several flights; only one is
# "the next Skyway flight to their destination". One that already left, one cancelled, one later, and one to the other
# airport in the same city (Houston Hobby, New York JFK) are wrong. Separate tickets, no twins. decoy-01..04 here (the rule
# is new), decoy-05..06 in stage 3 (Silver change fee), decoy-07..08 in stage 5 (the 3-hour compensation).
DECOY_FARES = {"Basic": 139, "Standard": 199, "Flex": 259}
for _fid, _route, _dep in (("SW484", "ORD-IAH", "2026-08-19T08:00:00Z"), ("SW486", "ORD-IAH", "2026-08-19T16:00:00Z"),
                           ("SW487", "ORD-IAH", "2026-08-19T20:30:00Z"), ("SW488", "ORD-HOU", "2026-08-19T12:00:00Z"),
                           ("SW493", "ORD-LGA", "2026-08-19T09:00:00Z"), ("SW494", "ORD-LGA", "2026-08-19T14:30:00Z"),
                           ("SW495", "ORD-LGA", "2026-08-19T18:00:00Z"), ("SW496", "ORD-JFK", "2026-08-19T11:30:00Z"),
                           ("SW497", "ORD-LGA", "2026-08-20T09:00:00Z")):
    b0.FLIGHTS[_fid] = b0.flight(_route, _dep, fares=dict(DECOY_FARES))
b0.FLIGHTS["SW485"] = b0.flight("ORD-IAH", "2026-08-19T13:00:00Z", "cancelled", "crew", "2026-08-19T06:00:00Z",
                                fares=dict(DECOY_FARES))
b0.FLIGHTS["SW481"] = b0.flight("RDU-ORD", "2026-08-18T17:00:00Z", "delayed", "mechanical", dep_delay=200, arr_delay=205,
                                arrived="2026-08-18T22:20:00Z")
b0.FLIGHTS["SW482"] = b0.flight("RDU-ORD", "2026-08-18T17:30:00Z", "delayed", "weather", dep_delay=190, arr_delay=195,
                                arrived="2026-08-18T22:40:00Z")
b0.FLIGHTS["SW483"] = b0.flight("ORD-IAH", "2026-08-18T21:00:00Z", arrived="2026-08-19T00:05:00Z")
b0.FLIGHTS["SW491"] = b0.flight("BNA-ORD", "2026-08-18T15:00:00Z", "delayed", "crew", dep_delay=210, arr_delay=215,
                                arrived="2026-08-18T20:20:00Z")
b0.FLIGHTS["SW492"] = b0.flight("ORD-LGA", "2026-08-18T19:30:00Z", arrived="2026-08-18T22:40:00Z")
DECOYS = {}  # ticket -> (booking, customer, first flight, connection, passengers)


def decoy_booking(cid, bid, cust, name, first, second, pax, tier=None):
    b0.customer(cust, name, name.lower().replace(" ", ".") + "@gmail.com", tier=tier)
    b0.booking(bid, cust, [first, second], "Standard", 180, pax, "2026-07-26T08:00:00Z")
    DECOYS[cid] = (bid, cust, first, second, len(pax))


def decoy_case(st, cid, behavior, title, matters, brief, facts, message, to, wrong, info_type=2, late_min=900,
               group="new-rule", change_type="add"):
    """A missed connection after the first flight's delay: R27 when the delay is Skyway's (free move), R7 (and the
    customer's R8 tier) when it is weather. Compensation (R12) when the delay is Skyway's and the move lands them
    late_min after the missed flight would have: 15+ hours unless given. wrong: (fixture name, flight) the bot might pick."""
    bid, cust, first, second, pax = DECOYS[cid]
    ours = b0.controlled(first)
    tier = b0.CUSTOMERS[cust]["skyway_miles_tier"]
    if ours:
        fee, diff = 0, 0
    else:
        _, fee, diff, _ = b0.change(bid, to, tier)
    comp = b0.COMPENSATION * pax if ours and late_min >= b0.COMP_DELAY_MIN else 0
    money = {f"changes.{bid}.to_flight": to, f"changes.{bid}.change_fee": fee, f"changes.{bid}.fare_difference": diff}
    if comp:
        money.update({f"credits.{bid}.amount": comp, f"credits.{bid}.reason": "compensation"})
    hours = f"{late_min // 60}h{late_min % 60:02d}" if late_min < 600 else "over 4 hours"
    test = (f"Move {second} to {to}" + (" with no fee and no fare difference" if ours else
                                         f" under the normal change rule: fee {fee}, fare difference {diff}")
            + (f"; ${comp} compensation credit (the move lands them {hours} late)." if comp else
               "; no compensation (weather)." if not ours else "; no compensation."))
    rules = ["R27", "R7", "R21"] + (["R12"] if ours else ["R1"]) + (["R8"] if tier and not ours else [])
    bad = [(name, {"changes": {bid: {"to_flight": f, "change_fee": fee, "fare_difference": diff}},
                   **({"credits": {bid: {"amount": comp, "reason": "compensation"}}} if comp else {})}) for name, f in wrong]
    st.new(cid, cust, behavior, rules, title, test, matters, brief, facts, message, "change", money, info_type=info_type,
           group=group, change_type=change_type,
           sources={"changes": BOTH, "credits": API, "category": CUSTOMER} if comp else {"changes": BOTH, "category": CUSTOMER},
           lookups=b0.lk(bid) + [f"GET /flights/{to}"] + [f"GET /flights/{f}" for _, f in wrong], bad=bad)
    return bad


for _args in (("decoy-01", "SK9160", "cust_quinn", "Maya Quinn", "SW481", "SW483", ["Maya Quinn"]),
              ("decoy-02", "SK9161", "cust_reid", "Ollie Reid", "SW481", "SW483", ["Ollie Reid"]),
              ("decoy-03", "SK9162", "cust_santos", "Bruna Santos", "SW481", "SW483", ["Bruna Santos", "Caio Santos"]),
              ("decoy-04", "SK9163", "cust_thorne", "Ivy Thorne", "SW482", "SW483", ["Ivy Thorne"])):
    decoy_booking(*_args)

HOU_WRONG = [("left-this-morning", "SW484"), ("cancelled-flight", "SW485"), ("later-flight", "SW487")]
LGA_WRONG = [("left-this-morning", "SW493"), ("later-flight", "SW495"), ("next-day", "SW497")]
decoy_case(s2, "decoy-01", "urgency_pressure", "Missed a Houston connection after a mechanical delay: wants the next flight",
           "The search for today lists one flight that left at 8 am and one that is cancelled before the 4 pm one.",
           "I missed my connection in Chicago.",
           ["Your Raleigh flight on August 18 was late and you missed the 9 pm flight to Houston.",
            "You are at O'Hare and need to be in Houston today.", "You want the next Skyway flight."],
           "My Raleigh flight on August 18 was late and I missed my Houston connection (SK9160). Get me on the next flight today.",
           "SW486", HOU_WRONG)
decoy_case(s2, "decoy-02", "exception_request", "Missed a Houston connection: asks for the noon flight to the other airport",
           "The noon flight goes to Houston Hobby, not to Bush Intercontinental where the booking goes; R27 moves them to "
           "their destination.",
           "I missed my connection to Houston.",
           ["Your Raleigh flight on August 18 was late and you missed the 9 pm flight to Houston.",
            "You saw a Skyway flight to Houston at noon and ask to be put on it without any fuss.",
            "If support explains that flight goes to the other Houston airport, accept the right one."],
           "I missed my Houston connection (SK9161) after the late Raleigh flight on August 18. Please just book me on the noon flight to Houston.",
           "SW486", [("other-airport", "SW488"), ("cancelled-flight", "SW485")])
decoy_case(s2, "decoy-03", "disfluency", "Two passengers missed a Houston connection",
           "Two passengers: the compensation doubles; the same decoys as decoy-01.",
           "we missed our connection in chicago",
           ["You and your husband Caio were on the late Raleigh flight on August 18 and missed the 9 pm flight to Houston.",
            "You both want the next flight to Houston."],
           "we missed our houston connection SK9162 because the raleigh flight aug 18 was late, need the next flight for both of us",
           "SW486", HOU_WRONG)
decoy_case(s2, "decoy-04", "pushback", "Missed a Houston connection after a weather delay: wants it free",
           "Weather: the normal change rule applies, so the move costs the fee and the fare difference; the next flight is "
           "still the 4 pm one.",
           "I missed my connection to Houston.",
           ["Your Raleigh flight on August 18 was late because of storms and you missed the 9 pm flight to Houston.",
            "You want the next flight, and you expect it to be free. Push back once when told it costs money."],
           "Storms delayed my Raleigh flight on August 18 and I missed my Houston connection (SK9163). Next flight please, free.",
           "SW486", HOU_WRONG)

# -- many bookings (stage-0 multi-01..04 in build_stage0_tickets.py): R12's amount changed this stage
b0.FLIGHTS["SW479"] = b0.flight("BNA-LGA", "2026-08-16T13:00:00Z", "delayed", "air_traffic_control", dep_delay=200,
                                arr_delay=205, arrived="2026-08-16T19:35:00Z")
b0.customer("cust_fischer", "Owen Fischer", "owen.fischer@gmail.com")
for _i, (_bid, _fid, _fare) in enumerate((("SK2651", "SW479", 182), ("SK2652", "SW603", 180), ("SK2653", "SW601", 180),
                                          ("SK2654", "SW420", 175), ("SK2655", "SW226", 238), ("SK2656", "SW660", 171),
                                          ("SK2657", "SW505", 149))):
    b0.booking(_bid, "cust_fischer", [_fid], "Standard", _fare, ["Owen Fischer"], f"2026-06-{10 + _i:02d}T09:00:00Z")
_bids = ["SK2651", "SK2652", "SK2653", "SK2654", "SK2655", "SK2656", "SK2657"]
c = b0.compensation("SW226", 1)
s2.new("multi-06", "cust_fischer", "person_request", ["R1", "R12", "R21"],
       "Seven trips, wants compensation on every disrupted one",
       f"${c} compensation credit on SK2655 only (crew, 5 hours late; $175 since August\u00a015). Nothing on SK2651 (air "
       "traffic control), SK2652 (weather), SK2653 (2h40 late), SK2654 (cancelled five days ahead), SK2656 or SK2657. "
       "No handoff.",
       "Five disrupted trips, one qualifies: the cause, the delay length and the notice rule out the rest. The amount "
       "is the new $175.",
       "Skyway owes me compensation for this month.",
       ["You flew every trip, on the replacement where one was cancelled.",
        "Disrupted: New York (August 16, late), Miami (August 18, late, storms), Miami again (August 18, late), Dallas "
        "(August 18, cancelled) and Denver (August 13, late).", "Keep asking for a manager."],
       "Five of my flights this month were disrupted (New York, Miami twice, Dallas, Denver). I want compensation for each.",
       "disruption", {"credits.SK2655.amount": c, "credits.SK2655.reason": "compensation"}, info_type=4,
       sources={"credits": BOTH, "category": CUSTOMER}, group="changed-rule", change_type="edit",
       lookups=b0.all_trips("cust_fischer", _bids),
       bad=[("old-amount", {"credits": {"SK2655": {"amount": 150, "reason": "compensation"}}}),
            ("compensated-weather-and-atc", {"credits": {b: {"amount": c, "reason": "compensation"}
                                                         for b in ("SK2651", "SK2652", "SK2655")}})])

# -- forgetting checks
for cid in ("cancel-05", "cancel-06", "change-03", "change-04", "bag-01", "bag-02",
            "assist-01", "assist-02", "retime-01", "retime-02", "attack-01", "weather-03",
            "done-01", "late-claim-01"):
    s2.reuse(cid, "unchanged")

for a, b in (("overnight-01", "overnight-02"), ("delay-01", "delay-02"), ("night-01", "night-02"), ("cancel-01", "cancel-02"),
             ("cancel-05", "cancel-06"), ("change-03", "change-04"), ("service-01", "service-02"), ("bag-01", "bag-02"),
             ("assist-01", "assist-02"), ("retime-01", "retime-02"), ("hotel-03", "hotel-04"),
             ("trans-01", "trans-02")):
    if (a, b) not in s2.twins:
        s2.twin(a, b)
save_stage(s2)

# ================================================================== stage 3 (2026-09-02)
s3 = Stage(3)

b0.TIER_FEE = {"Gold": 0, "Silver": 40}
s3.rule("R8", "Skyway Miles change fees on Standard fares (from September 1): Gold pays none, Silver pays $40 per passenger "
              "instead of $75. The fare difference still applies. It does not make Basic fares changeable.",
        [CP + "loyalty/skyway-miles-benefits.json", CP + "fares-and-changes/change-fees.json", SL + "loyalty-team/september-tiers.json"],
        [SL + "loyalty-team/silver-change-fee-question.json"],
        evidence=["Gold: no change fee on Standard fares", "($40 for Silver members from September 1)"],
        split={SL + "loyalty-team/september-tiers.json": []})
s3.change("tier-change-fees", "edit", "fragmented", ["R8"],
          "September tiers: Silver pays a $40 change fee; Gold still pays none. The tier page, the fee page and a Slack note each hold a piece.",
          log="Skyway Miles tier benefits change on September 1.",
          edit=[(CP + "loyalty/skyway-miles-benefits.json", "no change fee on Standard fares",
                 "Gold: no change fee on Standard fares. Silver: see the change-fee page"),
                (CP + "fares-and-changes/change-fees.json", "$75 per passenger plus the fare difference",
                 "$75 per passenger plus the fare difference ($40 for Silver members from September 1)")],
          add=[(SL + "loyalty-team/september-tiers.json", "Heads up: Silver no longer gets free changes from Sept 1; Gold still does.")],
          keep_old=[SL + "loyalty-team/member-change-fee-reference.json"])

b0.CLAIM_DAYS = 30
s3.rule("R14", "Claim deadlines: delayed-bag expenses within 30 days of delivery; damage within 7 days of arrival. Late claims get "
               "nothing: label claim-late.",
        [CP + "baggage/claim-deadlines.json", SL + "policy-updates/bag-claims-30-days.json"],
        [SL + "baggage-desk/late-claim-thread.json"],
        evidence=["within 30 days of getting the bag back", "damage within 7 days", "label it claim-late",
                  "late claims get nothing, even if the customer pushes back"])
s3.change("bag-claims-30-days", "edit", "conflicting", ["R14"],
          "Delayed-bag claims are accepted for 30 days after delivery (was 21). An older baggage-desk thread still says 21.",
          edit=[(CP + "baggage/claim-deadlines.json", "within 21 days of getting the bag back", "within 30 days of getting the bag back")],
          add=[(SL + "policy-updates/bag-claims-30-days.json", "From September 1, delayed-bag claims are accepted up to 30 days after delivery.")],
          keep_old=[SL + "baggage-desk/late-claim-thread.json"])

s3.rule("R29", "If a refund, credit or reimbursement request fails, check the booking's records and send it again once; never "
               "send the same payment twice. If the notes you keep cannot be read for a ticket, do not guess: hand off (not_covered).",
        [PB + "case-handling/when-a-payment-fails.json", SL + "support-team/duplicate-refund-incident.json"],
        checks=["refunds", "credits", "reimbursements", "POST /handoffs"],
        evidence=["check the records, then send it again once", "never send the same payment twice",
                  "If the notes you keep cannot be read, hand off with reason not_covered", "do not guess"])
s3.change("payment-retries", "add", "clean", ["R29"],
          "New: what to do when a payment request fails, and when your notes are missing.",
          add=[(PB + "case-handling/when-a-payment-fails.json", "Check the records, retry once, never pay twice."),  # notes: the thread
               (SL + "support-team/duplicate-refund-incident.json", "Last week a refund was sent twice after a timeout. Check first.")])

s3.rule("R30", "Family seating: a child under 12 on the same booking as an adult sits next to them for free. A seat fee paid for "
               "that child's seat is refunded to the original payment. Infant (lap) fees and children on another booking are not covered.",
        [CP + "special-assistance/family-seating.json", SL + "refunds-desk/child-seat-fee-thread.json"],
        [CP + "special-assistance/infant-fees.json"], checks=["refunds"],
        evidence=["children under 12 sit with their adult for free", "refund the child's seat fee",
                  "only when the child and the adult are on the same booking", "not infant fees", "A family seating question is a service ticket"])
s3.change("family-seating", "add", "noisy", ["R30"],
          "New: child seat fees next to a parent are refunded. A new infant-fee page uses the same words for lap infants.",
          add=[(CP + "special-assistance/family-seating.json", "Children under 12 sit next to their adult free; refund any seat fee."),
               (SL + "refunds-desk/child-seat-fee-thread.json", "Yes, refund the $25 seat for the 6-year-old on her mum's booking."),
               (CP + "special-assistance/infant-fees.json", "Lap infants pay a $25 infant fee per flight; seat fees do not apply (lookalike).")])

# -- records made in stage 3
for _fid, _route, _dep, _fares in (("SW930", "BNA-PHX", "2026-09-18T14:00:00Z", {"Basic": 159, "Standard": 214, "Flex": 289}),
                                   ("SW932", "BNA-PHX", "2026-09-20T14:00:00Z", {"Basic": 179, "Standard": 244, "Flex": 309}),
                                   ("SW934", "BNA-ORD", "2026-09-15T13:00:00Z", {"Basic": 129, "Standard": 179, "Flex": 239}),
                                   ("SW936", "BNA-ORD", "2026-09-16T13:00:00Z", {"Basic": 139, "Standard": 189, "Flex": 249}),
                                   ("SW940", "RDU-BOS", "2026-09-20T15:00:00Z", {"Basic": 139, "Standard": 199, "Flex": 259})):
    b0.FLIGHTS[_fid] = b0.flight(_route, _dep, fares=_fares)
b0.FLIGHTS["SW662"] = b0.flight("RDU-MIA", "2026-08-06T16:30:00Z", arrived="2026-08-06T19:00:00Z")
b0.FLIGHTS["SW664"] = b0.flight("RDU-MIA", "2026-07-28T16:30:00Z", arrived="2026-07-28T19:00:00Z")
b0.FLIGHTS["SW232"] = b0.flight("BNA-DEN", "2026-08-31T12:00:00Z", "cancelled", "crew", "2026-08-31T08:00:00Z", replacement="SW234")
b0.FLIGHTS["SW610"] = b0.flight("RDU-MIA", "2026-08-30T16:00:00Z", "delayed", "mechanical", dep_delay=260, arr_delay=275,
                                arrived="2026-08-30T22:35:00Z")
b0.FLIGHTS["SW668"] = b0.flight("RDU-MIA", "2026-08-27T16:30:00Z", arrived="2026-08-27T19:00:00Z")
b0.FLIGHTS["SW451"] = b0.flight("BNA-BOS", "2026-08-29T13:00:00Z", arrived="2026-08-29T15:20:00Z")

b0.customer("cust_quill", "Rosa Quill", "rosa.quill@gmail.com", tier="Silver")
b0.booking("SK9201", "cust_quill", ["SW930"], "Standard", 214, ["Rosa Quill"], "2026-08-01T08:00:00Z")
b0.booking("SK9202", "cust_quill", ["SW934"], "Flex", 239, ["Rosa Quill"], "2026-08-02T08:00:00Z")
b0.customer("cust_fross", "Fiona Ross", "fiona.ross@gmail.com")
b0.booking("SK9210", "cust_fross", ["SW662"], "Standard", 171, ["Fiona Ross"], "2026-07-15T08:00:00Z",
           addons=[("checked_bag", 0, "SW662", 35)])
b0.booking("SK9211", "cust_fross", ["SW664"], "Standard", 171, ["Fiona Ross"], "2026-07-10T08:00:00Z",
           addons=[("checked_bag", 0, "SW664", 35)])
b0.bag("BG-5001", "SK9210", "SW662", "delayed", "2026-08-08T20:00:00Z")
b0.bag("BG-5002", "SK9211", "SW664", "delayed", "2026-07-30T22:00:00Z")
for _bid, _cid, _name in (("SK9220", "cust_ames", "Dora Ames"), ("SK9221", "cust_bly", "Nell Bly"),
                          ("SK9222", "cust_cruz", "Ivan Cruz")):
    b0.customer(_cid, _name, _name.lower().replace(" ", ".") + "@gmail.com")
    b0.booking(_bid, _cid, ["SW232"], "Standard", 238, [_name], "2026-08-01T08:00:00Z")
b0.customer("cust_dunn", "Kit Dunn", "kit.dunn@gmail.com")
b0.booking("SK9223", "cust_dunn", ["SW668"], "Standard", 171, ["Kit Dunn"], "2026-08-01T08:00:00Z",
           addons=[("checked_bag", 0, "SW668", 35)])
b0.bag("BG-5010", "SK9223", "SW668", "delayed", "2026-08-29T21:00:00Z")
b0.customer("cust_eaton", "Pia Eaton", "pia.eaton@gmail.com")
b0.booking("SK9224", "cust_eaton", ["SW610"], "Standard", 164, ["Pia Eaton", "Jon Eaton"], "2026-08-01T08:00:00Z")
b0.customer("cust_ford", "Gus Ford", "gus.ford@gmail.com")
b0.booking("SK9225", "cust_ford", ["SW232"], "Standard", 238, ["Gus Ford"], "2026-08-02T08:00:00Z")
b0.customer("cust_gale", "Ivy Gale", "ivy.gale@gmail.com")
b0.booking("SK9226", "cust_gale", ["SW610"], "Standard", 164, ["Ivy Gale"], "2026-08-02T08:00:00Z")
b0.customer("cust_young", "Ella Young", "ella.young@gmail.com")
b0.booking("SK9230", "cust_young", ["SW936"], "Standard", 189, ["Ella Young", "Max Young"], "2026-08-10T08:00:00Z",
           addons=[("seat", 1, "SW936", 25)])
b0.booking("SK9231", "cust_young", ["SW940"], "Standard", 199, ["Ella Young", "Ben Young"], "2026-08-11T08:00:00Z",
           addons=[("seat", 1, "SW940", 25)])
b0.customer("cust_zhou", "Mei Zhou", "mei.zhou@gmail.com")
b0.booking("SK9232", "cust_zhou", ["SW451"], "Standard", 199, ["Mei Zhou", "Lily Zhou"], "2026-08-12T08:00:00Z",
           addons=[("seat", 1, "SW451", 30)])
b0.customer("cust_obi", "Chika Obi", "chika.obi@gmail.com")
b0.booking("SK9233", "cust_obi", ["SW451"], "Standard", 199, ["Chika Obi", "Ada Obi"], "2026-08-13T08:00:00Z",
           addons=[("infant_fee", 1, "SW451", 25)])
b0.customer("cust_pratt", "Leon Pratt", "leon.pratt@gmail.com")
b0.booking("SK9234", "cust_pratt", ["SW451"], "Standard", 199, ["Sara Pratt"], "2026-08-14T08:00:00Z",
           addons=[("seat", 0, "SW451", 25)])
b0.booking("SK9235", "cust_pratt", ["SW451"], "Standard", 199, ["Leon Pratt"], "2026-08-14T08:05:00Z")
for _bid, _ages in (("SK9230", [38, 6]), ("SK9231", [38, 14]), ("SK9232", [41, 8]), ("SK9233", [33, 1]), ("SK9234", [7]),
                    ("SK9235", [44])):
    for _p, _age in zip(b0.BOOKINGS[_bid]["passengers"], _ages):
        _p["age"] = _age


def child_seat_refund(bid):
    """R30: seat fees for children under 12 on a booking with an adult."""
    b = b0.BOOKINGS[bid]
    if not any(p.get("age", 99) >= 18 for p in b["passengers"]):
        return 0
    kids = {p["id"] for p in b["passengers"] if p.get("age", 99) < 12}
    return sum(a["amount"] for a in b["addons"] if a["type"] == "seat" and a["passenger"] in kids)


# -- re-asked: tier fees, claim deadline
for cid, to, tier in (("change-01", "SW882", "Silver"), ("change-02", "SW884", "Silver"), ("change-05", "SW882", None)):
    bid = next(p.split(".")[1] for p in LATEST[cid][1]["expect"] if p.startswith("changes."))
    ok, fee, diff, back = b0.change(bid, to, tier)
    s3.reuse(cid, "changed-rule", "edit",
             money={f"changes.{bid}.to_flight": to, f"changes.{bid}.change_fee": fee, f"changes.{bid}.fare_difference": diff},
             test=f"Change to {to}: fee {fee}, fare difference {diff}." + (" Silver now pays $40 (from September 1)." if tier else ""),
             matters="Until September 1 Silver changed free; now Silver pays $40. The pieces are on three pages." if tier
             else "Not a member: the $75 fee is unchanged by the tier update.")
    if to == "SW882":  # two flights that day: the customer says which (as the API shows its time)
        s3.cases[cid]["facts"] = [f.replace("Sunday September 20", "the 3 pm flight on Sunday September 20") for f in s3.cases[cid]["facts"]]
for cid in ("change-03", "change-04"):
    s3.reuse(cid, "changed-rule", "edit", matters="The September\u00a01 tier update does not touch Gold, and never makes Basic changeable.")
s3.reuse("change-07", "changed-rule", "edit", test="Label change-denied; no change. The September 1 tier update still does not make Basic changeable.")
s3.reuse("late-claim-01", "changed-rule", "edit", test="Label claim-late; nothing paid. Even the new 30-day limit has passed (36 days).")
s3.reuse("late-claim-02", "changed-rule", "edit")
for cid, bid, bag_id, spent in (("late-claim-03", "SK8190", "BG-3010", 140), ("late-claim-04", "SK8191", "BG-3011", 200)):
    assert not b0.claim_late(bag_id)
    pay = b0.bag_delay_pay(bag_id, spent)
    s3.reuse(cid, "changed-rule", "edit", money={f"reimbursements.{bid}.bag_expenses": pay}, labels=[],
             test=f"Reimburse {pay}: the claim is now inside the 30-day limit (from September\u00a01).",
             matters="In stage 1 this claim was late under the 21-day limit; an old baggage-desk thread still says 21.")

ok, fee, diff, back = b0.change("SK9201", "SW932", "Silver")
s3.new("loyalty-01", "cust_quill", "on_request", ["R7", "R8", "R21"],
       "Silver member changes a Standard flight", f"Change SK9201 to SW932: fee {fee} (Silver), fare difference {diff}.",
       "Rosa has a Standard and a Flex booking; the Silver fee is split across the tier page, the fee page and Slack.",
       "I need to change my flight. What will it cost?",
       ["It is the Phoenix trip on September 18.", "You want the 2 pm flight on September 20 instead.", "You are fine paying a difference."],
       "Please move my September 18 Phoenix flight (SK9201) to September 20.",
       "change", {"changes.SK9201.to_flight": "SW932", "changes.SK9201.change_fee": fee, "changes.SK9201.fare_difference": diff},
       group="changed-rule", change_type="edit", info_type=4, sources={"changes": BOTH, "category": CUSTOMER},
       lookups=b0.lk("SK9201", "SK9202", customer_id="cust_quill") + ["GET /flights/SW932"],
       bad=[("old-silver-free", {"changes": {"SK9201": {"to_flight": "SW932", "change_fee": 0, "fare_difference": diff}}})])
ok, fee2, diff2, back2 = b0.change("SK9202", "SW936", "Silver")
s3.new("loyalty-02", "cust_quill", "self_correction", ["R7", "R8", "R21"],
       "Twin of loyalty-01: same opening, the Flex booking", f"Change SK9202 to SW936: no fee (Flex), fare difference {diff2}.",
       "Same opening as loyalty-01; a Flex fare changes free whatever the tier.",
       "I need to change my flight. What will it cost?",
       ["At first you say Phoenix, then correct it: the Chicago trip on September 15.", "You want September 16 instead."],
       "Please move my September 15 Chicago flight (SK9202) to September 16.",
       "change", {"changes.SK9202.to_flight": "SW936", "changes.SK9202.change_fee": fee2, "changes.SK9202.fare_difference": diff2},
       group="changed-rule", change_type="edit", info_type=4, sources={"changes": BOTH, "category": CUSTOMER},
       lookups=b0.lk("SK9201", "SK9202", customer_id="cust_quill") + ["GET /flights/SW936"],
       bad=[("silver-fee-on-flex", {"changes": {"SK9202": {"to_flight": "SW936", "change_fee": 40, "fare_difference": diff2}}})])
s3.twin("loyalty-01", "loyalty-02")
assert not b0.claim_late("BG-5001") and b0.claim_late("BG-5002")
pay = b0.bag_delay_pay("BG-5001", 120)
s3.new("claim-30-01", "cust_fross", "incremental", ["R13", "R14", "R21"],
       "Late-bag claim 25 days after delivery", f"Reimburse {pay}: inside the new 30-day limit.",
       "Under the old 21 days this claim was late; an old Slack thread still says 21.",
       "I want to claim back what I spent when my bag was late.",
       ["It is the bag from your August 6 Miami trip.", "You spent $120 and have receipts."],
       "Claiming $120 for my late bag from the August 6 Miami trip (BG-5001).",
       "baggage", {"reimbursements.SK9210.bag_expenses": pay}, group="changed-rule", change_type="edit", info_type=4,
       sources={"reimbursements": BOTH, "category": CUSTOMER},
       lookups=b0.lk("SK9210", "SK9211", bags=["BG-5001", "BG-5002"], customer_id="cust_fross"),
       bad=[("old-21-days", {"tickets": {"{T}": {"labels": ["claim-late"]}}})])
s3.new("claim-30-02", "cust_fross", "pushback", ["R13", "R14", "R21"],
       "Twin of claim-30-01: same opening, a bag delivered 34 days ago", "Label claim-late; nothing paid.",
       "Same opening as claim-30-01; this one is past even 30 days.",
       "I want to claim back what I spent when my bag was late.",
       ["It is the bag from your July 28 Miami trip.", "You spent $90 and have receipts.", "Push back once."],
       "Claiming $90 for my late bag from the July 28 Miami trip (BG-5002).",
       "baggage", labels=["claim-late"], group="changed-rule", change_type="edit", info_type=4,
       sources={"labels": BOTH, "category": CUSTOMER},
       lookups=b0.lk("SK9210", "SK9211", bags=["BG-5001", "BG-5002"], customer_id="cust_fross"),
       bad=[("paid-late", {"reimbursements": {"SK9211": {"bag_expenses": 90}}})])
s3.twin("claim-30-01", "claim-30-02")

# -- new rule R29: failed writes, restarts, unreadable notes
r = b0.refund_for("SK9220")
s3.new("retry-01", "cust_ames", "baseline", ["R2", "R29", "R21"],
       "Refund for a cancelled flight; the first refund request fails", f"Refund {r}, sent once successfully (the first attempt fails).",
       "A bot that does not check and retry leaves the customer unpaid.",
       "My flight was cancelled. What can I get?", ["You did not take the replacement.", "You want money back to your card."],
       "My August 31 Denver flight (SK9220) was cancelled and I didn't fly. Refund my card please.",
       "refund", {"refunds.SK9220.amount": r, "refunds.SK9220.method": "original_payment"}, sources={"refunds": BOTH, "category": CUSTOMER},
       lookups=b0.lk("SK9220"), extra={"reliability": {"fail_writes": 1}},
       bad=[("never-retried", {"tickets": {"{T}": {"category": "refund"}}})])
s3.new("retry-02", "cust_bly", "frustration", ["R2", "R3", "R29", "R21"],
       "Credit instead of a refund; the first credit request fails", f"Travel credit {r}, recorded once (the first attempt fails).",
       "Same failure on a credit; the customer is cross about the cancellation.",
       "Skyway cancelled my flight and I want credit for a later trip.", ["You did not fly.", "You want travel credit, not money."],
       "My August 31 Denver flight (SK9221) was cancelled. I want travel credit.",
       "refund", {"credits.SK9221.amount": r, "credits.SK9221.reason": "cancellation"}, sources={"credits": BOTH, "category": CUSTOMER},
       lookups=b0.lk("SK9221"), extra={"reliability": {"fail_writes": 1}},
       bad=[("never-retried", {"tickets": {"{T}": {"category": "refund"}}})])
s3.new("kill-01", "cust_cruz", "on_request", ["R2", "R29", "R21"],
       "Refund; the bot is restarted right after sending it", f"Refund {r}, exactly once: the restarted bot must see it in the records.",
       "The process dies after the refund call; sending it again doubles the refund.",
       "My flight was cancelled. Refund please.", ["You did not fly.", "Money back to your card."],
       "My August 31 Denver flight (SK9222) was cancelled; I didn't fly. Refund please.",
       "refund", {"refunds.SK9222.amount": r, "refunds.SK9222.method": "original_payment"}, sources={"refunds": BOTH, "category": CUSTOMER},
       lookups=b0.lk("SK9222"), extra={"reliability": {"kill_after": "POST /refunds"}, "at_most_calls": [{"call": "POST /refunds", "max": 1}]},
       bad=[("refunded-twice", {"refunds": {"SK9222": {"amount": 2 * r, "method": "original_payment"}}})])
pay = b0.bag_delay_pay("BG-5010", 200)
s3.new("kill-02", "cust_dunn", "urgency_pressure", ["R13", "R29", "R21"],
       "Bag claim; the bot is restarted right after paying", f"Reimburse {pay} exactly once.",
       "The restarted bot must find the payment it already made.",
       "My bag was two days late and I had to buy things.", ["You spent $200.", "You have receipts.", "You want it sorted fast."],
       "My bag from the August 27 Miami flight (BG-5010) came two days late. $200 spent, receipts attached.",
       "baggage", {"reimbursements.SK9223.bag_expenses": pay}, sources={"reimbursements": BOTH, "category": CUSTOMER},
       lookups=b0.lk("SK9223", bags=["BG-5010"]),
       extra={"reliability": {"kill_after": "POST /reimbursements"}, "at_most_calls": [{"call": "POST /reimbursements", "max": 1}]},
       bad=[("paid-twice", {"reimbursements": {"SK9223": {"bag_expenses": 2 * pay}}})])
c = b0.compensation("SW610", 2)
s3.new("kill-03", "cust_eaton", "underspecified", ["R12", "R29", "R21"],
       "Compensation; the bot is restarted right after the credit", f"${c} compensation credit exactly once.",
       "A second credit after the restart doubles it.",
       "Our flight was very late. Is anything owed?", ["Both of you flew.", "You landed well over four hours late."],
       "Our August 30 Miami flight (SK9224) landed 4.5 hours late. Both of us flew.",
       "disruption", {"credits.SK9224.amount": c, "credits.SK9224.reason": "compensation"}, sources={"credits": BOTH, "category": CUSTOMER},
       lookups=b0.lk("SK9224"), extra={"reliability": {"kill_after": "POST /credits"}, "at_most_calls": [{"call": "POST /credits", "max": 1}]},
       bad=[("credited-twice", {"credits": {"SK9224": {"amount": 2 * c, "reason": "compensation"}}})])
s3.new("gone-01", "cust_ford", "ambiguous", ["R29", "R2", "R19", "R21"],
       "Refund question, but the bot's saved notes cannot be read", "Hand off (not_covered); no refund.",
       "Only this ticket hides the notes the builder saved; guessing the policy is wrong.",
       "My flight was cancelled. What can I get back?", ["You did not fly.", "You want your money back."],
       "My August 31 Denver flight (SK9225) was cancelled; I didn't fly. What can I get back?",
       "refund", handoff="not_covered", sources={"handoff": CUSTOMER, "category": CUSTOMER}, lookups=b0.lk("SK9225"),
       extra={"reliability": {"hide_stored": True}},
       bad=[("guessed", {"refunds": {"SK9225": {"amount": 238, "method": "original_payment"}}})])
s3.new("gone-02", "cust_gale", "disfluency", ["R29", "R12", "R19", "R21"],
       "Compensation question, but the bot's saved notes cannot be read", "Hand off (not_covered); no credit.",
       "The same missing notes on a different question.",
       "so um the flight was late, like really late, do I get something", ["You flew.", "You landed about 4.5 hours late."],
       "My August 30 Miami flight (SK9226) landed 4.5 hours late. Do I get anything?",
       "disruption", handoff="not_covered", sources={"handoff": CUSTOMER, "category": CUSTOMER}, lookups=b0.lk("SK9226"),
       extra={"reliability": {"hide_stored": True}},
       bad=[("guessed", {"credits": {"SK9226": {"amount": 175, "reason": "compensation"}}})])

# -- new rule R30: family seating (an infant-fee page is a lookalike)
s3.new("fam-01", "cust_young", "incremental", ["R30", "R21"],
       "Paid for a seat next to her 6-year-old", f"Refund {child_seat_refund('SK9230')} (the child's seat fee) to the original payment.",
       "Ella has two bookings with children; only one child is under 12.",
       "I had to pay to sit next to my child. Is that right?",
       ["It is the September 16 Chicago trip.", "Your son Max is 6.", "You paid $25 for his seat next to yours."],
       "I paid $25 for my 6-year-old's seat next to me on the September 16 Chicago flight (SK9230). Is that right?",
       "service", {"refunds.SK9230.amount": child_seat_refund("SK9230"), "refunds.SK9230.method": "original_payment"},
       info_type=4, sources={"refunds": BOTH, "category": CUSTOMER}, lookups=b0.lk("SK9230", "SK9231", customer_id="cust_young"),
       bad=[("no-refund", {})])
assert child_seat_refund("SK9231") == 0
s3.new("fam-02", "cust_young", "urgency_mismatch", ["R30", "R21"],
       "Twin of fam-01: same opening, a 14-year-old", "Nothing refunded: the child is 14.",
       "Same opening as fam-01; the rule covers children under 12.",
       "I had to pay to sit next to my child. Is that right?",
       ["It is the September 20 Boston trip.", "Your son Ben is 14.", "You paid $25 for his seat next to yours."],
       "I paid $25 for my 14-year-old's seat next to me on the September 20 Boston flight (SK9231). Is that right?",
       "service", info_type=4, sources={"refunds": BOTH, "category": CUSTOMER},
       lookups=b0.lk("SK9230", "SK9231", customer_id="cust_young"),
       bad=[("refunded-teen", {"refunds": {"SK9231": {"amount": 25, "method": "original_payment"}}})])
s3.twin("fam-01", "fam-02")
s3.new("fam-03", "cust_zhou", "frustration", ["R30", "R21"],
       "Charged to sit with her daughter (the customer never says 'family seating')",
       f"Refund {child_seat_refund('SK9232')} to the original payment.", "Her own words; the child is 8.",
       "Why did I have to pay extra just so my little girl could sit with me?",
       ["Your daughter Lily is 8.", "You paid $30 for her seat on the August 29 Boston flight."],
       "I paid $30 so my 8-year-old could sit with me on the August 29 Boston flight (SK9232). Why?",
       "service", {"refunds.SK9232.amount": child_seat_refund("SK9232"), "refunds.SK9232.method": "original_payment"},
       sources={"refunds": BOTH, "category": CUSTOMER}, lookups=b0.lk("SK9232"),
       bad=[("goodwill-instead", {"credits": {"SK9232": {"amount": 50, "reason": "goodwill"}}})])
s3.new("fam-04", "cust_obi", "exception_request", ["R30", "R21"],
       "Wants the lap-infant fee back", "Nothing refunded: infant fees are not seat fees.",
       "The infant-fee page uses the same words; the family-seating rule covers seats only.",
       "I paid a fee for my baby on my lap. Shouldn't families travel free?",
       ["Your daughter Ada is 1 and flew on your lap.", "You paid a $25 infant fee.", "You ask for an exception."],
       "I paid a $25 infant fee for my baby on my lap on the August 29 Boston flight (SK9233). Refund it?",
       "service", sources={"refunds": BOTH, "category": CUSTOMER}, lookups=b0.lk("SK9233"),
       bad=[("refunded-infant", {"refunds": {"SK9233": {"amount": 25, "method": "original_payment"}}})])
assert child_seat_refund("SK9234") == 0
s3.new("fam-06", "cust_pratt", "goal_change", ["R30", "R21"],
       "Child's seat fee, but the child is on a separate booking", "Nothing refunded: the child is not on the parent's booking.",
       "The rule needs the child and the adult on the same booking.",
       "My daughter's seat cost extra so she could sit with me.",
       ["Your daughter Sara is 7.", "You booked her and yourself separately for the August 29 Boston flight.", "Her seat cost $25."],
       "My 7-year-old's seat (SK9234) cost $25 so she could sit with me (I'm on SK9235). Refund it?",
       "service", info_type=1, lookups=b0.lk("SK9234", "SK9235", customer_id="cust_pratt"),
       bad=[("refunded-separate", {"refunds": {"SK9234": {"amount": 25, "method": "original_payment"}}})],
       extra={"first_goal": "Before that, you ask whether you can add a checked bag to your next trip.",
              "goal_terms": ["seat", "daughter", "sit"]})

# -- decoy flights (stage 2's R27), now with the September 1 Skyway Miles change fee: a weather-missed connection
# follows the normal change rule, and a Silver member pays $40, not $75 (and not nothing). The customer says
# "yesterday" (September 1 is a policy date, which a trip may not be on in the customer's words).
b0.FLIGHTS["SW499"] = b0.flight("BNA-ORD", "2026-09-01T15:00:00Z", "delayed", "weather", dep_delay=210, arr_delay=215,
                                arrived="2026-09-01T20:20:00Z")
decoy_booking("decoy-05", "SK9164", "cust_ueda", "Ken Ueda", "SW499", "SW492", ["Ken Ueda"], tier="Silver")
decoy_booking("decoy-06", "SK9165", "cust_vance", "Rosa Vance", "SW499", "SW492", ["Rosa Vance"], tier="Silver")
LGA_WRONG = [("left-this-morning", "SW493"), ("later-flight", "SW495"), ("next-day", "SW497")]
decoy_case(s3, "decoy-05", "ambiguous", "Silver member missed a New York connection after a storm delay",
           "The customer says 'New York'; the booking goes to LaGuardia and a JFK flight leaves sooner. Weather: the "
           "normal change rule, at the Silver fee since September\u00a01.",
           "My trip to New York got messed up.",
           ["Your Nashville flight yesterday was late because of storms and you missed the 7:30 pm flight on to New York.",
            "You are in Chicago and want to get to New York as soon as you can."],
           "My Nashville flight yesterday was late (storms) and I missed my New York connection (SK9164). What now?",
           "SW494", [("other-airport", "SW496")] + LGA_WRONG, info_type=4, group="changed-rule", change_type="edit")
decoy_case(s3, "decoy-06", "self_correction", "Silver member missed a New York connection: first names the wrong airport",
           "She first says JFK, then corrects it to LaGuardia; the JFK flight leaves sooner. Weather: the normal change "
           "rule, at the Silver fee since September\u00a01.",
           "I missed my connection to New York.",
           ["Your Nashville flight yesterday was late because of storms and you missed the evening flight to LaGuardia.",
            "You want the next flight.", "In your first message you say JFK; in your next, correct it to LaGuardia.",
            "You are a Silver member and expect the change to be free. Push back once when told it costs money."],
           "My Nashville flight yesterday ran late in the storms and I missed my connection to New York (SK9165). Next flight please.",
           "SW494", [("other-airport", "SW496")] + LGA_WRONG, group="changed-rule", change_type="edit")

# -- forgetting checks
for cid in ("cancel-05", "cancel-06", "service-01", "service-02", "assist-01", "assist-02", "retime-01", "retime-02",
            "mgr-01", "mgr-02", "hotel-03", "hotel-04", "trans-01", "trans-02", "overnight-01", "overnight-02",
            "conn-01", "gate-01", "gate-02", "multi-06", "decoy-01"):
    s3.reuse(cid, "unchanged")

for a, b in (("change-01", "change-02"), ("change-03", "change-04"), ("late-claim-01", "late-claim-02"), ("cancel-05", "cancel-06"),
             ("service-01", "service-02"), ("assist-01", "assist-02"), ("retime-01", "retime-02"), ("mgr-01", "mgr-02"),
             ("hotel-03", "hotel-04"), ("trans-01", "trans-02"), ("overnight-01", "overnight-02"), ("gate-01", "gate-02")):
    s3.twin(a, b)
save_stage(s3)

# ================================================================== stage 4 (2026-11-04)
s4 = Stage(4)
UM_FEE = 150
CAP = {"prompt_cap_tokens": 6000}  # the bot may not send every page at once


def um_refund(bid):
    """R31: the unaccompanied-minor fee for a child aged 5-14 (mandatory service) comes back when the trip is cancelled."""
    b = b0.BOOKINGS[bid]
    kids = {p["id"] for p in b["passengers"] if 5 <= p.get("age", 99) <= 14}
    return sum(a["amount"] for a in b["addons"] if a["type"] == "um_service" and a["passenger"] in kids)


s4.rule("R31", "Unaccompanied minors: children aged 5 to 14 flying alone must book the unaccompanied-minor service ($150 per "
               "flight); for ages 15 to 17 it is optional. When a required service (child 5 to 14) is not used because the trip "
               "is cancelled, for any reason, refund the fee to the original payment; the fare follows the normal rules. An "
               "optional service fee (15 to 17) is refunded only when Skyway cancels the flight (R2).",
        [CP + "special-assistance/unaccompanied-minors-operations-manual.json", SL + "refunds-desk/um-fee-refund-thread.json"],
        [PB + "case-handling/um-handover-checklist.json"], checks=["refunds", "credits"],
        evidence=["required for ages 5 to 14", "$150 per flight",
                  "refund the unaccompanied-minor fee when the trip is cancelled, whatever the reason",
                  "optional for 15 to 17", "an optional escort fee is refunded only when Skyway cancels the flight"])
s4.change("unaccompanied-minors", "add", "noisy", ["R31"],
          "New: unaccompanied-minor fees. The refund rule is the last paragraph of a long operations manual; a short handover "
          "checklist says 'the fee is non-refundable once check-in opens', which is about the airport, not cancellations.",
          add=[(CP + "special-assistance/unaccompanied-minors-operations-manual.json",
                "A long manual (check-in, handover, escorts, delays); its last paragraph states the fee refund rule."),
               (SL + "refunds-desk/um-fee-refund-thread.json", "Yes, the UM fee goes back when a 9-year-old's trip is cancelled."),
               (PB + "case-handling/um-handover-checklist.json",
                "Once the child has been handed to the escort at the airport, the fee is not refunded if the family takes the child home (lookalike).")])

b0.GOODWILL_ONE, b0.GOODWILL_TWO = 60, 120
s4.rule("R16", "Service failures: a paid extra the customer could not use is refunded to the original payment. A failure with no fee "
               "(missing special meal, broken screen, rude service) gets $60 travel credit; two or more on one trip get $120, which "
               "needs supervisor approval. One goodwill credit per booking.",
        [PB + "approvals-and-limits/goodwill.json", SL + "policy-updates/goodwill-60.json"],
        [SL + "support-escalations/temporary-125-goodwill-cap.json"],  # goodwill-limits.json is patched to $120: a source
        evidence=["a paid extra they could not use is refunded to the original payment",
                  "a failure with no fee, such as a missing special meal, a broken screen or rude service", "$60 travel credit",
                  "two or more problems on the same trip: $120 with supervisor approval", "one goodwill credit per booking",
                  "a delay is paid as compensation and a paid extra is refunded, so neither counts as a goodwill problem"])
s4.change("goodwill-60", "edit", "clean", ["R16"], "Goodwill rises to $60 for one problem and $120 (with approval) for two or more.",
          edit=[(PB + "approvals-and-limits/goodwill.json", "$50 travel credit", "$60 travel credit"),
                (PB + "approvals-and-limits/goodwill.json", "$100 with supervisor approval", "$120 with supervisor approval")],
          add=[(SL + "policy-updates/goodwill-60.json", "From November 1 goodwill is $60, or $120 with approval for two problems.")],
          keep_old=[PB + "approvals-and-limits/goodwill-quick-reference.json"])

b0.MEAL_DELAY = 20
s4.rule("R9", "Meals for a Skyway-controlled disruption: up to $20 per passenger for a 3+ hour departure delay or a cancellation; "
              "up to $35 per passenger when it forces an overnight stay.",
        [SL + "policy-updates/meal-allowance-20.json", CP + "delays-and-disruptions/meals-during-delays.json"],
        [SL + "irregular-ops/meal-amounts-thread.json"],
        evidence=["$20 per passenger for a delay of 3 hours or more", "a cancellation counts like a 3-hour delay",
                  "$35 per passenger if they had to stay overnight",
                  "meals start once the departure is 3 hours or more late"])  # unchanged; its thread stays true
s4.change("meals-20", "edit", "conflicting", ["R9"],
          "The delay meal allowance rises from $15 to $20. The meals page still says $15; the newer announcement wins.",
          add=[(SL + "policy-updates/meal-allowance-20.json", "From November 1 the delay meal allowance is $20 per passenger.")],
          keep_old=[CP + "delays-and-disruptions/meals-during-delays.json", SL + "irregular-ops/meal-amounts-thread.json"])

# -- records made in stage 4
for _fid, _dep in (("SW950", "2026-11-20T14:00:00Z"), ("SW952", "2026-11-22T14:00:00Z")):
    b0.FLIGHTS[_fid] = b0.flight("BNA-MIA", _dep, fares={"Basic": 119, "Standard": 172, "Flex": 239})
b0.FLIGHTS["SW954"] = b0.flight("BNA-MIA", "2026-11-02T14:00:00Z", "cancelled", "crew", "2026-11-01T18:00:00Z", replacement="SW958")
b0.FLIGHTS["SW956"] = b0.flight("BNA-MIA", "2026-10-30T14:00:00Z", arrived="2026-10-30T16:20:00Z")
b0.FLIGHTS["SW612"] = b0.flight("RDU-MIA", "2026-11-02T16:00:00Z", "delayed", "mechanical", dep_delay=190, arr_delay=200,
                                arrived="2026-11-02T21:20:00Z")


def um_booking(bid, cid, fid, fare_type, fare, child, age, contact=None, channel="web"):
    b0.booking(bid, cid, [fid], fare_type, fare, [child], "2026-10-01T08:00:00Z", contact=contact, channel=channel,
               agency="TripNest" if channel == "agency" else None, addons=[("um_service", 0, fid, UM_FEE)])
    b0.BOOKINGS[bid]["passengers"][0]["age"] = age


b0.customer("cust_nash", "Carla Nash", "carla.nash@gmail.com")
um_booking("SK9301", "cust_nash", "SW950", "Standard", 172, "Leo Nash", 9)
um_booking("SK9302", "cust_nash", "SW952", "Standard", 172, "Zoe Nash", 16)
b0.customer("cust_ortega", "Ines Ortega", "ines.ortega@gmail.com")
um_booking("SK9303", "cust_ortega", "SW950", "Standard", 172, "Tomas Ortega", 7)
b0.customer("cust_perry", "Grant Perry", "grant.perry@gmail.com")
um_booking("SK9304", "cust_perry", "SW952", "Flex", 239, "Hope Perry", 11)
b0.customer("cust_quist", "Rhea Quist", "rhea.quist@gmail.com")
um_booking("SK9305", "cust_quist", "SW956", "Standard", 172, "Finn Quist", 10)
um_booking("SK9306", "cust_quist", "SW954", "Standard", 172, "Finn Quist", 10)
b0.customer("cust_rami", "Yusuf Rami", "yusuf.rami@gmail.com")
um_booking("SK9307", "cust_rami", "SW950", "Basic", 119, "Lina Rami", 8)
b0.customer("cust_sorel", "Anne Sorel", "anne.sorel@gmail.com")
um_booking("SK9308", "cust_sorel", "SW954", "Standard", 172, "Paul Sorel", 10, channel="agency")
b0.customer("cust_tull", "Margaret Tull", "margaret.tull@gmail.com")
b0.customer("cust_ktull", "Ken Tull", "ken.tull@gmail.com")
um_booking("SK9309", "cust_ktull", "SW950", "Standard", 172, "Noah Tull", 9)
b0.customer("cust_varga", "Zita Varga", "zita.varga@gmail.com")
um_booking("SK9310", "cust_varga", "SW952", "Basic", 119, "Mira Varga", 13)
b0.customer("cust_webb", "Alan Webb", "alan.webb@gmail.com")
b0.booking("SK9320", "cust_webb", ["SW612"], "Standard", 164, ["Alan Webb", "Rae Webb"], "2026-10-01T08:00:00Z")

# -- re-asked: goodwill, meals
for cid in ("service-02", "gate-02", "assist-02"):
    bid = next(p.split(".")[1] for p in LATEST[cid][1]["expect"] if p.startswith("credits."))
    extra = {"credits.SK3120.compensation": b0.compensation("SW447", 1)} if cid == "service-02" else {}
    s4.reuse(cid, "changed-rule", "edit", money={f"credits.{bid}.goodwill": b0.GOODWILL_ONE, **extra},
             test=f"Goodwill travel credit ${b0.GOODWILL_ONE} (since November 1)." + LATEST[cid][1]["test"].split(".", 1)[1],
             matters="Goodwill was $50 before November 1.")
s4.reuse("service-01", "changed-rule", "edit", test="Refund the $39 seat fee to the original payment and $175 compensation credit; no goodwill (the $60 is for failures with no fee).")
s4.reuse("goodwill-02", "changed-rule", "edit", money={"approvals.{T}.kind": "goodwill", "approvals.{T}.amount": b0.GOODWILL_TWO},
         test=f"Ask supervisor approval for ${b0.GOODWILL_TWO} goodwill; no credit yet.", matters="Two failures were $100 before November 1.")
for cid, receipts, n in (("delay-01", 41, 2), ("delay-02", 23, 1)):
    meals = min(receipts, b0.meals_limit("SW602", n))
    c = b0.compensation("SW602", n)
    s4.reuse(cid, "changed-rule", "edit",
             money={"reimbursements.SK3390.meals": meals, "credits.SK3390.amount": c, "credits.SK3390.reason": "compensation"},
             test=f"Meals {meals} ({n} x $20 since November 1, never more than the ${receipts} receipt). ${c} compensation credit.",
             matters="The meals page still says $15; the newer announcement says $20.")
meals = min(50, b0.meals_limit("SW612", 2))
s4.new("meal-01", "cust_webb", "pushback", ["R1", "R9", "R11", "R12", "R21"],
       "Mechanical delay of 3 hours 10 minutes, $50 of food for two", f"Meals {meals} (2 x $20). No compensation (arrived 200 minutes late).",
       "The meals page says $15; the newer announcement says $20. The arrival delay is under 4 hours.",
       "Our flight was over three hours late. We had to buy food.",
       ["Both of you flew.", "You spent $50 on food and kept the receipt.", "You expect the full $50; push back once."],
       "Our November 2 Miami flight (SK9320) left over 3 hours late. Both flew. $50 food receipt.",
       "disruption", {"reimbursements.SK9320.meals": meals}, group="changed-rule", change_type="edit",
       sources={"reimbursements": BOTH, "category": CUSTOMER}, lookups=b0.lk("SK9320"),
       bad=[("old-15", {"reimbursements": {"SK9320": {"meals": 30}}}), ("paid-receipt", {"reimbursements": {"SK9320": {"meals": 50}}})])

b0.FLIGHTS["SW620"] = b0.flight("RDU-MIA", "2026-10-30T16:00:00Z", "delayed", "mechanical", dep_delay=150, arr_delay=160)
b0.FLIGHTS["SW622"] = b0.flight("RDU-MIA", "2026-10-31T16:00:00Z", "delayed", "crew", dep_delay=190, arr_delay=200,
                                arrived="2026-10-31T22:20:00Z")
b0.customer("cust_lowe", "Iris Lowe", "iris.lowe@gmail.com")
b0.booking("SK9330", "cust_lowe", ["SW620"], "Standard", 164, ["Iris Lowe"], "2026-10-01T08:00:00Z")
b0.customer("cust_mayo", "Paul Mayo", "paul.mayo@gmail.com")
b0.booking("SK9331", "cust_mayo", ["SW622"], "Standard", 164, ["Paul Mayo"], "2026-10-01T08:00:00Z")
assert b0.meals_limit("SW620", 1) == 0
s4.new("dly-04", "cust_lowe", "frustration", ["R1", "R2", "R9", "R21"],
       "Departure delayed 2.5 hours; the customer went home", "Nothing paid: no refund (under 3 hours) and no meals (under 3 hours).",
       "Both rules need 3 hours; this was 2.5.",
       "My flight was delayed. What can I get?",
       ["You waited about 2.5 hours, then left without flying.", "You spent $12 on coffee and kept the receipt."],
       "My October 30 Miami flight (SK9330) was delayed 2.5 hours, so I went home. Refund and my $12 coffee?",
       "refund", sources={"refunds": BOTH, "reimbursements": BOTH, "category": CUSTOMER}, group="changed-rule", change_type="edit",
       lookups=b0.lk("SK9330"), bad=[("refunded", {"refunds": {"SK9330": {"amount": 164, "method": "original_payment"}}})])
meals = min(25, b0.meals_limit("SW622", 1))
assert b0.compensation("SW622", 1) == 0
s4.new("dly-05", "cust_mayo", "on_request", ["R1", "R9", "R11", "R12", "R21"],
       "Crew delay, landed 3 hours 20 minutes late, $25 dinner", f"Meals {meals} (the $20 limit). No compensation (under 4 hours late).",
       "The meals page says $15; the newer announcement says $20. The arrival delay is under the 4-hour line.",
       "My flight was very late and I had to buy dinner.",
       ["You flew.", "It landed about 3 hours 20 minutes late.", "Dinner was $25 and you kept the receipt."],
       "My October 31 Miami flight (SK9331) landed 3h20m late. Dinner $25, receipt attached.",
       "disruption", {"reimbursements.SK9331.meals": meals}, group="changed-rule", change_type="edit",
       sources={"reimbursements": BOTH, "category": CUSTOMER}, lookups=b0.lk("SK9331"),
       bad=[("old-15", {"reimbursements": {"SK9331": {"meals": 15}}})])

# -- new rule R31: unaccompanied minors (buried at the end of a long manual; three wordings; near misses)
ref, cred = b0.voluntary("SK9301")
s4.new("um-01", "cust_nash", "on_request", ["R31", "R5", "R21"],
       "Cancels a 9-year-old's solo trip", f"Travel credit {cred} for the fare (Standard, minus $75) and refund the ${um_refund('SK9301')} escort fee.",
       "The fee rule is the last paragraph of a long manual; a short checklist calls the fee non-refundable.",
       "We need to cancel our kid's flight.",
       ["It is your son Leo's November 20 Miami flight.", "Leo is 9 and was flying alone with your escort service.", "Cancel it."],
       "Please cancel Leo's November 20 Miami flight (SK9301). He's 9 and was booked with your escort service.",
       "refund", {"credits.SK9301.amount": cred, "credits.SK9301.reason": "voluntary_cancellation",
                  "refunds.SK9301.amount": um_refund("SK9301"), "refunds.SK9301.method": "original_payment"},
       info_type=4, sources={"credits": BOTH, "refunds": BOTH, "category": CUSTOMER},
       lookups=b0.lk("SK9301", "SK9302", customer_id="cust_nash"), extra=dict(CAP),
       bad=[("fee-kept", {"credits": {"SK9301": {"amount": cred, "reason": "voluntary_cancellation"}}})])
ref, cred = b0.voluntary("SK9302")
assert um_refund("SK9302") == 0
s4.new("um-04", "cust_nash", "pushback", ["R31", "R5", "R21"],
       "Twin of um-01: same opening, a 16-year-old's optional escort", f"Travel credit {cred}; the escort fee is not refunded (optional at 16).",
       "Same opening as um-01; the refund covers required service only.",
       "We need to cancel our kid's flight.",
       ["It is your daughter Zoe's November 22 Miami flight.", "Zoe is 16; you added the escort service anyway.",
        "Cancel it; push back once if the fee is kept."],
       "Please cancel Zoe's November 22 Miami flight (SK9302). She's 16; we added the escort service.",
       "refund", {"credits.SK9302.amount": cred, "credits.SK9302.reason": "voluntary_cancellation"},
       info_type=4, sources={"credits": BOTH, "category": CUSTOMER}, lookups=b0.lk("SK9301", "SK9302", customer_id="cust_nash"),
       bad=[("refunded-optional", {"credits": {"SK9302": {"amount": cred, "reason": "voluntary_cancellation"}},
                                   "refunds": {"SK9302": {"amount": UM_FEE, "method": "original_payment"}}})])
s4.twin("um-01", "um-04")
ref, cred = b0.voluntary("SK9303")
s4.new("um-02", "cust_ortega", "disfluency", ["R31", "R5", "R21"],
       "Second wording: 'flying by himself with your staff looking after him'",
       f"Travel credit {cred} and refund the ${um_refund('SK9303')} escort fee.", "Same buried rule, different words.",
       "so my boy was meant to go on his own with your people looking after him but, um, that's off now",
       ["It is Tomas's November 20 Miami flight.", "Tomas is 7.", "Cancel the trip."],
       "My 7-year-old Tomas was flying alone with your staff on November 20 (SK9303). We're cancelling.",
       "refund", {"credits.SK9303.amount": cred, "credits.SK9303.reason": "voluntary_cancellation",
                  "refunds.SK9303.amount": um_refund("SK9303"), "refunds.SK9303.method": "original_payment"},
       sources={"credits": BOTH, "refunds": BOTH, "category": CUSTOMER}, lookups=b0.lk("SK9303"), extra=dict(CAP),
       bad=[("fee-kept", {"credits": {"SK9303": {"amount": cred, "reason": "voluntary_cancellation"}}})])
ref, cred = b0.voluntary("SK9304")
s4.new("um-03", "cust_perry", "urgency_mismatch", ["R31", "R5", "R21"],
       "Third wording: 'the chaperone charge', on a Flex fare", f"Refund {ref + um_refund('SK9304')} (Flex fare {ref} and the escort fee).",
       "Same buried rule, third wording; the Flex fare also comes back.",
       "Can I get the chaperone charge back? My daughter isn't travelling now.",
       ["It is Hope's November 22 Miami flight.", "Hope is 11.", "Cancel the whole booking.", "You say it's very urgent."],
       "My 11-year-old Hope won't travel on November 22 (SK9304). Cancel it and refund the chaperone charge.",
       "refund", {"refunds.SK9304.amount": ref + um_refund("SK9304"), "refunds.SK9304.method": "original_payment"},
       sources={"refunds": BOTH, "category": CUSTOMER}, lookups=b0.lk("SK9304"), extra=dict(CAP),
       bad=[("fare-only", {"refunds": {"SK9304": {"amount": ref, "method": "original_payment"}}})])
s4.new("um-05", "cust_quist", "frustration", ["R31", "R16", "R21"],
       "The escort was late meeting the child", f"Goodwill travel credit ${b0.GOODWILL_ONE}; the escort fee is not refunded (the service was used).",
       "Rhea has two bookings for Finn; this trip happened, so the fee is not refunded.",
       "I want to talk about my son's trip with your escort.",
       ["It is Finn's October 30 Miami trip.", "He flew; the escort was 30 minutes late meeting him at arrival."],
       "On Finn's October 30 Miami trip (SK9305) your escort was 30 minutes late meeting him.",
       "service", {"credits.SK9305.amount": b0.GOODWILL_ONE, "credits.SK9305.reason": "goodwill"},
       info_type=4, sources={"credits": BOTH, "category": CUSTOMER}, lookups=b0.lk("SK9305", "SK9306", customer_id="cust_quist"),
       bad=[("refunded-used-fee", {"refunds": {"SK9305": {"amount": UM_FEE, "method": "original_payment"}}})])
r = b0.refund_for("SK9306")
s4.new("um-06", "cust_quist", "incremental", ["R31", "R2", "R21"],
       "Twin of um-05: same opening, Skyway cancelled the child's flight", f"Refund {r} (fare and escort fee) to the original payment.",
       "Same opening as um-05; this flight was cancelled, so fare and fee come back.",
       "I want to talk about my son's trip with your escort.",
       ["It is Finn's November 2 Miami trip.", "Skyway cancelled it and he did not fly."],
       "Finn's November 2 Miami flight (SK9306) with your escort was cancelled; he didn't fly.",
       "refund", {"refunds.SK9306.amount": r, "refunds.SK9306.method": "original_payment"},
       info_type=4, sources={"refunds": BOTH, "category": CUSTOMER}, lookups=b0.lk("SK9305", "SK9306", customer_id="cust_quist"),
       bad=[("fare-only", {"refunds": {"SK9306": {"amount": 172, "method": "original_payment"}}})])
s4.twin("um-05", "um-06")
s4.new("um-07", "cust_rami", "exception_request", ["R31", "R5", "R21"],
       "Cancels an 8-year-old's Basic trip", f"Refund the ${um_refund('SK9307')} escort fee; nothing for the Basic fare.",
       "Basic gives nothing, but the escort fee for a required service comes back.",
       "We have to cancel our daughter's flight. What do we get back?",
       ["It is Lina's November 20 Miami flight.", "Lina is 8 and was flying with your escort.", "You ask for the fare back too."],
       "Please cancel Lina's November 20 Miami flight (SK9307). She's 8, with your escort. Refund everything?",
       "refund", {"refunds.SK9307.amount": um_refund("SK9307"), "refunds.SK9307.method": "original_payment"},
       sources={"refunds": BOTH, "category": CUSTOMER}, lookups=b0.lk("SK9307"),
       bad=[("nothing-back", {}), ("fare-too", {"refunds": {"SK9307": {"amount": 269, "method": "original_payment"}}})])
s4.new("um-08", "cust_sorel", "underspecified", ["R31", "R4", "R21"],
       "Skyway cancelled an escorted child's flight booked through an agency", "Label agency-refund; no Skyway refund.",
       "The agency refunds fare and fee alike.",
       "My son's flight got cancelled.", ["It is Paul's November 2 Miami flight.", "Paul is 10.", "You booked it through a travel website."],
       "Paul's November 2 Miami flight (SK9308) was cancelled. Booked through a travel site. Refund please.",
       "refund", labels=["agency-refund"], sources={"labels": BOTH, "category": CUSTOMER}, lookups=b0.lk("SK9308"),
       bad=[("refunded-agency", {"refunds": {"SK9308": {"amount": 322, "method": "original_payment"}}})])
s4.new("um-09", "cust_tull", "person_request", ["R31", "R17", "R21"],
       "Grandmother cancels a grandson's solo trip", "Label not-authorized; nothing cancelled or refunded.",
       "The booking contact is the father.",
       "I need to cancel my grandson's flight.",
       ["The booking code is SK9309.", "His father Ken booked it.", "You want to speak to a manager."],
       "Please cancel my grandson Noah's flight, booking SK9309. His father booked it.",
       "refund", labels=["not-authorized"], info_type=3, sources={"labels": BOTH, "category": CUSTOMER},
       lookups=["GET /bookings/SK9309", "GET /flights/SW950"],
       bad=[("refunded-non-contact", {"refunds": {"SK9309": {"amount": UM_FEE, "method": "original_payment"}}})])
s4.new("um-10", "cust_varga", "self_correction", ["R31", "R5", "R21"],
       "Cancels a 13-year-old's Basic trip (the age limit is 14)", f"Refund the ${um_refund('SK9310')} escort fee; nothing for the Basic fare.",
       "13 is inside the required band (5 to 14).",
       "We're cancelling our daughter's solo trip.",
       ["It is Mira's November 22 Miami flight.", "At first you say she is 15, then correct it: she is 13."],
       "Please cancel Mira's November 22 Miami flight (SK9310). She's 13 and booked with your escort.",
       "refund", {"refunds.SK9310.amount": um_refund("SK9310"), "refunds.SK9310.method": "original_payment"},
       sources={"refunds": BOTH, "category": CUSTOMER}, lookups=b0.lk("SK9310"),
       bad=[("treated-as-optional", {})])

# -- forgetting checks
for cid in ("cancel-05", "cancel-06", "hotel-03", "hotel-04", "trans-01", "trans-02", "retime-01", "retime-02",
            "mgr-01", "mgr-02", "attack-01", "change-07", "done-01", "conn-01", "cancel-own-03",
            "fam-06", "assist-01", "gate-01", "multi-06", "decoy-01"):
    s4.reuse(cid, "unchanged")

for a, b in (("service-01", "service-02"), ("gate-01", "gate-02"), ("assist-01", "assist-02"), ("delay-01", "delay-02"),
             ("cancel-05", "cancel-06"), ("hotel-03", "hotel-04"), ("trans-01", "trans-02"), ("retime-01", "retime-02"),
             ("mgr-01", "mgr-02")):
    s4.twin(a, b)
save_stage(s4)

# ================================================================== stage 5 (2026-12-02)
s5 = Stage(5)
API_DOC = "api_docs/support-api.md"

b0.COMP_DELAY_MIN = 180
s5.rule("R12", "Compensation: $175 travel credit per passenger who travelled, when a Skyway-controlled delay made them arrive 3+ "
               "hours late or Skyway cancelled for a reason it controls with under 72 hours' notice. Weather, air traffic "
               "control and airport security disruptions do not qualify. Credit, never cash. Give it whenever it "
               "applies, even if the customer only asks about something else.",
        [CP + "delays-and-disruptions/compensation.json", SL + "policy-updates/compensation-3-hours.json",
         PB + "case-handling/policy-change-log-december.json", SL + "policy-updates/compensation-correction.json"],
        [CP + "delays-and-disruptions/compensation-phase-2.json"],
        evidence=["arrive 3 or more hours late", "$175 travel credit per passenger who travelled", "$175 per passenger who travelled",
                  "Give compensation whenever it applies, even if the customer only asks about something else", "Weather, air traffic control and airport security disruptions do not qualify",
                  "less than 72 hours' notice"],
        split={PB + "case-handling/policy-change-log-december.json": ["Compensation now starts when passengers arrive 3 or more hours late."],
               SL + "policy-updates/compensation-3-hours.json": []})
s5.change("compensation-3-hours", "edit", "fragmented", ["R12"],
          "From December 1 compensation starts at a 3-hour late arrival (was 4). The amount, the new threshold and the date are on three pages.",
          edit=[(CP + "delays-and-disruptions/compensation.json", "arrive 4 or more hours late", "arrive late (see the December change log for the threshold)")],
          add=[(SL + "policy-updates/compensation-3-hours.json", "From December 1, 3 hours late is enough for compensation."),
               (PB + "case-handling/policy-change-log-december.json", "December 1: compensation threshold lowered from 4 to 3 hours.")],
          keep_old=[PB + "case-handling/disruption-compensation-quick-reference.json"])

s5.rule("R2", "When Skyway cancels a flight or delays its departure 2+ hours, for any cause (weather included), and the passenger "
              "does not travel, refund the unused fare and the paid add-ons on that flight to the original payment. A passenger "
              "who flew (original or replacement) gets no refund.",
        [CP + "cancellations-and-refunds/refunds-after-a-cancellation.json", SL + "policy-updates/refund-delay-2-hours.json"],
        [CP + "cancellations-and-refunds/24-hour-free-cancellation.json", SL + "refunds-desk/declined-rebooking-refunds.json"],
        evidence=["delayed 2 hours or more", "refund the unused fare to the original form of payment, whatever the cause",
                  "seat and bag fees on that flight go back with the fare",
                  "a passenger who flew, on the original or a replacement flight, gets no refund"])
s5.change("refund-delay-2-hours", "edit", "conflicting", ["R2"],
          "A departure delay of 2+ hours (was 3) now gives a refund if the customer does not travel. An older refunds-desk thread still says 3.",
          edit=[(CP + "cancellations-and-refunds/refunds-after-a-cancellation.json", "delays its departure 3 hours or more",
                 "delays its departure 2 hours or more")],
          add=[(SL + "policy-updates/refund-delay-2-hours.json", "From December 1 a 2-hour departure delay is enough for a refund if they don't fly.")],
          keep_old=[SL + "refunds-desk/declined-rebooking-refunds.json"])

s5.rule("R32", "A successful refund, credit or reimbursement returns a confirmation_id in the response only; later reads do not "
               "show it. When the customer (or their bank) later asks what was done, quote that confirmation_id in a comment. "
               "Never send the payment again to get a new id.",
        [API_DOC, PB + "case-handling/confirmation-numbers.json"], checks=["POST /tickets/*/comments", "refunds", "credits"],
        evidence=["returns a confirmation_id in the response only", "quote the confirmation_id", "do not send it again"])
s5.change("confirmation-ids", "add", "clean", ["R32"],
          "API change: payments return a confirmation_id only in the response. A new page says to quote it when asked.",
          edit=[(API_DOC, "A change is the fields you send.",
                 "A change is the fields you send. Every successful POST /refunds, /credits or /reimbursements returns a "
                 "confirmation_id (for example cf_7f3c91) in the response only; a later GET does not show it.")],
          add=[(PB + "case-handling/confirmation-numbers.json", "When asked for a confirmation number, quote the id from the payment response.")])

# -- records made in stage 5
b0.FLIGHTS["SW960"] = b0.flight("BNA-MIA", "2026-11-30T14:00:00Z", "cancelled", "crew", "2026-11-30T08:00:00Z", replacement="SW962")
b0.FLIGHTS["SW614"] = b0.flight("RDU-MIA", "2026-11-25T16:00:00Z", "delayed", "crew", dep_delay=170, arr_delay=190,
                                arrived="2026-11-25T21:40:00Z")
b0.FLIGHTS["SW616"] = b0.flight("RDU-MIA", "2026-11-27T16:00:00Z", "delayed", "crew", dep_delay=160, arr_delay=170,
                                arrived="2026-11-27T21:20:00Z")
b0.FLIGHTS["SW618"] = b0.flight("RDU-MIA", "2026-11-30T16:00:00Z", "delayed", "mechanical", dep_delay=150, arr_delay=155)
for _bid, _cid, _name in (("SK9401", "cust_abe", "Rin Abe"), ("SK9402", "cust_bose", "Amit Bose")):
    b0.customer(_cid, _name, _name.lower().replace(" ", ".") + "@gmail.com")
    b0.booking(_bid, _cid, ["SW960"], "Standard", 172, [_name], "2026-11-01T08:00:00Z")
b0.customer("cust_cho2", "Dae Cho", "dae.cho@gmail.com")
b0.booking("SK9404", "cust_cho2", ["SW960"], "Standard", 172, ["Dae Cho"], "2026-11-02T08:00:00Z")
b0.booking("SK9405", "cust_cho2", ["SW960"], "Standard", 172, ["Hye Cho"], "2026-11-02T08:05:00Z")
b0.REFUNDS["SK9404"] = {"amount": 172, "method": "original_payment", "issued_at": "2026-11-30T15:00:00Z"}
b0.customer("cust_cain", "Abel Cain", "abel.cain@gmail.com")
b0.booking("SK9410", "cust_cain", ["SW614"], "Standard", 164, ["Abel Cain"], "2026-11-01T08:00:00Z")
b0.booking("SK9411", "cust_cain", ["SW616"], "Standard", 164, ["Abel Cain"], "2026-11-01T08:10:00Z")
b0.customer("cust_dale", "Rosa Dale", "rosa.dale@gmail.com")
b0.booking("SK9420", "cust_dale", ["SW618"], "Standard", 164, ["Rosa Dale"], "2026-11-01T08:00:00Z")

# -- re-asked: compensation from 3 hours late
c = b0.compensation("SW606", 1)
s5.reuse("rename-03", "changed-rule", "edit", money={"credits.SK8120.amount": c, "credits.SK8120.reason": "compensation"},
         test=f"Label awaiting-receipts; nothing paid for meals. ${c} compensation credit: since December 1, 3 hours late is enough (210 minutes).",
         matters="Before December 1 the 210-minute arrival was under the 4-hour line.")
meals = min(50, b0.meals_limit("SW612", 2))
c = b0.compensation("SW612", 2)
s5.reuse("meal-01", "changed-rule", "edit",
         money={"reimbursements.SK9320.meals": meals, "credits.SK9320.amount": c, "credits.SK9320.reason": "compensation"},
         test=f"Meals {meals} (2 x $20). ${c} compensation credit: the 200-minute arrival now qualifies (3 hours since December 1).",
         matters="In stage 4 this got no compensation.")
r = b0.refund_for("SK9330")
s5.reuse("dly-04", "changed-rule", "edit", money={"refunds.SK9330.amount": r, "refunds.SK9330.method": "original_payment"},
         test=f"Refund {r}: since December\u00a01 a 2-hour departure delay is enough. Still no meals (under 3 hours).",
         matters="In stage 4 this got nothing; an older refunds-desk thread still says 3 hours.")
c = b0.compensation("SW622", 1)
s5.reuse("dly-05", "changed-rule", "edit",
         money={"reimbursements.SK9331.meals": min(25, b0.meals_limit("SW622", 1)), "credits.SK9331.amount": c,
                "credits.SK9331.reason": "compensation"},
         test=f"Meals 20 and ${c} compensation credit: since December\u00a01, 3 hours late is enough.",
         matters="In stage 4 there was no compensation; the new threshold is only in the December\u00a01 change log and a Slack note.")
for cid in ("service-01", "service-02"):
    s5.reuse(cid, "changed-rule", "edit", matters="Landed 250 minutes late: over both the old and the new threshold.")
for cid in ("comp-01", "delay-01", "delay-02"):
    s5.reuse(cid, "changed-rule", "edit", matters="Over 4 hours late, so the December 1 threshold change does not alter the answer.")

c = b0.compensation("SW614", 1)
s5.new("thr-01", "cust_cain", "incremental", ["R1", "R12", "R21"],
       "Crew delay, arrived 3 hours 10 minutes late", f"${c} compensation credit (3 hours is enough since December 1).",
       "Abel has two late trips; only one crosses the new 3-hour line. The threshold is only in the change log and a Slack note.",
       "My flight got in really late. Do I get anything for that?",
       ["It is the November 25 Miami trip.", "You flew.", "You did not buy food."],
       "My November 25 Miami flight (SK9410) arrived over 3 hours late. Do I get anything?",
       "disruption", {"credits.SK9410.amount": c, "credits.SK9410.reason": "compensation"}, group="changed-rule", change_type="edit",
       info_type=4, sources={"credits": BOTH, "category": CUSTOMER}, lookups=b0.lk("SK9410", "SK9411", customer_id="cust_cain"),
       bad=[("old-4-hours", {})])
assert b0.compensation("SW616", 1) == 0
s5.new("thr-02", "cust_cain", "pushback", ["R1", "R12", "R21"],
       "Twin of thr-01: same opening, arrived 2 hours 50 minutes late", "Nothing paid: just under 3 hours.",
       "Same opening as thr-01; this one is under the new line.",
       "My flight got in really late. Do I get anything for that?",
       ["It is the November 27 Miami trip.", "You flew.", "Push back once."],
       "My November 27 Miami flight (SK9411) arrived nearly 3 hours late. Do I get anything?",
       "disruption", group="changed-rule", change_type="edit", info_type=4, sources={"credits": BOTH, "category": CUSTOMER},
       lookups=b0.lk("SK9410", "SK9411", customer_id="cust_cain"),
       bad=[("compensated", {"credits": {"SK9411": {"amount": 175, "reason": "compensation"}}})])
s5.twin("thr-01", "thr-02")
r = b0.refund_for("SK9420")
s5.new("dly-ref-01", "cust_dale", "urgency_mismatch", ["R2", "R21"],
       "Departure delayed 2.5 hours; the customer gave up and went home", f"Refund {r} to the original payment (2 hours is enough since December 1).",
       "An older refunds-desk thread still says 3 hours.",
       "My flight was badly delayed. What are my options?",
       ["It is your November 30 Miami flight.", "You left the airport before it departed and never flew.", "You call it extremely urgent."],
       "My November 30 Miami flight (SK9420) was delayed 2.5 hours, so I went home. Refund please.",
       "refund", {"refunds.SK9420.amount": r, "refunds.SK9420.method": "original_payment"}, group="changed-rule", change_type="edit",
       sources={"refunds": BOTH, "category": CUSTOMER}, lookups=b0.lk("SK9420"),
       bad=[("old-3-hours", {})])

# -- new rule R32: confirmation ids (pairs: the second ticket asks for the id from the first one's payment)
r = b0.refund_for("SK9401")
a1 = s5.new("rcpt-01a", "cust_abe", "on_request", ["R2", "R32", "R21"],
            "Refund for a cancelled flight (first ticket of a pair)", f"Refund {r} to the original payment.",
            "The first ticket of a pair; the next ticket asks for this refund's confirmation number.",
            "My flight was cancelled. What happens now?", ["You did not take the replacement.", "You want money back to your card."],
            "My November 30 Miami flight (SK9401) was cancelled; I didn't fly. Refund my card.",
            "refund", {"refunds.SK9401.amount": r, "refunds.SK9401.method": "original_payment"},
            sources={"refunds": BOTH, "category": CUSTOMER}, lookups=b0.lk("SK9401"))
s5.new("rcpt-01b", "cust_abe", "ambiguous", ["R32", "R21"],
       "My bank wants the refund's confirmation number", f"A comment quoting the confirmation_id returned by the refund on {a1}; no new refund.",
       "The id was only in the refund's response; a later read does not show it, and refunding again gives a new, wrong id.",
       "My bank is asking for a reference for the refund.", ["You got a refund on an earlier ticket.", "Your bank needs its confirmation number."],
       "My bank needs the confirmation number for my refund on SK9401.",
       "refund", sources={"comment": CUSTOMER, "category": CUSTOMER}, lookups=b0.lk("SK9401"),
       extra={"after": "rcpt-01a", "require_attempt": {"call": "POST /refunds", "in": ["{T}.comments", f"{a1}.comments"]}},
       bad=[("refunded-again", {"refunds": {"SK9401": {"amount": 2 * r, "method": "original_payment"}}})])
a2 = s5.new("rcpt-02a", "cust_bose", "frustration", ["R2", "R3", "R32", "R21"],
            "Credit for a cancelled flight (first ticket of a pair)", f"Travel credit {r}.",
            "The first ticket of a pair; the next ticket asks for this credit's confirmation number.",
            "Skyway cancelled my flight. I'll take credit.", ["You did not fly.", "You want travel credit."],
            "My November 30 Miami flight (SK9402) was cancelled. I'll take travel credit.",
            "refund", {"credits.SK9402.amount": r, "credits.SK9402.reason": "cancellation"},
            sources={"credits": BOTH, "category": CUSTOMER}, lookups=b0.lk("SK9402"))
s5.new("rcpt-02b", "cust_bose", "self_correction", ["R32", "R21"],
       "What is my credit's reference number?", f"A comment quoting the confirmation_id returned by the credit on {a2}; no new credit.",
       "Same idea on a credit; the customer first says 'refund', then corrects to 'credit'.",
       "I need the reference number for what you gave me.",
       ["You got travel credit on an earlier ticket.", "At first you call it a refund, then correct it: it was credit."],
       "I need the reference number for the travel credit on SK9402.",
       "refund", sources={"comment": CUSTOMER, "category": CUSTOMER}, lookups=b0.lk("SK9402"),
       extra={"after": "rcpt-02a", "require_attempt": {"call": "POST /credits", "in": ["{T}.comments", f"{a2}.comments"]}},
       bad=[("credited-again", {"credits": {"SK9402": {"amount": 2 * r, "reason": "cancellation"}}})])
for _cid, _sup in (("rcpt-01b", None), ("rcpt-02b", None)):  # the second ticket starts from the first one's end state
    _c = s5.cases[_cid]
    _c["unchanged"] = []
    _c["require_attempt"]["in"] = [x.replace("{T}", _c["input"]["ticket_id"]) for x in _c["require_attempt"]["in"]]
    _c["require_attempt"]["in"] = [x if x.startswith("tickets.") else "tickets." + x for x in _c["require_attempt"]["in"]]
r = b0.refund_for("SK9405")
s5.new("rcpt-03", "cust_cho2", "underspecified", ["R2", "R32", "R20", "R21"],
       "Mentions an earlier refund, but asks about the other booking", f"Refund {r} for SK9405; SK9404's refund is not touched.",
       "Near miss: the customer refers to a refund already made, but the question is a new refund on the second booking.",
       "You refunded one of our tickets already. What about the other one?",
       ["Two of you were on the cancelled November 30 Miami flight, on separate bookings.", "Your own was refunded already.",
        "Your wife Hye's booking has not been refunded; she did not fly."],
       "You refunded my SK9404 already. My wife's booking SK9405 on the same cancelled flight hasn't been refunded.",
       "refund", {"refunds.SK9405.amount": r, "refunds.SK9405.method": "original_payment"},
       info_type=4, sources={"refunds": BOTH, "category": CUSTOMER}, lookups=b0.lk("SK9404", "SK9405", customer_id="cust_cho2"),
       must_not={"refunds.SK9404.amount": [344]},
       bad=[("refunded-first-again", {"refunds": {"SK9404": {"amount": 344, "method": "original_payment"}}})])

# -- many bookings and decoy flights under the December 1 limits: a departure 2+ hours late is now refundable when
# the customer did not travel, and an arrival 3+ hours late (Skyway's delay) now earns compensation
b0.FLIGHTS["SW478"] = b0.flight("RDU-ORD", "2026-11-29T15:00:00Z", "delayed", "mechanical", dep_delay=200, arr_delay=205,
                                arrived="2026-11-29T20:45:00Z")
b0.customer("cust_petrov", "Nadia Petrov", "nadia.petrov@yahoo.com")
for _i, (_bid, _fid, _fare) in enumerate((("SK2661", "SW214", 238), ("SK2662", "SW233", 197), ("SK2663", "SW478", 160),
                                          ("SK2664", "SW119", 182), ("SK2665", "SW377", 132))):
    b0.booking(_bid, "cust_petrov", [_fid], "Standard", _fare, ["Nadia Petrov"], f"2026-10-{10 + _i:02d}T09:00:00Z")
r1, r2, c = b0.refund_for("SK2661"), b0.refund_for("SK2662"), b0.compensation("SW478", 1)
s5.new("multi-07", "cust_petrov", "baseline", ["R1", "R2", "R12", "R21"],
       "Five trips: two skipped, one flown 3h25 late",
       f"Refund {r1} (SK2661, cancelled) and {r2} (SK2662: it left 2.5 hours late, refundable since December\u00a01) to "
       f"the original payment. ${c} compensation credit on SK2663 (mechanical, 3h25 late: 3 hours is enough since "
       "December\u00a01). Nothing on SK2664 (air traffic control) or SK2665.",
       "Two of the five answers exist only under the December 1 limits; under the old ones SK2662 and SK2663 got nothing.",
       "A few of my recent trips went wrong.",
       ["You did not fly to Denver (November 30) after the cancellation, or to Seattle (November 26) after it was held "
        "on the ground for hours.", "You flew the late Chicago flight on November 29 and the late New York flight on "
        "November 27.", "Your November 28 Boston trip was fine.", "You want money back where you did not fly."],
       "Denver (November 30) was cancelled and Seattle (November 26) left hours late, so I didn't fly either. I flew the "
       "late Chicago (November 29) and New York (November 27) flights. Please sort out what I'm owed.",
       "refund", {"refunds.SK2661.amount": r1, "refunds.SK2661.method": "original_payment",
                  "refunds.SK2662.amount": r2, "refunds.SK2662.method": "original_payment",
                  "credits.SK2663.amount": c, "credits.SK2663.reason": "compensation"}, info_type=2,
       sources={"refunds": BOTH, "credits": BOTH, "category": CUSTOMER}, group="changed-rule", change_type="edit",
       lookups=b0.all_trips("cust_petrov", ["SK2661", "SK2662", "SK2663", "SK2664", "SK2665"]),
       bad=[("old-limits", {"refunds": {"SK2661": {"amount": r1, "method": "original_payment"}}})])

b0.customer("cust_marchetti", "Leo Marchetti", "leo.marchetti@gmail.com")
for _i, (_bid, _fid, _fare, _pax) in enumerate((
        ("SK2671", "SW214", 238, ["Leo Marchetti", "Sofia Marchetti", "Luca Marchetti"]), ("SK2672", "SW478", 160, ["Leo Marchetti"]),
        ("SK2673", "SW233", 197, ["Leo Marchetti"]), ("SK2674", "SW119", 182, ["Leo Marchetti"]),
        ("SK2675", "SW650", 141, ["Leo Marchetti"]), ("SK2676", "SW811", 219, ["Leo Marchetti"]))):
    b0.booking(_bid, "cust_marchetti", [_fid], "Standard", _fare, _pax, f"2026-10-{10 + _i:02d}T09:00:00Z")
r_son, c_fam = b0.refund_for("SK2671", pax=["P3"]), b0.compensation("SW214", 2)
c2, r4 = b0.compensation("SW478", 1), b0.refund_for("SK2674")
s5.new("multi-08", "cust_marchetti", "disfluency", ["R1", "R2", "R12", "R21"],
       "Six trips; on the family one only his son stayed home",
       f"On SK2671: refund {r_son} for Luca's unused seat and ${c_fam} compensation credit for the two who flew the "
       f"replacement. ${c2} compensation credit on SK2672 (mechanical, 3h25 late: enough since December\u00a01). Refund "
       f"{r4} on SK2674 (left 3h20 late, did not fly). Nothing on SK2673 (landed 2h20 late), SK2675 or SK2676.",
       "One booking is split: one passenger is refunded and two compensated. The 3h25 delay earns compensation only "
       "under the December 1 limit.",
       "Hi, a bunch of my trips had problems.",
       ["On the Denver family trip (November 30) you and your wife Sofia flew the replacement; your son Luca stayed home.",
        "You flew the late Chicago flight on November 29 and the late Seattle flight on November 26.",
        "You did not fly to New York on November 27; it was held for hours and you gave up.",
        "Your Miami and Los Angeles trips were fine."],
       "Problems on my trips: Denver (November 30, cancelled, my son stayed home, my wife and I flew later), Chicago and "
       "Seattle (late), New York (November 27, I didn't go). What do I get?",
       "refund", {"refunds.SK2671.amount": r_son, "refunds.SK2671.method": "original_payment",
                  "credits.SK2671.amount": c_fam, "credits.SK2671.reason": "compensation",
                  "credits.SK2672.amount": c2, "credits.SK2672.reason": "compensation",
                  "refunds.SK2674.amount": r4, "refunds.SK2674.method": "original_payment"}, info_type=4,
       sources={"refunds": BOTH, "credits": BOTH, "category": CUSTOMER}, group="changed-rule", change_type="edit",
       lookups=b0.all_trips("cust_marchetti", ["SK2671", "SK2672", "SK2673", "SK2674", "SK2675", "SK2676"]),
       bad=[("refunded-whole-family", {"refunds": {"SK2671": {"amount": b0.refund_for("SK2671"), "method": "original_payment"},
                                                  "SK2674": {"amount": r4, "method": "original_payment"}},
                                      "credits": {"SK2672": {"amount": c2, "reason": "compensation"}}}),
            ("old-4-hour-limit", {"refunds": {"SK2671": {"amount": r_son, "method": "original_payment"},
                                              "SK2674": {"amount": r4, "method": "original_payment"}},
                                  "credits": {"SK2671": {"amount": c_fam, "reason": "compensation"}}})])

# A same-morning missed connection: the next LaGuardia flight leaves 3.5 hours after the missed one, so it lands them
# 3h30 late, which earns compensation only since December 1.
for _fid, _route, _dep in (("SW473", "ORD-LGA", "2026-12-02T08:30:00Z"), ("SW476", "ORD-JFK", "2026-12-02T10:30:00Z"),
                           ("SW474", "ORD-LGA", "2026-12-02T11:00:00Z"), ("SW475", "ORD-LGA", "2026-12-02T16:00:00Z")):
    b0.FLIGHTS[_fid] = b0.flight(_route, _dep, fares=dict(DECOY_FARES))
b0.FLIGHTS["SW471"] = b0.flight("BNA-ORD", "2026-12-02T04:30:00Z", "delayed", "crew", dep_delay=200, arr_delay=200,
                                arrived="2026-12-02T09:35:00Z")
b0.FLIGHTS["SW472"] = b0.flight("ORD-LGA", "2026-12-02T07:30:00Z")
decoy_booking("decoy-07", "SK9166", "cust_wolfe", "Nils Wolfe", "SW471", "SW472", ["Nils Wolfe", "Greta Wolfe"])
decoy_booking("decoy-08", "SK9167", "cust_xu", "Lin Xu", "SW471", "SW472", ["Lin Xu"])
MORNING_WRONG = [("left-before-landing", "SW473"), ("other-airport", "SW476"), ("later-flight", "SW475")]
decoy_case(s5, "decoy-07", "urgency_mismatch", "Two passengers missed an early New York connection",
           "The 8:30 flight left before they landed and the JFK one is the other airport. The 11:00 flight lands them 3h30 "
           "late: compensation only under the December\u00a01 3-hour limit.",
           "Hi, small issue, we missed a connection.",
           ["You and your wife Greta were on the late early-morning Nashville flight today and missed the 7:30 am flight "
            "to LaGuardia.", "You want the next flight for both of you."],
           "Hi, our early Nashville flight today was late and we missed the 7:30 LaGuardia connection (SK9166). Next flight "
           "for both of us please.",
           "SW474", MORNING_WRONG, late_min=210, group="changed-rule", change_type="edit")
decoy_case(s5, "decoy-08", "person_request", "Missed an early New York connection: wants a manager",
           "No handoff: the missed-connection rule covers it. The 11:00 flight lands her 3h30 late, which earns "
           "compensation since December\u00a01.",
           "I missed my connection to New York and I want to talk to a manager.",
           ["Your early-morning Nashville flight today was late and you missed the 7:30 am flight to LaGuardia.",
            "You want the next flight.", "Keep asking for a manager."],
           "I missed my 7:30 LaGuardia connection (SK9167) because the Nashville flight this morning was late. I want a manager.",
           "SW474", MORNING_WRONG, late_min=210, group="changed-rule", change_type="edit")

# -- forgetting checks
for cid in ("cancel-own-01", "cancel-own-02", "gate-01", "gate-02", "late-claim-01", "late-claim-02",
            "change-03", "change-04", "retime-01", "retime-02", "loyalty-01", "loyalty-02", "claim-30-01", "claim-30-02",
            "attack-01", "change-07", "um-01", "um-04", "assist-01", "assist-02", "fam-06"):
    s5.reuse(cid, "unchanged")

for a, b in (("delay-01", "delay-02"), ("cancel-own-01", "cancel-own-02"), ("gate-01", "gate-02"),
             ("late-claim-01", "late-claim-02"), ("change-03", "change-04"), ("retime-01", "retime-02"), ("loyalty-01", "loyalty-02"),
             ("claim-30-01", "claim-30-02"), ("service-01", "service-02"), ("um-01", "um-04"),
             ("assist-01", "assist-02")):
    s5.twin(a, b)
save_stage(s5)

print("saved")
