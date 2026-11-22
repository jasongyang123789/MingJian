"""Seminar Sprint 19 service tests: the explicit audit-retention purge.

Fake ports only — no live LLM calls. Purge tests seed audit rows
directly (white-box) for precise seq/age control, except the
budget-preservation test, which runs a real scripted wave.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from planagent.db import get_database
from planagent.domain.models import (
    SeminarAuditEventRecord,
    SeminarBoardRecord,
    SeminarChairBriefRecord,
    SeminarFinalRecord,
    SeminarReportRecord,
    SeminarRoundRecord,
    generate_id,
)
from planagent.services.seminar.audit import AuditEventKind
from planagent.services.seminar.models import (
    AuditPurgeRequest,
    SeminarCreateRequest,
    SynthesizeRequest,
)
from planagent.services.seminar.service import SeminarServiceError
from tests.skill_fixtures import ScriptedSkillPort, TokenUsage
from tests.test_seminar_agent_chair import make_agent_request
from tests.test_seminar_api import FakePortFactory
from tests.test_seminar_service import (
    make_request,
    make_run,
    make_service,
    setup_db,
    stable_model_script,
)
from tests.test_seminar_synthesis_service import (
    chair_script,
    model_script,
    run_to_collecting,
    verdict_a,
    verdict_b,
)

def _no_floor_request(**kwargs) -> SeminarCreateRequest:
    request = make_request(**kwargs)
    return request.model_copy(
        update={"audit_retention_max_events": None, "audit_retention_max_age_days": None}
    )


async def _seed_events(
    seminar_id: str,
    specs: list[tuple[int, float, str]],
) -> None:
    """Insert audit rows with explicit seq/age/kind (white-box seeding).

    Ages anchor to real now: a fixed anchor goes stale and the
    older-than-days purge (cutoff from real utc_now()) starts
    deleting "0-day" events once the anchor ages past the cutoff
    (2026-11-22 time-bomb: the old fixed anchor was 2026-11-16,
    six days before the 5-day cutoff caught up with it).
    """
    base = datetime.now(UTC)
    async with get_database().session() as session:
        for seq, age_days, kind in specs:
            session.add(
                SeminarAuditEventRecord(
                    id=generate_id(),
                    seminar_id=seminar_id,
                    seq=seq,
                    model_id=None,
                    stage=None,
                    kind=kind,
                    detail={},
                    round_no=None,
                    stage_call_id=None,
                    created_at=base - timedelta(days=age_days),
                )
            )
        await session.commit()


async def _audit_rows(seminar_id: str) -> list[SeminarAuditEventRecord]:
    async with get_database().session() as session:
        result = await session.execute(
            select(SeminarAuditEventRecord)
            .where(SeminarAuditEventRecord.seminar_id == seminar_id)
            .order_by(SeminarAuditEventRecord.seq)
        )
        return list(result.scalars().all())


async def _count_rows(model: object, seminar_id: str) -> int:
    async with get_database().session() as session:
        result = await session.execute(
            select(model).where(model.seminar_id == seminar_id)  # type: ignore[attr-defined]
        )
        return len(list(result.scalars().all()))


async def _create_seminar(service, run_id: str, request) -> str:
    async with get_database().session() as session:
        created = await service.create_seminar(session, run_id, request)
    return created.seminar_id


# --- purge boundaries --------------------------------------------------------


@pytest.mark.asyncio
async def test_purge_exact_limit_is_noop_but_writes_summary(monkeypatch, tmp_path: Path) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    service = make_service(FakePortFactory({"chair-1": ScriptedSkillPort({})}))
    seminar_id = await _create_seminar(
        service, run.id, _no_floor_request(roster_ids=["model-a", "model-b"])
    )
    await _seed_events(
        seminar_id,
        [(1, 0, "stage_call_finished"), (2, 0, "stage_call_finished"), (3, 0, "report_written")],
    )
    async with get_database().session() as session:
        outcome = await service.purge_audit_events(
            session, seminar_id, AuditPurgeRequest(keep_last_n=3)
        )
    assert outcome.deleted_count == 0
    assert outcome.deleted_oldest_seq is None
    assert outcome.deleted_newest_seq is None
    assert outcome.remaining_count == 4
    rows = await _audit_rows(seminar_id)
    assert [row.seq for row in rows] == [1, 2, 3, 4]
    summary = rows[-1]
    assert summary.kind == AuditEventKind.RETENTION_PURGED
    assert summary.detail["deleted_count"] == 0
    assert summary.detail["keep_last_n"] == 3


@pytest.mark.asyncio
async def test_purge_over_limit_deletes_oldest_only(monkeypatch, tmp_path: Path) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    service = make_service(FakePortFactory({"chair-1": ScriptedSkillPort({})}))
    seminar_id = await _create_seminar(
        service, run.id, _no_floor_request(roster_ids=["model-a", "model-b"])
    )
    await _seed_events(seminar_id, [(seq, 0, "stage_call_finished") for seq in range(1, 6)])
    async with get_database().session() as session:
        outcome = await service.purge_audit_events(
            session, seminar_id, AuditPurgeRequest(keep_last_n=2)
        )
    assert outcome.deleted_count == 3
    assert outcome.deleted_oldest_seq == 1
    assert outcome.deleted_newest_seq == 3
    assert outcome.remaining_count == 3
    rows = await _audit_rows(seminar_id)
    assert [row.seq for row in rows] == [4, 5, 6]
    assert rows[-1].kind == AuditEventKind.RETENTION_PURGED
    assert rows[-1].detail["deleted_count"] == 3


@pytest.mark.asyncio
async def test_purge_older_than_days_deletes_old_events_only(monkeypatch, tmp_path: Path) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    service = make_service(FakePortFactory({"chair-1": ScriptedSkillPort({})}))
    seminar_id = await _create_seminar(
        service, run.id, _no_floor_request(roster_ids=["model-a", "model-b"])
    )
    await _seed_events(
        seminar_id,
        [
            (1, 10, "stage_call_finished"),
            (2, 10, "stage_call_finished"),
            (3, 0, "stage_call_finished"),
        ],
    )
    async with get_database().session() as session:
        outcome = await service.purge_audit_events(
            session, seminar_id, AuditPurgeRequest(older_than_days=5)
        )
    assert outcome.deleted_count == 2
    rows = await _audit_rows(seminar_id)
    assert [row.seq for row in rows] == [3, 4]
    assert rows[-1].detail["older_than_days"] == 5


@pytest.mark.asyncio
async def test_purge_full_wipe_seq_continues_monotonically(monkeypatch, tmp_path: Path) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    service = make_service(FakePortFactory({"chair-1": ScriptedSkillPort({})}))
    seminar_id = await _create_seminar(
        service, run.id, _no_floor_request(roster_ids=["model-a", "model-b"])
    )
    await _seed_events(seminar_id, [(seq, 0, "stage_call_finished") for seq in range(1, 4)])
    async with get_database().session() as session:
        first = await service.purge_audit_events(
            session, seminar_id, AuditPurgeRequest(keep_last_n=0)
        )
    assert first.deleted_count == 3
    assert first.remaining_count == 1
    rows = await _audit_rows(seminar_id)
    assert [row.seq for row in rows] == [4]
    # A second full wipe purges the first summary and continues the
    # seq — seqs never restart.
    async with get_database().session() as session:
        second = await service.purge_audit_events(
            session, seminar_id, AuditPurgeRequest(keep_last_n=0)
        )
    assert second.deleted_count == 1
    rows = await _audit_rows(seminar_id)
    assert [row.seq for row in rows] == [5]
    assert rows[0].kind == AuditEventKind.RETENTION_PURGED


# --- policy floor ------------------------------------------------------------


@pytest.mark.asyncio
async def test_purge_below_event_floor_refuses_and_deletes_nothing(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    service = make_service(FakePortFactory({"chair-1": ScriptedSkillPort({})}))
    # Default policy floor: 1000 events / 90 days.
    seminar_id = await _create_seminar(
        service, run.id, make_request(roster_ids=["model-a", "model-b"])
    )
    await _seed_events(seminar_id, [(1, 0, "stage_call_finished"), (2, 0, "stage_call_finished")])
    async with get_database().session() as session:
        with pytest.raises(SeminarServiceError) as exc_info:
            await service.purge_audit_events(session, seminar_id, AuditPurgeRequest(keep_last_n=5))
    assert exc_info.value.code == "seminar_retention_floor"
    rows = await _audit_rows(seminar_id)
    # Both seeded events survive; exactly one refusal event was added.
    assert [row.seq for row in rows] == [1, 2, 3]
    assert rows[-1].kind == AuditEventKind.REFUSAL
    assert rows[-1].detail["code"] == "seminar_retention_floor"


@pytest.mark.asyncio
async def test_purge_below_age_floor_refuses(monkeypatch, tmp_path: Path) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    service = make_service(FakePortFactory({"chair-1": ScriptedSkillPort({})}))
    seminar_id = await _create_seminar(
        service, run.id, make_request(roster_ids=["model-a", "model-b"])
    )
    async with get_database().session() as session:
        with pytest.raises(SeminarServiceError) as exc_info:
            await service.purge_audit_events(
                session, seminar_id, AuditPurgeRequest(older_than_days=10)
            )
    assert exc_info.value.code == "seminar_retention_floor"


@pytest.mark.asyncio
async def test_purge_at_floor_boundary_is_allowed(monkeypatch, tmp_path: Path) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    service = make_service(FakePortFactory({"chair-1": ScriptedSkillPort({})}))
    seminar_id = await _create_seminar(
        service, run.id, make_request(roster_ids=["model-a", "model-b"])
    )
    await _seed_events(seminar_id, [(1, 0, "stage_call_finished")])
    async with get_database().session() as session:
        outcome = await service.purge_audit_events(
            session, seminar_id, AuditPurgeRequest(keep_last_n=1000, older_than_days=90)
        )
    assert outcome.deleted_count == 0
    assert outcome.remaining_count == 2


def test_purge_request_requires_at_least_one_criterion() -> None:
    with pytest.raises(ValidationError, match="keep_last_n"):
        AuditPurgeRequest()


# --- isolation and non-interference ------------------------------------------


@pytest.mark.asyncio
async def test_purge_one_seminar_leaves_another_untouched(monkeypatch, tmp_path: Path) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    service = make_service(FakePortFactory({"chair-1": ScriptedSkillPort({})}))
    first = await _create_seminar(
        service, run.id, _no_floor_request(roster_ids=["model-a", "model-b"])
    )
    second = await _create_seminar(
        service, run.id, _no_floor_request(roster_ids=["model-a", "model-b"])
    )
    await _seed_events(first, [(seq, 0, "stage_call_finished") for seq in range(1, 4)])
    await _seed_events(second, [(seq, 0, "stage_call_finished") for seq in range(1, 4)])
    async with get_database().session() as session:
        await service.purge_audit_events(session, first, AuditPurgeRequest(keep_last_n=0))
    assert [row.seq for row in await _audit_rows(first)] == [4]
    assert [row.seq for row in await _audit_rows(second)] == [1, 2, 3]


@pytest.mark.asyncio
async def test_purge_leaves_reports_rounds_finals_and_briefs_untouched(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    # Model-chair seminar: rounds + finals + a report.
    ports = {
        "model-a": ScriptedSkillPort(model_script(2, verdict_a())),
        "model-b": ScriptedSkillPort(model_script(2, verdict_b())),
        "chair-1": ScriptedSkillPort(chair_script(copies=1)),
    }
    service = make_service(FakePortFactory(ports))
    model_seminar = await run_to_collecting(
        service,
        run.id,
        request=make_request(roster_ids=["model-a", "model-b"]).model_copy(
            update={"audit_retention_max_events": None, "audit_retention_max_age_days": None}
        ),
    )
    async with get_database().session() as session:
        await service.synthesize_seminar(session, model_seminar, SynthesizeRequest())
    # Agent-chair seminar: rounds + finals + a chair brief.
    agent_ports = {
        "model-a": ScriptedSkillPort(model_script(2, verdict_a())),
        "model-b": ScriptedSkillPort(model_script(2, verdict_b())),
    }
    agent_service = make_service(FakePortFactory(agent_ports))
    agent_seminar = await run_to_collecting(
        agent_service,
        run.id,
        request=make_agent_request(roster_ids=["model-a", "model-b"]).model_copy(
            update={
                "audit_retention_max_events": None,
                "audit_retention_max_age_days": None,
            }
        ),
    )
    async with get_database().session() as session:
        await agent_service.synthesize_seminar(session, agent_seminar, SynthesizeRequest())
    before = {
        "rounds": await _count_rows(SeminarRoundRecord, model_seminar),
        "finals": await _count_rows(SeminarFinalRecord, model_seminar),
        "reports": await _count_rows(SeminarReportRecord, model_seminar),
        "briefs": await _count_rows(SeminarChairBriefRecord, agent_seminar),
        "board": await _count_rows(SeminarBoardRecord, model_seminar),
    }
    assert before["rounds"] > 0 and before["finals"] == 2
    assert before["reports"] == 1 and before["briefs"] == 1
    async with get_database().session() as session:
        await service.purge_audit_events(session, model_seminar, AuditPurgeRequest(keep_last_n=0))
    async with get_database().session() as session:
        await agent_service.purge_audit_events(
            session, agent_seminar, AuditPurgeRequest(keep_last_n=0)
        )
    after = {
        "rounds": await _count_rows(SeminarRoundRecord, model_seminar),
        "finals": await _count_rows(SeminarFinalRecord, model_seminar),
        "reports": await _count_rows(SeminarReportRecord, model_seminar),
        "briefs": await _count_rows(SeminarChairBriefRecord, agent_seminar),
        "board": await _count_rows(SeminarBoardRecord, model_seminar),
    }
    assert after == before


# --- budget preservation and retention status --------------------------------


@pytest.mark.asyncio
async def test_budgets_and_diagnosis_hold_across_full_purge(monkeypatch, tmp_path: Path) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    usage = TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    script = stable_model_script(1)
    usage_script = {key: [usage for _ in queue] for key, queue in script.items()}
    ports = {
        "model-a": ScriptedSkillPort(stable_model_script(1), usage_script=usage_script),
        "model-b": ScriptedSkillPort(stable_model_script(1), usage_script=usage_script),
        "chair-1": ScriptedSkillPort({}),
    }
    service = make_service(FakePortFactory(ports))
    request = make_request(roster_ids=["model-a", "model-b"], max_rounds=1).model_copy(
        update={"audit_retention_max_events": None, "audit_retention_max_age_days": None}
    )
    seminar_id = await _create_seminar(service, run.id, request)
    async with get_database().session() as session:
        await service.advance_seminar(session, seminar_id)
    async with get_database().session() as session:
        detail_before = await service.get_seminar_detail(session, seminar_id)
    assert detail_before.budgets["tokens_used"] == 24 * 15
    assert detail_before.diagnosis["stage_calls"] == 24
    deleted_before = len(await _audit_rows(seminar_id))
    async with get_database().session() as session:
        outcome = await service.purge_audit_events(
            session, seminar_id, AuditPurgeRequest(keep_last_n=0)
        )
    assert outcome.deleted_count == deleted_before
    async with get_database().session() as session:
        detail_after = await service.get_seminar_detail(session, seminar_id)
    assert detail_after.budgets["tokens_used"] == 24 * 15
    assert detail_after.budgets["stage_calls_used"] == 24
    # Diagnosis reflects SURVIVING events only: after a full purge the
    # finished events are gone, so diagnosis stage_calls/total_tokens
    # drop to zero — while the budget ledger holds via roll-forward.
    assert detail_after.diagnosis["stage_calls"] == 0
    assert detail_after.diagnosis["total_tokens"] == 0
    assert detail_after.diagnosis["events_purged"] == deleted_before


@pytest.mark.asyncio
async def test_retention_status_in_detail_and_read_endpoint(monkeypatch, tmp_path: Path) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    service = make_service(FakePortFactory({"chair-1": ScriptedSkillPort({})}))
    request = make_request(roster_ids=["model-a", "model-b"]).model_copy(
        update={"audit_retention_max_events": 2, "audit_retention_max_age_days": 30}
    )
    seminar_id = await _create_seminar(service, run.id, request)
    await _seed_events(seminar_id, [(seq, 0, "stage_call_finished") for seq in range(1, 4)])
    async with get_database().session() as session:
        await service.purge_audit_events(session, seminar_id, AuditPurgeRequest(keep_last_n=2))
    async with get_database().session() as session:
        detail = await service.get_seminar_detail(session, seminar_id)
        retention = await service.get_audit_retention(session, seminar_id)
    assert detail.retention == {
        "seminar_id": seminar_id,
        "event_count": 3,
        "oldest_seq": 2,
        "newest_seq": 4,
        "max_events": 2,
        "max_age_days": 30,
    }
    assert retention.event_count == 3
    assert retention.oldest_seq == 2
    assert retention.newest_seq == 4


@pytest.mark.asyncio
async def test_purge_unknown_seminar_raises_lookup_error(monkeypatch, tmp_path: Path) -> None:
    setup_db(monkeypatch, tmp_path)
    await make_run()  # initializes the tables
    service = make_service(FakePortFactory({"chair-1": ScriptedSkillPort({})}))
    async with get_database().session() as session:
        with pytest.raises(LookupError):
            await service.purge_audit_events(
                session, "missing-seminar", AuditPurgeRequest(keep_last_n=1)
            )
        with pytest.raises(LookupError):
            await service.get_audit_retention(session, "missing-seminar")
