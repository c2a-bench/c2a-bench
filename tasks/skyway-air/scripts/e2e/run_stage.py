"""Run the real grader (verify.py run) on one stage with the scripted bot and a scripted customer: no model calls.

    python3 /e2e/run_stage.py N     # inside the tests image, as root, with this folder mounted at /e2e

The bot (bot/run) makes each ticket's correct calls from plan.json; the customer always answers "Thanks, that's all I
needed." So every ticket should pass. This checks the harness in the container: paths, the bot user (runuser), the
trace hook install, the server, ticket pairs, retries, kills, hidden files and the reward. It does not check answers.
"""
import os
import shutil
import sys

sys.path.insert(0, "/tests")
import customer  # noqa: E402
import verify  # noqa: E402

customer.ask = lambda *a, **k: {"reply": "Thanks, that's all I needed.", "corrected": False, "switched": False}
n = sys.argv[1]
base = "/tests" if n == "0" else f"/tests/stages/stage{n}"
shutil.copytree("/e2e/bot", "/app/bot", dirs_exist_ok=True)  # the bot under test lives at /app/bot, as in a real run
os.makedirs("/tmp/e2e-state", exist_ok=True)
os.chmod("/tmp/e2e-state", 0o777)  # the bot runs as the unprivileged bot user
os.environ.update({"STAGE": f"stage{n}", "BOT_MODEL": f"e2e/{n}"})
sys.argv = ["verify.py", "run", "--cases", f"{base}/cases.json", "--seed", f"{base}/seed", "--rules", f"{base}/rules.json",
            "--no-replay", "--workers", "8", "--bot-timeout", "60"]
verify.main()
