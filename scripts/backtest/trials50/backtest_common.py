"""Shared config for the trials50 backtest harness (scripts/backtest/trials50).

All runners in this directory import this module. It puts the repo root on
``sys.path`` (so ``import planagent`` resolves from the repo checkout, the
same convention as scripts/acme_baseline_probe.py) and centralises the
three things that used to be hardcoded per script:

- backend base URL (``BACKTEST_BASE``, default http://127.0.0.1:8024)
- run directory for raw JSON / DB / summaries (``BACKTEST_RUN_DIR``,
  default ~/.cache/mingjian-backtest/trials50-fbook — outside the repo,
  so a rerun never dirties the worktree)
- local-proxy secret (``PLANAGENT_LOCAL_PROXY_SECRET`` env, else
  ``$BACKTEST_RUN_DIR/.proxy-secret`` written by start-backend.sh, else
  a ``BACKTEST_LOCAL_ENV`` file holding ``PLANAGENT_LOCAL_PROXY_SECRET=...``)

Harness scripts use urllib and must run with ambient env: do NOT apply
``env -u NO_PROXY -u no_proxy`` to them (that unsetting is for the pytest
invocation only — it strips ``no_proxy`` and routes 127.0.0.1 through the
egress proxy, which drops the connection).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HARNESS_DIR = Path(__file__).resolve().parent
REPO_ROOT = HARNESS_DIR.parent.parent.parent  # scripts/backtest/trials50 -> repo root

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DB_NAME = "trials50-fbook.db"


def get_base() -> str:
    """Scratch-backend base URL (BACKTEST_BASE, default http://127.0.0.1:8024)."""
    return os.environ.get("BACKTEST_BASE", "http://127.0.0.1:8024")


def get_run_dir() -> Path:
    """Run directory for raw JSON / DB / summaries (BACKTEST_RUN_DIR).

    Default: ~/.cache/mingjian-backtest/trials50-fbook. Point it at a tmpfs
    path for faster SQLite commits if desired.
    """
    default = Path.home() / ".cache" / "mingjian-backtest" / "trials50-fbook"
    d = Path(os.environ.get("BACKTEST_RUN_DIR", str(default))).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_db_path() -> Path:
    """Backend DB path (must match what start-backend.sh passes)."""
    return get_run_dir() / DB_NAME


def get_secret() -> str:
    """Local-proxy secret shared by the scratch backend and the runners.

    Priority: PLANAGENT_LOCAL_PROXY_SECRET env > $BACKTEST_RUN_DIR/.proxy-secret
    (written by start-backend.sh) > BACKTEST_LOCAL_ENV file.
    """
    s = os.environ.get("PLANAGENT_LOCAL_PROXY_SECRET")
    if s:
        return s
    f = get_run_dir() / ".proxy-secret"
    if f.exists():
        return f.read_text().strip()
    env_file = os.environ.get("BACKTEST_LOCAL_ENV", "")
    if env_file:
        p = Path(env_file).expanduser()
        if p.exists():
            for line in p.read_text().splitlines():
                if line.startswith("PLANAGENT_LOCAL_PROXY_SECRET="):
                    return line.strip().split("=", 1)[1].strip()
    raise SystemExit(
        "no proxy secret: set PLANAGENT_LOCAL_PROXY_SECRET, or start the backend "
        "with start-backend.sh (it writes $BACKTEST_RUN_DIR/.proxy-secret), or set "
        "BACKTEST_LOCAL_ENV to a file containing PLANAGENT_LOCAL_PROXY_SECRET=..."
    )


def get_seamfix_ref() -> Path:
    """Seam-fix reference replay dir (BACKTEST_SEAMFIX_REF override).

    Default is the committed reference/seamfix/ in this harness dir: the
    B-arm 09-child-replay packages from the seam-fix rerun (ON + OFF),
    used by score_headlines.py as the reference batch.
    """
    override = os.environ.get("BACKTEST_SEAMFIX_REF")
    if override:
        return Path(override).expanduser()
    return HARNESS_DIR / "reference" / "seamfix"
