"""API tests for option B: directions as variable overrides.

Covers the override endpoint end to end through the production
wiring (the scenario-branch adapter in the route deps): child-run
creation with the fixed override in the child's variables
fragment, the stored ``override`` mapping with its pinned
override record, refuse-before-write grounding validation with
zero branches created, no-clobber name skips, the 503 path when
no branch runner is wired, per-direction failure isolation via a
scripted runner, derive's no-clobber extension to override rows,
and the override → ensemble → generate loop. Same scratch-SQLite
+ in-memory-bus + empty-LLM-keys pattern as the Sprint 1-14 and
option C tests. No live LLM call is ever made.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from planagent.config import get_settings, reset_settings_cache
from planagent.db import get_database, reset_database_cache
from planagent.domain.models import ScenarioBranchRecord, SimulationRun
from planagent.main import create_app
from planagent.services.narratives.overrides import BranchRequest, BranchResult
from planagent.services.narratives.service import NarrativeService

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


def setup_app(monkeypatch, tmp_path: Path, db_name: str = "planagent-overrides.db") -> None:
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
        "company_id": "overrides-test-co",
        "company_name": "Overrides Test Co",
        "market": "ai",
        "tick_count": 4,
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
    response = client.post(f"/runs/{run_id}/monte-carlo", json={"trials": trials, "metric": "cash"})
    assert response.status_code == 201, response.text
    return response.json()


def _override(client: TestClient, run_id: str, payload: dict):
    return client.post(f"/runs/{run_id}/directions/override", json=payload)


def _mappings(client: TestClient, run_id: str) -> list[dict]:
    listed = client.get(f"/runs/{run_id}/directions/mappings")
    assert listed.status_code == 200, listed.text
    return listed.json()["mappings"]


def _branch_count(client: TestClient, run_id: str) -> int:
    compared = client.get(f"/runs/{run_id}/scenario-compare")
    assert compared.status_code == 200, compared.text
    return compared.json()["branch_count"]


async def _read_run_configuration(run_id: str) -> dict:
    database = get_database()
    async with database.session() as session:
        run = await session.get(SimulationRun, run_id)
        assert run is not None
        return dict(run.configuration or {})


async def _read_branch_assumptions(branch_id: str) -> list[str]:
    database = get_database()
    async with database.session() as session:
        branch = await session.get(ScenarioBranchRecord, branch_id)
        assert branch is not None
        return list(branch.assumptions)


class ScriptedBranchRunner:
    """Branch runner that fails on scripted call numbers."""

    def __init__(self, fail_on_calls: set[int] | None = None) -> None:
        self.fail_on_calls = fail_on_calls or set()
        self.calls: list[BranchRequest] = []

    def is_available(self) -> bool:
        return True

    async def create_branch(
        self, _session: AsyncSession, _parent_run_id: str, request: BranchRequest
    ) -> BranchResult:
        self.calls.append(request)
        if len(self.calls) in self.fail_on_calls:
            raise RuntimeError("scripted branch failure")
        index = len(self.calls)
        return BranchResult(
            branch_id=f"branch-{index}", run_id=f"child-{index}", fork_step=request.fork_step
        )


def _bind_runner(app, runner) -> None:
    """Inject a scripted branch runner (the route resolves the
    service from app state on every request)."""
    app.state.narrative_service = NarrativeService(get_settings(), branch_runner=runner)


def _direction(name: str, overrides: dict, **extra) -> dict:
    payload = {"name": name, "overrides": overrides}
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Override: happy path + provenance
# ---------------------------------------------------------------------------


def test_override_creates_child_run_and_stores_active_mapping(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        parent = _create_run(client, decomposition=PASSING_TREE)
        response = _override(
            client,
            parent["id"],
            {"directions": [_direction("Boost cash", {"cash": 80}, mece_branches=["Demand"])]},
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["anchor_run_id"] == parent["id"]
        assert body["override_hash"].startswith("sha256:")
        assert body["directions_considered"] == 1
        assert len(body["outcomes"]) == 1
        outcome = body["outcomes"][0]
        assert outcome["status"] == "stored"
        assert outcome["name"] == "Boost cash"
        assert outcome["mapping_id"]
        assert outcome["branch_id"]
        assert outcome["child_run_id"]
        assert outcome["child_run_id"] != parent["id"]
        assert outcome["fork_step"] == 2  # midpoint default for tick_count 4
        assert outcome["child_status"] == "COMPLETED"
        assert "monte-carlo" in outcome["reason"]
        assert _branch_count(client, parent["id"]) == 1

        rows = _mappings(client, parent["id"])
        assert len(rows) == 1
        row = rows[0]
        assert row["name"] == "Boost cash"
        assert row["source_run_id"] == outcome["child_run_id"]
        assert row["arm"] == "baseline"
        assert row["mece_branches"] == ["Demand"]
        assert row["deliberation_id"] is None
        assert row["origin"] == "override"
        assert row["status"] == "active"
        assert row["user_edited"] is False
        assert row["position"] == 0
        assert row["proposal_record"] is None
        record = row["override_record"]
        assert record["overrides"] == {"cash": 80.0}
        assert record["branch_id"] == outcome["branch_id"]
        assert record["fork_step"] == 2
        assert record["override_hash"] == body["override_hash"]

        # The child run itself carries the fixed override.
        configuration = asyncio.run(_read_run_configuration(outcome["child_run_id"]))
        bindings = configuration["variables"]["bindings"]
        assert configuration["variables"]["branch_override"] is True
        assert len(bindings["variables"]) == 1
        assert bindings["variables"][0]["id"] == "cash"
        distribution = bindings["variables"][0]["distribution"]
        assert distribution["type"] == "fixed"
        assert distribution["value"] == 80.0
        assumptions = asyncio.run(_read_branch_assumptions(outcome["branch_id"]))
        assert assumptions == ["Direction 'Boost cash': override cash=80.0."]


def test_override_explicit_fork_step_is_honored(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        parent = _create_run(client, decomposition=PASSING_TREE)
        response = _override(
            client,
            parent["id"],
            {"directions": [_direction("Early fork", {"cash": 80}, fork_step=1)]},
        )
        assert response.status_code == 201, response.text
        outcome = response.json()["outcomes"][0]
        assert outcome["status"] == "stored"
        assert outcome["fork_step"] == 1
        row = _mappings(client, parent["id"])[0]
        assert row["override_record"]["fork_step"] == 1


def test_override_same_request_same_hash(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        parent = _create_run(client, decomposition=PASSING_TREE)
        payload = {"directions": [_direction("Boost cash", {"cash": 80})]}
        first = _override(client, parent["id"], payload)
        second = _override(client, parent["id"], payload)
        assert first.status_code == 201 and second.status_code == 201
        assert first.json()["override_hash"] == second.json()["override_hash"]
        assert first.json()["outcomes"][0]["status"] == "stored"
        assert second.json()["outcomes"][0]["status"] == "skipped"
        assert len(_mappings(client, parent["id"])) == 1
        assert _branch_count(client, parent["id"]) == 1


# ---------------------------------------------------------------------------
# Override: refuse-before-write
# ---------------------------------------------------------------------------


def test_override_refuses_unknown_variable_and_creates_nothing(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        parent = _create_run(client, decomposition=PASSING_TREE)
        response = _override(
            client, parent["id"], {"directions": [_direction("Boost", {"nope": 1})]}
        )
        assert response.status_code == 400, response.text
        assert response.json()["detail"]["code"] == "direction_override_unknown_variable"
        assert _mappings(client, parent["id"]) == []
        assert _branch_count(client, parent["id"]) == 0


def test_override_refuses_unknown_mece_branch_and_creates_nothing(
    monkeypatch, tmp_path: Path
) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        parent = _create_run(client, decomposition=PASSING_TREE)
        response = _override(
            client,
            parent["id"],
            {"directions": [_direction("Boost", {"cash": 80}, mece_branches=["Nope"])]},
        )
        assert response.status_code == 400, response.text
        assert response.json()["detail"]["code"] == "direction_unknown_mece_branch"
        assert _mappings(client, parent["id"]) == []
        assert _branch_count(client, parent["id"]) == 0


def test_override_refuses_missing_snapshot_and_creates_nothing(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        parent = _create_run(client, decomposition=PASSING_TREE)
        response = _override(
            client,
            parent["id"],
            {"directions": [_direction("Boost", {"cash": 80}, fork_step=99)]},
        )
        assert response.status_code == 400, response.text
        assert response.json()["detail"]["code"] == "direction_override_no_snapshot"
        assert _mappings(client, parent["id"]) == []
        assert _branch_count(client, parent["id"]) == 0


def test_override_refuses_one_bad_direction_before_any_branch(monkeypatch, tmp_path: Path) -> None:
    # Whole-request grounding: a bad second direction refuses the
    # valid first one too, before any branch is created.
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        parent = _create_run(client, decomposition=PASSING_TREE)
        response = _override(
            client,
            parent["id"],
            {
                "directions": [
                    _direction("Good", {"cash": 80}),
                    _direction("Bad", {"nope": 1}),
                ]
            },
        )
        assert response.status_code == 400, response.text
        assert response.json()["detail"]["code"] == "direction_override_unknown_variable"
        assert _mappings(client, parent["id"]) == []
        assert _branch_count(client, parent["id"]) == 0


def test_override_refuses_noncompleted_anchor(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        created = client.post("/simulation/runs", json=simulation_payload(execution_mode="QUEUED"))
        assert created.status_code == 201, created.text
        response = _override(
            client, created.json()["id"], {"directions": [_direction("Boost", {"cash": 80})]}
        )
        assert response.status_code == 400, response.text
        assert response.json()["detail"]["code"] == "direction_requires_completed_run"


def test_override_refuses_anchor_without_bindings(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        payload = simulation_payload(decomposition=PASSING_TREE)
        del payload["variable_set"]
        created = client.post("/simulation/runs", json=payload)
        assert created.status_code == 201, created.text
        response = _override(
            client, created.json()["id"], {"directions": [_direction("Boost", {"cash": 80})]}
        )
        assert response.status_code == 400, response.text
        assert response.json()["detail"]["code"] == "direction_override_requires_bindings"


def test_override_unknown_run_404(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        response = _override(
            client, "no-such-run", {"directions": [_direction("Boost", {"cash": 80})]}
        )
        assert response.status_code == 404


def test_override_rejects_invalid_payloads(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        parent = _create_run(client, decomposition=PASSING_TREE)
        assert _override(client, parent["id"], {"directions": []}).status_code == 422
        assert (
            _override(
                client,
                parent["id"],
                {
                    "directions": [
                        _direction("Boost", {"cash": 80}),
                        _direction("Boost", {"cash": 90}),
                    ]
                },
            ).status_code
            == 422
        )
        assert (
            _override(
                client, parent["id"], {"directions": [_direction("Boost", {"cash": "80"})]}
            ).status_code
            == 422
        )
        assert (
            _override(client, parent["id"], {"directions": [_direction("Boost", {})]}).status_code
            == 422
        )
        assert _mappings(client, parent["id"]) == []
        assert _branch_count(client, parent["id"]) == 0


# ---------------------------------------------------------------------------
# Override: no-clobber + runner failures
# ---------------------------------------------------------------------------


def test_override_skips_existing_name_without_creating_branch(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        parent = _create_run(client, decomposition=PASSING_TREE)
        first = _override(client, parent["id"], {"directions": [_direction("Boost", {"cash": 80})]})
        assert first.status_code == 201, first.text
        second = _override(
            client, parent["id"], {"directions": [_direction("Boost", {"cash": 120})]}
        )
        assert second.status_code == 201, second.text
        outcome = second.json()["outcomes"][0]
        assert outcome["status"] == "skipped"
        assert outcome["mapping_id"] is None
        assert outcome["child_run_id"] is None
        assert "already exists" in outcome["reason"]
        rows = _mappings(client, parent["id"])
        assert len(rows) == 1
        assert rows[0]["override_record"]["overrides"] == {"cash": 80.0}
        assert _branch_count(client, parent["id"]) == 1


def test_override_never_overwrites_user_edited_mapping(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        parent = _create_run(client, decomposition=PASSING_TREE)
        _create_ensemble(client, parent["id"])
        created = client.post(
            f"/runs/{parent['id']}/directions/mappings",
            json={"name": "Boost", "source_run_id": parent["id"], "arm": "baseline"},
        )
        assert created.status_code == 201, created.text
        updated = client.put(
            f"/runs/{parent['id']}/directions/mappings/{created.json()['id']}",
            json={"arm": "strategy"},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["user_edited"] is True
        response = _override(
            client, parent["id"], {"directions": [_direction("Boost", {"cash": 80})]}
        )
        assert response.status_code == 201, response.text
        assert response.json()["outcomes"][0]["status"] == "skipped"
        rows = _mappings(client, parent["id"])
        assert len(rows) == 1
        assert rows[0]["origin"] == "authored"
        assert rows[0]["arm"] == "strategy"
        assert rows[0]["user_edited"] is True
        assert _branch_count(client, parent["id"]) == 0


def test_override_without_runner_returns_503_and_writes_nothing(
    monkeypatch, tmp_path: Path
) -> None:
    setup_app(monkeypatch, tmp_path)
    app = create_app()
    with TestClient(app) as client:
        parent = _create_run(client, decomposition=PASSING_TREE)
        app.state.narrative_service = NarrativeService(get_settings())
        response = _override(
            client, parent["id"], {"directions": [_direction("Boost", {"cash": 80})]}
        )
        assert response.status_code == 503, response.text
        assert response.json()["detail"]["code"] == "direction_override_unavailable"
        assert _mappings(client, parent["id"]) == []
        assert _branch_count(client, parent["id"]) == 0


def test_override_partial_branch_failure_leaves_others_stored(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    app = create_app()
    with TestClient(app) as client:
        parent = _create_run(client, decomposition=PASSING_TREE)
        runner = ScriptedBranchRunner(fail_on_calls={2})
        _bind_runner(app, runner)
        response = _override(
            client,
            parent["id"],
            {
                "directions": [
                    _direction("First", {"cash": 80}),
                    _direction("Second", {"cash": 90}),
                ]
            },
        )
        assert response.status_code == 201, response.text
        outcomes = response.json()["outcomes"]
        assert [outcome["status"] for outcome in outcomes] == ["stored", "failed"]
        assert "scripted branch failure" in outcomes[1]["reason"]
        assert outcomes[1]["mapping_id"] is None
        assert len(runner.calls) == 2
        rows = _mappings(client, parent["id"])
        assert len(rows) == 1
        assert rows[0]["name"] == "First"
        assert rows[0]["source_run_id"] == "child-1"


def test_derive_skips_override_direction(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        parent = _create_run(client, decomposition=PASSING_TREE)
        _create_ensemble(client, parent["id"])
        overridden = _override(
            client,
            parent["id"],
            {
                "directions": [
                    _direction("Highest P50", {"cash": 80}, arm="strategy"),
                ]
            },
        )
        assert overridden.status_code == 201, overridden.text
        child_run_id = overridden.json()["outcomes"][0]["child_run_id"]
        derived = client.post(f"/runs/{parent['id']}/directions/derive")
        assert derived.status_code == 200, derived.text
        highest = next(
            outcome for outcome in derived.json()["outcomes"] if outcome["rule_id"] == "highest_p50"
        )
        assert highest["status"] == "skipped"
        assert "override" in highest["reason"]
        rows = _mappings(client, parent["id"])
        kept = next(row for row in rows if row["name"] == "Highest P50")
        assert kept["origin"] == "override"
        assert kept["status"] == "active"
        assert kept["arm"] == "strategy"
        assert kept["source_run_id"] == child_run_id


# ---------------------------------------------------------------------------
# Override → ensemble → generate
# ---------------------------------------------------------------------------


def test_override_then_ensemble_then_generate(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        parent = _create_run(client, decomposition=PASSING_TREE)
        overridden = _override(
            client,
            parent["id"],
            {
                "directions": [
                    _direction("Boost cash", {"cash": 80}, mece_branches=["Demand"]),
                ]
            },
        )
        assert overridden.status_code == 201, overridden.text
        mapping_id = overridden.json()["outcomes"][0]["mapping_id"]
        child_run_id = overridden.json()["outcomes"][0]["child_run_id"]

        # No eager ensemble: generation refuses until one exists.
        early = client.post(f"/runs/{parent['id']}/narratives", json={})
        assert early.status_code == 400, early.text
        assert early.json()["detail"]["code"] == "narrative_requires_ensemble"

        _create_ensemble(client, child_run_id)
        generated = client.post(f"/runs/{parent['id']}/narratives", json={})
        assert generated.status_code == 201, generated.text
        body = generated.json()
        assert body["direction_mapping_ids"] == [mapping_id]
        direction = body["body"]["directions"][0]
        assert direction["name"] == "Boost cash"
        assert direction["mece_trace"]["branches"][0]["name"] == "Demand"
        assert direction["mece_trace"]["branches"][0]["scope"] == ["demand"]
