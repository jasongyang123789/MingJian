"""Synthesize lock provider tests (Sprint 19).

Pins both providers against the same contract: acquire/release,
expiry takeover with fencing, holder-matched release, wait timeout,
and multi-connection serialization. The multi-connection test uses
THREADS with separate engines/connections against one SQLite file
(the brief's accepted form — separate processes were not needed:
NullPool gives each session a fresh connection, and threads prove
the cross-connection atomicity of the insert/takeover dance).
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from planagent.db import get_database
from planagent.domain.models import (
    SeminarRecord,
    SeminarSynthesizeLeaseRecord,
    generate_id,
    utc_now,
)
from planagent.services.seminar.locks import (
    LeaseLockProvider,
    LockTimeoutError,
    ProcessLockProvider,
)
from tests.test_seminar_service import setup_db


async def _make_seminar_row() -> str:
    """Insert a bare seminar row (the lease FK target)."""
    await get_database().ensure_initialized()
    seminar_id = generate_id()
    async with get_database().session() as session:
        session.add(
            SeminarRecord(
                id=seminar_id,
                run_id=generate_id(),
                topic="lock test",
                case_snapshot={},
                case_snapshot_hash="sha256:test",
                roster=[],
                config={},
                chair_model={},
                status="collecting",
                created_at=utc_now(),
                updated_at=utc_now(),
            )
        )
        await session.commit()
    return seminar_id


async def _lease_rows() -> list[SeminarSynthesizeLeaseRecord]:
    async with get_database().session() as session:
        result = await session.execute(select(SeminarSynthesizeLeaseRecord))
        return list(result.scalars().all())


def _factory():
    return get_database().session()


# --- process provider ------------------------------------------------------


async def test_process_provider_serializes_waiters(monkeypatch, tmp_path: Path) -> None:
    setup_db(monkeypatch, tmp_path)
    provider = ProcessLockProvider()
    entered: list[str] = []

    async def _hold(name: str, delay: float) -> None:
        async with provider.acquire("seminar-1") as acquisition:
            entered.append(name)
            if name == "second":
                assert acquisition.contended is True
                assert acquisition.wait_ms > 0
                assert acquisition.took_over_expired is False
            await asyncio.sleep(delay)

    await asyncio.gather(_hold("first", 0.1), _hold("second", 0.0))
    assert entered == ["first", "second"]


async def test_process_provider_uncontended_acquire_is_not_contended(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    provider = ProcessLockProvider()
    async with provider.acquire("seminar-1") as acquisition:
        assert acquisition.contended is False
        assert acquisition.fencing_token == 0


# --- lease provider: acquire / release --------------------------------------


async def test_lease_acquire_writes_a_row_and_release_deletes_it(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    seminar_id = await _make_seminar_row()
    provider = LeaseLockProvider(_factory, ttl_seconds=60.0)
    async with provider.acquire(seminar_id) as acquisition:
        assert acquisition.contended is False
        assert acquisition.fencing_token == 1
        assert acquisition.took_over_expired is False
        rows = await _lease_rows()
        assert len(rows) == 1
        assert rows[0].seminar_id == seminar_id
        assert rows[0].holder_id == acquisition.holder_id
        assert rows[0].fencing_token == 1
    assert await _lease_rows() == []


async def test_lease_second_acquirer_waits_then_acquires(monkeypatch, tmp_path: Path) -> None:
    setup_db(monkeypatch, tmp_path)
    seminar_id = await _make_seminar_row()
    first = LeaseLockProvider(_factory, ttl_seconds=60.0)
    second = LeaseLockProvider(_factory, ttl_seconds=60.0)
    acquired: list[str] = []

    async def _hold(
        provider: LeaseLockProvider, name: str, delay: float, start_delay: float = 0.0
    ) -> None:
        await asyncio.sleep(start_delay)
        async with provider.acquire(seminar_id) as acquisition:
            acquired.append(name)
            if name == "second":
                assert acquisition.contended is True
                assert acquisition.wait_ms > 0
                # Fresh insert after the first holder released: token 1.
                assert acquisition.fencing_token == 1
                assert acquisition.took_over_expired is False
            await asyncio.sleep(delay)

    await asyncio.gather(
        _hold(first, "first", 0.2),
        _hold(second, "second", 0.0, start_delay=0.05),
    )
    assert acquired == ["first", "second"]
    assert await _lease_rows() == []


async def test_lease_release_only_deletes_for_the_holding_holder(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    seminar_id = await _make_seminar_row()
    provider = LeaseLockProvider(_factory, ttl_seconds=60.0)
    attempt = await provider._try_acquire(seminar_id, "holder-a")
    assert attempt is not None
    await provider._release(seminar_id, "holder-b")  # wrong holder: no-op
    assert len(await _lease_rows()) == 1
    await provider._release(seminar_id, "holder-a")
    assert await _lease_rows() == []


async def test_lease_wait_timeout_raises_and_leaves_the_row_held(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    seminar_id = await _make_seminar_row()
    holder = LeaseLockProvider(_factory, ttl_seconds=60.0)
    waiter = LeaseLockProvider(_factory, ttl_seconds=60.0, wait_timeout_seconds=0.2)
    async with holder.acquire(seminar_id):
        with pytest.raises(LockTimeoutError, match="Timed out"):
            async with waiter.acquire(seminar_id):
                pass
        assert len(await _lease_rows()) == 1
    assert await _lease_rows() == []


async def test_lease_invalid_config_refuses(monkeypatch, tmp_path: Path) -> None:
    setup_db(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="ttl_seconds"):
        LeaseLockProvider(_factory, ttl_seconds=0)
    with pytest.raises(ValueError, match="wait_timeout_seconds"):
        LeaseLockProvider(_factory, wait_timeout_seconds=-1)


# --- lease provider: expiry takeover ----------------------------------------


async def test_lease_expiry_takeover_bumps_the_fencing_token(monkeypatch, tmp_path: Path) -> None:
    setup_db(monkeypatch, tmp_path)
    seminar_id = await _make_seminar_row()
    crashed = LeaseLockProvider(_factory, ttl_seconds=0.1)
    # Simulate a crash: acquire without ever releasing.
    attempt = await crashed._try_acquire(seminar_id, "crashed-holder")
    assert attempt is not None and attempt[0] == 1
    await asyncio.sleep(0.15)  # past the TTL
    taker = LeaseLockProvider(_factory, ttl_seconds=60.0)
    async with taker.acquire(seminar_id) as acquisition:
        assert acquisition.took_over_expired is True
        assert acquisition.previous_holder_id == "crashed-holder"
        assert acquisition.fencing_token == 2
        rows = await _lease_rows()
        assert len(rows) == 1
        assert rows[0].fencing_token == 2
    assert await _lease_rows() == []


async def test_lease_live_lease_is_never_taken_over(monkeypatch, tmp_path: Path) -> None:
    setup_db(monkeypatch, tmp_path)
    seminar_id = await _make_seminar_row()
    holder = LeaseLockProvider(_factory, ttl_seconds=60.0)
    attempt = await holder._try_acquire(seminar_id, "live-holder")
    assert attempt is not None
    taker = LeaseLockProvider(_factory, ttl_seconds=60.0, wait_timeout_seconds=0.2)
    with pytest.raises(LockTimeoutError):
        async with taker.acquire(seminar_id):
            pass
    rows = await _lease_rows()
    assert len(rows) == 1
    assert rows[0].holder_id == "live-holder"
    assert rows[0].fencing_token == 1
    await holder._release(seminar_id, "live-holder")


# --- multi-connection serialization (threads) --------------------------------


def test_lease_serializes_across_connections_in_threads(monkeypatch, tmp_path: Path) -> None:
    """Two threads, separate engines/connections, one SQLite file: the
    second acquirer must wait for the first holder's release — no
    overlap — proving the insert/takeover dance is atomic across
    connections."""
    setup_db(monkeypatch, tmp_path)
    db_path = (tmp_path / "seminar.db").resolve().as_posix()
    url = f"sqlite+aiosqlite:///{db_path}"

    async def _prepare() -> str:
        return await _make_seminar_row()

    seminar_id = asyncio.run(_prepare())
    events: list[tuple[str, float]] = []
    events_lock = threading.Lock()
    first_acquired = threading.Event()

    def _record(name: str) -> None:
        with events_lock:
            events.append((name, time.monotonic()))

    def _worker(name: str, hold_seconds: float, wait_for_start: bool) -> None:
        async def _run() -> None:
            engine = create_async_engine(url, poolclass=NullPool, connect_args={"timeout": 30})
            factory = async_sessionmaker(engine, expire_on_commit=False)
            provider = LeaseLockProvider(factory, ttl_seconds=60.0)
            if wait_for_start:
                await asyncio.to_thread(first_acquired.wait, 5.0)
            async with provider.acquire(seminar_id):
                _record(f"{name}-acquired")
                if name == "first":
                    first_acquired.set()
                await asyncio.sleep(hold_seconds)
                _record(f"{name}-releasing")
            _record(f"{name}-released")
            await engine.dispose()

        asyncio.run(_run())

    first = threading.Thread(target=_worker, args=("first", 0.3, False))
    second = threading.Thread(target=_worker, args=("second", 0.0, True))
    first.start()
    second.start()
    first.join(timeout=30)
    second.join(timeout=30)
    assert not first.is_alive() and not second.is_alive()

    stamps = dict(events)
    assert stamps["first-acquired"] < stamps["second-acquired"]
    # No overlap: the second acquirer only proceeds after release.
    assert stamps["second-acquired"] >= stamps["first-released"]
    assert stamps["second-acquired"] - stamps["first-released"] < 1.0

    async def _check_empty() -> list[SeminarSynthesizeLeaseRecord]:
        return await _lease_rows()

    assert asyncio.run(_check_empty()) == []
