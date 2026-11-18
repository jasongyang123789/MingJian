"""Hardening tests for option B: post-commit orphan cleanup + same-name races.

Covers the two runtime gaps left open by OPTION-B.md §6:

- a branch runner that fails AFTER its internal commit must not
  leave an orphan branch row: the committed branch is discarded
  (branch row, child run, and every row branch execution created
  for that child), the other directions in the request are
  unaffected, and the failure is reported per direction;
- two concurrent override calls naming the same direction must
  resolve to exactly one ``stored`` + one ``skipped`` (201, never
  a 500), with the loser's branch discarded and the first row
  untouched. The unique constraint arbitrates; no locking.

Same scratch-SQLite + in-memory-bus + empty-LLM-keys pattern as
the option B API tests. No live LLM call is ever made. The
concurrency test switches its scratch database to WAL mode:
rollback-journal SQLite lets a second session's read transaction
block the first session's commit, which would deadlock the
choreographed overlap; WAL readers never block the writer, so
the loser's flush hits the unique constraint exactly as on
Postgres. The unique-violation matcher is unit-tested with both
the SQLite and the Postgres driver messages.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from planagent.api.routes._deps import SimulationBranchRunner
from planagent.config import get_settings, reset_settings_cache
from planagent.db import get_database, reset_database_cache
from planagent.domain.api import ScenarioRunCreate
from planagent.domain.models import (
    DecisionOption,
    DecisionRecordRecord,
    DirectionMappingRecord,
    ExternalShockRecord,
    GeneratedReport,
    GeoAssetRecord,
    Hypothesis,
    PredictionCalibrationContext,
    PredictionSeries,
    PredictionVersion,
    ScenarioBranchRecord,
    SimulationRun,
    StateSnapshotRecord,
)
from planagent.events.bus import InMemoryEventBus
from planagent.main import create_app
from planagent.services.narratives.models import (
    DirectionOverrideRequest,
    DirectionOverrideSpec,
)
from planagent.services.narratives.overrides import (
    BranchCreationFailed,
    BranchRequest,
    BranchResult,
)
from planagent.services.narratives.service import (
    NarrativeService,
    _is_mapping_unique_violation,
)
from planagent.services.simulation import SimulationService
from planagent.services.variables.models import VariableSet
from planagent.simulation.rules import RuleRegistry

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


def setup_app(monkeypatch, tmp_path: Path, db_name: str = "planagent-hardening.db") -> None:
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
        "company_id": "hardening-test-co",
        "company_name": "Hardening Test Co",
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


def _bind_runner(app, runner) -> None:
    app.state.narrative_service = NarrativeService(get_settings(), branch_runner=runner)


def build_simulation_service() -> SimulationService:
    return SimulationService(
        settings=get_settings(),
        event_bus=InMemoryEventBus(),
        rule_registry=RuleRegistry(Path("rules")),
    )


# ---------------------------------------------------------------------------
# Row-count helpers (SQLite does not enforce foreign keys here, so the
# tests assert zero dangling rows explicitly, table by table)
# ---------------------------------------------------------------------------


async def _dependent_counts(child_id: str) -> dict[str, int]:
    database = get_database()
    async with database.session() as session:
        counts: dict[str, int] = {}
        by_run = [
            ("snapshots", StateSnapshotRecord, StateSnapshotRecord.run_id),
            ("decision_records", DecisionRecordRecord, DecisionRecordRecord.run_id),
            ("shocks", ExternalShockRecord, ExternalShockRecord.run_id),
            ("reports", GeneratedReport, GeneratedReport.run_id),
            ("geo_assets", GeoAssetRecord, GeoAssetRecord.run_id),
            ("options", DecisionOption, DecisionOption.run_id),
            ("hypotheses", Hypothesis, Hypothesis.run_id),
            (
                "calibration_contexts",
                PredictionCalibrationContext,
                PredictionCalibrationContext.run_id,
            ),
        ]
        for name, model, column in by_run:
            counts[name] = int(
                await session.scalar(
                    select(func.count()).select_from(model).where(column == child_id)
                )
                or 0
            )
        series_ids = list(
            (
                await session.scalars(
                    select(PredictionSeries.id).where(
                        PredictionSeries.source_run_id == child_id
                    )
                )
            ).all()
        )
        counts["series"] = len(series_ids)
        if series_ids:
            counts["versions"] = int(
                await session.scalar(
                    select(func.count())
                    .select_from(PredictionVersion)
                    .where(PredictionVersion.series_id.in_(series_ids))
                )
                or 0
            )
        else:
            counts["versions"] = 0
        counts["branches"] = int(
            await session.scalar(
                select(func.count())
                .select_from(ScenarioBranchRecord)
                .where(ScenarioBranchRecord.run_id == child_id)
            )
            or 0
        )
        counts["runs"] = int(
            await session.scalar(
                select(func.count())
                .select_from(SimulationRun)
                .where(SimulationRun.id == child_id)
            )
            or 0
        )
        return counts


async def _parent_branch_ids(parent_id: str) -> list[str]:
    database = get_database()
    async with database.session() as session:
        parent = await session.get(SimulationRun, parent_id)
        assert parent is not None
        return list((parent.summary or {}).get("scenario_branch_ids", []))


async def _all_branch_ids() -> list[str]:
    database = get_database()
    async with database.session() as session:
        return list((await session.scalars(select(ScenarioBranchRecord.id))).all())


async def _run_count() -> int:
    database = get_database()
    async with database.session() as session:
        return int(await session.scalar(select(func.count()).select_from(SimulationRun)) or 0)


async def _mapping_rows(anchor_id: str) -> list[DirectionMappingRecord]:
    database = get_database()
    async with database.session() as session:
        rows = list(
            (
                await session.scalars(
                    select(DirectionMappingRecord).where(
                        DirectionMappingRecord.anchor_run_id == anchor_id
                    )
                )
            ).all()
        )
        for row in rows:
            session.expunge(row)
        return rows


# ---------------------------------------------------------------------------
# Fix 1: post-commit runner failure discards the committed branch
# ---------------------------------------------------------------------------


class CommitThenRaiseRunner:
    """Real branch creation that raises after committing, on scripted calls."""

    def __init__(
        self, simulation_service: SimulationService, fail_on_calls: set[int] | None = None
    ) -> None:
        self._service = simulation_service
        self.fail_on_calls = fail_on_calls or set()
        self.calls: list[BranchRequest] = []
        self.committed: list[tuple[str, str]] = []
        self.discards: list[str] = []

    def is_available(self) -> bool:
        return True

    async def create_branch(
        self, session: AsyncSession, parent_run_id: str, request: BranchRequest
    ) -> BranchResult:
        self.calls.append(request)
        branch = await self._service.create_scenario_run(
            session,
            parent_run_id,
            ScenarioRunCreate(
                fork_step=request.fork_step,
                variable_set=request.variable_set,
                assumptions=request.assumptions,
            ),
        )
        self.committed.append((branch.id, branch.run_id))
        if len(self.calls) in self.fail_on_calls:
            raise BranchCreationFailed(
                "commit-then-raise",
                branch_id=branch.id,
                run_id=branch.run_id,
            )
        return BranchResult(
            branch_id=branch.id, run_id=branch.run_id, fork_step=branch.fork_step
        )

    async def discard_branch(self, session: AsyncSession, branch_id: str) -> bool:
        self.discards.append(branch_id)
        return await self._service.delete_scenario_branch(session, branch_id)


def test_commit_then_raise_discards_branch_and_keeps_others(
    monkeypatch, tmp_path: Path
) -> None:
    setup_app(monkeypatch, tmp_path)
    app = create_app()
    with TestClient(app) as client:
        parent = _create_run(client, decomposition=PASSING_TREE)
        runner = CommitThenRaiseRunner(build_simulation_service(), fail_on_calls={2})
        _bind_runner(app, runner)
        response = client.post(
            f"/runs/{parent['id']}/directions/override",
            json={
                "directions": [
                    {"name": "First", "overrides": {"cash": 80}},
                    {"name": "Second", "overrides": {"cash": 120}},
                ]
            },
        )
        assert response.status_code == 201, response.text
        outcomes = response.json()["outcomes"]
        assert [outcome["status"] for outcome in outcomes] == ["stored", "failed"]
        assert "after commit" in outcomes[1]["reason"]
        assert "was discarded" in outcomes[1]["reason"]
        assert outcomes[1]["mapping_id"] is None
        assert len(runner.calls) == 2
        assert len(runner.committed) == 2
        assert len(runner.discards) == 1
        failed_branch_id, failed_child_id = runner.committed[1]
        assert runner.discards == [failed_branch_id]
        assert failed_branch_id in outcomes[1]["reason"]

        # No orphan rows for the failed branch anywhere.
        counts = asyncio.run(_dependent_counts(failed_child_id))
        assert counts == {name: 0 for name in counts}, counts
        assert asyncio.run(_all_branch_ids()) == [runner.committed[0][0]]
        assert asyncio.run(_run_count()) == 2  # parent + stored child
        assert asyncio.run(_parent_branch_ids(parent["id"])) == [runner.committed[0][0]]

        # The stored direction is intact.
        rows = asyncio.run(_mapping_rows(parent["id"]))
        assert len(rows) == 1
        assert rows[0].name == "First"
        assert rows[0].source_run_id == runner.committed[0][1]
        assert rows[0].origin == "override"


class UnknownIdentityRunner:
    """Raises a post-commit failure with no branch identity at all."""

    def __init__(self) -> None:
        self.discards: list[str] = []

    def is_available(self) -> bool:
        return True

    async def create_branch(
        self, _session: AsyncSession, _parent_run_id: str, _request: BranchRequest
    ) -> BranchResult:
        raise BranchCreationFailed("commit-then-raise, identities unknown")

    async def discard_branch(self, _session: AsyncSession, branch_id: str) -> bool:
        self.discards.append(branch_id)
        return True


def test_commit_then_raise_without_identity_discards_nothing(
    monkeypatch, tmp_path: Path
) -> None:
    setup_app(monkeypatch, tmp_path)
    app = create_app()
    with TestClient(app) as client:
        parent = _create_run(client, decomposition=PASSING_TREE)
        runner = UnknownIdentityRunner()
        _bind_runner(app, runner)
        response = client.post(
            f"/runs/{parent['id']}/directions/override",
            json={"directions": [{"name": "Only", "overrides": {"cash": 80}}]},
        )
        assert response.status_code == 201, response.text
        outcomes = response.json()["outcomes"]
        assert [outcome["status"] for outcome in outcomes] == ["failed"]
        assert "No branch identity was reported" in outcomes[0]["reason"]
        assert runner.discards == []
        assert asyncio.run(_all_branch_ids()) == []
        assert asyncio.run(_mapping_rows(parent["id"])) == []


# ---------------------------------------------------------------------------
# delete_scenario_branch: the cleanup mechanism itself
# ---------------------------------------------------------------------------


def test_delete_scenario_branch_removes_branch_dependents_and_scrubs_parent(
    monkeypatch, tmp_path: Path
) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        parent = _create_run(client, decomposition=PASSING_TREE)

    async def make_branch() -> tuple[str, str]:
        database = get_database()
        async with database.session() as session:
            branch = await build_simulation_service().create_scenario_run(
                session,
                parent["id"],
                ScenarioRunCreate(fork_step=2, assumptions=["delete-me"]),
            )
            return branch.id, branch.run_id

    branch_id, child_id = asyncio.run(make_branch())
    before = asyncio.run(_dependent_counts(child_id))
    assert before["branches"] == 1
    assert before["runs"] == 1
    assert before["snapshots"] > 0
    assert before["reports"] == 1
    assert before["options"] > 0
    assert branch_id in asyncio.run(_parent_branch_ids(parent["id"]))
    parent_snapshots_before = asyncio.run(_dependent_counts(parent["id"]))["snapshots"]
    assert parent_snapshots_before > 0

    async def delete(scenario_id: str) -> bool:
        database = get_database()
        async with database.session() as session:
            return await build_simulation_service().delete_scenario_branch(
                session, scenario_id
            )

    assert asyncio.run(delete(branch_id)) is True
    after = asyncio.run(_dependent_counts(child_id))
    assert after == {name: 0 for name in after}, after
    assert branch_id not in asyncio.run(_parent_branch_ids(parent["id"]))
    # The parent run and its own rows are untouched.
    assert asyncio.run(_dependent_counts(parent["id"]))["runs"] == 1
    assert asyncio.run(_dependent_counts(parent["id"]))["snapshots"] == parent_snapshots_before
    # Idempotent, and a missing id is False rather than an error.
    assert asyncio.run(delete(branch_id)) is False
    assert asyncio.run(delete("no-such-branch")) is False


# ---------------------------------------------------------------------------
# Adapter: post-commit failure conversion + discard delegation
# ---------------------------------------------------------------------------


class _RaisingBranch:
    """A branch row whose fork_step access fails after commit."""

    id = "branch-x"
    run_id = "child-x"

    @property
    def fork_step(self) -> int:
        raise RuntimeError("expired attribute")


class _DeadBranch:
    """A branch row on which every attribute access fails."""

    def __getattr__(self, _name: str) -> object:
        raise RuntimeError("detached instance")


class _StubSimulationService:
    def __init__(self, branch: object, delete_result: bool = True) -> None:
        self.branch = branch
        self.delete_result = delete_result
        self.deleted: list[str] = []

    async def create_scenario_run(
        self, _session: AsyncSession, _parent_run_id: str, _payload: ScenarioRunCreate
    ) -> object:
        return self.branch

    async def delete_scenario_branch(self, _session: AsyncSession, scenario_id: str) -> bool:
        self.deleted.append(scenario_id)
        return self.delete_result


def _branch_request() -> BranchRequest:
    return BranchRequest(
        fork_step=2,
        variable_set=VariableSet.model_validate(BOUND_SET),
        assumptions=["adapter"],
    )


def test_adapter_converts_result_building_failure_with_identities() -> None:
    runner = SimulationBranchRunner(_StubSimulationService(_RaisingBranch()))  # type: ignore[arg-type]
    with pytest.raises(BranchCreationFailed) as caught:
        asyncio.run(runner.create_branch(None, "parent", _branch_request()))  # type: ignore[arg-type]
    assert "could not be reported" in str(caught.value)
    assert caught.value.branch_id == "branch-x"
    assert caught.value.run_id == "child-x"


def test_adapter_reports_unknown_identities_when_branch_unreadable() -> None:
    runner = SimulationBranchRunner(_StubSimulationService(_DeadBranch()))  # type: ignore[arg-type]
    with pytest.raises(BranchCreationFailed) as caught:
        asyncio.run(runner.create_branch(None, "parent", _branch_request()))  # type: ignore[arg-type]
    assert caught.value.branch_id is None
    assert caught.value.run_id is None


def test_adapter_discard_delegates_to_simulation_service() -> None:
    stub = _StubSimulationService(_RaisingBranch(), delete_result=False)
    runner = SimulationBranchRunner(stub)  # type: ignore[arg-type]
    assert asyncio.run(runner.discard_branch(None, "branch-9")) is False  # type: ignore[arg-type]
    assert stub.deleted == ["branch-9"]


# ---------------------------------------------------------------------------
# Refresh guard: a post-commit refresh failure cleans up, then surfaces
# ---------------------------------------------------------------------------


def test_create_scenario_run_refresh_failure_cleans_up(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        parent = _create_run(client, decomposition=PASSING_TREE)

    original_refresh = AsyncSession.refresh

    async def flaky_refresh(self, instance, *args, **kwargs):
        if isinstance(instance, ScenarioBranchRecord):
            raise RuntimeError("simulated refresh failure")  # noqa: TRY004 — simulating an infrastructure failure, not a type error
        return await original_refresh(self, instance, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "refresh", flaky_refresh)

    async def attempt() -> None:
        database = get_database()
        async with database.session() as session:
            with pytest.raises(RuntimeError, match="simulated refresh failure"):
                await build_simulation_service().create_scenario_run(
                    session,
                    parent["id"],
                    ScenarioRunCreate(fork_step=2, assumptions=["refresh-guard"]),
                )

    asyncio.run(attempt())
    assert asyncio.run(_all_branch_ids()) == []
    assert asyncio.run(_run_count()) == 1
    assert asyncio.run(_parent_branch_ids(parent["id"])) == []


# ---------------------------------------------------------------------------
# Fix 2: concurrent same-name override calls
# ---------------------------------------------------------------------------


class GatedRunner:
    """Real branch creation gated so both concurrent calls overlap."""

    def __init__(self, simulation_service: SimulationService) -> None:
        self._service = simulation_service
        self.discards: list[str] = []
        self._arrived = 0
        self._gate = asyncio.Event()

    def is_available(self) -> bool:
        return True

    async def create_branch(
        self, session: AsyncSession, parent_run_id: str, request: BranchRequest
    ) -> BranchResult:
        self._arrived += 1
        if self._arrived == 2:
            self._gate.set()
        await asyncio.wait_for(self._gate.wait(), timeout=30)
        branch = await self._service.create_scenario_run(
            session,
            parent_run_id,
            ScenarioRunCreate(
                fork_step=request.fork_step,
                variable_set=request.variable_set,
                assumptions=request.assumptions,
            ),
        )
        return BranchResult(
            branch_id=branch.id, run_id=branch.run_id, fork_step=branch.fork_step
        )

    async def discard_branch(self, session: AsyncSession, branch_id: str) -> bool:
        self.discards.append(branch_id)
        return await self._service.delete_scenario_branch(session, branch_id)


def _enable_wal(db_path: Path) -> None:
    connection = sqlite3.connect(db_path)
    try:
        mode = connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
    finally:
        connection.close()
    assert mode == "wal", mode


def test_concurrent_same_name_override_stores_once_and_skips_loser(
    monkeypatch, tmp_path: Path
) -> None:
    db_name = "planagent-race.db"
    setup_app(monkeypatch, tmp_path, db_name=db_name)
    with TestClient(create_app()) as client:
        parent = _create_run(client, decomposition=PASSING_TREE)
    _enable_wal(tmp_path / db_name)

    runner = GatedRunner(build_simulation_service())

    async def one(overrides: dict[str, float]):
        database = get_database()
        async with database.session() as session:
            service = NarrativeService(get_settings(), branch_runner=runner)
            return await service.override(
                session,
                parent["id"],
                DirectionOverrideRequest(
                    directions=[
                        DirectionOverrideSpec(name="Race", overrides=overrides)
                    ]
                ),
            )

    async def both():
        return await asyncio.gather(one({"cash": 80}), one({"cash": 120}))

    results = asyncio.run(both())
    statuses = sorted(outcome.status for result in results for outcome in result.outcomes)
    assert statuses == ["skipped", "stored"]
    stored = next(
        outcome
        for result in results
        for outcome in result.outcomes
        if outcome.status == "stored"
    )
    skipped = next(
        outcome
        for result in results
        for outcome in result.outcomes
        if outcome.status == "skipped"
    )
    assert "concurrently" in skipped.reason
    assert stored.mapping_id is not None

    rows = asyncio.run(_mapping_rows(parent["id"]))
    assert len(rows) == 1
    assert rows[0].name == "Race"
    assert rows[0].source_run_id == stored.child_run_id
    assert asyncio.run(_run_count()) == 2  # parent + exactly one child
    assert len(asyncio.run(_all_branch_ids())) == 1
    # The loser's branch was discarded exactly once.
    assert len(runner.discards) == 1
    assert runner.discards[0] not in asyncio.run(_all_branch_ids())


# ---------------------------------------------------------------------------
# Unique-violation matcher: SQLite + Postgres driver messages
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (
            "UNIQUE constraint failed: direction_mappings.anchor_run_id, direction_mappings.name",
            True,
        ),
        (
            'duplicate key value violates unique constraint "uq_direction_mappings_anchor_name"',
            True,
        ),
        ("FOREIGN KEY constraint failed", False),
        ("NOT NULL constraint failed: direction_mappings.name", False),
        (
            'duplicate key value violates unique constraint "simulation_runs_pkey"',
            False,
        ),
    ],
)
def test_is_mapping_unique_violation(message: str, expected: bool) -> None:
    exc = IntegrityError("INSERT INTO direction_mappings ...", {}, Exception(message))
    assert _is_mapping_unique_violation(exc) is expected


def test_is_mapping_unique_violation_without_driver_error() -> None:
    exc = IntegrityError(
        'INSERT ... violates unique constraint "uq_direction_mappings_anchor_name"',
        {},
        None,
    )
    assert _is_mapping_unique_violation(exc) is True
