"""Where the EnterpriseRAG doc generator and its Skyway data live.

The generator is kept in the repo at tools/doc-gen (upstream: github.com/onyx-dot-app/EnterpriseRAG-Bench,
see its C2A.md). Set ERB_GEN_DIR to use another checkout.

The repo's docs (environment/app/docs) are the source of truth. The generator's generated_data/sources is a working
copy that sync_erb_sources.py fills from them; scripts that write stage-0 docs into both call require_in_sync() first,
so a stale copy can never overwrite the repo's docs.
"""
import hashlib
import os
import sys
from pathlib import Path

TASK = Path(__file__).resolve().parents[1]
REPO = TASK.parents[1]
ERB = Path(os.environ.get("ERB_GEN_DIR") or REPO / "tools" / "doc-gen").expanduser()
DATA = ERB / "generated_data"
SOURCES = DATA / "sources"
STAFF = DATA / "employee_directory.yaml"
ENV_DOCS = TASK / "environment" / "app" / "docs"


def _digest(root):
    """{relative path: sha1} of every doc (.json) under root."""
    out = {}
    for f in root.rglob("*.json"):
        out[str(f.relative_to(root))] = hashlib.sha1(f.read_bytes()).hexdigest()
    return out


def differences(limit=5):
    """(missing in sources, extra in sources, different content), each a short list, between the repo's stage-0 docs
    and the generator's sources."""
    repo, src = _digest(ENV_DOCS), _digest(SOURCES) if SOURCES.exists() else {}
    missing = sorted(set(repo) - set(src))
    extra = sorted(set(src) - set(repo))
    changed = sorted(p for p in set(repo) & set(src) if repo[p] != src[p])
    return missing, extra, changed


def require_in_sync():
    """Stop unless the generator's sources match the repo's docs exactly."""
    missing, extra, changed = differences()
    if missing or extra or changed:
        sys.exit(f"{SOURCES} does not match {ENV_DOCS}: {len(missing)} missing, {len(extra)} extra, "
                 f"{len(changed)} different (e.g. {(missing + extra + changed)[:3]}). "
                 f"Run python3 tasks/skyway-air/scripts/sync_erb_sources.py first.")
