"""API tests for override re-forks: editing a stored override mapping's
fixed values by creating a NEW branch run and repointing the SAME mapping.

A stored override mapping's fixed values are baked into its branch run,
so "editing" them must never silently rewrite the pinned
``override_record``: the re-fork endpoint creates one new scenario
branch with the new values, repoints the mapping (same id, name, and
position) at the new child run, and leaves the old branch run and its
rows untouched (append-only history). Covers the happy path with the
old branch untouched, grounding refusals with zero branches created,
wrong-origin / inactive refusals, fork-step default vs explicit,
concurrent-delete surfacing as a named 409, and post-commit failure
handling via the hardening discard mechanism. Same scratch-SQLite +
in-memory-bus + empty-LLM-keys pattern as the option B tests. No live
LLM call is ever made.
"""

from __future__ import annotations

import asyncio
import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from planagent.config import get_settings, reset_settings_cache
from planagent.db import get_database, reset_database_cache
from planagent.domain.models import DirectionMappingRecord, ScenarioBranchRecord, SimulationRun
from planagent.main import create_app
from planagent.services.narratives.models import DirectionOverrideReforkRequest
from planagent.services.narratives.overrides import (
    BranchCreationFailed,
    BranchRequest,
    BranchResult,
)
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


def setup_app(monkeypatch, tmp_path: Path, db_name: str = "planagent-reforks.db") -> None:
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
        "company_id": "reforks-test-co",
        "company_name": "Reforks Test Co",
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


def _refork(client: TestClient, run_id: str, mapping_id: str, payload: dict):
    return client.post(f"/runs/{run_id}/directions/mappings/{mapping_id}/refork", json=payload)


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


async def _set_mapping_status(mapping_id: str, status: str) -> None:
    database = get_database()
    async with database.session() as session:
        row = await session.get(DirectionMappingRecord, mapping_id)
        assert row is not None
        row.status = status
        await session.commit()


async def _set_run_status(run_id: str, status: str) -> None:
    database = get_database()
    async with database.session() as session:
        run = await session.get(SimulationRun, run_id)
        assert run is not None
        run.status = status
        await session.commit()


async def _strip_anchor_bindings(run_id: str) -> None:
    database = get_database()
    async with database.session() as session:
        run = await session.get(SimulationRun, run_id)
        assert run is not None
        configuration = dict(run.configuration or {})
        configuration.pop("variables", None)
        run.configuration = configuration
        await session.commit()


def _override_one(client: TestClient, parent_id: str) -> tuple[dict, dict]:
    """Create one override direction; return (outcome, stored mapping row)."""
    response = _override(
        client,
        parent_id,
        {
            "directions": [
                {"name": "Boost cash", "overrides": {"cash": 80}, "mece_branches": ["Demand"]}
            ]
        },
    )
    assert response.status_code == 201, response.text
    outcome = response.json()["outcomes"][0]
    assert outcome["status"] == "stored"
    rows = _mappings(client, parent_id)
    assert len(rows) == 1
    return outcome, rows[0]


def _bind_runner(app, runner) -> None:
    """Inject a scripted branch runner (the route resolves the
    service from app state on every request)."""
    app.state.narrative_service = NarrativeService(get_settings(), branch_runner=runner)


class FailingBranchRunner:
    """Branch runner that raises a scripted failure on create_branch."""

    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls: list[BranchRequest] = []
        self.discards: list[str] = []

    def is_available(self) -> bool:
        return True

    async def create_branch(
        self, _session: AsyncSession, _parent_run_id: str, request: BranchRequest
    ) -> BranchResult:
        self.calls.append(request)
        raise self.error

    async def discard_branch(self, _session: AsyncSession, branch_id: str) -> bool:
        self.discards.append(branch_id)
        return True


class DeletingBranchRunner:
    """Branch runner that deletes the target mapping mid-flight.

    The delete commits through the same session, so the service's
    post-creation re-fetch finds the row gone — the concurrent
    delete the re-fork endpoint must surface as a named error.
    """

    def __init__(self, mapping_id: str) -> None:
        self.mapping_id = mapping_id
        self.calls: list[BranchRequest] = []
        self.discards: list[str] = []

    def is_available(self) -> bool:
        return True

    async def create_branch(
        self, session: AsyncSession, _parent_run_id: str, request: BranchRequest
    ) -> BranchResult:
        self.calls.append(request)
        await session.execute(
            delete(DirectionMappingRecord).where(DirectionMappingRecord.id == self.mapping_id)
        )
        await session.commit()
        return BranchResult(branch_id="branch-new", run_id="child-new", fork_step=request.fork_step)

    async def discard_branch(self, _session: AsyncSession, branch_id: str) -> bool:
        self.discards.append(branch_id)
        return True


