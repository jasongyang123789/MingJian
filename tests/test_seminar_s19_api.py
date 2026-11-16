"""Seminar Sprint 19 API tests: the audit purge + retention endpoints,
the retention field on GET detail, and the lease lock provider over
real HTTP via TestClient. Fake ports only — no live LLM calls.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from tests.skill_fixtures import ScriptedSkillPort
from tests.test_seminar_api import (
    FakePortFactory,
    _client_with_factory,
    _create_completed_run,
    _seminar_body,
    setup_app,
)
from tests.test_seminar_synthesis_service import (
    chair_script,
    model_script,
    verdict_a,
    verdict_b,
)


def _model_factory() -> FakePortFactory:
    return FakePortFactory(
        {
            "model-a": ScriptedSkillPort(model_script(2, verdict_a())),
            "model-b": ScriptedSkillPort(model_script(2, verdict_b())),
            "chair-1": ScriptedSkillPort(chair_script(copies=1)),
        }
    )


def _create_seminar(client: TestClient, **overrides) -> str:
    run = _create_completed_run(client)
    created = client.post(f"/runs/{run['id']}/seminars", json=_seminar_body(**overrides))
    assert created.status_code == 201, created.text
    return created.json()["seminar_id"]


def _audit_count(client: TestClient, seminar_id: str) -> int:
    response = client.get(f"/seminars/{seminar_id}/audit")
    assert response.status_code == 200, response.text
    return len(response.json())


def test_purge_endpoint_compacts_and_reports_status(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with _client_with_factory(_model_factory()) as client:
        seminar_id = _create_seminar(
            client,
            audit_retention_max_events=None,
            audit_retention_max_age_days=None,
        )
        assert client.post(f"/seminars/{seminar_id}/advance").status_code == 200
        before = _audit_count(client, seminar_id)
        assert before > 2
        response = client.post(
            f"/seminars/{seminar_id}/audit/purge", json={"keep_last_n": 2}
        )
        assert response.status_code == 200, response.text
        outcome = response.json()
        assert outcome["deleted_count"] == before - 2
        assert outcome["deleted_oldest_seq"] == 1
        assert outcome["deleted_newest_seq"] == before - 2
        assert outcome["remaining_count"] == 3
        assert outcome["retention"]["event_count"] == 3
        assert outcome["retention"]["oldest_seq"] == before - 1
        assert outcome["retention"]["newest_seq"] == before + 1
        assert outcome["retention"]["max_events"] is None
        # GET /audit still returns a plain list — survivors + summary.
        events = client.get(f"/seminars/{seminar_id}/audit").json()
        assert [event["seq"] for event in events] == [before - 1, before, before + 1]
        assert events[-1]["kind"] == "retention_purged"


def test_purge_endpoint_floor_refusal_is_400_with_code(
    monkeypatch, tmp_path: Path
) -> None:
    setup_app(monkeypatch, tmp_path)
    with _client_with_factory(_model_factory()) as client:
        seminar_id = _create_seminar(client)  # default floor: 1000 / 90
        response = client.post(
            f"/seminars/{seminar_id}/audit/purge", json={"keep_last_n": 5}
        )
        assert response.status_code == 400, response.text
        assert response.json()["detail"]["code"] == "seminar_retention_floor"


def test_purge_endpoint_requires_a_criterion(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with _client_with_factory(_model_factory()) as client:
        seminar_id = _create_seminar(client)
        response = client.post(f"/seminars/{seminar_id}/audit/purge", json={})
        assert response.status_code == 422, response.text


def test_purge_endpoint_unknown_seminar_is_404(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with _client_with_factory(_model_factory()) as client:
        response = client.post(
            "/seminars/missing-seminar/audit/purge", json={"keep_last_n": 1}
        )
        assert response.status_code == 404, response.text


def test_retention_endpoint_returns_status(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with _client_with_factory(_model_factory()) as client:
        seminar_id = _create_seminar(client)
        assert client.post(f"/seminars/{seminar_id}/advance").status_code == 200
        response = client.get(f"/seminars/{seminar_id}/audit/retention")
        assert response.status_code == 200, response.text
        retention = response.json()
        assert retention["seminar_id"] == seminar_id
        assert retention["event_count"] == _audit_count(client, seminar_id)
        assert retention["oldest_seq"] == 1
        assert retention["newest_seq"] == retention["event_count"]
        assert retention["max_events"] == 1000
        assert retention["max_age_days"] == 90


def test_retention_endpoint_unknown_seminar_is_404(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with _client_with_factory(_model_factory()) as client:
        response = client.get("/seminars/missing-seminar/audit/retention")
        assert response.status_code == 404, response.text


def test_detail_includes_retention_status(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with _client_with_factory(_model_factory()) as client:
        seminar_id = _create_seminar(
            client, audit_retention_max_events=50, audit_retention_max_age_days=30
        )
        response = client.get(f"/seminars/{seminar_id}")
        assert response.status_code == 200, response.text
        retention = response.json()["retention"]
        assert retention["event_count"] == 0
        assert retention["oldest_seq"] is None
        assert retention["max_events"] == 50
        assert retention["max_age_days"] == 30


def test_lease_lock_provider_synthesizes_over_http(
    monkeypatch, tmp_path: Path
) -> None:
    setup_app(monkeypatch, tmp_path)
    with _client_with_factory(_model_factory()) as client:
        seminar_id = _create_seminar(client, synthesize_lock_provider="lease")
        assert client.post(f"/seminars/{seminar_id}/advance").status_code == 200
        assert client.post(f"/seminars/{seminar_id}/advance").status_code == 200
        assert client.post(f"/seminars/{seminar_id}/finalize").status_code == 200
        response = client.post(f"/seminars/{seminar_id}/synthesize", json={})
        assert response.status_code == 201, response.text
        assert response.json()["version"] == 1
