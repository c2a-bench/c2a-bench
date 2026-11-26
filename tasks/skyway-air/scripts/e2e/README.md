# Harness check with a scripted bot

A no-cost end-to-end check of the grader. `bot/run` is not an AI: it makes each ticket's correct calls from
`plan.json` (rebuilt from the tickets), skipping payments already made, retrying a failed write and quoting the
confirmation id on follow-ups. `run_stage.py` runs the real `verify.py run` with the customer model replaced by a fixed
reply. Every ticket should pass; a failure means the harness, not the answer, is broken. It does not test answer
quality or the real customer model.

Run inside the tests image (see the commands in the PR description), one container per stage.
