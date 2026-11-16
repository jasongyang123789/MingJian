"""Synthesize lock providers (Sprint 19).

Concurrent synthesize / chair-submission requests to one seminar
serialize instead of refusing (Sprint 18). The lock is an
abstraction with two providers, selected per seminar by config:

* :class:`ProcessLockProvider` — the Sprint 18 behavior: one
  ``asyncio.Lock`` per seminar id, held by the service instance.
  Default. Correct for the single-process deployment; locks are
  never deleted (Sprint 18 decision 11).
* :class:`LeaseLockProvider` — a distributed lease in the
  ``seminar_synthesize_leases`` table (migration 0040): at most one
  row per seminar, acquired with an atomic insert-or-takeover
  dance, released by a holder-matched delete, with expiry as the
  crash backstop. The SQL is portable (plain insert / conditional
  update / conditional delete) — the same code path runs on SQLite
  and Postgres. Waiters poll with backoff up to a configurable wait
  timeout; a crashed holder's expired lease is taken over by the
  next acquirer, and the takeover is reported to the caller so the
  service can audit it.

Both providers satisfy the same queue contract: waiters serialize
and proceed on freshly re-read state as new versions. The
``synthesizing`` stuck-state check in the service is unchanged and
is the second line of defense if a lease holder is taken over
mid-synthesis (its TTL was too short): the taker observes
``synthesizing`` while holding the lock and refuses as stuck,
while the original holder's release is a safe no-op (holder
mismatch).

No renewal exists in Sprint 19: the TTL must cover a full
synthesis (chair stages included). The default (600s) covers the
slowest observed live synthesis (~235s for 11 stages) with margin.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

from sqlalchemy import delete, update
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from planagent.domain.models import SeminarSynthesizeLeaseRecord, generate_id, utc_now

logger = logging.getLogger(__name__)

#: Default lease time-to-live: long enough for a full synthesis
#: (chair stages included) with margin over the slowest observed
#: live synthesis (~235s). No renewal in Sprint 19.
DEFAULT_LEASE_TTL_SECONDS = 600.0

#: Default maximum time a lease waiter polls before giving up.
DEFAULT_LOCK_WAIT_TIMEOUT_SECONDS = 120.0

#: Poll backoff for lease waiters: starts here, doubles to the cap.
_LEASE_POLL_START_SECONDS = 0.05
_LEASE_POLL_MAX_SECONDS = 0.25


class LockTimeoutError(TimeoutError):
    """A lease waiter gave up: the lock stayed held past the wait timeout."""


@dataclass(frozen=True)
class LockAcquisition:
    """What an acquire observed, for the caller to audit.

    ``contended`` is true when the acquirer waited at all;
    ``took_over_expired`` is true when the acquisition took over a
    crashed holder's expired lease (lease provider only).
    ``fencing_token`` orders successive holders of a contended lease
    row (0 for the process provider, which has no fencing).
    """

    wait_ms: float
    contended: bool
    took_over_expired: bool
    previous_holder_id: str | None
    fencing_token: int
    holder_id: str


class SynthesizeLockProvider(Protocol):
    """Serializes synthesize/submission requests for one seminar."""

    @asynccontextmanager
    async def acquire(self, seminar_id: str) -> AsyncIterator[LockAcquisition]:
        """Hold the seminar's synthesize lock for the block."""
        ...


