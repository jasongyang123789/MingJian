"""Seminar Sprint 18 API tests: the chair-brief response, the
chair-synthesis endpoint, and the audit endpoint — over real HTTP
via TestClient. Fake ports only — no live LLM calls.
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
    cluster_payload,
    model_script,
    synthesis_payload,
    verdict_a,
    verdict_b,
)


def _run_to_collecting(client: TestClient, *, chair_mode: str = "agent") -> str:
    run = _create_completed_run(client)
    created = client.post(
        f"/runs/{run['id']}/seminars",
        json=_seminar_body(chair_mode=chair_mode),
    )
    assert created.status_code == 201, created.text
    seminar_id = created.json()["seminar_id"]
    assert client.post(f"/seminars/{seminar_id}/advance").status_code == 200
    assert client.post(f"/seminars/{seminar_id}/advance").status_code == 200
    assert client.post(f"/seminars/{seminar_id}/finalize").status_code == 200
    return seminar_id


def _agent_factory() -> FakePortFactory:
    # No chair port at all: agent mode must never consult one.
    return FakePortFactory(
        {
            "model-a": ScriptedSkillPort(model_script(2, verdict_a())),
            "model-b": ScriptedSkillPort(model_script(2, verdict_b())),
        }
    )


def _model_factory() -> FakePortFactory:
    return FakePortFactory(
        {
            "model-a": ScriptedSkillPort(model_script(2, verdict_a())),
            "model-b": ScriptedSkillPort(model_script(2, verdict_b())),
            "chair-1": ScriptedSkillPort(chair_script(copies=1)),
        }
    )


def test_synthesize_agent_mode_returns_200_with_chair_brief(
    monkeypatch, tmp_path: Path
) -> None:
    setup_app(monkeypatch, tmp_path)
    with _client_with_factory(_agent_factory()) as client:
        seminar_id = _run_to_collecting(client)
        response = client.post(f"/seminars/{seminar_id}/synthesize", json={})
        assert response.status_code == 200, response.text
        brief = response.json()
        assert brief["brief_version"] == 1
        assert brief["prepass"]["item_count"] == 11
        assert brief["prepass"]["exact_duplicate_groups"] == 3
        assert brief["finals_used"] == 2
        assert brief["roster_size"] == 2
        assert len(brief["verdicts"]) == 2
        assert brief["chair_model_id"] == "glint-agent"
        assert "agent chair" in brief["participation_note"]
        assert brief["submit_endpoint"] == f"POST /seminars/{seminar_id}/chair-synthesis"
        detail = client.get(f"/seminars/{seminar_id}")
        assert detail.json()["status"] == "collecting"  # awaiting chair input


def test_chair_synthesis_endpoint_returns_201_agent_chair_report(
    monkeypatch, tmp_path: Path
) -> None:
    setup_app(monkeypatch, tmp_path)
    with _client_with_factory(_agent_factory()) as client:
        seminar_id = _run_to_collecting(client)
        assert client.post(f"/seminars/{seminar_id}/synthesize", json={}).status_code == 200
        response = client.post(
            f"/seminars/{seminar_id}/chair-synthesis",
            json={
                "clusters": cluster_payload(),
                "synthesis": synthesis_payload(),
                "brief_version": 1,
            },
        )
        assert response.status_code == 201, response.text
        report = response.json()
        assert report["version"] == 1
        assert report["production_path"] == "agent_chair"
        assert report["chair_model_id"] == "glint-agent"
        assert report["agreement_level"] == "low"


def test_chair_synthesis_endpoint_rejects_model_mode_seminar(
    monkeypatch, tmp_path: Path
) -> None:
    setup_app(monkeypatch, tmp_path)
    with _client_with_factory(_model_factory()) as client:
        seminar_id = _run_to_collecting(client, chair_mode="model")
        response = client.post(
            f"/seminars/{seminar_id}/chair-synthesis",
            json={"clusters": cluster_payload(), "synthesis": synthesis_payload()},
        )
        assert response.status_code == 400, response.text
        assert response.json()["detail"]["code"] == "seminar_chair_mode_mismatch"


def test_chair_synthesis_endpoint_rejects_coverage_failure(
    monkeypatch, tmp_path: Path
) -> None:
    setup_app(monkeypatch, tmp_path)
    with _client_with_factory(_agent_factory()) as client:
        seminar_id = _run_to_collecting(client)
        assert client.post(f"/seminars/{seminar_id}/synthesize", json={}).status_code == 200
        dropped = cluster_payload()
        dropped["claims"] = dropped["claims"][:-1]
        response = client.post(
            f"/seminars/{seminar_id}/chair-synthesis",
            json={"clusters": dropped, "synthesis": synthesis_payload()},
        )
        assert response.status_code == 400, response.text
        assert response.json()["detail"]["code"] == "chair_submission_coverage_failed"
        detail = client.get(f"/seminars/{seminar_id}")
        assert detail.json()["reports"] == []


def test_audit_endpoint_returns_ordered_events_with_filters(
    monkeypatch, tmp_path: Path
) -> None:
    setup_app(monkeypatch, tmp_path)
    with _client_with_factory(_agent_factory()) as client:
        seminar_id = _run_to_collecting(client)
        response = client.get(f"/seminars/{seminar_id}/audit")
        assert response.status_code == 200, response.text
        events = response.json()
        seqs = [event["seq"] for event in events]
        assert seqs == sorted(seqs)
        assert seqs[0] == 1
        started = client.get(
            f"/seminars/{seminar_id}/audit", params={"kind": "stage_call_started"}
        )
        assert started.status_code == 200
        assert started.json()
        assert all(event["kind"] == "stage_call_started" for event in started.json())
        model_a = client.get(
            f"/seminars/{seminar_id}/audit", params={"model_id": "model-a"}
        )
        assert model_a.status_code == 200
        assert model_a.json()
        assert all(event["model_id"] == "model-a" for event in model_a.json())
        bogus = client.get(f"/seminars/{seminar_id}/audit", params={"kind": "bogus"})
        assert bogus.status_code == 400
        assert bogus.json()["detail"]["code"] == "seminar_audit_unknown_kind"


def test_detail_includes_budgets_and_diagnosis(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with _client_with_factory(_agent_factory()) as client:
        seminar_id = _run_to_collecting(client)
        detail = client.get(f"/seminars/{seminar_id}")
        assert detail.status_code == 200
        body = detail.json()
        assert body["budgets"]["max_stage_calls"] == 200
        assert body["budgets"]["max_tokens"] == 1_000_000
        assert body["budgets"]["stage_calls_used"] == 50  # 2 models x 25 calls
        assert body["diagnosis"]["stage_calls"] == 50
        assert body["diagnosis"]["error_counts"] == {}


def test_synthesize_model_mode_still_returns_201_report(
    monkeypatch, tmp_path: Path
) -> None:
    setup_app(monkeypatch, tmp_path)
    with _client_with_factory(_model_factory()) as client:
        seminar_id = _run_to_collecting(client, chair_mode="model")
        response = client.post(f"/seminars/{seminar_id}/synthesize", json={})
        assert response.status_code == 201, response.text
        assert response.json()["production_path"] == "chair"
        assert response.json()["version"] == 1
