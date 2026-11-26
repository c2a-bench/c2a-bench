"""Write the large-policy docs: generator projects for the prose docs, script-written station and country pages.

    python3 build_docs.py work WORK      # set up an isolated generator copy in WORK with every stage's projects
    (in WORK: python -m src.scripts.data_gen_stage_1_generate_clean_data.step_7_generate_project_documents)
    python3 build_docs.py collect WORK   # copy the generated prose docs into docs/, check them
    python3 build_docs.py stages         # after collect: stage 1-5 edits (moved station/country values, retirements)
    python3 build_docs.py check          # check every doc in docs/ (sentences word for word, excluded terms)

docs/stage0/ holds the stage-0 docs (paths under docs/, as in /app/docs); docs/stage<N>/ holds stage N's new and
changed docs, and docs/stage<N>/removed.json the docs it removes. The generator copy is isolated (its own sources and
cache), so nothing of tools/doc-gen or skyway-air's generation state is touched.

Every doc goes through EnterpriseRAG step 7 with the same kind of description build_doc_projects.py gives the tested
rule docs: the sentences word for word, nothing else that sounds like policy. Station and country pages are written
as prose by the generator (facts.py gives each its own facts, conditions and phrasing), so no script can parse them.
"""
import hashlib
import json
import re
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
ERB = REPO / "tools" / "doc-gen"
OUT = HERE / "docs"
sys.path.insert(0, str(HERE))
import plan as P  # noqa: E402

WINDOWS = {0: ("2026-01-12", "2026-05-15"), 1: ("2026-05-26", "2026-06-30"), 2: ("2026-07-06", "2026-08-18"),
           3: ("2026-08-20", "2026-09-01"), 4: ("2026-09-08", "2026-11-03"), 5: ("2026-11-09", "2026-12-01")}
DEPTS = {"checkin": "Airport & Ground Operations", "documents": "Customer Support",
         "privacy": "Digital & Technology", "facilities": "Airport & Ground Operations",
         "enquiries": "Marketing & Communications", "stations": "Airport & Ground Operations",
         "countries": "Customer Support"}
BANNED = ("refunds, travel credit, compensation, reimbursements, payments, fees, fares, prices, costs, vouchers, "
          "delays, cancellations, missed connections, hotels, meals, taxis, bags or luggage, claims, damage, pets, "
          "children or minors, families, wheelchairs or assistance, illness or medical matters, injuries, legal "
          "matters, discrimination, travel agencies or travel managers, who may act on a booking, batteries or "
          "dangerous goods, Skyway Miles or membership tiers, weather, approvals or approving, connections or "
          "connecting flights (say changing planes), ground transport or getting to and from the airport, or handing a "
          "case to a person")


def h(key, n):
    return int(hashlib.sha256(key.encode()).hexdigest()[:12], 16) % n


def day(n, key):
    a, b = (date.fromisoformat(x) for x in WINDOWS[n])
    return (a + timedelta(days=h(key, (b - a).days + 1))).isoformat()


def staff():
    out, dept = {}, None
    for line in (ERB / "generated_data" / "employee_directory.yaml").read_text().splitlines():
        m = re.match(r"^  ([A-Za-z][^:]+):\s*$", line)
        if m:
            dept = m.group(1).strip()
            out[dept] = []
            continue
        m = re.match(r'^\s+- name: "?([^"]+)"?', line)
        if m and dept and not P.excluded_hits(m.group(1)):  # no "Petrov" or "Price" tripping the term check
            out[dept].append(m.group(1))
    return out


# ------------------------------------------------------------------ what each stage holds
def stage_rules(n):
    """The rules in force at stage n: stage-0 rules plus new ones, minus retired ones."""
    rules = {r: (a, s) for r, a, s in P.RULES}
    for k in range(1, n + 1):
        for r, a, s in P.STAGE_NEW_RULES[k]:
            rules[r] = (a, s)
        rules.pop(P.STAGE_RETIRED[k], None)
    return rules


