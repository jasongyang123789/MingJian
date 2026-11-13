"""API tests for the MECE layer (Sprint 1, PRD delta D1).

Covers the standalone validation endpoint, the simulation-run creation
gate (refusal leaves no run behind), and retrieval of the stored audit
trail. Uses the same scratch-SQLite + in-memory-bus + empty-LLM-keys
pattern as the other API test modules; no Docker, no model keys.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from planagent.config import reset_settings_cache
from planagent.db import reset_database_cache
from planagent.main import create_app

PASSING_TREE = {
    "topic": "Should we launch?",
    "root": {
        "name": "Should we launch?",
        "scope": ["demand", "cost"],
        "children": [
            {"name": "Demand", "scope": ["demand"]},
            {"name": "Cost", "scope": ["cost"]},
        ],
    },
}

OVERLAP_TREE = {
    "topic": "Should we launch?",
    "root": {
        "name": "Should we launch?",
        "scope": ["demand", "cost"],
        "children": [
            {"name": "Demand", "scope": ["demand", "cost"]},
            {"name": "Cost", "scope": ["cost"]},
        ],
    },
}

GAP_TREE = {
    "topic": "Should we launch?",
    "root": {
        "name": "Should we launch?",
        "scope": ["demand", "cost", "risk"],
        "children": [
            {"name": "Demand", "scope": ["demand"]},
            {"name": "Cost", "scope": ["cost"]},
        ],
    },
}


def build_database_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.resolve().as_posix()}"


def disable_openai(monkeypatch) -> None:
    monkeypatch.setenv("PLANAGENT_OPENAI_API_KEY", "")
    monkeypatch.setenv("PLANAGENT_OPENAI_BASE_URL", "")
    monkeypatch.setenv("PLANAGENT_OPENAI_PRIMARY_API_KEY", "")
    monkeypatch.setenv("PLANAGENT_OPENAI_PRIMARY_BASE_URL", "")
    monkeypatch.setenv("PLANAGENT_OPENAI_EXTRACTION_API_KEY", "")
    monkeypatch.setenv("PLANAGENT_OPENAI_EXTRACTION_BASE_URL", "")
    monkeypatch.setenv("PLANAGENT_OPENAI_REPORT_API_KEY", "")
    monkeypatch.setenv("PLANAGENT_OPENAI_REPORT_BASE_URL", "")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def setup_app(monkeypatch, tmp_path: Path, db_name: str = "planagent-mece.db") -> None:
    monkeypatch.setenv("PLANAGENT_DATABASE_URL", build_database_url(tmp_path / db_name))
    monkeypatch.setenv("PLANAGENT_EVENT_BUS_BACKEND", "memory")
    monkeypatch.setenv("PLANAGENT_INLINE_INGEST_DEFAULT", "true")
    monkeypatch.setenv("PLANAGENT_INLINE_SIMULATION_DEFAULT", "true")
    disable_openai(monkeypatch)
    reset_settings_cache()
    reset_database_cache()


def simulation_payload(decomposition: dict | None) -> dict:
    payload: dict = {
        "company_id": "mece-test-co",
        "company_name": "MECE Test Co",
        "market": "ai",
        "tick_count": 2,
        "actor_template": "ai_model_provider",
    }
    if decomposition is not None:
        payload["decomposition"] = decomposition
    return payload


def test_validate_endpoint_returns_verdict_in_payload(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        passing = client.post("/mece/validate", json=PASSING_TREE)
        assert passing.status_code == 200
        assert passing.json()["is_mece"] is True
        assert passing.json()["issues"] == []

        failing = client.post("/mece/validate", json=OVERLAP_TREE)
        assert failing.status_code == 200
        body = failing.json()
        assert body["is_mece"] is False
        assert [issue["kind"] for issue in body["issues"]] == ["overlap"]
        assert body["issues"][0]["tags"] == ["cost"]

        # Routers are mounted bare and under /api; both serve MECE.
        prefixed = client.post("/api/mece/validate", json=PASSING_TREE)
        assert prefixed.status_code == 200
        assert prefixed.json()["is_mece"] is True


def test_validate_endpoint_rejects_malformed_tree(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        response = client.post(
            "/mece/validate",
            json={"topic": "t", "root": {"name": "  ", "scope": ["a"]}},
        )
        assert response.status_code == 422


def test_gate_refuses_overlapping_decomposition_and_creates_no_run(
    monkeypatch, tmp_path: Path
) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        response = client.post(
            "/simulation/runs", json=simulation_payload(OVERLAP_TREE)
        )
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert detail["code"] == "mece_validation_failed"
        assert detail["validation"]["is_mece"] is False
        assert [issue["kind"] for issue in detail["validation"]["issues"]] == ["overlap"]

        # Refusal leaves nothing behind: no run row was written.
        runs = client.get("/simulation/runs")
        assert runs.status_code == 200
        assert runs.json() == []


def test_gate_refuses_gap_decomposition(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        response = client.post("/simulation/runs", json=simulation_payload(GAP_TREE))
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert detail["code"] == "mece_validation_failed"
        assert [issue["kind"] for issue in detail["validation"]["issues"]] == ["gap"]
        assert detail["validation"]["issues"][0]["tags"] == ["risk"]

        runs = client.get("/simulation/runs")
        assert runs.json() == []


def test_gate_passes_and_persists_audit_trail(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        created = client.post(
            "/simulation/runs", json=simulation_payload(PASSING_TREE)
        )
        assert created.status_code == 201
        run = created.json()
        assert run["status"] == "COMPLETED"
        run_id = run["id"]

        stored = client.get(f"/runs/{run_id}/mece")
        assert stored.status_code == 200
        body = stored.json()
        assert body["run_id"] == run_id
        assert body["decomposition"]["root"]["name"] == "Should we launch?"
        assert body["decomposition"]["root"]["scope"] == ["demand", "cost"]
        assert body["validation"]["is_mece"] is True
        assert body["validation"]["scope_tag_count"] == 2
        assert body["validation"]["issues"] == []


def test_run_without_decomposition_is_unchanged(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        created = client.post("/simulation/runs", json=simulation_payload(None))
        assert created.status_code == 201
        assert created.json()["status"] == "COMPLETED"

        stored = client.get(f"/runs/{created.json()['id']}/mece")
        assert stored.status_code == 404


def test_get_mece_for_missing_run_is_404(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        response = client.get("/runs/does-not-exist/mece")
        assert response.status_code == 404