# ---------------------------------------------------------------------------
# Refork request model validation (unit)
# ---------------------------------------------------------------------------


def test_refork_request_normalizes_keys_and_coerces_ints() -> None:
    request = DirectionOverrideReforkRequest(overrides={" cash ": 80})
    assert request.overrides == {"cash": 80.0}
    assert request.fork_step is None


@pytest.mark.parametrize(
    "payload",
    [
        {"overrides": {}},
        {"overrides": {"  ": 80}},
        {"overrides": {"cash": 80, " cash": 90}},
        {"overrides": {"cash": "80"}},
        {"overrides": {"cash": True}},
        {"overrides": {"cash": math.nan}},
        {"overrides": {"cash": math.inf}},
        {"overrides": {"cash": 80}, "fork_step": 0},
        {"overrides": {"cash": 80}, "surprise": 1},
    ],
)
def test_refork_request_rejects_bad_payloads(payload: dict) -> None:
    with pytest.raises(ValidationError):
        DirectionOverrideReforkRequest(**payload)


# ---------------------------------------------------------------------------
# Refork: happy path + old-branch history
# ---------------------------------------------------------------------------


def test_refork_creates_new_branch_and_repoints_mapping(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        parent = _create_run(client, decomposition=PASSING_TREE)
        outcome, row = _override_one(client, parent["id"])
        old_child_id = outcome["child_run_id"]
        old_branch_id = outcome["branch_id"]

        response = _refork(client, parent["id"], row["id"], {"overrides": {"cash": 90}})
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["branch_id"]
        assert body["branch_id"] != old_branch_id
        assert body["child_run_id"] != old_child_id
        assert body["child_run_id"] != parent["id"]
        assert body["fork_step"] == 2  # midpoint default for tick_count 4
        assert body["child_status"] == "COMPLETED"
        assert body["override_hash"].startswith("sha256:")
        assert "monte-carlo" in body["reason"]
        assert "left untouched" in body["reason"]

        mapping = body["mapping"]
        assert mapping["id"] == row["id"]
        assert mapping["name"] == "Boost cash"
        assert mapping["position"] == 0
        assert mapping["source_run_id"] == body["child_run_id"]
        assert mapping["origin"] == "override"
        assert mapping["status"] == "active"
        assert mapping["arm"] == "baseline"
        assert mapping["mece_branches"] == ["Demand"]
        assert mapping["user_edited"] is True
        record = mapping["override_record"]
        assert record["overrides"] == {"cash": 90.0}
        assert record["branch_id"] == body["branch_id"]
        assert record["fork_step"] == 2
        assert record["override_hash"] == body["override_hash"]

        # One mapping row (repointed, not duplicated); two branches
        # (the old one survives as append-only history).
        rows = _mappings(client, parent["id"])
        assert len(rows) == 1
        assert rows[0]["id"] == row["id"]
        assert _branch_count(client, parent["id"]) == 2

        # The old child run still carries the old fixed value; the
        # new child carries the new one; the new branch record
        # carries the re-fork assumption line.
        old_configuration = asyncio.run(_read_run_configuration(old_child_id))
        old_bindings = old_configuration["variables"]["bindings"]["variables"]
        old_distribution = next(v for v in old_bindings if v["id"] == "cash")["distribution"]
        assert old_distribution["type"] == "fixed"
        assert old_distribution["value"] == 80.0
        new_configuration = asyncio.run(_read_run_configuration(body["child_run_id"]))
        new_bindings = new_configuration["variables"]["bindings"]["variables"]
        new_distribution = next(v for v in new_bindings if v["id"] == "cash")["distribution"]
        assert new_distribution["type"] == "fixed"
        assert new_distribution["value"] == 90.0
        assumptions = asyncio.run(_read_branch_assumptions(body["branch_id"]))
        assert assumptions == ["Direction 'Boost cash': override cash=90.0."]


def test_refork_explicit_fork_step_is_honored(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        parent = _create_run(client, decomposition=PASSING_TREE)
        _outcome, row = _override_one(client, parent["id"])
        response = _refork(
            client, parent["id"], row["id"], {"overrides": {"cash": 90}, "fork_step": 1}
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["fork_step"] == 1
        assert body["mapping"]["override_record"]["fork_step"] == 1
        assert body["mapping"]["override_record"]["overrides"] == {"cash": 90.0}


# ---------------------------------------------------------------------------
# Refork: refusals before any branch is created
# ---------------------------------------------------------------------------


def test_refork_refuses_unknown_variable_and_creates_nothing(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        parent = _create_run(client, decomposition=PASSING_TREE)
        outcome, row = _override_one(client, parent["id"])
        response = _refork(client, parent["id"], row["id"], {"overrides": {"nope": 1}})
        assert response.status_code == 400, response.text
        assert response.json()["detail"]["code"] == "direction_override_unknown_variable"
        assert _branch_count(client, parent["id"]) == 1
        rows = _mappings(client, parent["id"])
        assert len(rows) == 1
        assert rows[0]["source_run_id"] == outcome["child_run_id"]
        assert rows[0]["override_record"]["overrides"] == {"cash": 80.0}


def test_refork_refuses_missing_snapshot_and_creates_nothing(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        parent = _create_run(client, decomposition=PASSING_TREE)
        outcome, row = _override_one(client, parent["id"])
        response = _refork(
            client, parent["id"], row["id"], {"overrides": {"cash": 90}, "fork_step": 99}
        )
        assert response.status_code == 400, response.text
        assert response.json()["detail"]["code"] == "direction_override_no_snapshot"
        assert _branch_count(client, parent["id"]) == 1
        rows = _mappings(client, parent["id"])
        assert rows[0]["source_run_id"] == outcome["child_run_id"]
        assert rows[0]["override_record"]["overrides"] == {"cash": 80.0}


def test_refork_refuses_wrong_origin(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        parent = _create_run(client, decomposition=PASSING_TREE)
        _create_ensemble(client, parent["id"])
        created = client.post(
            f"/runs/{parent['id']}/directions/mappings",
            json={"name": "My pick", "source_run_id": parent["id"], "arm": "baseline"},
        )
        assert created.status_code == 201, created.text
        mapping = created.json()
        assert mapping["origin"] == "authored"
        response = _refork(client, parent["id"], mapping["id"], {"overrides": {"cash": 90}})
        assert response.status_code == 400, response.text
        assert response.json()["detail"]["code"] == "direction_mapping_not_override"
        assert _branch_count(client, parent["id"]) == 0


def test_refork_refuses_inactive_mapping(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        parent = _create_run(client, decomposition=PASSING_TREE)
        outcome, row = _override_one(client, parent["id"])
        asyncio.run(_set_mapping_status(row["id"], "rejected"))
        response = _refork(client, parent["id"], row["id"], {"overrides": {"cash": 90}})
        assert response.status_code == 400, response.text
        assert response.json()["detail"]["code"] == "direction_mapping_not_active"
        assert _branch_count(client, parent["id"]) == 1
        rows = _mappings(client, parent["id"])
        assert rows[0]["source_run_id"] == outcome["child_run_id"]
        assert rows[0]["override_record"]["overrides"] == {"cash": 80.0}


def test_refork_refuses_noncompleted_anchor(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        parent = _create_run(client, decomposition=PASSING_TREE)
        _outcome, row = _override_one(client, parent["id"])
        asyncio.run(_set_run_status(parent["id"], "QUEUED"))
        response = _refork(client, parent["id"], row["id"], {"overrides": {"cash": 90}})
        assert response.status_code == 400, response.text
        assert response.json()["detail"]["code"] == "direction_requires_completed_run"
        assert _branch_count(client, parent["id"]) == 1


def test_refork_requires_bindings(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        parent = _create_run(client, decomposition=PASSING_TREE)
        _outcome, row = _override_one(client, parent["id"])
        asyncio.run(_strip_anchor_bindings(parent["id"]))
        response = _refork(client, parent["id"], row["id"], {"overrides": {"cash": 90}})
        assert response.status_code == 400, response.text
        assert response.json()["detail"]["code"] == "direction_override_requires_bindings"
        assert _branch_count(client, parent["id"]) == 1


def test_refork_unknown_mapping_404(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        parent = _create_run(client, decomposition=PASSING_TREE)
        response = _refork(client, parent["id"], "mapping-missing", {"overrides": {"cash": 90}})
        assert response.status_code == 404, response.text


def test_refork_mapping_of_another_run_404(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        parent = _create_run(client, decomposition=PASSING_TREE)
        _outcome, row = _override_one(client, parent["id"])
        other = _create_run(client)
        response = _refork(client, other["id"], row["id"], {"overrides": {"cash": 90}})
        assert response.status_code == 404, response.text
        assert _branch_count(client, parent["id"]) == 1
        assert _branch_count(client, other["id"]) == 0


def test_refork_rejects_invalid_payloads(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        parent = _create_run(client, decomposition=PASSING_TREE)
        _outcome, row = _override_one(client, parent["id"])
        for payload in (
            {"overrides": {}},
            {"overrides": {"cash": "90"}},
            {"overrides": {"cash": 90}, "fork_step": 0},
            {"overrides": {"cash": 90}, "surprise": 1},
        ):
            response = _refork(client, parent["id"], row["id"], payload)
            assert response.status_code == 422, (payload, response.text)
        assert _branch_count(client, parent["id"]) == 1


def test_refork_without_runner_returns_503_and_writes_nothing(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    app = create_app()
    with TestClient(app) as client:
        parent = _create_run(client, decomposition=PASSING_TREE)
        outcome, row = _override_one(client, parent["id"])
        app.state.narrative_service = NarrativeService(get_settings())
        response = _refork(client, parent["id"], row["id"], {"overrides": {"cash": 90}})
        assert response.status_code == 503, response.text
        assert response.json()["detail"]["code"] == "direction_override_unavailable"
        assert _branch_count(client, parent["id"]) == 1
        rows = _mappings(client, parent["id"])
        assert rows[0]["source_run_id"] == outcome["child_run_id"]
        assert rows[0]["override_record"]["overrides"] == {"cash": 80.0}


# ---------------------------------------------------------------------------
# Refork: branch failures reuse the hardening mechanism
# ---------------------------------------------------------------------------


def test_refork_post_commit_failure_discards_new_branch(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    app = create_app()
    with TestClient(app) as client:
        parent = _create_run(client, decomposition=PASSING_TREE)
        outcome, row = _override_one(client, parent["id"])
        runner = FailingBranchRunner(
            BranchCreationFailed("boom after commit", branch_id="branch-new", run_id="child-new")
        )
        _bind_runner(app, runner)
        response = _refork(client, parent["id"], row["id"], {"overrides": {"cash": 90}})
        assert response.status_code == 400, response.text
        detail = response.json()["detail"]
        assert detail["code"] == "direction_override_refork_failed"
        assert "branch-new" in detail["message"]
        assert "was discarded" in detail["message"]
        assert runner.discards == ["branch-new"]
        assert _branch_count(client, parent["id"]) == 1
        rows = _mappings(client, parent["id"])
        assert rows[0]["source_run_id"] == outcome["child_run_id"]
        assert rows[0]["override_record"]["overrides"] == {"cash": 80.0}


def test_refork_post_commit_failure_without_identity_discards_nothing(
    monkeypatch, tmp_path: Path
) -> None:
    setup_app(monkeypatch, tmp_path)
    app = create_app()
    with TestClient(app) as client:
        parent = _create_run(client, decomposition=PASSING_TREE)
        outcome, row = _override_one(client, parent["id"])
        runner = FailingBranchRunner(BranchCreationFailed("boom, identity unknown"))
        _bind_runner(app, runner)
        response = _refork(client, parent["id"], row["id"], {"overrides": {"cash": 90}})
        assert response.status_code == 400, response.text
        detail = response.json()["detail"]
        assert detail["code"] == "direction_override_refork_failed"
        assert "No branch identity was reported" in detail["message"]
        assert runner.discards == []
        assert _branch_count(client, parent["id"]) == 1
        rows = _mappings(client, parent["id"])
        assert rows[0]["source_run_id"] == outcome["child_run_id"]


def test_refork_plain_branch_failure_reports_named_error(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    app = create_app()
    with TestClient(app) as client:
        parent = _create_run(client, decomposition=PASSING_TREE)
        outcome, row = _override_one(client, parent["id"])
        runner = FailingBranchRunner(RuntimeError("scripted branch failure"))
        _bind_runner(app, runner)
        response = _refork(client, parent["id"], row["id"], {"overrides": {"cash": 90}})
        assert response.status_code == 400, response.text
        detail = response.json()["detail"]
        assert detail["code"] == "direction_override_refork_failed"
        assert "Branch creation failed: scripted branch failure" in detail["message"]
        assert runner.discards == []
        assert _branch_count(client, parent["id"]) == 1
        rows = _mappings(client, parent["id"])
        assert rows[0]["source_run_id"] == outcome["child_run_id"]


def test_refork_concurrent_delete_surfaces_conflict_and_discards_branch(
    monkeypatch, tmp_path: Path
) -> None:
    setup_app(monkeypatch, tmp_path)
    app = create_app()
    with TestClient(app) as client:
        parent = _create_run(client, decomposition=PASSING_TREE)
        _outcome, row = _override_one(client, parent["id"])
        runner = DeletingBranchRunner(row["id"])
        _bind_runner(app, runner)
        response = _refork(client, parent["id"], row["id"], {"overrides": {"cash": 90}})
        assert response.status_code == 409, response.text
        detail = response.json()["detail"]
        assert detail["code"] == "direction_mapping_deleted_concurrently"
        assert "was deleted" in detail["message"]
        assert runner.discards == ["branch-new"]
        assert _mappings(client, parent["id"]) == []
        # The original branch survives: only the new branch was discarded.
        assert _branch_count(client, parent["id"]) == 1
