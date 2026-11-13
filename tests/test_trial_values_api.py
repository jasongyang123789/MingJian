"""API tests for the Sprint 8 trial-values read (distribution charts).

``GET /runs/{run_id}/monte-carlo/trial-values`` exposes the per-trial
metric values behind a stored ensemble — re-read from the trial run
rows, never re-executed — pinned by the same trial-values hash the
robustness analyses carry. Same scratch-SQLite + in-memory-bus +
empty-LLM-keys pattern as the Sprint 3 tests.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from planagent.config import reset_settings_cache
from planagent.db import reset_database_cache
from planagent.main import create_app
from planagent.services.distributions import summarize_samples

BOUND_SET = {
    "name": "case",
    "variables": [
        {
            "id": "cash",
            "unit": "k",
            "distribution": {"type": "triangular", "min": 60, "mode": 100, "max": 140},
            "evidence_ref": "estimate: founder judgment",
        },
        {
            "id": "pipeline",
            "unit": "x",
            "distribution": {"type": "normal", "mean": 1.0, "std": 0.1},
            "evidence_ref": "estimate: founder judgment",
        },
    ],
    "internal": {"team": "20 people"},
}


def setup_app(monkeypatch, tmp_path: Path, db_name: str = "planagent-trial-values.db") -> Path:
    db_path = tmp_path / db_name
    monkeypatch.setenv(
        "PLANAGENT_DATABASE_URL", f"sqlite+aiosqlite:///{db_path.resolve().as_posix()}"
    )
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
    return db_path


def _create_bound_run(client: TestClient) -> dict:
    created = client.post(
        "/simulation/runs",
        json={
            "company_id": "trial-values-test-co",
            "company_name": "Trial Values Test Co",
            "market": "ai",
            "tick_count": 2,
            "seed": 7,
            "actor_template": "default",
            "variable_set": BOUND_SET,
        },
    )
    assert created.status_code == 201, created.text
    return created.json()


def _run_ensemble(client: TestClient, run_id: str, trials: int = 10) -> dict:
    response = client.post(
        f"/runs/{run_id}/monte-carlo",
        json={
            "trials": trials,
            "seed": 11,
            "metric": "cash",
            "loss_threshold": 90,
            "strategy_levers": {"pipeline": 1.0},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_trial_values_match_stored_summaries_and_robustness_hash(
    monkeypatch, tmp_path: Path
) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_bound_run(client)
        ensemble = _run_ensemble(client, run["id"])

        response = client.get(f"/runs/{run['id']}/monte-carlo/trial-values")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["ensemble_id"] == ensemble["ensemble_id"]
        assert body["base_run_id"] == run["id"]
        assert body["metric"] == "cash"
        assert body["loss_threshold"] == 90
        assert body["trial_values_hash"].startswith("sha256:")
        assert len(body["baseline"]) == 10
        assert len(body["strategy"]) == 10

        # The returned values are exactly the values behind the stored
        # summaries: re-aggregating them reproduces both arms.
        for arm in ("baseline", "strategy"):
            recomputed = summarize_samples(body[arm], 90)
            stored = ensemble[arm]
            for key in ("n", "mean", "min", "max", "p10", "p50", "p90", "stddev", "p_loss"):
                assert recomputed[key] == stored[key], (arm, key)

        # The hash matches the one pinned on a robustness analysis of
        # the same ensemble: chart and analysis share one input set.
        shortfall = client.post(
            f"/runs/{run['id']}/robustness/expected-shortfall",
            json={"alpha": 0.05, "tail": "lower"},
        )
        assert shortfall.status_code == 201, shortfall.text
        assert shortfall.json()["trial_values_hash"] == body["trial_values_hash"]

        # Dual mounting: the /api prefix serves the same read.
        prefixed = client.get(f"/api/runs/{run['id']}/monte-carlo/trial-values")
        assert prefixed.status_code == 200
        assert prefixed.json()["ensemble_id"] == body["ensemble_id"]
        assert prefixed.json()["trial_values_hash"] == body["trial_values_hash"]


def test_trial_values_404_without_ensemble_or_run(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_bound_run(client)
        missing = client.get(f"/runs/{run['id']}/monte-carlo/trial-values")
        assert missing.status_code == 404

        unknown = client.get("/runs/does-not-exist/monte-carlo/trial-values")
        assert unknown.status_code == 404


def test_trial_values_400_when_trial_row_loses_its_final_state(monkeypatch, tmp_path: Path) -> None:
    db_path = setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_bound_run(client)
        ensemble = _run_ensemble(client, run["id"], trials=2)
        trial_id = ensemble["trial_run_ids"]["baseline"][0]

        # Simulate a pruned/corrupt trial row by wiping its summary
        # directly in the scratch database (no API deletes runs).
        connection = sqlite3.connect(db_path)
        try:
            connection.execute(
                "UPDATE simulation_runs SET summary = '{}' WHERE id = ?", (trial_id,)
            )
            connection.commit()
        finally:
            connection.close()

        response = client.get(f"/runs/{run['id']}/monte-carlo/trial-values")
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "robustness_trial_values_missing"
