"""Fix batch 3: Postgres-only bugs found by Docker retry 6.

Bug 1 — ``_persist_raw_item`` called ``.on_conflict_do_nothing()`` on a
generic ``sqlalchemy.insert``, which has no such method; only the
Postgres-dialect insert does. The SQLite branch never executes that
line, so no SQLite test caught it. These tests exercise the real
branch code with a dialect-mocked session: on the old code the first
test raises the exact production ``AttributeError``.

Bug 2 — ``derive_sub_seed`` returns 63-bit integers, but
``SimulationRun.seed`` was ``Integer`` (32-bit on Postgres), so the
Monte Carlo trial-row flush failed with ``integer out of range``.
SQLite integers are 64-bit, so SQLite cannot reproduce the failure:
the regression proof here is the column-type assertion (which fails
on the old model) plus the migration drill in
``tests/unit/test_migrations.py``; the live Postgres proof is the hub
re-run after merge.

Test strategy is recorded explicitly because there is no live Postgres
on this VM: statement compilation against the ``postgresql`` dialect
plus dialect-mocked session execution for bug 1, and column-type +
persistence assertions for bug 2.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import BigInteger, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import Insert as PostgresInsert

from planagent.config import Settings, reset_settings_cache
from planagent.db import get_database, reset_database_cache
from planagent.domain.api import SourceSeedInput
from planagent.domain.enums import EventTopic
from planagent.domain.models import (
    CalibrationFitRecord,
    IngestRun,
    RawSourceItem,
    SimulationRun,
    generate_id,
    utc_now,
)
from planagent.events.bus import InMemoryEventBus
from planagent.services.distributions.canonical import derive_sub_seed
from planagent.services.pipeline import PhaseOnePipelineService, build_dedupe_key


def _make_item(**overrides: Any) -> SourceSeedInput:
    defaults = {
        "source_type": "rss",
        "source_url": "https://example.com/article",
        "title": "Test Title",
        "content_text": "Body content.",
    }
    defaults.update(overrides)
    return SourceSeedInput(**defaults)


def _make_service(tmp_path: Path) -> PhaseOnePipelineService:
    settings = Settings(source_snapshot_dir=tmp_path / "snapshots")
    return PhaseOnePipelineService(settings, InMemoryEventBus())


def _make_run() -> IngestRun:
    return IngestRun(id="run-1", request_payload={"tenant_id": "tenant-1"})


class _FakeScalars:
    def __init__(self, row: RawSourceItem) -> None:
        self._row = row

    def one(self) -> RawSourceItem:
        return self._row


class _FakeSession:
    """Minimal AsyncSession stand-in with a spoofed dialect name."""

    def __init__(self, dialect_name: str, row: RawSourceItem | None = None) -> None:
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name=dialect_name))
        self._row = row
        self.statements: list[Any] = []
        self.added: list[Any] = []
        self.rowcount = 1
        self.execute_calls = 0
        self.scalars_calls = 0

    async def execute(self, stmt: Any) -> SimpleNamespace:
        self.execute_calls += 1
        self.statements.append(stmt)
        return SimpleNamespace(rowcount=self.rowcount)

    async def scalars(self, _stmt: Any) -> _FakeScalars:
        self.scalars_calls += 1
        assert self._row is not None
        return _FakeScalars(self._row)

    async def flush(self) -> None:
        return None

    def add(self, obj: Any) -> None:
        self.added.append(obj)


def _make_raw() -> RawSourceItem:
    return RawSourceItem(
        id="raw-1",
        tenant_id="tenant-1",
        preset_id=None,
        source_type="rss",
        source_url="https://example.com/article",
        title="Test Title",
        content_text="Body content.",
        published_at=None,
        source_metadata={},
        dedupe_key="deadbeef",
        knowledge_status="PENDING",
    )


class TestPostgresInsertBranch:
    async def test_postgres_branch_uses_dialect_insert_with_on_conflict(
        self, tmp_path: Path
    ) -> None:
        """The exact production traceback, replayed without Postgres.

        Old code: ``insert(RawSourceItem).values(...).on_conflict_do_nothing()``
        raises ``AttributeError`` before the session is ever touched.
        Fixed code: the executed statement is a Postgres-dialect insert
        rendering ``ON CONFLICT (dedupe_key) DO NOTHING``.
        """
        service = _make_service(tmp_path)
        raw = _make_raw()
        session = _FakeSession("postgresql", row=raw)
        emitted: list[Any] = []

        result = await service._persist_raw_item(session, _make_run(), _make_item(), emitted)

        assert result is raw
        assert session.execute_calls == 1
        stmt = session.statements[0]
        assert isinstance(stmt, PostgresInsert)
        compiled = str(stmt.compile(dialect=postgresql.dialect()))
        assert "ON CONFLICT (dedupe_key) DO NOTHING" in compiled
        assert len(emitted) == 1
        assert emitted[0].topic is EventTopic.RAW_INGESTED

    async def test_postgres_branch_duplicate_returns_none_without_reselect(
        self, tmp_path: Path
    ) -> None:
        """rowcount 0 (conflict, nothing inserted) skips the re-select."""
        service = _make_service(tmp_path)
        session = _FakeSession("postgresql", row=_make_raw())
        session.rowcount = 0
        emitted: list[Any] = []

        result = await service._persist_raw_item(session, _make_run(), _make_item(), emitted)

        assert result is None
        assert session.scalars_calls == 0
        assert emitted == []

    async def test_sqlite_branch_still_uses_orm_path(self, tmp_path: Path) -> None:
        """The SQLite branch is untouched: no statement is executed, the
        ORM-constructed row (carrying the dedupe key) is returned."""
        service = _make_service(tmp_path)
        session = _FakeSession("sqlite")
        emitted: list[Any] = []
        item = _make_item()

        result = await service._persist_raw_item(session, _make_run(), item, emitted)

        assert session.execute_calls == 0
        assert isinstance(result, RawSourceItem)
        assert result.dedupe_key == build_dedupe_key(item)
        assert len(emitted) == 1


def _setup_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str) -> None:
    monkeypatch.setenv(
        "PLANAGENT_DATABASE_URL",
        f"sqlite+aiosqlite:///{(tmp_path / name).resolve().as_posix()}",
    )
    monkeypatch.setenv("PLANAGENT_EVENT_BUS_BACKEND", "memory")
    monkeypatch.setenv("PLANAGENT_OPENAI_API_KEY", "")
    monkeypatch.setenv("PLANAGENT_OPENAI_PRIMARY_API_KEY", "")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    reset_settings_cache()
    reset_database_cache()


class TestSeedBigIntegerColumns:
    def test_simulation_run_seed_column_is_bigint(self) -> None:
        """Fails on the old model (Integer); the Postgres DDL follows the
        model type, so this pins the 64-bit column."""
        assert isinstance(SimulationRun.__table__.c.seed.type, BigInteger)

    def test_calibration_fit_seed_column_is_bigint(self) -> None:
        assert isinstance(CalibrationFitRecord.__table__.c.seed.type, BigInteger)

    def test_derived_sub_seed_is_63_bit(self) -> None:
        """The exact production value class: above the 32-bit range."""
        trial_seed = derive_sub_seed(7, "monte-carlo", "0")
        assert trial_seed > 2**31 - 1
        assert trial_seed < 2**63

    async def test_63bit_derived_seed_persists_on_simulation_run(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _setup_db(monkeypatch, tmp_path, "fixbatch3-run.db")
        trial_seed = derive_sub_seed(7, "monte-carlo", "0")
        await get_database().ensure_initialized()
        run = SimulationRun(
            id=generate_id(),
            domain_id="corporate",
            actor_template="default",
            tick_count=2,
            seed=trial_seed,
            configuration={},
            summary={},
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        async with get_database().session() as session:
            session.add(run)
            await session.commit()
        async with get_database().session() as session:
            stored = await session.get(SimulationRun, run.id)
            assert stored is not None
            assert stored.seed == trial_seed

    async def test_63bit_seed_persists_on_calibration_fit(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _setup_db(monkeypatch, tmp_path, "fixbatch3-fit.db")
        big_seed = 2**62 + 12345
        await get_database().ensure_initialized()
        record = CalibrationFitRecord(
            id=generate_id(),
            kind="rule_weights",
            domain_id="corporate",
            ridge_strength=1.0,
            seed=big_seed,
            bootstrap_draws=10,
            level=0.95,
            source_run_ids=[],
            n_observations=0,
            changes={},
            inputs_hash="sha256:fixbatch3",
            created_at=utc_now(),
        )
        async with get_database().session() as session:
            session.add(record)
            await session.commit()
        async with get_database().session() as session:
            stored = await session.get(CalibrationFitRecord, record.id)
            assert stored is not None
            assert stored.seed == big_seed
            rows = (
                await session.execute(
                    select(CalibrationFitRecord.id).where(
                        CalibrationFitRecord.seed == big_seed
                    )
                )
            ).scalars().all()
            assert rows == [record.id]
