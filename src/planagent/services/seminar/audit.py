"""Seminar audit log (Sprint 18).

The append-only ``seminar_audit_events`` table is the seminar's
flight recorder: a reader with ONLY this log must be able to locate
exactly which step failed, which call, and why. Every event carries
the seminar id, a per-seminar monotonic ``seq``, a timestamp, the
model id (nullable — seminar-level events have none), the stage
(template id, nullable), an event kind, a JSON detail payload, and
correlation ids (``round_no`` and ``stage_call_id``).

Event kinds:

* ``stage_call_started`` / ``stage_call_finished`` — one pair per
  stage-call ATTEMPT (retries are separate attempts sharing one
  ``stage_call_id``). The finished event carries duration, token
  usage, attempts-so-far, the outcome (``ok`` or an
  :class:`~planagent.services.seminar.errors.ErrorKind` value), and
  the budget position after the call. A started event with no
  finished event means the call never returned.
* ``retry`` — a timeout retry was scheduled: attempt number,
  backoff, and the timeout that caused it.
* ``budget_exhausted`` — a budget check blocked a call: which
  budget, used/limit. Budget checks that PASS are not separate
  events; the budget position rides on every ``stage_call_finished``
  event instead, so the log stays readable.
* ``fallback`` — a chair stage failed and the deterministic path
  took over: stage, error kind, reason.
* ``queue_wait`` — a synthesize request waited for the per-seminar
  synthesize lock: wait duration in ms.
* ``status_transition`` — the seminar state machine moved: from/to
  and the trigger (advance / finalize / synthesize / rollback).
* ``chair_brief_produced`` — an agent-chair brief was written:
  brief version + hash.
* ``synthesis_submitted`` — an agent-chair submission was accepted:
  brief version, production path.
* ``report_written`` — a report version was stored: version,
  production paths, partial flag, hash.
* ``synthesis_failed`` — a synthesize/submission attempt failed
  after the status moved to synthesizing: the error kind + message,
  recorded alongside the rollback transition.
* ``refusal`` — a request was refused before any state change:
  the error code + message. Refusals write ONLY the audit event.

Events are collected in memory by :class:`AuditRecorder` during an
operation and flushed into the same transaction as the state change
they describe, so an event and its state change commit or roll back
together. Refusal events commit on their own (there is no other
state change to join).

``seq`` assignment happens at flush time (max existing seq + 1,
then consecutive), in the same order the recorder collected the
events. Flushes happen in the service's sequential persistence
sections — the same discipline as board ``seq`` assignment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from planagent.domain.models import SeminarAuditEventRecord, generate_id, utc_now


class AuditEventKind:
    """Audit event kind strings (stable; stored in the table)."""

    STAGE_CALL_STARTED = "stage_call_started"
    STAGE_CALL_FINISHED = "stage_call_finished"
    RETRY = "retry"
    BUDGET_EXHAUSTED = "budget_exhausted"
    FALLBACK = "fallback"
    QUEUE_WAIT = "queue_wait"
    STATUS_TRANSITION = "status_transition"
    CHAIR_BRIEF_PRODUCED = "chair_brief_produced"
    SYNTHESIS_SUBMITTED = "synthesis_submitted"
    REPORT_WRITTEN = "report_written"
    SYNTHESIS_FAILED = "synthesis_failed"
    REFUSAL = "refusal"

    ALL: frozenset[str] = frozenset(
        {
            STAGE_CALL_STARTED,
            STAGE_CALL_FINISHED,
            RETRY,
            BUDGET_EXHAUSTED,
            FALLBACK,
            QUEUE_WAIT,
            STATUS_TRANSITION,
            CHAIR_BRIEF_PRODUCED,
            SYNTHESIS_SUBMITTED,
            REPORT_WRITTEN,
            SYNTHESIS_FAILED,
            REFUSAL,
        }
    )


@dataclass
class PendingAuditEvent:
    """One collected-but-unflushed audit event."""

    model_id: str | None
    stage: str | None
    kind: str
    detail: dict[str, Any] = field(default_factory=dict)
    round_no: int | None = None
    stage_call_id: str | None = None


class AuditRecorder:
    """Collects audit events during one operation; flushes them in one
    transaction with the operation's state change."""

    def __init__(self) -> None:
        self._pending: list[PendingAuditEvent] = []

    @property
    def pending(self) -> list[PendingAuditEvent]:
        return list(self._pending)

    def record(
        self,
        kind: str,
        *,
        model_id: str | None = None,
        stage: str | None = None,
        detail: dict[str, Any] | None = None,
        round_no: int | None = None,
        stage_call_id: str | None = None,
    ) -> None:
        if kind not in AuditEventKind.ALL:
            raise ValueError(f"Unknown audit event kind {kind!r}.")
        self._pending.append(
            PendingAuditEvent(
                model_id=model_id,
                stage=stage,
                kind=kind,
                detail=dict(detail or {}),
                round_no=round_no,
                stage_call_id=stage_call_id,
            )
        )

    async def flush(self, session: AsyncSession, *, seminar_id: str) -> int:
        """Insert pending events with consecutive seqs; no commit.

        The caller commits (together with the state change the events
        describe). Returns the number of events flushed. Flushed
        events are dropped from the pending list.
        """
        if not self._pending:
            return 0
        result = await session.execute(
            select(func.max(SeminarAuditEventRecord.seq)).where(
                SeminarAuditEventRecord.seminar_id == seminar_id
            )
        )
        next_seq = int(result.scalar() or 0)
        count = 0
        for pending in self._pending:
            next_seq += 1
            session.add(
                SeminarAuditEventRecord(
                    id=generate_id(),
                    seminar_id=seminar_id,
                    seq=next_seq,
                    model_id=pending.model_id,
                    stage=pending.stage,
                    kind=pending.kind,
                    detail=pending.detail,
                    round_no=pending.round_no,
                    stage_call_id=pending.stage_call_id,
                    created_at=utc_now(),
                )
            )
            count += 1
        self._pending.clear()
        return count


