"""Seminar Sprint 19 service tests: the distributed synthesize lock
providers and the similarity-provider config switch.

Fake ports only — no live LLM calls. The lease provider tests run
against the same SQLite file the service uses, with lease sessions
from the shared database (NullPool: a fresh connection per session),
mirroring the multi-connection unit tests.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from planagent.config import get_settings
from planagent.db import get_database
from planagent.domain.models import (
    SeminarReportRecord,
    SeminarSynthesizeLeaseRecord,
    utc_now,
)
from planagent.services.seminar.models import SynthesizeRequest
from planagent.services.seminar.service import SeminarService, SeminarServiceError
from planagent.services.seminar.similarity import StaticVectorProvider
from tests.skill_fixtures import ScriptedSkillPort
from tests.test_seminar_agent_chair import make_agent_request
from tests.test_seminar_api import FakePortFactory
from tests.test_seminar_hardening import SlowPort, audit_events
from tests.test_seminar_service import make_request, make_run, setup_db
from tests.test_seminar_synthesis_service import (
    chair_script,
    model_script,
    run_to_collecting,
    verdict_a,
    verdict_b,
)


def _lease_service(factory: FakePortFactory, **kwargs) -> SeminarService:
    return SeminarService(
        get_settings(),
        port_factory=factory,
        lease_session_factory=get_database().session,
        **kwargs,
    )


async def _lease_rows(seminar_id: str) -> list[SeminarSynthesizeLeaseRecord]:
    async with get_database().session() as session:
        result = await session.execute(
            select(SeminarSynthesizeLeaseRecord).where(
                SeminarSynthesizeLeaseRecord.seminar_id == seminar_id
            )
        )
        return list(result.scalars().all())


async def _seed_lease(
    seminar_id: str, *, holder_id: str, fencing_token: int, expires_in: timedelta
) -> None:
    async with get_database().session() as session:
        session.add(
            SeminarSynthesizeLeaseRecord(
                seminar_id=seminar_id,
                holder_id=holder_id,
                fencing_token=fencing_token,
                expires_at=utc_now() + expires_in,
                acquired_at=utc_now(),
                holder_label="seeded-test-holder",
            )
        )
        await session.commit()


# --- queue contract: both providers ------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("lock_provider", ["process", "lease"])
async def test_both_lock_providers_serialize_into_versions_1_and_2(
    monkeypatch, tmp_path: Path, lock_provider: str
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    chair_port = SlowPort(ScriptedSkillPort(chair_script(copies=2)), delay=0.2)
    ports = {
        "model-a": ScriptedSkillPort(model_script(2, verdict_a())),
        "model-b": ScriptedSkillPort(model_script(2, verdict_b())),
        "chair-1": chair_port,
    }
    service = _lease_service(FakePortFactory(ports))  # type: ignore[arg-type]
    request = make_request(roster_ids=["model-a", "model-b"], max_rounds=2).model_copy(
        update={"synthesize_lock_provider": lock_provider}
    )
    seminar_id = await run_to_collecting(service, run.id, request)

    async def _synthesize() -> SynthesizeRequest:
        async with get_database().session() as session:
            return await service.synthesize_seminar(session, seminar_id, SynthesizeRequest())

    first, second = await asyncio.gather(_synthesize(), _synthesize())
    assert {first.version, second.version} == {1, 2}
    assert first.report_hash == second.report_hash
    waits = await audit_events(seminar_id, kind="queue_wait")
    assert len(waits) == 1
    assert waits[0]["detail"]["wait_ms"] > 0
    assert waits[0]["detail"]["trigger"] == "synthesize"
    async with get_database().session() as session:
        detail = await service.get_seminar_detail(session, seminar_id)
    assert detail.status == "reported"
    assert len(detail.reports) == 2
    # The lease provider leaves no rows behind after release.
    assert await _lease_rows(seminar_id) == []


# --- lease takeover and timeout ----------------------------------------------


@pytest.mark.asyncio
async def test_expired_lease_is_taken_over_and_audited(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    ports = {
        "model-a": ScriptedSkillPort(model_script(2, verdict_a())),
        "model-b": ScriptedSkillPort(model_script(2, verdict_b())),
        "chair-1": ScriptedSkillPort(chair_script(copies=1)),
    }
    service = _lease_service(FakePortFactory(ports))
    request = make_request(roster_ids=["model-a", "model-b"], max_rounds=2).model_copy(
        update={"synthesize_lock_provider": "lease"}
    )
    seminar_id = await run_to_collecting(service, run.id, request)
    # A crashed holder's lease, long expired.
    await _seed_lease(
        seminar_id,
        holder_id="dead-holder",
        fencing_token=3,
        expires_in=timedelta(seconds=-60),
    )
    async with get_database().session() as session:
        result = await service.synthesize_seminar(session, seminar_id, SynthesizeRequest())
    assert result.version == 1
    takeovers = await audit_events(seminar_id, kind="lease_takeover")
    assert len(takeovers) == 1
    assert takeovers[0]["detail"]["previous_holder_id"] == "dead-holder"
    assert takeovers[0]["detail"]["fencing_token"] == 4
    assert takeovers[0]["detail"]["trigger"] == "synthesize"
    assert await _lease_rows(seminar_id) == []


@pytest.mark.asyncio
async def test_lease_wait_timeout_refuses_and_records_a_refusal(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    ports = {
        "model-a": ScriptedSkillPort(model_script(2, verdict_a())),
        "model-b": ScriptedSkillPort(model_script(2, verdict_b())),
        "chair-1": ScriptedSkillPort(chair_script(copies=1)),
    }
    service = _lease_service(FakePortFactory(ports))
    request = make_request(roster_ids=["model-a", "model-b"], max_rounds=2).model_copy(
        update={
            "synthesize_lock_provider": "lease",
            "lock_wait_timeout_seconds": 0.2,
        }
    )
    seminar_id = await run_to_collecting(service, run.id, request)
    # A live holder that will not release within the wait timeout.
    await _seed_lease(
        seminar_id,
        holder_id="live-holder",
        fencing_token=1,
        expires_in=timedelta(seconds=600),
    )
    async with get_database().session() as session:
        with pytest.raises(SeminarServiceError) as exc_info:
            await service.synthesize_seminar(session, seminar_id, SynthesizeRequest())
    assert exc_info.value.code == "seminar_synthesize_lock_timeout"
    refusals = await audit_events(seminar_id, kind="refusal")
    assert len(refusals) == 1
    assert refusals[0]["detail"]["code"] == "seminar_synthesize_lock_timeout"
    async with get_database().session() as session:
        result = await session.execute(
            select(SeminarReportRecord).where(SeminarReportRecord.seminar_id == seminar_id)
        )
        assert list(result.scalars().all()) == []
    # The other holder's lease is untouched.
    rows = await _lease_rows(seminar_id)
    assert len(rows) == 1
    assert rows[0].holder_id == "live-holder"


# --- similarity provider switch ----------------------------------------------


@pytest.mark.asyncio
async def test_embedding_similarity_without_provider_refuses_at_creation(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    service = SeminarService(
        get_settings(), port_factory=FakePortFactory({"chair-1": ScriptedSkillPort({})})
    )
    request = make_request(roster_ids=["model-a", "model-b"]).model_copy(
        update={"similarity_provider": "embedding"}
    )
    async with get_database().session() as session:
        with pytest.raises(SeminarServiceError) as exc_info:
            await service.create_seminar(session, run.id, request)
    assert exc_info.value.code == "seminar_similarity_provider_missing"


@pytest.mark.asyncio
async def test_embedding_similarity_with_provider_records_provider_in_prepass(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    ports = {
        "model-a": ScriptedSkillPort(model_script(2, verdict_a())),
        "model-b": ScriptedSkillPort(model_script(2, verdict_b())),
    }
    service = _lease_service(
        FakePortFactory(ports),
        vector_provider=StaticVectorProvider({}),
    )
    request = make_agent_request(roster_ids=["model-a", "model-b"]).model_copy(
        update={"similarity_provider": "embedding"}
    )
    seminar_id = await run_to_collecting(service, run.id, request)
    async with get_database().session() as session:
        brief = await service.synthesize_seminar(session, seminar_id, SynthesizeRequest())
    assert brief.prepass["similarity_provider"] == "embedding"


@pytest.mark.asyncio
async def test_jaccard_default_records_jaccard_provider_in_prepass(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    ports = {
        "model-a": ScriptedSkillPort(model_script(2, verdict_a())),
        "model-b": ScriptedSkillPort(model_script(2, verdict_b())),
    }
    service = _lease_service(
        FakePortFactory(ports),
        vector_provider=StaticVectorProvider({}),
    )
    seminar_id = await run_to_collecting(
        service, run.id, make_agent_request(roster_ids=["model-a", "model-b"])
    )
    async with get_database().session() as session:
        brief = await service.synthesize_seminar(session, seminar_id, SynthesizeRequest())
    assert brief.prepass["similarity_provider"] == "jaccard"