class ProcessLockProvider:
    """Per-process asyncio locks (Sprint 18 behavior, unchanged).

    One lock per seminar id, kept for the provider's lifetime —
    deleting a lock after use would race a waiter.
    """

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    @asynccontextmanager
    async def acquire(self, seminar_id: str) -> AsyncIterator[LockAcquisition]:
        lock = self._locks.get(seminar_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[seminar_id] = lock
        contended = lock.locked()
        waited_since = time.monotonic()
        await lock.acquire()
        try:
            yield LockAcquisition(
                wait_ms=(time.monotonic() - waited_since) * 1000.0,
                contended=contended,
                took_over_expired=False,
                previous_holder_id=None,
                fencing_token=0,
                holder_id="process",
            )
        finally:
            lock.release()


def _as_aware(moment: datetime) -> datetime:
    """Treat a naive timestamp read from the DB as UTC.

    SQLite returns datetimes without tzinfo; Postgres returns aware
    ones. All writers store UTC, so naive reads are UTC.
    """
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


class LeaseLockProvider:
    """Distributed leases in ``seminar_synthesize_leases``.

    ``session_factory`` must produce short-lived sessions (one per
    lease operation) against the shared database — lease
    transactions commit independently of the caller's session.
    """

    def __init__(
        self,
        session_factory: Callable[[], AsyncSession],
        *,
        ttl_seconds: float = DEFAULT_LEASE_TTL_SECONDS,
        wait_timeout_seconds: float = DEFAULT_LOCK_WAIT_TIMEOUT_SECONDS,
        holder_label: str | None = None,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError(f"ttl_seconds must be positive; got {ttl_seconds}.")
        if wait_timeout_seconds <= 0:
            raise ValueError(
                f"wait_timeout_seconds must be positive; got {wait_timeout_seconds}."
            )
        self._session_factory = session_factory
        self._ttl_seconds = ttl_seconds
        self._wait_timeout_seconds = wait_timeout_seconds
        self._holder_label = holder_label or f"pid:{os.getpid()}"

    @asynccontextmanager
    async def acquire(self, seminar_id: str) -> AsyncIterator[LockAcquisition]:
        holder_id = generate_id()
        started = time.monotonic()
        poll_seconds = _LEASE_POLL_START_SECONDS
        contended = False
        while True:
            attempt = await self._try_acquire(seminar_id, holder_id)
            if attempt is not None:
                fencing_token, took_over, previous_holder_id = attempt
                try:
                    yield LockAcquisition(
                        wait_ms=(time.monotonic() - started) * 1000.0,
                        contended=contended,
                        took_over_expired=took_over,
                        previous_holder_id=previous_holder_id,
                        fencing_token=fencing_token,
                        holder_id=holder_id,
                    )
                finally:
                    await self._release(seminar_id, holder_id)
                return
            contended = True
            elapsed = time.monotonic() - started
            if elapsed >= self._wait_timeout_seconds:
                raise LockTimeoutError(
                    f"Timed out after {self._wait_timeout_seconds:g}s waiting for "
                    f"the synthesize lock on seminar {seminar_id}."
                )
            await asyncio.sleep(min(poll_seconds, self._wait_timeout_seconds - elapsed))
            poll_seconds = min(poll_seconds * 2, _LEASE_POLL_MAX_SECONDS)

    async def _try_acquire(
        self, seminar_id: str, holder_id: str
    ) -> tuple[int, bool, str | None] | None:
        """One acquisition attempt: fresh insert, else expiry takeover.

        Returns ``(fencing_token, took_over, previous_holder_id)`` on
        success, ``None`` when the lease is live-held (caller polls).
        Each attempt is its own transaction. The expiry check runs in
        Python (no DB-side datetime comparison — SQLite and Postgres
        render bound datetimes differently); the takeover UPDATE is
        conditional on the observed holder id, which is sufficient
        for atomicity because holders never extend a lease and
        holder ids are unique per acquisition.
        """
        now = utc_now()
        expires_at = now + timedelta(seconds=self._ttl_seconds)
        async with self._session_factory() as session:
            session.add(
                SeminarSynthesizeLeaseRecord(
                    seminar_id=seminar_id,
                    holder_id=holder_id,
                    fencing_token=1,
                    expires_at=expires_at,
                    acquired_at=now,
                    holder_label=self._holder_label,
                )
            )
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
            except OperationalError:
                # SQLite "database is locked" under writer contention:
                # transient, like a held lease — the caller polls.
                await session.rollback()
                return None
            else:
                return (1, False, None)
            row = await session.get(SeminarSynthesizeLeaseRecord, seminar_id)
            if row is None:
                return None  # released between our attempts; retry
            if _as_aware(row.expires_at) > now:
                return None  # live lease held
            previous_holder_id = row.holder_id
            fencing_token = row.fencing_token + 1
            result = await session.execute(
                update(SeminarSynthesizeLeaseRecord)
                .where(SeminarSynthesizeLeaseRecord.seminar_id == seminar_id)
                .where(SeminarSynthesizeLeaseRecord.holder_id == previous_holder_id)
                .values(
                    holder_id=holder_id,
                    fencing_token=fencing_token,
                    expires_at=expires_at,
                    acquired_at=now,
                    holder_label=self._holder_label,
                )
            )
            try:
                await session.commit()
            except OperationalError:
                await session.rollback()
                return None
            if result.rowcount == 1:
                return (fencing_token, True, previous_holder_id)
            return None  # another acquirer won the race; retry

    async def _release(self, seminar_id: str, holder_id: str) -> None:
        """Delete the lease row only if this holder still holds it.

        Best-effort: if the delete fails or matches nothing (the
        lease expired and was taken over), the TTL is the backstop
        and the row harms nothing.
        """
        try:
            async with self._session_factory() as session:
                await session.execute(
                    delete(SeminarSynthesizeLeaseRecord)
                    .where(SeminarSynthesizeLeaseRecord.seminar_id == seminar_id)
                    .where(SeminarSynthesizeLeaseRecord.holder_id == holder_id)
                )
                await session.commit()
        except SQLAlchemyError:
            logger.debug(
                "Lease release failed for seminar %s (TTL backstop applies).",
                seminar_id,
                exc_info=True,
            )


__all__ = [
    "DEFAULT_LEASE_TTL_SECONDS",
    "DEFAULT_LOCK_WAIT_TIMEOUT_SECONDS",
    "LeaseLockProvider",
    "LockAcquisition",
    "LockTimeoutError",
    "ProcessLockProvider",
    "SynthesizeLockProvider",
]