class AuditEventRead(BaseModel):
    """One stored audit event, served in seq order."""

    model_config = ConfigDict(extra="forbid")

    id: str
    seminar_id: str
    seq: int
    model_id: str | None = None
    stage: str | None = None
    kind: str
    detail: dict[str, Any] = Field(default_factory=dict)
    round_no: int | None = None
    stage_call_id: str | None = None
    created_at: str


class DiagnosisSummary(BaseModel):
    """The GET-detail diagnosis summary, computed from audit events.

    Counts by error kind (from finished stage calls, budget
    exhaustions, fallbacks, and synthesis failures), total tokens and
    total duration (from finished stage calls that reported them),
    and the stage-call / retry totals. Seminars with no audit events
    (created before S18, or never run) report all zeros — never an
    error.
    """

    model_config = ConfigDict(extra="forbid")

    error_counts: dict[str, int] = Field(default_factory=dict)
    total_tokens: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_duration_ms: float = 0.0
    stage_calls: int = 0
    stage_call_attempts: int = 0
    retries: int = 0
    fallbacks: int = 0
    queue_waits: int = 0
    queue_wait_total_ms: float = 0.0
    refusals: int = 0


class BudgetRead(BaseModel):
    """Budget limits + usage + remaining, served on GET detail."""

    model_config = ConfigDict(extra="forbid")

    max_stage_calls: int
    stage_calls_used: int
    stage_calls_remaining: int
    max_tokens: int
    tokens_used: int
    tokens_remaining: int