def changed_by(code, n):
    """The stages (<= n) whose plan changes this station's or country's values."""
    out = []
    for k in range(1, n + 1):
        sp = P.stage_plan(k)
        if code in sp["station_value_changes"] or code in sp["country_value_changes"]:
            out.append(k)
    return out


def salt(code, n):
    """A marker of the last stage that changed this station or country (stage 0: none), for keys and dates."""
    ks = changed_by(code, n)
    return f"#s{ks[-1]}" if ks else ""


def prose_docs():
    """{stage: {docs/... path: {"states": [...], "area": ..., "kind": ..., "rules": [...]}}} for the generator."""
    out = {n: {} for n in range(6)}
    for path, d in P.stage0_docs().items():
        out[0][path] = d  # rule pages, threads, decoys, station and country handbooks, Slack updates
    for n in range(1, 6):
        sp = P.stage_plan(n)
        for rid, area, sents in sp["new_rules"]:
            conf, slack = P.AREAS[area]
            out[n][f"docs/{conf}/{area}-{rid.lower()}.json"] = {"states": sents, "area": area, "kind": "page",
                                                                "rules": [rid]}
            out[n][f"docs/{slack}/{area}-{rid.lower()}-thread.json"] = {"states": sents, "area": area,
                                                                        "kind": "thread", "rules": [rid]}
        rid = sp["retired_rule"]
        area = next(a for r, a, _ in P.RULES if r == rid)
        out[n][f"docs/confluence/policy-and-compliance/change-log/{area}-{rid.lower()}-retired.json"] = {
            "states": [f"From {WINDOWS[n][0]}, this no longer applies: " + " ".join(dict((r, s) for r, _, s in P.RULES)[rid])],
            "area": area, "kind": "retired", "rules": [rid]}
        for code in sp["drafts"]:
            city = dict(P.STATIONS)[code]
            out[n][f"docs/slack/airport-ops/{P.slug(city)}-{code.lower()}-cut-off-proposal.json"] = {
                "states": [f"Proposal, not in force: move {city} ({code}) "
                           f"{'international' if code in P.INTL else 'domestic'} check-in cut-off to "
                           f"{([75, 90, 105, 120] if code in P.INTL else [30, 40, 50, 60])[h(code + str(n), 4)]} minutes. "
                           f"Until it is agreed the station handbook times stand."],
                "area": "stations", "kind": "draft", "rules": []}
    return out


def page_of(n, rid):
    """The stage-0 page that states a rule (for editing when it retires)."""
    for path, d in P.stage0_docs().items():
        if d["kind"] == "page" and rid in d["rules"]:
            return path
    return None


# ------------------------------------------------------------------ generator projects
def describe(path, d, n):
    kind, place = path.split("/")[1], path.split("/")[2]
    a, b = WINDOWS[n]
    sentences = "; ".join(f'"{x}"' for x in d["states"])
    if d["kind"] == "station":
        code = d["rules"][0]
        city = dict(P.STATIONS)[code]
        head = (f"The Skyway station handbook page for {city} ({code}) in the airport-operations space, last updated "
                f"between {a} and {b}: a practical page for support agents about Skyway at that airport, written in "
                f"prose under headings of your own choosing (not a table, not one line per fact), in any order")
    elif d["kind"] == "country":
        head = (f"A travel-documents page in the customer-policies space about what Skyway checks at check-in for "
                f"travellers flying to {d['rules'][0]}, last updated between {a} and {b}, written in prose under "
                f"headings of your own choosing (not a table)")
    elif d["kind"] == "update":
        head = (f"A short Slack thread in #airport-ops where a station lead posts a change to the station handbook, "
                f"dated in early May 2026 (between 2026-05-01 and 2026-05-15)")
    elif d["kind"] == "retired":
        head = f"A short entry in the Skyway policy change log, dated between {a} and {b}"
    elif kind == "slack":
        head = (f"A Slack thread in #{place} between Skyway staff, dated between {a} and {b}: a normal working "
                f"conversation; one message may carry each sentence below")
    else:
        head = f"A Confluence page in the {place} space for support agents, last updated between {a} and {b}"
    extra = " Its status is draft." if d["kind"] == "draft" else ""
    tail = " Do not end the thread with a summary." if kind == "slack" else ""
    return (f"{head}. It must contain these sentences word for word: {sentences}.{extra} Do not state any other "
            f"policy, limit, time or rule.{tail} Do not name any airport, airport code or city other than ones in these "
            f"sentences. Do not mention {BANNED}.")


