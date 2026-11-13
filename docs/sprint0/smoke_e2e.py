"""Sprint 0 end-to-end smoke test (no LLM, no Docker).

Mirrors the documented example flow in examples/agent_startup/README.md:
ingest seed evidence -> run baseline simulation -> read decision trace,
workbench and options. Uses a scratch SQLite DB and empty LLM keys, the
same pattern the repo's own API tests use (tests/test_phase1_api.py).

Deliberately does NOT call POST /debates/trigger: the debate workflow
uses LLMDebateAdapter (src/planagent/services/debate/workflow.py) and
requires a real model key. That step is the documented LLM boundary.

Usage (from repo root):
    .venv/bin/python docs/sprint0/smoke_e2e.py
Exit code 0 = all exercised steps passed; writes
docs/sprint0/smoke-evidence.json with request/response evidence.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# --- Environment BEFORE importing planagent (settings are cached) ---
# This VM's NO_PROXY/no_proxy contain bracketed IPv6 literals that httpx
# cannot parse when AsyncOpenAI clients are constructed (httpx.InvalidURL:
# Invalid port). The app makes no external calls in this smoke test, so
# drop the bypass lists for this process. See SPRINT0.md section 4.
for _k in ("NO_PROXY", "no_proxy"):
    os.environ.pop(_k, None)
REPO = Path(__file__).resolve().parents[2]
DB_PATH = Path("/tmp/sprint0-smoke.db")
if DB_PATH.exists():
    DB_PATH.unlink()
os.environ["PLANAGENT_DATABASE_URL"] = f"sqlite+aiosqlite:///{DB_PATH}"
os.environ["PLANAGENT_OPENAI_API_KEY"] = ""
os.environ["PLANAGENT_OPENAI_BASE_URL"] = ""
os.environ["PLANAGENT_ANTHROPIC_API_KEY"] = ""
os.environ["PLANAGENT_MCP_ENABLED"] = "false"
os.environ["PLANAGENT_EVENT_BUS_BACKEND"] = "memory"  # no Redis in this env
os.environ["PLANAGENT_INLINE_INGEST_DEFAULT"] = "true"
os.environ["PLANAGENT_INLINE_SIMULATION_DEFAULT"] = "true"

sys.path.insert(0, str(REPO / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from planagent.config import reset_settings_cache  # noqa: E402
from planagent.db import reset_database_cache  # noqa: E402
from planagent.main import create_app  # noqa: E402

evidence: dict = {"steps": []}


def record(name: str, status: int, body) -> None:
    evidence["steps"].append({"step": name, "status": status, "body": body})
    print(f"[{status}] {name}: {json.dumps(body, ensure_ascii=False)[:400]}")


def main() -> int:
    reset_settings_cache()
    reset_database_cache()
    failures = []
    with TestClient(create_app()) as client:
        # 1. Health
        r = client.get("/health")
        record("GET /health", r.status_code, r.json())
        if r.status_code != 200:
            failures.append("health")

        # 2. Ingest seed evidence
        ingest_payload = json.loads(
            (REPO / "examples/agent_startup/evidence_ingest.json").read_text()
        )
        r = client.post("/ingest/runs", json=ingest_payload)
        body = r.json()
        record("POST /ingest/runs", r.status_code, body)
        if r.status_code != 201:
            failures.append("ingest")
        ingest_id = body.get("id")

        # 3. Baseline simulation (4 ticks)
        sim_payload = json.loads(
            (REPO / "examples/agent_startup/baseline_simulation.json").read_text()
        )
        r = client.post("/simulation/runs", json=sim_payload)
        body = r.json()
        record("POST /simulation/runs", r.status_code, body)
        if r.status_code != 201:
            failures.append("simulation")
        run_id = body.get("id")
        run_status = body.get("status")

        # 4. Decision trace
        if run_id:
            r = client.get(f"/runs/{run_id}/decision-trace")
            trace = r.json()
            methods = [t.get("decision_method") for t in trace] if isinstance(trace, list) else []
            record(
                "GET /runs/{id}/decision-trace",
                r.status_code,
                {"records": len(trace) if isinstance(trace, list) else trace, "methods": methods},
            )
            if r.status_code != 200 or len(trace) != sim_payload["tick_count"]:
                failures.append("decision-trace")

            # 5. Workbench
            r = client.get(f"/runs/{run_id}/workbench")
            record("GET /runs/{id}/workbench", r.status_code, {"keys": sorted(r.json())} if r.status_code == 200 else r.text[:200])
            if r.status_code != 200:
                failures.append("workbench")

            # 6. Decision options
            r = client.get(f"/runs/{run_id}/options")
            options = r.json()
            record(
                "GET /runs/{id}/options",
                r.status_code,
                {"options": len(options) if isinstance(options, list) else options},
            )
            if r.status_code != 200:
                failures.append("options")

        evidence["summary"] = {
            "ingest_run_id": ingest_id,
            "simulation_run_id": run_id,
            "simulation_status": run_status,
            "llm_boundary": "POST /debates/trigger NOT exercised: requires a real LLM key "
            "(LLMDebateAdapter in services/debate/workflow.py).",
            "failures": failures,
        }

    out = REPO / "docs/sprint0/smoke-evidence.json"
    out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
    print(f"evidence -> {out}")
    print("SMOKE:", "PASS" if not failures else f"FAIL {failures}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
