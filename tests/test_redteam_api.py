"""API tests for the red-team layer (Phase 4, Track 8).

The red-team service is pre-seeded on ``app.state`` with a scripted
LLM port, so every test runs without a live LLM call. Covers the
snapshot endpoint (both acceptance cases), the run-based endpoints
(persist + list), and the honest LLM-boundary status codes
(503 unavailable, 502 malformed). Same scratch-SQLite + in-memory-bus
+ empty-LLM-keys pattern as the Sprint 6 skill tests.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from planagent.config import get_settings, reset_settings_cache
from planagent.db import reset_database_cache
from planagent.main import create_app
from planagent.services.redteam.service import RedTeamService
from tests.redteam_cases import (
    complete_case_snapshot_dict,
    desay_2020_snapshot_dict,
)
from tests.redteam_fixtures import ScriptedRedTeamPort, redteam_desay_script
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


def setup_app(monkeypatch, tmp_path: Path, db_name: str = "planagent-redteam.db") -> None:
    monkeypatch.setenv("PLANAGENT_DATABASE_URL", build_database_url(tmp_path / db_name))
    monkeypatch.setenv("PLANAGENT_EVENT_BUS_BACKEND", "memory")
    monkeypatch.setenv("PLANAGENT_INLINE_INGEST_DEFAULT", "true")
    monkeypatch.setenv("PLANAGENT_INLINE_SIMULATION_DEFAULT", "true")
    disable_openai(monkeypatch)
    reset_settings_cache()
    reset_database_cache()


def _client_with_port(port) -> TestClient:
    app = create_app()
    app.state.red_team_service = RedTeamService(get_settings(), llm_port=port)
    return TestClient(app)


def test_analyze_desay_snapshot_flags_both_misses(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    port = ScriptedRedTeamPort(redteam_desay_script())
    with _client_with_port(port) as client:
        response = client.post(
            "/red-team/analyze",
            json={"snapshot": desay_2020_snapshot_dict(), "mode": "auto"},
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["pipeline"] == "red_team"
        assert result["case_id"] == "desay-2020"
        assert result["llm_source"] == "red_team_fixture"
        by_key = {(f["kind"], f["target"]): f for f in result["findings"]}
        assert by_key[("missing_driver", "nev_penetration")]["severity"] == "high"
        assert by_key[("missing_driver", "nev_penetration")]["source"] == "completeness_check"
        assert by_key[("missing_link", "domain_controller_substitution")]["severity"] == "high"
        assert by_key[("missing_driver", "downside_shock")]["source"] == "red_team_fixture"
        assert all(
            f["boundary_class"] in ("fixable_defect", "acceptable_limit", "unclassified")
            and f["boundary_basis"]
            for f in result["findings"]
        )
        assert by_key[("missing_driver", "nev_penetration")]["boundary_class"] == "fixable_defect"
        assert result["counts_by_severity"] == {"high": 2, "medium": 2}
        port.assert_exhausted()


def test_analyze_complete_case_is_clean(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    port = ScriptedRedTeamPort(redteam_desay_script())
    with _client_with_port(port) as client:
        response = client.post(
            "/red-team/analyze",
            json={"snapshot": complete_case_snapshot_dict(), "mode": "completeness_only"},
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["findings"] == []
        assert result["llm_source"] == "none"
        assert port.calls == []


def test_analyze_desay_completeness_only(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    port = ScriptedRedTeamPort(redteam_desay_script())
    with _client_with_port(port) as client:
        response = client.post(
            "/red-team/analyze",
            json={"snapshot": desay_2020_snapshot_dict(), "mode": "completeness_only"},
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert len(result["findings"]) == 3
        assert result["llm_source"] == "none"
        assert port.calls == []


def test_live_mode_without_llm_is_503(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    port = ScriptedSkillPort({}, available=False)
    with _client_with_port(port) as client:
        response = client.post(
            "/red-team/analyze",
            json={"snapshot": desay_2020_snapshot_dict(), "mode": "live"},
        )
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "red_team_llm_unavailable"


def test_malformed_llm_output_is_502(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    bad = {
        "redteam.challenge": [
            {
                "findings": [
                    {
                        "kind": "missing_magic",
                        "target": "x",
                        "severity": "high",
                        "summary": "s",
                        "evidence": ["e"],
                        "suggested_fix": "f",
                    }
                ]
            }
        ]
    }
    port = ScriptedRedTeamPort(bad)
    with _client_with_port(port) as client:
        response = client.post(
            "/red-team/analyze",
            json={"snapshot": desay_2020_snapshot_dict(), "mode": "auto"},
        )
        assert response.status_code == 502
        assert response.json()["detail"]["code"] == "red_team_contract_failed"


def _create_completed_run(client: TestClient) -> dict:
    payload = {
        "company_id": "redteam-test-co",
        "company_name": "Red Team Test Co",
        "market": "ai",
        "tick_count": 2,
        "seed": 7,
        "actor_template": "default",
        "variable_set": BOUND_SET,
        "decomposition": PASSING_TREE,
    }
    created = client.post("/simulation/runs", json=payload)
    assert created.status_code == 201, created.text
    run = created.json()
    assert run["status"] == "COMPLETED"
    return run


def test_run_red_team_persists_and_lists(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    port = ScriptedRedTeamPort(redteam_desay_script())
    with _client_with_port(port) as client:
        run = _create_completed_run(client)
        response = client.post(
            f"/runs/{run['id']}/red-team",
            json={"mode": "completeness_only"},
        )
        assert response.status_code == 201, response.text
        record = response.json()
        assert record["pipeline"] == "red_team"
        assert record["run_id"] == run["id"]
        # The tiny bound case names no drivers: no findings.
        assert record["result"]["findings"] == []
        assert record["result"]["case_id"] == run["id"]
        assert port.calls == []

        listed = client.get(f"/runs/{run['id']}/red-team")
        assert listed.status_code == 200
        assert listed.json()["run_id"] == run["id"]
        assert [item["id"] for item in listed.json()["red_team_runs"]] == [record["id"]]


def test_run_red_team_empty_for_fresh_run(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    port = ScriptedRedTeamPort({})
    with _client_with_port(port) as client:
        run = _create_completed_run(client)
        listed = client.get(f"/runs/{run['id']}/red-team")
        assert listed.status_code == 200
        assert listed.json()["red_team_runs"] == []


def test_run_red_team_on_missing_run_is_404(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    port = ScriptedRedTeamPort(redteam_desay_script())
    with _client_with_port(port) as client:
        response = client.post("/runs/nope/red-team", json={"mode": "auto"})
        assert response.status_code == 404
        listed = client.get("/runs/nope/red-team")
        assert listed.status_code == 404
        assert port.calls == []
