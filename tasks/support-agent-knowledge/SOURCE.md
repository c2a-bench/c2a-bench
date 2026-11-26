# Source

Docs from [EnterpriseRAG-Bench](https://github.com/onyx-dot-app/EnterpriseRAG-Bench) (Redwood Inference), MIT.

## How the data was made

Download the bench first, from the repo root: `python3 scripts/fetch_bench.py --revision <commit>`. The scripts below
work on the downloaded files.

- **Packs.** `Rcomplete` is Redwood Inference's stage-0 docs, cleaned: the trap and decoy pages removed, and a note on
  each current policy page that it is the one in force. Every other pack is `Rcomplete` with one change, so a score
  drop can be put down to that change alone. `scripts/build_packs.py` builds them; [`packs/README.md`](packs/README.md)
  says what each one changes.
- **Tickets.** The task keeps Redwood Inference's 17 stage-0 tickets and adds 50 written for it, every one answerable
  from `Rcomplete`, most touching a fact some pack changes. `scripts/build_tickets.py` writes the new tickets, their
  seed data and fixtures. Customers here are plain: no ticket has a special behaviour.
- **Facts.** `python3 scripts/build_facts.py tasks/support-agent-knowledge` (from the repo root) splits the rules into
  the facts the judge checks.

From `tasks/support-agent-knowledge`:

```bash
python3 scripts/build_packs.py && python3 scripts/build_tickets.py
```

On the downloaded bench they give back the published packs, tickets and facts.
