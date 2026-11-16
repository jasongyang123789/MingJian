"""Audit recorder + diagnosis tests (Sprint 18).

Pins seq assignment (consecutive, continuing from the stored max),
the diagnosis rollups, and the ledger totals that seed budgets. The
flush tests use a real SQLite database via the shared setup helper.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from planagent.db import get_database
from planagent.domain.models import (
    SeminarAuditEventRecord,
    SeminarRecord,
    generate_id,
    utc_now,
)
from planagent.services.seminar.audit import (
    AuditEventKind,
    AuditRecorder,
    compute_diagnosis,
    ledger_totals,
    rollup_usage_by_model,
)
from tests.test_seminar_service import make_run, setup_db


def _finished(
    *,
    model_id: str = "model-a",
    attempt: int = 1,
    outcome: str = "ok",
    usage: dict | None = None,
    duration_ms: float = 10.0,
) -> dict:
    return {
        "kind": AuditEventKind.STAGE_CALL_FINISHED,
        "model_id": model_id,
        "stage": "seminar.reflect",
        "detail": {
            "attempt": attempt,
            "outcome": outcome,
            "usage": usage,
            "duration_ms": duration_ms,
        },
    }


def test_recorder_rejects_unknown_kind() -> None:
    recorder = AuditRecorder()
    with pytest.raises(ValueError, match="Unknown audit event kind"):
        recorder.record("not_a_kind")


def test_compute_diagnosis_counts_errors_tokens_and_durations() -> None:
    events = [
        _finished(usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}),
        _finished(outcome="timeout", duration_ms=25.0),
        _finished(attempt=2, outcome="ok", usage={"total_tokens": 7}, duration_ms=5.0),
        {"kind": AuditEventKind.RETRY, "model_id": "model-a", "detail": {}},
        {
            "kind": AuditEventKind.STAGE_FAILURE,
            "model_id": "model-a",
            "detail": {"error_kind": "timeout", "stage": "analysis"},
        },
        {
            "kind": AuditEventKind.FALLBACK,
            "model_id": "chair-1",
            "detail": {"error_kind": "contract"},
        },
        {
            "kind": AuditEventKind.QUEUE_WAIT,
            "model_id": None,
            "detail": {"wait_ms": 120.0},
        },
        {
            "kind": AuditEventKind.QUEUE_WAIT,
            "model_id": None,
            "detail": {"wait_ms": 30.0},
        },
        {"kind": AuditEventKind.REFUSAL, "model_id": None, "detail": {"code": "x"}},
        {
            "kind": AuditEventKind.BUDGET_EXHAUSTED,
            "model_id": "model-a",
            "detail": {"budget": "max_tokens"},
        },
        {
            "kind": AuditEventKind.SYNTHESIS_FAILED,
            "model_id": None,
            "detail": {"error_kind": "error"},
        },
    ]
    diagnosis = compute_diagnosis(events)
    # Error counts record FAILURES, not attempts: the failed first
    # attempt is visible via the retry count, and the budget event is
    # not double-counted (its stage failure carries the kind).
    assert diagnosis.error_counts == {
        "timeout": 1,
        "contract": 1,
        "error": 1,
    }
    assert diagnosis.total_tokens == 22
    assert diagnosis.total_prompt_tokens == 10
    assert diagnosis.total_completion_tokens == 5
    assert diagnosis.total_duration_ms == 40.0
    # stage_calls counts logical calls (first attempts only); attempts
    # counts every finished attempt.
    assert diagnosis.stage_calls == 2
    assert diagnosis.stage_call_attempts == 3
    assert diagnosis.retries == 1
    assert diagnosis.fallbacks == 1
    assert diagnosis.queue_waits == 2
    assert diagnosis.queue_wait_total_ms == 150.0
    assert diagnosis.refusals == 1


def test_compute_diagnosis_empty_log_is_all_zeros() -> None:
    diagnosis = compute_diagnosis([])
    assert diagnosis.error_counts == {}
    assert diagnosis.total_tokens == 0
    assert diagnosis.stage_calls == 0
    assert diagnosis.retries == 0


def test_ledger_totals_counts_finished_attempts_and_reported_tokens() -> None:
    events = [
        _finished(usage={"total_tokens": 15}),
        _finished(outcome="timeout", usage=None),
        {"kind": AuditEventKind.STAGE_CALL_STARTED, "model_id": "m", "detail": {}},
        {"kind": AuditEventKind.RETRY, "model_id": "m", "detail": {}},
    ]
    calls, tokens = ledger_totals(events)
    assert calls == 2
    assert tokens == 15


def test_rollup_usage_by_model() -> None:
    events = [
        _finished(model_id="model-a", usage={"prompt_tokens": 10, "total_tokens": 10}),
        _finished(model_id="model-a", usage={"prompt_tokens": 5, "total_tokens": 5}),
        _finished(model_id="model-b", usage={"total_tokens": 100}),
        _finished(model_id="model-b", usage=None),
    ]
    rollup = rollup_usage_by_model(events)
    assert rollup["model-a"] == {
        "prompt_tokens": 15,
        "completion_tokens": 0,
        "total_tokens": 15,
        "stage_calls": 2,
    }
    assert rollup["model-b"] == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 100,
        "stage_calls": 2,
    }


async def test_flush_assigns_consecutive_seqs_from_stored_max(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    seminar_id = generate_id()
    # Seed the seminar row + one event row directly so the flush must
    # continue from seq 7.
    await get_database().ensure_initialized()
    async with get_database().session() as session:
        session.add(
            SeminarRecord(
                id=seminar_id,
                run_id=run.id,
                topic="t",
                case_snapshot={},
                case_snapshot_hash="sha256:x",
                roster=[],
                config={},
                chair_model={},
                status="open",
                created_at=utc_now(),
                updated_at=utc_now(),
            )
        )
        session.add(
            SeminarAuditEventRecord(
                id=generate_id(),
                seminar_id=seminar_id,
                seq=7,
                model_id=None,
                stage=None,
                kind=AuditEventKind.STATUS_TRANSITION,
                detail={},
                round_no=None,
                stage_call_id=None,
            )
        )
        await session.commit()
    recorder = AuditRecorder()
    recorder.record(AuditEventKind.REFUSAL, detail={"code": "x"})
    recorder.record(AuditEventKind.REFUSAL, detail={"code": "y"})
    async with get_database().session() as session:
        flushed = await recorder.flush(session, seminar_id=seminar_id)
        await session.commit()
    assert flushed == 2
    assert recorder.pending == []
    async with get_database().session() as session:
        result = await session.execute(
            select(SeminarAuditEventRecord)
            .where(SeminarAuditEventRecord.seminar_id == seminar_id)
            .order_by(SeminarAuditEventRecord.seq)
        )
        rows = list(result.scalars().all())
    assert [row.seq for row in rows] == [7, 8, 9]
    assert rows[1].detail == {"code": "x"}
    assert rows[2].detail == {"code": "y"}


async def test_flush_with_no_pending_events_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    await make_run()
    recorder = AuditRecorder()
    async with get_database().session() as session:
        assert await recorder.flush(session, seminar_id=generate_id()) == 0
        result = await session.execute(select(SeminarAuditEventRecord))
        assert list(result.scalars().all()) == []
