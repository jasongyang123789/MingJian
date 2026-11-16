"""Agent-chair mode tests (Sprint 18, Ho directive 2026-11-16).

Covers the agent-chair flow end to end at the service level: creation
without a chair liveness check, chair-brief production + versioning,
submission validation (same contracts, same merge-map coverage rule),
report writing with agent provenance, the deterministic-fallback
flag, and every refusal. Fake ports only — no live LLM calls.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
from sqlalchemy import select

from planagent.db import get_database
from planagent.domain.models import (
    SeminarAuditEventRecord,
    SeminarChairBriefRecord,
)
from planagent.services.seminar.models import (
    AGENT_CHAIR_MODEL_ID,
    ChairBriefRead,
    ChairSynthesisRequest,
    ModelPortConfig,
    RosterEntry,
    SeminarCreateRequest,
    SynthesizeRead,
    SynthesizeRequest,
)
from planagent.services.seminar.service import SeminarServiceError
from tests.skill_fixtures import ScriptedSkillPort
from tests.test_seminar_service import (
    FakePortFactory,
    make_request,
    make_run,
    make_service,
    setup_db,
)
from tests.test_seminar_synthesis_service import (
    chair_script,
    cluster_payload,
    model_script,
    report_rows,
    run_to_collecting,
    seminar_status,
    synthesis_payload,
    verdict_a,
    verdict_b,
)

TOPIC = "Should we launch the AI customer-service line?"


def make_agent_request(
    *,
    roster_ids: list[str],
    max_rounds: int = 2,
    chair_id: str = "chair-1",
) -> SeminarCreateRequest:
    return SeminarCreateRequest(
        topic=TOPIC,
        decision_question=TOPIC,
        options=["Phased rollout", "Full launch"],
        roster=[RosterEntry(model_id=model_id) for model_id in roster_ids],
        pipeline="strategy_team",
        mode="standard",
        max_rounds=max_rounds,
        chair_model=ModelPortConfig(model_id=chair_id),
        chair_mode="agent",
    )


async def brief_rows() -> list[SeminarChairBriefRecord]:
    async with get_database().session() as session:
        result = await session.execute(
            select(SeminarChairBriefRecord).order_by(SeminarChairBriefRecord.version)
        )
        return list(result.scalars().all())


async def audit_kinds(seminar_id: str) -> list[str]:
    async with get_database().session() as session:
        result = await session.execute(
            select(SeminarAuditEventRecord)
            .where(SeminarAuditEventRecord.seminar_id == seminar_id)
            .order_by(SeminarAuditEventRecord.seq)
        )
        return [row.kind for row in result.scalars().all()]


async def run_agent_to_collecting(service, run_id: str, rounds: int = 2) -> str:
    return await run_to_collecting(
        service,
        run_id,
        make_agent_request(roster_ids=["model-a", "model-b"], max_rounds=rounds),
        rounds=rounds,
    )


def agent_ports() -> dict[str, ScriptedSkillPort]:
    return {
        "model-a": ScriptedSkillPort(model_script(2, verdict_a())),
        "model-b": ScriptedSkillPort(model_script(2, verdict_b())),
    }


# --- creation ------------------------------------------------------------


async def test_agent_mode_creation_skips_chair_liveness_check(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    # No chair port in the factory at all: creation must not consult
    # it in agent mode.
    service = make_service(FakePortFactory(agent_ports()))
    async with get_database().session() as session:
        created = await service.create_seminar(
            session, run.id, make_agent_request(roster_ids=["model-a", "model-b"])
        )
    assert created.status == "open"
    assert created.config.chair_mode == "agent"
    assert created.config.chair_participates is False


async def test_model_mode_creation_still_checks_chair_liveness(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    dead_chair = ScriptedSkillPort({}, available=False)
    ports = dict(agent_ports())
    ports["chair-1"] = dead_chair
    service = make_service(FakePortFactory(ports))
    from planagent.services.seminar.service import SeminarChairUnavailable

    async with get_database().session() as session:
        with pytest.raises(SeminarChairUnavailable):
            await service.create_seminar(
                session, run.id, make_request(roster_ids=["model-a", "model-b"])
            )


# --- brief production ------------------------------------------------------


async def test_synthesize_in_agent_mode_produces_a_stored_brief(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    service = make_service(FakePortFactory(agent_ports()))
    seminar_id = await run_agent_to_collecting(service, run.id)
    async with get_database().session() as session:
        result = await service.synthesize_seminar(session, seminar_id, SynthesizeRequest())
    assert isinstance(result, ChairBriefRead)
    assert result.brief_version == 1
    assert result.brief_hash.startswith("sha256:")
    assert result.chair_model_id == AGENT_CHAIR_MODEL_ID
    assert result.chair_mode == "agent"
    assert result.finals_used == 2
    assert result.roster_size == 2
    assert result.partial is False
    assert result.prepass["item_count"] == 11
    assert result.prepass["exact_duplicate_groups"] == 3
    assert "near_duplicate_groups" in result.prepass
    assert result.deterministic_clusters["production"] == "deterministic_prepass"
    assert result.disagreements == []
    assert result.computed_metrics["finals_used"] == 2
    assert [entry["model_id"] for entry in result.verdicts] == ["model-a", "model-b"]
    assert "agent chair" in result.participation_note
    assert result.absent_models == []
    assert result.submit_endpoint == f"POST /seminars/{seminar_id}/chair-synthesis"
    # No status change, no report row, one stored brief row.
    assert await seminar_status(seminar_id) == "collecting"
    assert await report_rows() == []
    rows = await brief_rows()
    assert len(rows) == 1
    assert rows[0].version == 1
    assert rows[0].brief_hash == result.brief_hash
    assert "chair_brief_produced" in await audit_kinds(seminar_id)


async def test_re_synthesize_writes_a_new_brief_version_with_the_same_hash(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    service = make_service(FakePortFactory(agent_ports()))
    seminar_id = await run_agent_to_collecting(service, run.id)
    async with get_database().session() as session:
        first = await service.synthesize_seminar(session, seminar_id, SynthesizeRequest())
        second = await service.synthesize_seminar(session, seminar_id, SynthesizeRequest())
    assert isinstance(first, ChairBriefRead) and isinstance(second, ChairBriefRead)
    assert first.brief_version == 1
    assert second.brief_version == 2
    assert first.brief_hash == second.brief_hash
    assert len(await brief_rows()) == 2
    assert await report_rows() == []


async def test_brief_refusals_match_synthesize_thresholds(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    service = make_service(FakePortFactory(agent_ports()))
    async with get_database().session() as session:
        created = await service.create_seminar(
            session, run.id, make_agent_request(roster_ids=["model-a", "model-b"])
        )
    async with get_database().session() as session:
        with pytest.raises(SeminarServiceError) as excinfo:
            await service.synthesize_seminar(session, created.seminar_id, SynthesizeRequest())
    assert excinfo.value.code == "seminar_not_ready"
    assert await brief_rows() == []


# --- submission ------------------------------------------------------------


async def _briefed_seminar(service, run_id: str) -> tuple[str, ChairBriefRead]:
    seminar_id = await run_agent_to_collecting(service, run_id)
    async with get_database().session() as session:
        brief = await service.synthesize_seminar(session, seminar_id, SynthesizeRequest())
    assert isinstance(brief, ChairBriefRead)
    return seminar_id, brief


async def test_submission_writes_agent_chair_report(monkeypatch, tmp_path: Path) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    service = make_service(FakePortFactory(agent_ports()))
    seminar_id, brief = await _briefed_seminar(service, run.id)
    async with get_database().session() as session:
        read = await service.submit_chair_synthesis(
            session,
            seminar_id,
            ChairSynthesisRequest(
                clusters=cluster_payload(), synthesis=synthesis_payload()
            ),
        )
    assert isinstance(read, SynthesizeRead)
    assert read.version == 1
    assert read.production_path == "agent_chair"
    assert read.cluster_production == "agent_chair"
    assert read.chair_model_id == AGENT_CHAIR_MODEL_ID
    assert read.partial is False
    assert read.agreement_level == "low"
    assert read.status == "reported"
    assert await seminar_status(seminar_id) == "reported"
    rows = await report_rows()
    assert len(rows) == 1
    assert rows[0].synthesis["chair_mode"] == "agent"
    assert rows[0].synthesis["brief_version"] == 1
    assert rows[0].synthesis["brief_hash"] == brief.brief_hash
    assert rows[0].synthesis["submitted_by"] == AGENT_CHAIR_MODEL_ID
    assert rows[0].clusters["production"] == "agent_chair"
    assert rows[0].clusters["stage"] is None
    kinds = await audit_kinds(seminar_id)
    assert "synthesis_submitted" in kinds
    assert "report_written" in kinds


async def test_submitted_report_document_carries_agent_provenance(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    service = make_service(FakePortFactory(agent_ports()))
    seminar_id, _ = await _briefed_seminar(service, run.id)
    async with get_database().session() as session:
        await service.submit_chair_synthesis(
            session,
            seminar_id,
            ChairSynthesisRequest(
                clusters=cluster_payload(), synthesis=synthesis_payload()
            ),
        )
        detail = await service.get_report(session, seminar_id, 1)
    header = detail.document["header"]
    assert header["chair_mode"] == "agent"
    assert header["chair_model_id"] == AGENT_CHAIR_MODEL_ID
    assert header["brief_version"] == 1
    assert "chair_provenance_note" in header
    assert "agent chair" in header["chair_provenance_note"]
    assert detail.document["unified_recommendation"]["provenance"] == "deliberated"
    assert detail.document["canonical_claims"]["provenance"] == "deliberated"
    assert detail.document["disagreements"]["count"] == 1
    chair_config = detail.document["audit_appendix"]["chair_config"]
    assert chair_config["chair_mode"] == "agent"


async def test_submission_with_dropped_item_refuses_with_zero_rows(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    service = make_service(FakePortFactory(agent_ports()))
    seminar_id, _ = await _briefed_seminar(service, run.id)
    dropped = cluster_payload()
    dropped["claims"] = dropped["claims"][:-1]  # drop the claim covering I9
    async with get_database().session() as session:
        with pytest.raises(SeminarServiceError) as excinfo:
            await service.submit_chair_synthesis(
                session,
                seminar_id,
                ChairSynthesisRequest(clusters=dropped, synthesis=synthesis_payload()),
            )
    assert excinfo.value.code == "chair_submission_coverage_failed"
    assert "I9" in str(excinfo.value)
    assert await report_rows() == []
    assert await seminar_status(seminar_id) == "collecting"
    assert "refusal" in await audit_kinds(seminar_id)


async def test_submission_with_contract_violation_refuses_with_zero_rows(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    service = make_service(FakePortFactory(agent_ports()))
    seminar_id, _ = await _briefed_seminar(service, run.id)
    bad_clusters = {"claims": [{"sources": [{"item_id": "I1", "stance": "support"}]}]}
    async with get_database().session() as session:
        with pytest.raises(SeminarServiceError) as excinfo:
            await service.submit_chair_synthesis(
                session,
                seminar_id,
                ChairSynthesisRequest(clusters=bad_clusters, synthesis=synthesis_payload()),
            )
    assert excinfo.value.code == "chair_submission_contract_failed"
    assert await report_rows() == []
    assert await seminar_status(seminar_id) == "collecting"


async def test_submission_with_bad_synthesis_contract_refuses(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    service = make_service(FakePortFactory(agent_ports()))
    seminar_id, _ = await _briefed_seminar(service, run.id)
    bad_synthesis = copy.deepcopy(synthesis_payload())
    del bad_synthesis["minority_report"]
    async with get_database().session() as session:
        with pytest.raises(SeminarServiceError) as excinfo:
            await service.submit_chair_synthesis(
                session,
                seminar_id,
                ChairSynthesisRequest(clusters=cluster_payload(), synthesis=bad_synthesis),
            )
    assert excinfo.value.code == "chair_submission_contract_failed"
    assert await report_rows() == []


async def test_submission_on_model_mode_seminar_refuses(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    ports = dict(agent_ports())
    ports["chair-1"] = ScriptedSkillPort(chair_script())
    service = make_service(FakePortFactory(ports))
    seminar_id = await run_to_collecting(
        service, run.id, make_request(roster_ids=["model-a", "model-b"], max_rounds=2)
    )
    async with get_database().session() as session:
        with pytest.raises(SeminarServiceError) as excinfo:
            await service.submit_chair_synthesis(
                session,
                seminar_id,
                ChairSynthesisRequest(
                    clusters=cluster_payload(), synthesis=synthesis_payload()
                ),
            )
    assert excinfo.value.code == "seminar_chair_mode_mismatch"
    assert await report_rows() == []


async def test_submission_without_a_brief_refuses(monkeypatch, tmp_path: Path) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    service = make_service(FakePortFactory(agent_ports()))
    seminar_id = await run_agent_to_collecting(service, run.id)
    async with get_database().session() as session:
        with pytest.raises(SeminarServiceError) as excinfo:
            await service.submit_chair_synthesis(
                session,
                seminar_id,
                ChairSynthesisRequest(
                    clusters=cluster_payload(), synthesis=synthesis_payload()
                ),
            )
    assert excinfo.value.code == "seminar_no_chair_brief"


async def test_submission_with_unknown_brief_version_refuses(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    service = make_service(FakePortFactory(agent_ports()))
    seminar_id, _ = await _briefed_seminar(service, run.id)
    async with get_database().session() as session:
        with pytest.raises(SeminarServiceError) as excinfo:
            await service.submit_chair_synthesis(
                session,
                seminar_id,
                ChairSynthesisRequest(
                    clusters=cluster_payload(),
                    synthesis=synthesis_payload(),
                    brief_version=99,
                ),
            )
    assert excinfo.value.code == "seminar_unknown_brief_version"


async def test_submission_pins_the_requested_brief_version(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    service = make_service(FakePortFactory(agent_ports()))
    seminar_id = await run_agent_to_collecting(service, run.id)
    async with get_database().session() as session:
        await service.synthesize_seminar(session, seminar_id, SynthesizeRequest())
        await service.synthesize_seminar(session, seminar_id, SynthesizeRequest())
        read = await service.submit_chair_synthesis(
            session,
            seminar_id,
            ChairSynthesisRequest(
                clusters=cluster_payload(),
                synthesis=synthesis_payload(),
                brief_version=1,
            ),
        )
    assert read.version == 1
    rows = await report_rows()
    assert rows[0].synthesis["brief_version"] == 1


async def test_resubmission_creates_a_new_version_with_the_same_hash(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    service = make_service(FakePortFactory(agent_ports()))
    seminar_id, _ = await _briefed_seminar(service, run.id)
    request = ChairSynthesisRequest(
        clusters=cluster_payload(), synthesis=synthesis_payload()
    )
    async with get_database().session() as session:
        first = await service.submit_chair_synthesis(session, seminar_id, request)
        second = await service.submit_chair_synthesis(session, seminar_id, request)
    assert first.version == 1
    assert second.version == 2
    assert first.report_hash == second.report_hash
    assert len(await report_rows()) == 2


# --- deterministic fallback -----------------------------------------------


async def test_deterministic_fallback_flag_writes_fallback_report_in_agent_mode(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    service = make_service(FakePortFactory(agent_ports()))
    seminar_id = await run_agent_to_collecting(service, run.id)
    async with get_database().session() as session:
        read = await service.synthesize_seminar(
            session, seminar_id, SynthesizeRequest(deterministic_fallback=True)
        )
    assert isinstance(read, SynthesizeRead)
    assert read.production_path == "deterministic_fallback"
    assert read.cluster_production == "deterministic_prepass"
    assert read.chair_model_id == AGENT_CHAIR_MODEL_ID
    assert read.agreement_level is None
    assert await seminar_status(seminar_id) == "reported"
    assert await brief_rows() == []


async def test_deterministic_fallback_flag_skips_chair_calls_in_model_mode(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    chair_port = ScriptedSkillPort(chair_script())
    ports = dict(agent_ports())
    ports["chair-1"] = chair_port
    service = make_service(FakePortFactory(ports))
    seminar_id = await run_to_collecting(
        service, run.id, make_request(roster_ids=["model-a", "model-b"], max_rounds=2)
    )
    async with get_database().session() as session:
        read = await service.synthesize_seminar(
            session, seminar_id, SynthesizeRequest(deterministic_fallback=True)
        )
    assert read.production_path == "deterministic_fallback"
    assert chair_port.calls == []


# --- stuck status ------------------------------------------------------------


async def test_synthesize_on_stuck_seminar_refuses_with_named_code(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    service = make_service(FakePortFactory(agent_ports()))
    seminar_id = await run_agent_to_collecting(service, run.id)
    async with get_database().session() as session:
        from planagent.domain.models import SeminarRecord

        record = await session.get(SeminarRecord, seminar_id)
        assert record is not None
        record.status = "synthesizing"
        await session.commit()
    async with get_database().session() as session:
        with pytest.raises(SeminarServiceError) as excinfo:
            await service.synthesize_seminar(session, seminar_id, SynthesizeRequest())
    assert excinfo.value.code == "seminar_synthesize_stuck"
    assert await report_rows() == []
    assert await seminar_status(seminar_id) == "synthesizing"
