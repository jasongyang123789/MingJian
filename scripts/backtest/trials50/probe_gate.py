"""Gate preflight probe (AGENTS.md): one SQLite create/insert/commit
under the run's TMPDIR. Exit 0 iff the write-denial gate is open
right now; exit 1 otherwise. A single pass does not guarantee the
whole run stays open — it only gates the start.
"""
import os
import sqlite3
import sys
import tempfile

PROBE_DIR = os.environ.get("BACKTEST_PROBE_DIR", tempfile.gettempdir())
os.makedirs(PROBE_DIR, exist_ok=True)

try:
    p = tempfile.mktemp(suffix=".db", dir=PROBE_DIR)
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE t (a INT)")
    c.execute("INSERT INTO t VALUES (1)")
    c.commit()
    c.close()
    os.unlink(p)
    print("probe OK")
except Exception as e:  # noqa: BLE001 — any failure means the gate is closed
    print(f"probe FAIL: {e}")
    sys.exit(1)
