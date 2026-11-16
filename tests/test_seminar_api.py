"""API tests for the Sprint 16–17 seminar endpoints.

The seminar service is pre-seeded on ``app.state`` with a fake-port
factory, so every test runs without a live LLM call. Covers the
create / advance / finalize / synthesize endpoints, the GET
endpoints (S17), and the honest status codes (400/404/503).
State assertions live in the service tests; these tests pin the HTTP
surface and response shapes.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from planagent.config import get_settings, reset_settings_cache
from planagent.db import reset_database_cache
from planagent.main import create_app
from planagent.services.seminar.models import ModelPortConfig
from planagent.services.seminar.service import SeminarService
from tests.skill_fixtures import ScriptedSkillPort
from tests.test_seminar_service import (
    reflection_payload,
    stable_model_script,
    verdict_payload,
)

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

TOPIC = "Should we launch the AI customer-service line?"


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


def setup_app(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(
        "PLANAGENT_DATABASE_URL", build_database_url(tmp_path / "planagent-seminar.db")
    )
    monkeypatch.setenv("PLANAGENT_EVENT_BUS_BACKEND", "memory")
    monkeypatch.setenv("PLANAGENT_INLINE_INGEST_DEFAULT", "true")
    monkeypatch.setenv("PLANAGENT_INLINE_SIMULATION_DEFAULT", "true")
    disable_openai(monkeypatch)
    reset_settings_cache()
    reset_database_cache()


def simulation_payload(**overrides) -> dict:
    payload: dict = {
        "company_id": "seminar-test-co",
        "company_name": "Seminar Test Co",
        "market": "ai",
        "tick_count": 2,
        "seed": 7,
        "actor_template": "default",
    }
    payload.update(overrides)
    return payload


class FakePortFactory:
    def __init__(self, ports: dict[str, ScriptedSkillPort]) -> None:
        self.ports = ports

    def __call__(self, config: ModelPortConfig) -> ScriptedSkillPort:
        return self.ports[config.model_id]


def _client_with_factory(factory: FakePortFactory) -> TestClient:
    app = create_app()
    app.state.seminar_service = SeminarService(get_settings(), port_factory=factory)
    return TestClient(app)


def _create_completed_run(client: TestClient) -> dict:
    payload = simulation_payload(variable_set=BOUND_SET, decomposition=PASSING_TREE)
    created = client.post("/simulation/runs", json=payload)
    assert created.status_code == 201, created.text
    run = created.json()
    assert run["status"] == "COMPLETED"
    return run


def _seminar_body(**overrides) -> dict:
    body: dict = {
        "topic": TOPIC,
        "decision_question": TOPIC,
        "options": ["Phased rollout", "Full launch"],
        "roster": [{"model_id": "model-a"}, {"model_id": "model-b"}],
        "pipeline": "strategy_team",
        "mode": "standard",
        "max_rounds": 2,
        "chair_model": {"model_id": "chair-1"},
    }
    body.update(overrides)
    return body


def test_create_seminar_returns_201_with_snapshot_hash(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    factory = FakePortFactory({"chair-1": ScriptedSkillPort({})})
    with _client_with_factory(factory) as client:
        run = _create_completed_run(client)
        response = client.post(f"/runs/{run['id']}/seminars", json=_seminar_body())
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["status"] == "open"
        assert body["run_id"] == run["id"]
        assert body["case_snapshot_hash"].startswith("sha256:")
        assert body["topic"] == TOPIC
        assert [entry["model_id"] for entry in body["roster"]] == ["model-a", "model-b"]
        assert body["chair_model"]["model_id"] == "chair-1"


def test_create_seminar_rejects_small_roster_with_400(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    factory = FakePortFactory({"chair-1": ScriptedSkillPort({})})
    with _client_with_factory(factory) as client:
        run = _create_completed_run(client)
        response = client.post(
            f"/runs/{run['id']}/seminars",
            json=_seminar_body(roster=[{"model_id": "solo"}]),
        )
        assert response.status_code == 400, response.text
        assert response.json()["detail"]["code"] == "seminar_roster_too_small"


def test_create_seminar_chair_unconfigured_returns_503(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    factory = FakePortFactory({"chair-1": ScriptedSkillPort({}, available=False)})
    with _client_with_factory(factory) as client:
        run = _create_completed_run(client)
        response = client.post(f"/runs/{run['id']}/seminars", json=_seminar_body())
        assert response.status_code == 503, response.text
        assert response.json()["detail"]["code"] == "seminar_chair_unavailable"


def test_create_seminar_missing_run_returns_404(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    factory = FakePortFactory({"chair-1": ScriptedSkillPort({})})
    with _client_with_factory(factory) as client:
        response = client.post("/runs/does-not-exist/seminars", json=_seminar_body())
        assert response.status_code == 404, response.text


def test_advance_and_finalize_flow_over_http(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    factory = FakePortFactory(
        {
            "model-a": ScriptedSkillPort(stable_model_script(2)),
            "model-b": ScriptedSkillPort(stable_model_script(2)),
            "chair-1": ScriptedSkillPort({}),
        }
    )
    with _client_with_factory(factory) as client:
        run = _create_completed_run(client)
        created = client.post(f"/runs/{run['id']}/seminars", json=_seminar_body())
        assert created.status_code == 201, created.text
        seminar_id = created.json()["seminar_id"]

        wave1 = client.post(f"/seminars/{seminar_id}/advance")
        assert wave1.status_code == 200, wave1.text
        body = wave1.json()
        assert body["wave_no"] == 1
        assert body["status"] == "running"
        assert [m["status"] for m in body["per_model"]] == ["completed", "completed"]
        assert [m["board_snapshot_seq"] for m in body["per_model"]] == [0, 0]

        wave2 = client.post(f"/seminars/{seminar_id}/advance")
        assert wave2.status_code == 200, wave2.text
        assert wave2.json()["status"] == "collecting"
        assert [m["board_snapshot_seq"] for m in wave2.json()["per_model"]] == [2, 2]

        finalized = client.post(f"/seminars/{seminar_id}/finalize")
        assert finalized.status_code == 200, finalized.text
        assert [f["status"] for f in finalized.json()["finals"]] == ["final", "final"]


def test_advance_and_finalize_missing_seminar_return_404(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    factory = FakePortFactory({"chair-1": ScriptedSkillPort({})})
    with _client_with_factory(factory) as client:
        assert client.post("/seminars/nope/advance").status_code == 404
        assert client.post("/seminars/nope/finalize").status_code == 404


def _chair_script_for_shared_verdicts() -> dict:
    """Cluster + synthesize payloads for two models sharing the S16
    verdict builder: 6 items (3 per model), 3 exact-duplicate groups."""
    return {
        "seminar.cluster": [
            {
                "claims": [
                    {
                        "claim": "Runway is 14 months",
                        "sources": [
                            {"item_id": "I1", "stance": "support"},
                            {"item_id": "I4", "stance": "support"},
                        ],
                    },
                    {
                        "claim": "Demand grows",
                        "sources": [
                            {"item_id": "I2", "stance": "support"},
                            {"item_id": "I5", "stance": "support"},
                        ],
                    },
                    {
                        "claim": "Fewer than six conversions",
                        "sources": [
                            {"item_id": "I3", "stance": "support"},
                            {"item_id": "I6", "stance": "support"},
                        ],
                    },
                ]
            }
        ],
        "seminar.synthesize": [
            {
                "unified_recommendation": "Phase the rollout.",
                "recommendation_basis": "consensus",
                "agreement_level": "high",
                "alternatives_ranked": ["Phased rollout", "Full launch"],
                "aggregation_rule": "Both models ranked identically.",
                "key_evidence": [
                    {"text": "Runway is 14 months", "source_models": ["model-a", "model-b"]}
                ],
                "kill_criteria": [
                    {
                        "text": "Fewer than six conversions",
                        "source_models": ["model-a", "model-b"],
                    }
                ],
                "minority_report": "No dissenting views were held.",
                "open_questions": [],
                "chair_notes": "The models agreed throughout.",
            }
        ],
    }


def test_synthesize_and_get_endpoints_over_http(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    factory = FakePortFactory(
        {
            "model-a": ScriptedSkillPort(stable_model_script(2)),
            "model-b": ScriptedSkillPort(stable_model_script(2)),
            "chair-1": ScriptedSkillPort(_chair_script_for_shared_verdicts()),
        }
    )
    with _client_with_factory(factory) as client:
        run = _create_completed_run(client)
        created = client.post(f"/runs/{run['id']}/seminars", json=_seminar_body())
        seminar_id = created.json()["seminar_id"]
        assert client.post(f"/seminars/{seminar_id}/advance").status_code == 200
        assert client.post(f"/seminars/{seminar_id}/advance").status_code == 200
        assert client.post(f"/seminars/{seminar_id}/finalize").status_code == 200

        synthesized = client.post(f"/seminars/{seminar_id}/synthesize", json={})
        assert synthesized.status_code == 201, synthesized.text
        body = synthesized.json()
        assert body["version"] == 1
        assert body["partial"] is False
        assert body["agreement_level"] == "high"
        assert body["production_path"] == "chair"
        assert body["status"] == "reported"

        detail = client.get(f"/seminars/{seminar_id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["status"] == "reported"
        assert detail.json()["finals_count"] == 2
        assert detail.json()["board_publications"] == 4

        board = client.get(f"/seminars/{seminar_id}/board")
        assert board.status_code == 200
        assert [row["seq"] for row in board.json()] == [1, 2, 3, 4]

        rounds = client.get(f"/seminars/{seminar_id}/rounds")
        assert rounds.status_code == 200
        assert len(rounds.json()) == 4

        finals = client.get(f"/seminars/{seminar_id}/finals")
        assert finals.status_code == 200
        assert len(finals.json()) == 2

        reports = client.get(f"/seminars/{seminar_id}/reports")
        assert reports.status_code == 200
        assert len(reports.json()) == 1
        assert reports.json()[0]["version"] == 1

        report = client.get(f"/seminars/{seminar_id}/reports/1")
        assert report.status_code == 200, report.text
        document = report.json()["document"]
        assert document["unified_recommendation"]["text"] == "Phase the rollout."
        assert len(document["canonical_claims"]["claims"]) == 3

        run_seminars = client.get(f"/runs/{run['id']}/seminars")
        assert run_seminars.status_code == 200
        assert len(run_seminars.json()) == 1
        assert run_seminars.json()[0]["report_versions"] == 1


def test_synthesize_and_get_missing_ids_return_404(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    factory = FakePortFactory({"chair-1": ScriptedSkillPort({})})
    with _client_with_factory(factory) as client:
        assert client.post("/seminars/nope/synthesize", json={}).status_code == 404
        assert client.get("/seminars/nope").status_code == 404
        assert client.get("/seminars/nope/board").status_code == 404
        assert client.get("/seminars/nope/rounds").status_code == 404
        assert client.get("/seminars/nope/finals").status_code == 404
        assert client.get("/seminars/nope/reports").status_code == 404
        assert client.get("/seminars/nope/reports/1").status_code == 404
        assert client.get("/runs/nope/seminars").status_code == 404


def test_reflection_and_verdict_payload_builders_are_contract_valid() -> None:
    """Guards the shared builders used by the service tests."""
    from planagent.services.seminar.contracts import FinalVerdict, Reflection

    Reflection.model_validate(reflection_payload())
    FinalVerdict.model_validate(verdict_payload())
