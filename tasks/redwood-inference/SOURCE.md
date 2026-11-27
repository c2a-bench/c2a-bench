# Source

Docs from [EnterpriseRAG-Bench](https://github.com/onyx-dot-app/EnterpriseRAG-Bench) (Redwood Inference), MIT.

## How the data was made

Download the bench first, from the repo root: `python3 scripts/fetch_bench.py --revision <commit>`. The scripts below
work on the downloaded files.

- **Docs.** Stage 0 is a small set of Redwood Inference's docs from EnterpriseRAG-Bench. Each later stage's update
  (`steps/stageN/workdir/stageN_update`) holds, in `new_docs/`, the pages the stage adds and the full new version of
  each page it changes; `changes.json` lists the update and any small text edits.
- **Rules and tickets, stage 0.** `scripts/build_stage0_tickets.py` writes the support API doc, the seed data, the
  rules (`tests/rules.json`), the tickets (`tests/cases.json`) and the fixtures the grader is tested on. Each ticket is
  written in the script: the rules it needs, the customer's opening and the facts the customer shares only when asked,
  the customer's behaviour, and the end state that passes (field values, labels, calls that must or must not be made).
- **Rules and tickets, stages 1-5.** `scripts/build_stage_tickets.py` builds each stage on the one before. It keeps the
  earlier tickets, and adds tickets whose right answer the stage changed, tickets that check an unchanged rule is not
  forgotten, and tickets on the new rules.
- **Customer behaviours.** Every ticket has one behaviour, set in the scripts above. The behaviours are listed in
  `scripts/behavior/types.json`, and `tests/customer.py` turns each into instructions for the simulated customer. A
  behaviour changes only how the customer talks, never the facts or the right answer.
- **Facts.** `python3 scripts/build_facts.py tasks/redwood-inference` (from the repo root) splits the rules into the
  facts the judge checks.

Run the two ticket scripts from `tasks/redwood-inference`, stage 0 first:

```bash
python3 scripts/build_stage0_tickets.py && python3 scripts/build_stage_tickets.py
```

On the downloaded bench they write back the published rules and tickets, and `build_facts.py` the published facts.
