# Knowledge packs

`Rcomplete` (downloaded into `steps/Rcomplete/workdir/pack/docs` by `scripts/fetch_bench.py`) is the source of truth.
`scripts/build_packs.py` builds every other pack from it with one controlled change, checks that each pack changes only
what its condition allows, and compares the result with the downloaded packs (`--write` writes them into `steps/`).
`_extras/` holds what the packs add or remove.

| Pack | Built from Rcomplete by | Checked |
| --- | --- | --- |
| `Rcomplete` | — (cleaned stage-0 docs: traps/decoys removed; authority notes on current pages). Baseline `Qcomplete`. | — |
| `Rfragmented` | Moving whole sections word for word onto sibling pages (audit: legal review, routing; tagging: offering, primary symptom; API keys: revoke procedure, post-actions; token accounting: double counting). Nothing added or reworded. | Its lines equal Rcomplete's |
| `Rincomplete` | The edits in `_extras/Rincomplete/edits.json`: offering and symptom-timeout label names, audit routing and legal gates, token-accounting label, Eng-engaged paging line removed; placeholders where a page would say so. | Only those pages change; removed facts are not readable anywhere |
| `Rconflicting` | Adding `_extras/Rconflicting` (SLA v1 2025, audit v0 draft, 2025 routing shortcut, Slack label thread); the current pages supersede them. | Rcomplete pages unchanged |
| `Rnoisy` | Adding `_extras/Rnoisy` (look-alike playbooks from the redwood-inference stage-1 corpus that answer none of the tickets). | Rcomplete pages unchanged |