def ledger_totals(events: list[dict[str, Any]]) -> tuple[int, int]:
    """Stage-call attempts + tokens consumed, from audit event dicts.

    Counts ``stage_call_finished`` events (one per attempt) and sums
    their reported total tokens. Events without usage contribute zero
    tokens — usage is only counted when a port reported it.
    """
    calls = 0
    tokens = 0
    for event in events:
        if event.get("kind") != AuditEventKind.STAGE_CALL_FINISHED:
            continue
        calls += 1
        detail = event.get("detail") or {}
        usage = detail.get("usage") or {}
        tokens += int(usage.get("total_tokens") or 0)
    return calls, tokens


def rollup_usage_by_model(events: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Per-model token rollups from audit event dicts."""
    rollup: dict[str, dict[str, int]] = {}
    for event in events:
        if event.get("kind") != AuditEventKind.STAGE_CALL_FINISHED:
            continue
        model_id = str(event.get("model_id") or "unknown")
        detail = event.get("detail") or {}
        usage = detail.get("usage") or {}
        entry = rollup.setdefault(
            model_id,
            {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "stage_calls": 0},
        )
        entry["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
        entry["completion_tokens"] += int(usage.get("completion_tokens") or 0)
        entry["total_tokens"] += int(usage.get("total_tokens") or 0)
        entry["stage_calls"] += 1
    return rollup


def compute_diagnosis(events: list[dict[str, Any]]) -> DiagnosisSummary:
    """Build the diagnosis summary from audit event dicts (pure)."""
    error_counts: dict[str, int] = {}
    total_tokens = 0
    total_prompt = 0
    total_completion = 0
    total_duration = 0.0
    stage_calls = 0
    attempts = 0
    retries = 0
    fallbacks = 0
    queue_waits = 0
    queue_wait_ms = 0.0
    refusals = 0
    for event in events:
        kind = event.get("kind")
        detail = event.get("detail") or {}
        if kind == AuditEventKind.STAGE_CALL_FINISHED:
            attempts += 1
            outcome = str(detail.get("outcome") or "")
            if outcome != "ok":
                error_counts[outcome] = error_counts.get(outcome, 0) + 1
            usage = detail.get("usage") or {}
            total_prompt += int(usage.get("prompt_tokens") or 0)
            total_completion += int(usage.get("completion_tokens") or 0)
            total_tokens += int(usage.get("total_tokens") or 0)
            total_duration += float(detail.get("duration_ms") or 0.0)
            if int(detail.get("attempt") or 1) == 1:
                stage_calls += 1
        elif kind == AuditEventKind.RETRY:
            retries += 1
        elif kind == AuditEventKind.BUDGET_EXHAUSTED:
            error_counts["budget_exhausted"] = error_counts.get("budget_exhausted", 0) + 1
        elif kind == AuditEventKind.FALLBACK:
            fallbacks += 1
            error_kind = str(detail.get("error_kind") or "")
            if error_kind:
                error_counts[error_kind] = error_counts.get(error_kind, 0) + 1
        elif kind == AuditEventKind.QUEUE_WAIT:
            queue_waits += 1
            queue_wait_ms += float(detail.get("wait_ms") or 0.0)
        elif kind == AuditEventKind.SYNTHESIS_FAILED:
            error_kind = str(detail.get("error_kind") or "")
            if error_kind:
                error_counts[error_kind] = error_counts.get(error_kind, 0) + 1
        elif kind == AuditEventKind.REFUSAL:
            refusals += 1
    return DiagnosisSummary(
        error_counts=error_counts,
        total_tokens=total_tokens,
        total_prompt_tokens=total_prompt,
        total_completion_tokens=total_completion,
        total_duration_ms=total_duration,
        stage_calls=stage_calls,
        stage_call_attempts=attempts,
        retries=retries,
        fallbacks=fallbacks,
        queue_waits=queue_waits,
        queue_wait_total_ms=queue_wait_ms,
        refusals=refusals,
    )


__all__ = [
    "AuditEventKind",
    "AuditEventRead",
    "AuditRecorder",
    "BudgetRead",
    "DiagnosisSummary",
    "PendingAuditEvent",
    "compute_diagnosis",
    "ledger_totals",
    "rollup_usage_by_model",
]
