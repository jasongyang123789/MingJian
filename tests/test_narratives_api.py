"""API tests for Sprint 13 decision-direction narratives.

Covers generation (success, byte-identity across regenerations,
versioning), refusal codes (no ensemble, unknown source run,
non-completed anchor, unknown MECE branch, loop mismatch), list/get
reads, and the strictly-separated polish hook (scripted port
success, 503 unavailable, 502 contract failure). Same
scratch-SQLite + in-memory-bus + empty-LLM-keys pattern as the
Sprint 1-12 tests. No live LLM call is ever made.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from planagent.config import get_settings, reset_settings_cache
from planagent.db import reset_database_cache
from planagent.main import create_app
from planagent.services.narratives.polish import POLISH_TEMPLATE_ID
from planagent.services.narratives.service import NarrativeService
from tests.skill_fixtures import ScriptedSkillPort

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

TRIGGERS = [
    {
        "kind": "threshold",
        "name": "cash-floor",
        "field": "cash",
        "operator": "<",
        "threshold": 70.0,
    }
]


def build_database_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.resolve().as_posix()}"


def setup_app(monkeypatch, tmp_path: Path, db_name: str = "planagent-narratives.db") -> None:
    monkeypatch.setenv("PLANAGENT_DATABASE_URL", build_database_url(tmp_path / db_name))
    monkeypatch.setenv("PLANAGENT_EVENT_BUS_BACKEND", "memory")
    monkeypatch.setenv("PLANAGENT_INLINE_INGEST_DEFAULT", "true")
    monkeypatch.setenv("PLANAGENT_INLINE_SIMULATION_DEFAULT", "true")
    monkeypatch.setenv("PLANAGENT_OPENAI_API_KEY", "")
    monkeypatch.setenv("PLANAGENT_OPENAI_BASE_URL", "")
    monkeypatch.setenv("PLANAGENT_OPENAI_PRIMARY_API_KEY", "")
    monkeypatch.setenv("PLANAGENT_OPENAI_PRIMARY_BASE_URL", "")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    reset_settings_cache()
    reset_database_cache()


def simulation_payload(**overrides) -> dict:
    payload: dict = {
        "company_id": "narratives-test-co",
        "company_name": "Narratives Test Co",
        "market": "ai",
        "tick_count": 2,
        "seed": 7,
        "actor_template": "default",
        "variable_set": BOUND_SET,
    }
    payload.update(overrides)
    return payload


def _create_run(client: TestClient, **overrides) -> dict:
    created = client.post("/simulation/runs", json=simulation_payload(**overrides))
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "COMPLETED"
    return created.json()


def _create_ensemble(client: TestClient, run_id: str, trials: int = 5) -> dict:
    response = client.post(
        f"/runs/{run_id}/monte-carlo", json={"trials": trials, "metric": "cash"}
    )
    assert response.status_code == 201, response.text
    return response.json()


def _generate(client: TestClient, run_id: str, **overrides) -> dict:
    payload: dict = {
        "topic": "Launch decision",
        "directions": [{"name": "Go all in", "source_run_id": run_id}],
    }
    payload.update(overrides)
    return client.post(f"/runs/{run_id}/narratives", json=payload)


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def test_generate_narrative_success(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client, decomposition=PASSING_TREE)
        ensemble = _create_ensemble(client, run["id"])
        response = _generate(
            client,
            run["id"],
            directions=[
                {
                    "name": "Go all in",
                    "source_run_id": run["id"],
                    "mece_branches": ["Demand"],
                }
            ],
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["version"] == 1
        assert body["topic"] == "Launch decision"
        assert body["inputs_hash"].startswith("sha256:")
        assert body["content_hash"].startswith("sha256:")
        assert body["polish"] is None
        artifact = body["body"]
        assert artifact["anchor_run_id"] == run["id"]
        assert artifact["topic_source"] == "request"
        assert artifact["mece"]["topic"] == "Should we launch?"
        assert artifact["mece"]["is_mece"] is True
        direction = artifact["directions"][0]
        assert direction["name"] == "Go all in"
        assert direction["rank"] == 1
        assert direction["distribution"]["ensemble_id"] == ensemble["ensemble_id"]
        assert direction["distribution"]["metric"] == "cash"
        assert direction["distribution"]["trials"] == 5
        assert direction["mece_trace"]["branches"][0]["name"] == "Demand"
        assert direction["mece_trace"]["branches"][0]["scope"] == ["demand"]
        assert direction["premortem"]["provenance"] == "template"
        assert direction["first_step"]["provenance"] == "template"
        assert "Go all in" in artifact["markdown"]
        assert "[template]" in artifact["markdown"]


def test_generate_narrative_byte_identical_across_regenerations(
    monkeypatch, tmp_path: Path
) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client)
        _create_ensemble(client, run["id"])
        first = _generate(client, run["id"])
        second = _generate(client, run["id"])
        assert first.status_code == 201
        assert second.status_code == 201
        assert first.json()["version"] == 1
        assert second.json()["version"] == 2
        assert first.json()["content_hash"] == second.json()["content_hash"]
        assert first.json()["inputs_hash"] == second.json()["inputs_hash"]
        assert first.json()["body"] == second.json()["body"]
        assert first.json()["id"] != second.json()["id"]


def test_generate_refuses_without_ensemble_and_writes_nothing(
    monkeypatch, tmp_path: Path
) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client)
        response = _generate(client, run["id"])
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert detail["code"] == "narrative_requires_ensemble"
        assert f"/runs/{run['id']}/monte-carlo" in detail["message"]
        listing = client.get(f"/runs/{run['id']}/narratives")
        assert listing.status_code == 200
        assert listing.json()["narratives"] == []


def test_generate_refuses_unknown_source_run(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client)
        _create_ensemble(client, run["id"])
        response = _generate(
            client,
            run["id"],
            directions=[{"name": "Ghost", "source_run_id": "run-does-not-exist"}],
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "narrative_unknown_source_run"


def test_generate_refuses_noncompleted_anchor(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        queued = client.post(
            "/simulation/runs", json=simulation_payload(execution_mode="QUEUED")
        )
        assert queued.status_code == 201
        response = _generate(client, queued.json()["id"])
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "narrative_requires_completed_run"


def test_generate_refuses_unknown_mece_branch(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client, decomposition=PASSING_TREE)
        _create_ensemble(client, run["id"])
        response = _generate(
            client,
            run["id"],
            directions=[
                {
                    "name": "Go all in",
                    "source_run_id": run["id"],
                    "mece_branches": ["Nope"],
                }
            ],
        )
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert detail["code"] == "narrative_unknown_mece_branch"
        assert "Nope" in detail["message"]
        assert "Demand" in detail["message"]


def test_generate_unknown_run_404(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        response = _generate(client, "run-missing")
        assert response.status_code == 404


def test_generate_with_loop_context_and_mismatch_refusal(
    monkeypatch, tmp_path: Path
) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client)
        other = _create_run(client)
        _create_ensemble(client, run["id"])
        loop = client.post(
            "/loops",
            json={"name": "Watch", "baseline_run_id": run["id"], "triggers": TRIGGERS},
        )
        assert loop.status_code == 201, loop.text
        loop_id = loop.json()["id"]
        response = _generate(client, run["id"], loop_id=loop_id)
        assert response.status_code == 201, response.text
        artifact = response.json()["body"]
        assert artifact["loop_context"]["loop_id"] == loop_id
        assert artifact["loop_context"]["trigger_count"] == 1
        kinds = [s["kind"] for s in artifact["directions"][0]["signals"]]
        assert kinds == ["loop_trigger"]
        assert "cash-floor" in artifact["directions"][0]["signals"][0]["text"]

        _create_ensemble(client, other["id"])
        mismatch = _generate(client, other["id"], loop_id=loop_id)
        assert mismatch.status_code == 400
        assert mismatch.json()["detail"]["code"] == "narrative_loop_baseline_mismatch"


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def test_list_and_get_narratives(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client)
        _create_ensemble(client, run["id"])
        first = _generate(client, run["id"])
        second = _generate(client, run["id"])
        assert first.status_code == 201
        assert second.status_code == 201
        listing = client.get(f"/runs/{run['id']}/narratives")
        assert listing.status_code == 200
        narratives = listing.json()["narratives"]
        assert [item["version"] for item in narratives] == [2, 1]
        fetched = client.get(f"/runs/{run['id']}/narratives/{first.json()['id']}")
        assert fetched.status_code == 200
        assert fetched.json()["version"] == 1
        assert fetched.json()["polish"] is None
        wrong_run = client.get(f"/runs/run-other/narratives/{first.json()['id']}")
        assert wrong_run.status_code == 404
        missing = client.get(f"/runs/{run['id']}/narratives/narrative-missing")
        assert missing.status_code == 404


# ---------------------------------------------------------------------------
# Polish hook
# ---------------------------------------------------------------------------


def _client_with_port(port: ScriptedSkillPort) -> TestClient:
    app = create_app()
    app.state.narrative_service = NarrativeService(get_settings(), llm_port=port)
    return TestClient(app)


def test_polish_success_stores_alongside_artifact(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    port = ScriptedSkillPort(
        {POLISH_TEMPLATE_ID: [{"polished_markdown": "# Polished launch brief"}]}
    )
    with _client_with_port(port) as client:
        run = _create_run(client)
        _create_ensemble(client, run["id"])
        created = _generate(client, run["id"])
        assert created.status_code == 201
        narrative_id = created.json()["id"]
        response = client.post(f"/runs/{run['id']}/narratives/{narrative_id}/polish")
        assert response.status_code == 201, response.text
        polish = response.json()
        assert polish["polished_markdown"] == "# Polished launch brief"
        assert polish["template_id"] == "narrative.polish"
        assert polish["template_version"] == "1"
        assert polish["model"] == "fixture"
        fetched = client.get(f"/runs/{run['id']}/narratives/{narrative_id}")
        assert fetched.json()["polish"]["id"] == polish["id"]
        assert fetched.json()["content_hash"] == created.json()["content_hash"]
        assert fetched.json()["body"] == created.json()["body"]
        port.assert_exhausted()


def test_polish_unavailable_returns_503_and_writes_nothing(
    monkeypatch, tmp_path: Path
) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client)
        _create_ensemble(client, run["id"])
        created = _generate(client, run["id"])
        assert created.status_code == 201
        response = client.post(
            f"/runs/{run['id']}/narratives/{created.json()['id']}/polish"
        )
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "narrative_polish_unavailable"
        fetched = client.get(f"/runs/{run['id']}/narratives/{created.json()['id']}")
        assert fetched.json()["polish"] is None


def test_polish_contract_failure_returns_502_and_writes_nothing(
    monkeypatch, tmp_path: Path
) -> None:
    setup_app(monkeypatch, tmp_path)
    port = ScriptedSkillPort({POLISH_TEMPLATE_ID: [{"wrong_key": "nope"}]})
    with _client_with_port(port) as client:
        run = _create_run(client)
        _create_ensemble(client, run["id"])
        created = _generate(client, run["id"])
        assert created.status_code == 201
        response = client.post(
            f"/runs/{run['id']}/narratives/{created.json()['id']}/polish"
        )
        assert response.status_code == 502
        assert response.json()["detail"]["code"] == "narrative_polish_contract_failed"
        fetched = client.get(f"/runs/{run['id']}/narratives/{created.json()['id']}")
        assert fetched.json()["polish"] is None


def test_polish_unknown_narrative_404(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client)
        response = client.post(f"/runs/{run['id']}/narratives/narrative-missing/polish")
        assert response.status_code == 404
