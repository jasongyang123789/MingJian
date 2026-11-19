"""Acme baseline probe for Track 8 (NOT part of the test suite).

Reproduces the FIX-INFLECTION-DIFFUSION.md probe: BOUND_SET run,
seed 7, tick 2; monte-carlo trials 5, seed 42, metric cash. Baseline
P50 must stay exactly 99.8143 — the red-team layer must not change
baseline behavior (it adds files + API wiring only, no numeric-core
changes). Prints the P50 and exits 0 iff it equals 99.8143.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

for _k in ("NO_PROXY", "no_proxy"):
    os.environ.pop(_k, None)
os.environ["PLANAGENT_DATABASE_URL"] = "sqlite+aiosqlite:////tmp/acme-baseline-probe.db"
os.environ["PLANAGENT_EVENT_BUS_BACKEND"] = "memory"
os.environ["PLANAGENT_INLINE_INGEST_DEFAULT"] = "true"
os.environ["PLANAGENT_INLINE_SIMULATION_DEFAULT"] = "true"
os.environ["PLANAGENT_OPENAI_API_KEY"] = ""
os.environ["PLANAGENT_OPENAI_BASE_URL"] = ""
os.environ.pop("OPENAI_API_KEY", None)

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "tests"))

from fastapi.testclient import TestClient  # noqa: E402

from planagent.config import reset_settings_cache  # noqa: E402
from planagent.db import reset_database_cache  # noqa: E402
from planagent.main import create_app  # noqa: E402
from test_distributions_api import BOUND_SET, simulation_payload  # noqa: E402

DB_PATH = Path("/tmp/acme-baseline-probe.db")
if DB_PATH.exists():
    DB_PATH.unlink()
reset_settings_cache()
reset_database_cache()


def main() -> int:
    with TestClient(create_app()) as client:
        payload = simulation_payload(variable_set=BOUND_SET)
        created = client.post("/simulation/runs", json=payload)
        assert created.status_code == 201, created.text
        run = created.json()
        assert run["status"] == "COMPLETED", run
        mc = client.post(
            f"/runs/{run['id']}/monte-carlo",
            json={"trials": 5, "seed": 42, "metric": "cash"},
        )
        assert mc.status_code == 201, mc.text
        p50 = mc.json()["baseline"]["p50"]
        print(f"Acme baseline P50 (cash, trials 5, seed 42): {p50}")
        if p50 == 99.8143:
            print("BASELINE UNCHANGED: 99.8143")
            return 0
        print("BASELINE CHANGED — expected 99.8143")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