def work(dest, only=None):
    dest = Path(dest)
    if dest.exists():
        sys.exit(f"{dest} exists: pick a new folder")
    dest.mkdir(parents=True)
    for item in ("src", "requirements.txt", "pyproject.toml"):
        src = ERB / item
        (shutil.copytree if src.is_dir() else shutil.copyfile)(src, dest / item)
    (dest / "generated_data").mkdir()
    for f in (ERB / "generated_data").iterdir():
        if f.is_file():
            shutil.copyfile(f, dest / "generated_data" / f.name)
    for guide in (ERB / "generated_data" / "sources").rglob("agents.md"):
        to = dest / "generated_data" / guide.relative_to(ERB / "generated_data")
        to.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(guide, to)
    (dest / "generation_cache" / "projects").mkdir(parents=True)
    people = staff()
    manifest = {}
    count = 0
    for n, docs in prose_docs().items():
        for path, d in sorted(docs.items()):
            if only is not None and "sources/" + path[len("docs/"):] not in only:
                continue
            # one doc per project: a writer sees its whole project, and these must not borrow from each other
            name = f"skyway-large-s{n}-{Path(path).stem}"
            pool = people.get(DEPTS.get(d["area"], "Customer Support"), []) + people.get("Customer Support", [])
            picked = [pool[(h(name, 10**6) + 7 * i) % len(pool)] for i in range(3)]
            project = {"description": "Skyway Air support documentation and staff discussion.",
                       "files": [{"path": "sources/" + path[len("docs/"):], "description": describe(path, d, n)}],
                       "people": [{"name": p, "project_role": "staff"} for p in picked]}
            (dest / "generation_cache" / "projects" / f"{name}.json").write_text(json.dumps(project, indent=2))
            manifest["sources/" + path[len("docs/"):]] = {"stage": n, "states": d["states"], "kind": d["kind"]}
            count += 1
    (dest / "large_manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"{count} projects in {dest}/generation_cache/projects. Generate with:")
    print(f"  cd {dest} && uv venv -q && uv pip install -q -r requirements.txt && "
          f"sh -c 'set -a && . {REPO}/.env && set +a && export LLM_PROVIDER=openai "
          f"LLM_API_KEY=\"$OPENAI_API_KEY\" LLM_MODEL_NAME=gpt-5.6-terra CHEAP_LLM_MODEL_NAME=gpt-5.6-luna "
          f"PYTHONPATH=$PWD USAGE_LOG=usage.jsonl && .venv/bin/python -m "
          f"src.scripts.data_gen_stage_1_generate_clean_data.step_7_generate_project_documents "
          f"--project-parallelism 20'")


# ------------------------------------------------------------------ collect and check
def norm(t):
    return re.sub(r"\s+", " ", t.replace("’", "'").replace("‘", "'").replace("“", '"')
                  .replace("”", '"').replace("—", "-").replace("–", "-")).strip()


def doc_text(doc):
    return norm(" ".join(v if isinstance(v, str) else " ".join(map(str, v)) for k, v in doc.items()
                         if k not in ("dataset_doc_uuid", "title_field_name", "content_field_names", "author",
                                      "participants", "status", "document_type", "owner_team", "source_system",
                                      "channel", "created_at", "last_updated")))


def problems(doc, states, path=""):
    text = doc_text(doc)
    out = [f"missing: {s[:60]}" for s in states if norm(s) not in text]
    hits = P.excluded_hits(text, P.own_station(path))
    if hits:
        out.append(f"excluded terms: {hits}")
    return out


def collect(work_dir):
    work_dir = Path(work_dir)
    manifest = json.loads((work_dir / "large_manifest.json").read_text())
    bad, ok = {}, 0
    for src, m in manifest.items():
        f = work_dir / "generated_data" / src
        if not f.exists():
            bad[src] = ["not generated"]
            continue
        doc = json.loads(f.read_text())
        p = problems(doc, m["states"], src)
        if p:
            bad[src] = p
            continue
        to = OUT / f"stage{m['stage']}" / ("docs/" + src[len("sources/"):])
        to.parent.mkdir(parents=True, exist_ok=True)
        to.write_text(json.dumps(doc, indent=2) + "\n")
        ok += 1
    (HERE / "regenerate.json").write_text(json.dumps(bad, indent=1) + "\n")
    print(f"{ok} docs collected, {len(bad)} to regenerate (regenerate.json)")
    for k, v in list(bad.items())[:20]:
        print(f"  {k}: {v}")


# ------------------------------------------------------------------ station and country pages
def soft(t):
    """norm() without joining lines: quotes and dashes made plain, runs of spaces collapsed, line breaks kept."""
    t = (t.replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')
         .replace("\u2014", "-").replace("\u2013", "-"))
    return re.sub(r"[ \t]+", " ", t)


def rewrite(doc, pairs):
    """Replace each (old, new) sentence in the doc's text fields; returns how many were found."""
    found = 0
    for k, v in doc.items():
        if k in ("title", "dataset_doc_uuid", "title_field_name", "content_field_names"):
            continue
        vals = v if isinstance(v, list) else [v] if isinstance(v, str) else []
        new_vals = []
        for x in vals:
            if isinstance(x, str):
                for old, new in pairs:
                    if norm(old) and norm(old) in soft(x):
                        x = soft(x).replace(norm(old), new)
                        found += 1
            new_vals.append(x)
        doc[k] = new_vals if isinstance(v, list) else (new_vals[0] if new_vals else v)
    return found


def reword_pages():
    """Swap each stage-0 station, country and Slack-update page's sentences for their reworded versions
    (reword_map.json, via plan.py). Run before `stages`, which then moves the reworded sentences."""
    done, missing = 0, []
    for path, d in P.stage0_docs().items():
        if d["kind"] not in ("station", "country", "update"):
            continue
        f = OUT / "stage0" / path
        if not f.exists():
            missing.append(path)
            continue
        code = d["rules"][0]
        if d["kind"] == "station":
            city = dict(P.STATIONS)[code]
            old, new = P.station_page(code, city, reword=False), P.station_page(code, city)
        elif d["kind"] == "country":
            old, new = P.country_page(code, reword=False), P.country_page(code)
        else:
            city = dict(P.STATIONS)[code]
            old, new = P.station_update(code, city, reword=False)[1], P.station_update(code, city)[1]
        pairs = [(o, n) for o, n in zip(old, new) if o != n]
        doc = json.loads(f.read_text())
        text = doc_text(doc)
        pairs = [(o, n) for o, n in pairs if norm(o) in text]  # already swapped on a rerun
        if not pairs:
            continue
        if rewrite(doc, pairs) < len(pairs):
            missing.append(path)
            continue
        f.write_text(json.dumps(doc, indent=2) + "\n")
        done += 1
    print(f"reworded sentences swapped into {done} pages; {len(missing)} problems {missing[:5]}")


def stage_edits():
    """Stages 1-5: a changed station or country page is the latest version of its generated page with the moved
    sentences replaced; a retired rule's sentences leave its page. Run after collect."""
    edited, missing = 0, []

    def latest(n, page):
        return next((OUT / f"stage{k}" / page for k in range(n - 1, -1, -1) if (OUT / f"stage{k}" / page).exists()), None)

    for n in range(1, 6):
        moves = []
        for code, city in P.STATIONS:
            if n in changed_by(code, n):
                old = P.station_page(code, city, changed_by(code, n - 1))
                new = P.station_page(code, city, changed_by(code, n))
                page = f"docs/confluence/airport-operations/stations/{P.slug(city)}-{code.lower()}.json"
                moves.append((page, [(o, w) for o, w in zip(old, new) if o != w], "station" + code))
        for c in P.COUNTRIES:
            if n in changed_by(c, n):
                old, new = P.country_page(c, changed_by(c, n - 1)), P.country_page(c, changed_by(c, n))
                page = f"docs/confluence/customer-policies/travel-documents/countries/{P.slug(c)}.json"
                moves.append((page, [(o, w) for o, w in zip(old, new) if o != w], "country" + c))
        rid = P.STAGE_RETIRED[n]
        moves.append((page_of(n, rid), [(x, "") for x in dict((r, s) for r, _, s in P.RULES)[rid]], "retire" + rid))
        for page, pairs, key in moves:
            src = latest(n, page)
            if src is None:
                missing.append(f"stage {n}: {page} not collected")
                continue
            doc = json.loads(src.read_text())
            if rewrite(doc, pairs) < len(pairs):
                missing.append(f"stage {n}: {page}: a changed sentence is not in the page")
                continue
            doc["last_updated"] = day(n, key)
            to = OUT / f"stage{n}" / page
            to.parent.mkdir(parents=True, exist_ok=True)
            to.write_text(json.dumps(doc, indent=2) + "\n")
            edited += 1
    print(f"{edited} stage edits written; {len(missing)} problems")
    for m in missing[:20]:
        print("  " + m)


def add_labels():
    """Give every collected stage-0 station and country page its label line (plan.station_page / country_page end
    with it), appended as a short "Ticket handling" section, so pages generated before the line existed need no
    regeneration."""
    added = 0
    for path, d in P.stage0_docs().items():
        if d["kind"] not in ("station", "country"):
            continue
        f = OUT / "stage0" / path
        if not f.exists():
            continue
        doc = json.loads(f.read_text())
        line = d["states"][-1]
        if norm(line) in doc_text(doc):
            continue
        if isinstance(doc.get("content"), str):
            doc["content"] = doc["content"].rstrip() + "\n\n## Ticket handling\n\n" + line
        else:
            doc["ticket_handling"] = line
            doc.setdefault("content_field_names", []).append("ticket_handling")
        f.write_text(json.dumps(doc, indent=2) + "\n")
        added += 1
    print(f"label line added to {added} pages")


def missing_list():
    """Every planned doc not collected yet, for work --regenerate; and collected docs no longer planned (removed)."""
    planned = {n: set(docs) for n, docs in prose_docs().items()}
    todo, stale = [], 0
    for n, paths in planned.items():
        for p in paths:
            if not (OUT / f"stage{n}" / p).exists():
                todo.append("sources/" + p[len("docs/"):])
    for f in OUT.glob("stage0/docs/**/*.json"):
        rel = f.relative_to(OUT / "stage0").as_posix()
        if rel not in planned[0]:
            f.unlink()
            stale += 1
    (HERE / "regenerate.json").write_text(json.dumps(sorted(todo), indent=1) + "\n")
    print(f"{len(todo)} docs to generate (regenerate.json); {stale} stage-0 docs no longer planned removed")


def check():
    bad = 0
    total = 0
    for n in range(6):
        for f in sorted((OUT / f"stage{n}").rglob("*.json")):
            doc = json.loads(f.read_text())
            hits = P.excluded_hits(doc_text(doc), P.own_station(f.as_posix()))
            total += 1
            if hits:
                bad += 1
                print(f"  stage {n} {f.relative_to(OUT / f'stage{n}')}: {hits}")
    print(f"{total} docs, {bad} with excluded terms")
    return 1 if bad else 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "work":
        only = set(json.loads((HERE / "regenerate.json").read_text())) if "--regenerate" in sys.argv else None
        work(sys.argv[2], only)
    elif cmd == "collect":
        collect(sys.argv[2])
    elif cmd == "stages":
        stage_edits()
    elif cmd == "reword":
        reword_pages()
    elif cmd == "labels":
        add_labels()
    elif cmd == "missing":
        missing_list()
    elif cmd == "check":
        raise SystemExit(check())
    else:
        print(__doc__)
