"""API tests for the Sprint 11 monitoring worker (evaluate + record).

Covers one monitoring cycle over the Sprint 9 loop fixtures: fired /
quiet / no-data outcomes, fingerprint dedup (unchanged inputs write
no new row), new rows when observations or registrations change,
recorded error rows with per-loop isolation, the automation
boundary (a cycle creates no runs or iterations and mutates no loop
state), the evaluation-history endpoint, and the worker itself
(``MonitoringWorker.run_once`` + CLI registration + schedule
config).

Same scratch-SQLite + in-memory-bus + empty-LLM-keys pattern as the
Sprint 1–10 tests. The evidence-free setup is deliberate: with no
claims ingested, every tick takes the ``monitor`` fallback, so the
baseline's final state equals its sampled starting state and the
tests verify the monitoring machinery, not a forecast.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from planagent.config import get_settings, reset_settings_cache
from planagent.db import get_database, reset_database_cache
from planagent.domain.models import SimulationRun, StrategyLoopRecord
from planagent.events.bus import build_event_bus
from planagent.main import create_app
from planagent.services.simulation import SimulationService
from planagent.simulation.rules import get_rule_registry
from planagent.worker_cli import build_worker, list_workers
from planagent.workers.monitoring import MonitoringWorker

BOUND_SET = {
    "name": "case",
    "variables": [
        {
            "id": "cash",
            "unit": "k",
            "distribution": {"type": "triangular", "min": 60, "mode": 100, "max": 140},
            "evidence_ref": "estimate: founder judgment",
        },
    ],
    "internal": {"team": "20 people"},
}

BASELINE_CUTOFF = "2026-01-01T00:00:00Z"
REVIEW_TIME = "2026-02-01T00:00:00Z"

TRIGGERS = [
    {
        "kind": "threshold",
        "name": "cash-floor",
        "field": "cash",
        "operator": "<",
        "threshold": 70.0,
    },
    {
        "kind": "gate",
        "name": "cash-mean",
        "field": "cash",
        "gate": {
            "name": "cash-mean-gate",
            "metric": "mean",
            "arm": "baseline",
            "operator": "<",
            "threshold": 90.0,
        },
    },
    {
        "kind": "deviation",
        "name": "cash-drift",
        "field": "cash",
        "reference_value": 100.0,
        "tolerance": 20.0,
        "consecutive": 2,
    },
]


def build_database_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.resolve().as_posix()}"


def setup_app(monkeypatch, tmp_path: Path, db_name: str = "planagent-monitoring.db") -> None:
    monkeypatch.setenv("PLANAGENT_DATABASE_URL", build_database_url(tmp_path / db_name))
    monkeypatch.setenv("PLANAGENT_EVENT_BUS_BACKEND", "memory")
    monkeypatch.setenv("PLANAGENT_INLINE_INGEST_DEFAULT", "true")
    monkeypatch.setenv("PLANAGENT_INLINE_SIMULATION_DEFAULT", "true")
    monkeypatch.setenv("PLANAGENT_OPENAI_API_KEY", "")
    monkeypatch.setenv("PLANAGENT_OPENAI_BASE_URL", "")
    monkeypatch.setenv("PLANAGENT_OPENAI_PRIMARY_API_KEY", "")
    monkeypatch.setenv("PLANAGENT_OPENAI_PRIMARY_BASE_URL", "")
    monkeypatch.setenv("PLANAGENT_OPENAI_EXTRACTION_API_KEY", "")
    monkeypatch.setenv("PLANAGENT_OPENAI_EXTRACTION_BASE_URL", "")
    monkeypatch.setenv("PLANAGENT_OPENAI_REPORT_API_KEY", "")
    monkeypatch.setenv("PLANAGENT_OPENAI_REPORT_BASE_URL", "")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    reset_settings_cache()
    reset_database_cache()


def _create_baseline_run(client: TestClient, **overrides) -> dict:
    payload: dict = {
        "company_id": "loop-test-co",
        "company_name": "Loop Test Co",
        "market": "ai",
        "tick_count": 2,
        "seed": 7,
        "actor_template": "default",
        "variable_set": BOUND_SET,
        "decision_time": BASELINE_CUTOFF,
    }
    payload.update(overrides)
    created = client.post("/simulation/runs", json=payload)
    assert created.status_code == 201, created.text
    run = created.json()
    assert run["status"] == "COMPLETED"
    return run


def _create_loop(client: TestClient, run_id: str, **overrides) -> dict:
    payload: dict = {"name": "AI service line", "baseline_run_id": run_id, "triggers": TRIGGERS}
    payload.update(overrides)
    response = client.post("/loops", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _record_observation(client: TestClient, loop_id: str, value: float, observed_at: str) -> dict:
    response = client.post(
        f"/loops/{loop_id}/observations",
        json={"field": "cash", "value": value, "observed_at": observed_at},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _run_cycle(client: TestClient) -> dict:
    response = client.post("/loops/monitoring/evaluate")
    assert response.status_code == 200, response.text
    return response.json()


def _history(client: TestClient, loop_id: str, **params) -> list[dict]:
    response = client.get(f"/loops/{loop_id}/evaluations", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _run_count(client: TestClient) -> int:
    response = client.get("/simulation/runs")
    assert response.status_code == 200, response.text
    return len(response.json())


# ------------------------------------------------------------------- cycles


def test_cycle_evaluates_and_records_fired(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        baseline = _create_baseline_run(client)
        loop = _create_loop(client, baseline["id"])
        registration_id = loop["triggers"][0]["id"]
        obs1 = _record_observation(client, loop["id"], 95.0, "2026-01-10T00:00:00Z")
        obs2 = _record_observation(client, loop["id"], 65.0, "2026-01-20T00:00:00Z")
        obs3 = _record_observation(client, loop["id"], 60.0, "2026-01-25T00:00:00Z")

        cycle = _run_cycle(client)
        assert cycle["loops_evaluated"] == 1
        assert cycle["loops_skipped"] == 0
        assert cycle["loops_fired"] == 1
        assert cycle["loops_errored"] == 0
        assert cycle["errors"] == []
        assert len(cycle["loops"]) == 1
        loop_result = cycle["loops"][0]
        assert loop_result["loop_id"] == loop["id"]
        assert loop_result["result"] == "evaluated"
        assert loop_result["summary"] == "fired"

        rows = _history(client, loop["id"])
        assert len(rows) == 1
        row = rows[0]
        assert row["id"] == loop_result["evaluation_id"]
        assert row["cycle_id"] == cycle["cycle_id"]
        assert row["registration_id"] == registration_id
        assert row["observation_ids"] == [obs1["id"], obs2["id"], obs3["id"]]
        assert row["observation_fingerprint"].startswith("sha256:")
        assert row["summary"] == "fired"
        assert row["error_code"] is None
        assert row["error_message"] is None
        outcomes = {item["name"]: item for item in row["outcomes"]}
        assert outcomes["cash-floor"]["fired"] is True
        assert outcomes["cash-floor"]["observed_value"] == 60.0  # latest overall
        assert outcomes["cash-mean"]["fired"] is True
        assert outcomes["cash-mean"]["observed_value"] == pytest.approx((95 + 65 + 60) / 3)
        assert outcomes["cash-drift"]["fired"] is True
        assert outcomes["cash-drift"]["observed_value"] == 40.0  # |60 - 100|
        assert outcomes["cash-drift"]["reference_value"] == 100.0
        assert outcomes["cash-drift"]["consecutive_breaches"] == 2


def test_cycle_dedups_unchanged_inputs(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        baseline = _create_baseline_run(client)
        loop = _create_loop(client, baseline["id"])
        _record_observation(client, loop["id"], 95.0, "2026-01-10T00:00:00Z")

        first = _run_cycle(client)
        assert first["loops_evaluated"] == 1
        first_row_id = first["loops"][0]["evaluation_id"]

        second = _run_cycle(client)
        assert second["loops_evaluated"] == 0
        assert second["loops_skipped"] == 1
        assert second["loops"][0]["result"] == "skipped_unchanged"
        assert second["loops"][0]["evaluation_id"] == first_row_id
        assert second["cycle_id"] != first["cycle_id"]

        assert len(_history(client, loop["id"])) == 1


def test_cycle_records_a_new_row_when_observations_change(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        baseline = _create_baseline_run(client)
        loop = _create_loop(client, baseline["id"])
        _record_observation(client, loop["id"], 95.0, "2026-01-10T00:00:00Z")
        _run_cycle(client)

        _record_observation(client, loop["id"], 60.0, "2026-01-20T00:00:00Z")
        second = _run_cycle(client)
        assert second["loops_evaluated"] == 1
        assert second["loops_skipped"] == 0
        assert second["loops_fired"] == 1

        rows = _history(client, loop["id"])
        assert len(rows) == 2
        assert len(rows[0]["observation_ids"]) == 2  # newest first
        assert len(rows[1]["observation_ids"]) == 1
        assert rows[0]["cycle_id"] != rows[1]["cycle_id"]


def test_cycle_records_a_new_row_when_registration_changes(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        baseline = _create_baseline_run(client)
        loop = _create_loop(client, baseline["id"])
        old_registration_id = loop["triggers"][0]["id"]
        _record_observation(client, loop["id"], 95.0, "2026-01-10T00:00:00Z")
        _run_cycle(client)

        registered = client.post(
            f"/loops/{loop['id']}/triggers",
            json={
                "triggers": [
                    {
                        "kind": "threshold",
                        "name": "cash-ceiling",
                        "field": "cash",
                        "operator": ">",
                        "threshold": 90.0,
                    }
                ],
                "supersedes": old_registration_id,
            },
        )
        assert registered.status_code == 201, registered.text
        new_registration_id = registered.json()["id"]

        second = _run_cycle(client)
        assert second["loops_evaluated"] == 1
        rows = _history(client, loop["id"])
        assert len(rows) == 2
        assert rows[0]["registration_id"] == new_registration_id
        assert rows[0]["outcomes"][0]["name"] == "cash-ceiling"
        assert rows[0]["summary"] == "fired"  # 95 > 90
        assert rows[1]["registration_id"] == old_registration_id


def test_cycle_records_no_data_without_triggers(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        baseline = _create_baseline_run(client)
        loop = _create_loop(client, baseline["id"], triggers=[])
        _record_observation(client, loop["id"], 60.0, "2026-01-10T00:00:00Z")

        cycle = _run_cycle(client)
        assert cycle["loops_evaluated"] == 1
        assert cycle["loops_fired"] == 0
        rows = _history(client, loop["id"])
        assert len(rows) == 1
        assert rows[0]["summary"] == "no_data"
        assert rows[0]["outcomes"] == []
        assert rows[0]["registration_id"] is None

        # The no-data row dedups like any other: no observations were
        # added and no triggers registered, so the next cycle skips.
        assert _run_cycle(client)["loops_skipped"] == 1
        assert len(_history(client, loop["id"])) == 1


def test_cycle_records_no_data_without_observations(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        baseline = _create_baseline_run(client)
        loop = _create_loop(client, baseline["id"])

        cycle = _run_cycle(client)
        assert cycle["loops_evaluated"] == 1
        rows = _history(client, loop["id"])
        assert len(rows) == 1
        assert rows[0]["summary"] == "no_data"
        assert rows[0]["observation_ids"] == []
        assert all(item["status"] == "no_data" for item in rows[0]["outcomes"])
        assert len(rows[0]["outcomes"]) == 3


def test_cycle_records_quiet(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        baseline = _create_baseline_run(client)
        loop = _create_loop(client, baseline["id"])
        _record_observation(client, loop["id"], 95.0, "2026-01-10T00:00:00Z")
        _record_observation(client, loop["id"], 100.0, "2026-01-20T00:00:00Z")
        _record_observation(client, loop["id"], 105.0, "2026-01-25T00:00:00Z")

        cycle = _run_cycle(client)
        assert cycle["loops_evaluated"] == 1
        assert cycle["loops_fired"] == 0
        rows = _history(client, loop["id"])
        assert rows[0]["summary"] == "quiet"
        assert all(item["status"] == "quiet" for item in rows[0]["outcomes"])


def test_cycle_on_an_empty_fleet_writes_nothing(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        cycle = _run_cycle(client)
        assert cycle["loops_evaluated"] == 0
        assert cycle["loops_skipped"] == 0
        assert cycle["loops_fired"] == 0
        assert cycle["loops_errored"] == 0
        assert cycle["loops"] == []
        assert cycle["errors"] == []


# -------------------------------------------------------------------- errors


def test_cycle_records_error_and_isolates_loops(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        healthy_baseline = _create_baseline_run(client)
        healthy = _create_loop(client, healthy_baseline["id"])
        _record_observation(client, healthy["id"], 60.0, "2026-01-10T00:00:00Z")

        # A deviation trigger with no explicit reference needs the
        # baseline run's final-state value; strip it so the
        # evaluation fails loudly, exactly as the Sprint 9 review
        # path would fail it.
        broken_baseline = _create_baseline_run(client, company_id="loop-test-co-2")
        broken = _create_loop(
            client,
            broken_baseline["id"],
            triggers=[
                {
                    "kind": "deviation",
                    "name": "cash-drift",
                    "field": "cash",
                    "tolerance": 20.0,
                    "consecutive": 2,
                }
            ],
        )
        _record_observation(client, broken["id"], 60.0, "2026-01-10T00:00:00Z")

        async def strip_final_cash() -> None:
            database = get_database()
            async with database.session() as session:
                row = await session.get(SimulationRun, broken_baseline["id"])
                assert row is not None
                summary = dict(row.summary or {})
                final_state = dict(summary.get("final_state") or {})
                final_state.pop("cash", None)
                summary["final_state"] = final_state
                row.summary = summary
                await session.commit()

        asyncio.run(strip_final_cash())

        cycle = _run_cycle(client)
        assert cycle["loops_evaluated"] == 2
        assert cycle["loops_fired"] == 1
        assert cycle["loops_errored"] == 1
        assert cycle["errors"] == []  # recorded errors are rows, not cycle errors

        broken_rows = _history(client, broken["id"])
        assert len(broken_rows) == 1
        assert broken_rows[0]["summary"] == "error"
        assert broken_rows[0]["error_code"] == "loop_trigger_evaluation_failed"
        assert "cash" in (broken_rows[0]["error_message"] or "")
        assert broken_rows[0]["outcomes"] == []

        healthy_rows = _history(client, healthy["id"])
        assert len(healthy_rows) == 1
        assert healthy_rows[0]["summary"] == "fired"

        # The error row dedups: the same inputs would fail the same
        # way, so the next cycle skips both loops.
        second = _run_cycle(client)
        assert second["loops_evaluated"] == 0
        assert second["loops_skipped"] == 2
        assert second["loops_errored"] == 1
        assert len(_history(client, broken["id"])) == 1


def test_cycle_records_corrupt_registration_as_error(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        baseline = _create_baseline_run(client)
        loop = _create_loop(client, baseline["id"])
        _record_observation(client, loop["id"], 60.0, "2026-01-10T00:00:00Z")

        async def corrupt_triggers() -> None:
            database = get_database()
            async with database.session() as session:
                row = await session.get(StrategyLoopRecord, loop["id"])
                assert row is not None
                row.triggers = [{"kind": "nonsense"}]
                await session.commit()

        asyncio.run(corrupt_triggers())

        cycle = _run_cycle(client)
        assert cycle["loops_evaluated"] == 1
        assert cycle["loops_errored"] == 1
        rows = _history(client, loop["id"])
        assert len(rows) == 1
        assert rows[0]["summary"] == "error"
        assert rows[0]["error_code"] == "loop_corrupt_registration"
        assert rows[0]["registration_id"] is None

        assert _run_cycle(client)["loops_skipped"] == 1
        assert len(_history(client, loop["id"])) == 1


# ------------------------------------------------------------------ boundary


def test_cycle_creates_no_runs_or_iterations_and_mutates_nothing(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        baseline = _create_baseline_run(client)
        loop = _create_loop(client, baseline["id"])
        _record_observation(client, loop["id"], 60.0, "2026-01-10T00:00:00Z")
        started = client.post(
            f"/loops/{loop['id']}/iterations",
            json={"decision_time": REVIEW_TIME},
        )
        assert started.status_code == 201, started.text
        iteration_id = started.json()["id"]
        runs_before = _run_count(client)

        cycle = _run_cycle(client)
        assert cycle["loops_evaluated"] == 1
        assert cycle["loops_fired"] == 1

        assert _run_count(client) == runs_before
        timeline = client.get(f"/loops/{loop['id']}/timeline")
        assert timeline.status_code == 200
        body = timeline.json()
        assert len(body["iterations"]) == 1
        assert body["iterations"][0]["id"] == iteration_id
        assert body["iterations"][0]["state"] == "open"
        assert body["iterations"][0]["trigger_evaluations"] == []
        assert body["iterations"][0]["resimulation"] is None
        assert body["loop"]["triggers"] == loop["triggers"]
        assert body["loop"]["updated_at"] == loop["updated_at"]


# ------------------------------------------------------------------- history


def test_evaluation_history_paginates_newest_first(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        baseline = _create_baseline_run(client)
        loop = _create_loop(client, baseline["id"])
        _record_observation(client, loop["id"], 95.0, "2026-01-10T00:00:00Z")
        _run_cycle(client)
        _record_observation(client, loop["id"], 65.0, "2026-01-20T00:00:00Z")
        _run_cycle(client)
        _record_observation(client, loop["id"], 60.0, "2026-01-25T00:00:00Z")
        _run_cycle(client)

        rows = _history(client, loop["id"])
        assert len(rows) == 3
        assert [len(row["observation_ids"]) for row in rows] == [3, 2, 1]
        assert len({row["cycle_id"] for row in rows}) == 3

        page = _history(client, loop["id"], limit=2)
        assert [len(row["observation_ids"]) for row in page] == [3, 2]
        middle = _history(client, loop["id"], limit=1, offset=1)
        assert [len(row["observation_ids"]) for row in middle] == [2]


def test_evaluation_history_404_for_unknown_loop(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        response = client.get("/loops/no-such-loop/evaluations")
        assert response.status_code == 404


# -------------------------------------------------------------------- worker


def test_worker_run_once_records_evaluations(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        baseline = _create_baseline_run(client)
        loop = _create_loop(client, baseline["id"])
        _record_observation(client, loop["id"], 60.0, "2026-01-10T00:00:00Z")

        worker = build_worker("monitoring-worker")
        assert isinstance(worker, MonitoringWorker)
        assert worker.default_interval_seconds == 3600.0
        result = asyncio.run(worker.run_once())
        assert result["loops_evaluated"] == 1
        assert result["loops_skipped"] == 0
        assert result["loops_fired"] == 1
        assert result["loops_errored"] == 0
        assert result["errors"] == []

        rows = _history(client, loop["id"])
        assert len(rows) == 1
        assert rows[0]["cycle_id"] == result["cycle_id"]

        # Second run dedups through the worker path too.
        again = asyncio.run(worker.run_once())
        assert again["loops_evaluated"] == 0
        assert again["loops_skipped"] == 1
        assert len(_history(client, loop["id"])) == 1


def test_worker_interval_comes_from_settings(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PLANAGENT_MONITORING_WORKER_INTERVAL_SECONDS", "60")
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()):
        worker = build_worker("monitoring-worker")
        assert isinstance(worker, MonitoringWorker)
        assert worker.default_interval_seconds == 60.0
        assert get_settings().monitoring_worker_interval_seconds == 60


def test_monitoring_worker_is_listed(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    workers = {item["worker_id"]: item for item in list_workers()}
    assert "monitoring-worker" in workers
    assert workers["monitoring-worker"]["consumes"] == ()
    assert workers["monitoring-worker"]["produces"] == ()
    assert "never creates runs" in workers["monitoring-worker"]["summary"]


def test_cycle_accepts_pinned_cycle_id_and_time(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        baseline = _create_baseline_run(client)
        loop = _create_loop(client, baseline["id"])
        _record_observation(client, loop["id"], 60.0, "2026-01-10T00:00:00Z")

        settings = get_settings()
        service = SimulationService(
            settings, build_event_bus(settings), get_rule_registry(settings.rules_dir)
        )

        async def run_pinned() -> dict:
            database = get_database()
            async with database.session() as session:
                result = await service.run_monitoring_cycle(
                    session,
                    cycle_id="cycle-pinned",
                    evaluated_at=datetime(2026, 3, 1, tzinfo=UTC),
                )
            return result.model_dump(mode="json")

        result = asyncio.run(run_pinned())
        assert result["cycle_id"] == "cycle-pinned"
        assert result["evaluated_at"].startswith("2026-03-01T00:00:00")
        rows = _history(client, loop["id"])
        assert rows[0]["cycle_id"] == "cycle-pinned"
