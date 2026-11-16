"""API tests for the Sprint 6 skill grafts (PRD delta D9).

The skill service is pre-seeded on ``app.state`` with a scripted LLM
port, so every test runs without a live LLM call. Covers pipeline
endpoints (persist + list), the MECE proposal endpoint (valid + failing
proposals), the validator gate refusing a proposed failing tree, and
the honest LLM-boundary status codes (503 unavailable, 502 malformed).
Same scratch-SQLite + in-memory-bus + empty-LLM-keys pattern as the
Sprint 1-5 tests.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from planagent.config import get_settings, reset_settings_cache
from planagent.db import reset_database_cache
from planagent.main import create_app
from planagent.services.skills.service import SkillDeliberationService
from tests.skill_fixtures import (
    ScriptedSkillPort,
    advisory_board_script,
    load_fixture,
    mece_proposal_script,
    strategy_team_script,
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


def setup_app(monkeypatch, tmp_path: Path, db_name: str = "planagent-skills.db") -> None:
    monkeypatch.setenv("PLANAGENT_DATABASE_URL", build_database_url(tmp_path / db_name))
    monkeypatch.setenv("PLANAGENT_EVENT_BUS_BACKEND", "memory")
    monkeypatch.setenv("PLANAGENT_INLINE_INGEST_DEFAULT", "true")
    monkeypatch.setenv("PLANAGENT_INLINE_SIMULATION_DEFAULT", "true")
    disable_openai(monkeypatch)
    reset_settings_cache()
    reset_database_cache()


def simulation_payload(**overrides) -> dict:
    payload: dict = {
        "company_id": "skills-test-co",
        "company_name": "Skills Test Co",
        "market": "ai",
        "tick_count": 2,
        "seed": 7,
        "actor_template": "default",
    }
    payload.update(overrides)
    return payload


def _client_with_port(port: ScriptedSkillPort) -> TestClient:
    app = create_app()
    app.state.skill_service = SkillDeliberationService(get_settings(), llm_port=port)
    return TestClient(app)


def _create_completed_run(client: TestClient, **overrides) -> dict:
    payload = simulation_payload(variable_set=BOUND_SET, decomposition=PASSING_TREE)
    payload.update(overrides)
    created = client.post("/simulation/runs", json=payload)
    assert created.status_code == 201, created.text
    run = created.json()
    assert run["status"] == "COMPLETED"
    return run


def test_strategy_team_run_persists_and_lists(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    port = ScriptedSkillPort(strategy_team_script(mode="standard"))
    with _client_with_port(port) as client:
        run = _create_completed_run(client)

        response = client.post(
            f"/runs/{run['id']}/skills/strategy-team",
            json={"topic": "Should we launch the AI line?", "mode": "standard"},
        )
        assert response.status_code == 201, response.text
        record = response.json()
        assert record["pipeline"] == "strategy_team"
        assert record["mode"] == "standard"
        assert record["run_id"] == run["id"]
        result = record["result"]
        assert result["synthesis"]["recommended_option"] == "Phased rollout"
        assert result["tally"]["must_address"] == [
            "Delivery capacity cannot cover launch volume",
            "Demand growth assumption is untested",
        ]
        assert all(
            stage["template_version"] == "2" and stage["contract_version"] == "2"
            for stage in result["stages"]
        )
        port.assert_exhausted()

        # The engine artifacts reached the deliberation context.
        assert "MECE decomposition" in port.calls[0]["user_content"]
        assert "Variable table" in port.calls[0]["user_content"]

        listed = client.get(f"/runs/{run['id']}/skills/deliberations")
        assert listed.status_code == 200
        assert listed.json()["run_id"] == run["id"]
        assert [item["id"] for item in listed.json()["deliberations"]] == [record["id"]]


def test_advisory_board_run_persists(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    port = ScriptedSkillPort(advisory_board_script(mode="standard"))
    with _client_with_port(port) as client:
        run = _create_completed_run(client)
        response = client.post(
            f"/runs/{run['id']}/skills/advisory-board",
            json={
                "decision": "Should we launch the AI line?",
                "options": ["Phased rollout", "Full launch", "Partner-led"],
                "mode": "standard",
            },
        )
        assert response.status_code == 201, response.text
        record = response.json()
        assert record["pipeline"] == "advisory_board"
        assert record["result"]["contract"]["verdict"] == "validate_first"
        assert record["result"]["has_unmitigated_veto"] is False
        assert len(record["result"]["vetoes"]) == 1
        port.assert_exhausted()


def test_deliberations_empty_for_fresh_run(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    port = ScriptedSkillPort({})
    with _client_with_port(port) as client:
        run = _create_completed_run(client)
        listed = client.get(f"/runs/{run['id']}/skills/deliberations")
        assert listed.status_code == 200
        assert listed.json()["deliberations"] == []


def test_deliberation_on_missing_run_is_404(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    port = ScriptedSkillPort(strategy_team_script(mode="standard"))
    with _client_with_port(port) as client:
        response = client.post(
            "/runs/nope/skills/strategy-team",
            json={"topic": "T"},
        )
        assert response.status_code == 404
        listed = client.get("/runs/nope/skills/deliberations")
        assert listed.status_code == 404
        assert port.calls == []


def test_deliberation_requires_completed_run(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    # Inline execution off: the run stays PENDING (queued, never run).
    monkeypatch.setenv("PLANAGENT_INLINE_SIMULATION_DEFAULT", "false")
    reset_settings_cache()
    reset_database_cache()
    port = ScriptedSkillPort(strategy_team_script(mode="standard"))
    with _client_with_port(port) as client:
        created = client.post("/simulation/runs", json=simulation_payload())
        assert created.status_code == 201, created.text
        run = created.json()
        assert run["status"] == "PENDING"
        response = client.post(
            f"/runs/{run['id']}/skills/strategy-team",
            json={"topic": "T"},
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "skills_requires_completed_run"
        assert port.calls == []


def test_unavailable_llm_is_503_and_writes_nothing(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    port = ScriptedSkillPort({}, available=False)
    with _client_with_port(port) as client:
        run = _create_completed_run(client)
        response = client.post(
            f"/runs/{run['id']}/skills/strategy-team",
            json={"topic": "T"},
        )
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "skill_llm_unavailable"
        listed = client.get(f"/runs/{run['id']}/skills/deliberations")
        assert listed.json()["deliberations"] == []


def test_malformed_llm_output_is_502_and_writes_nothing(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    script = strategy_team_script(mode="standard")
    script["mckinsey.intake_classify"] = [{"problem_statement": "only one field"}]
    port = ScriptedSkillPort(script)
    with _client_with_port(port) as client:
        run = _create_completed_run(client)
        response = client.post(
            f"/runs/{run['id']}/skills/strategy-team",
            json={"topic": "T"},
        )
        assert response.status_code == 502
        detail = response.json()["detail"]
        assert detail["code"] == "skill_contract_failed"
        assert detail["template_id"] == "mckinsey.intake_classify"
        assert detail["contract_version"] == "2"
        listed = client.get(f"/runs/{run['id']}/skills/deliberations")
        assert listed.json()["deliberations"] == []


def test_mece_propose_valid_tree(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    port = ScriptedSkillPort(mece_proposal_script(valid=True))
    with _client_with_port(port) as client:
        response = client.post(
            "/mece/propose",
            json={"topic": "Should we launch?", "context_lines": ["cash is tight"]},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["validation"]["is_mece"] is True
        assert payload["proposal"]["topic"] == "Should we launch the AI customer-service line?"
        assert payload["stage"]["template_id"] == "mece.propose_tree"
        port.assert_exhausted()


def test_mece_propose_failing_tree_is_refused_by_the_gate(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    port = ScriptedSkillPort(mece_proposal_script(valid=False))
    with _client_with_port(port) as client:
        proposed = client.post("/mece/propose", json={"topic": "Should we launch?"})
        assert proposed.status_code == 200
        payload = proposed.json()
        assert payload["validation"]["is_mece"] is False
        assert [issue["kind"] for issue in payload["validation"]["issues"]] == ["overlap"]

        # The proposed failing tree is refused exactly like a
        # hand-authored failing tree: 400, no run row written.
        refused = client.post(
            "/simulation/runs",
            json=simulation_payload(decomposition=payload["proposal"]),
        )
        assert refused.status_code == 400
        detail = refused.json()["detail"]
        assert detail["code"] == "mece_validation_failed"
        assert detail["validation"]["is_mece"] is False

        runs = client.get("/simulation/runs")
        assert runs.status_code == 200
        assert runs.json() == []


def test_mece_propose_unavailable_llm_is_503(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    port = ScriptedSkillPort({}, available=False)
    with _client_with_port(port) as client:
        response = client.post("/mece/propose", json={"topic": "T"})
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "skill_llm_unavailable"


def test_proposed_valid_tree_attaches_to_a_run(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    port = ScriptedSkillPort(mece_proposal_script(valid=True))
    with _client_with_port(port) as client:
        proposed = client.post("/mece/propose", json={"topic": "Should we launch?"})
        assert proposed.json()["validation"]["is_mece"] is True
        created = client.post(
            "/simulation/runs",
            json=simulation_payload(decomposition=proposed.json()["proposal"]),
        )
        assert created.status_code == 201, created.text
        assert created.json()["status"] == "COMPLETED"


def test_fixture_tree_matches_proposal_contract() -> None:
    # The recorded invalid fixture is a well-formed tree (contract OK)
    # that fails validation (validator NO) — the two layers stay apart.
    assert load_fixture("mece_propose_invalid")["root"]["children"][0]["scope"] == [
        "demand",
        "capability",
    ]
