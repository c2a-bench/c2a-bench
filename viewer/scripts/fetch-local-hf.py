"""Download the two commit-pinned HF datasets from datasets/production.json into $C2A_LOCAL_DATA/{benchmark,runs} (resumable)."""
import json
import os
from huggingface_hub import snapshot_download

root = os.environ.get("C2A_LOCAL_DATA") or os.path.expanduser("~/.cache/c2a-bench/local-data")
release = json.load(open("datasets/production.json"))
for side in ("benchmark", "runs"):
    ref = release[side]
    snapshot_download(ref["repository"], repo_type="dataset", revision=ref["revision"], local_dir=f"{root}/{side}")
open(f"{root}/.done", "w").close()  # marks a complete download
