"""Seminar hardening tests (Sprint 18): retries, budgets, token
accounting, the synthesize queue, and the audit log — end to end at
the service level. Fake ports only — no live LLM calls.
"""

from __future__ import annotations

import asyncio
import copy
from pathlib import Path

import pytest
from sqlalchemy import select

from planagent.db import get_database
from planagent.domain.models import SeminarRoundRecord
from planagent.services.seminar.models import (
    ModelPortConfig,
    RosterEntry,
    SeminarCreateRequest,
    SynthesizeRequest,
)
from planagent.services.seminar.service import SeminarServiceError, SeminarService
from planagent.services.skills.orchestration import SkillLLMResponse, TokenUsage
from tests.skill_fixtures import ScriptedSkillPort, strategy_team_script
from tests.test_seminar_service import (
    FakePortFactory,
    failing_analysis_script,
    make_request,
    make_run,
    make_service,
    merge_scripts,
    reflection_payload,
    setup_db,
    stable_model_script,
    verdict_payload,
)
from tests.test_seminar_synthesis_service import (
    chair_script,
    model_script,
    run_to_collecting,
    verdict_a,
    verdict_b,
)

TOPIC = "Should we launch the AI customer-service line?"


def make_budget_request(
    *,
    roster_ids: list[str],
    max_rounds: int = 1,
    max_stage_calls: int = 200,
    max_tokens: int = 1_000_000,
    max_retries: int = 2,
    retry_backoff_seconds: float = 0.0,
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
        max_stage_calls=max_stage_calls,
        max_tokens=max_tokens,
        max_retries=max_retries,
        retry_backoff_seconds=retry_backoff_seconds,
    )


class FlakyPort:
    """Wraps a port: raises TimeoutError on the first N calls to one
    template, then delegates. Proves retries happen at the stage
    level without touching the fixture scripts."""

    def __init__(
        self, wrapped: ScriptedSkillPort, *, template_id: str, failures: int
    ) -> None:
        self._wrapped = wrapped
        self._template_id = template_id
        self._failures_left = failures
        self.timeouts_raised = 0

    def is_available(self) -> bool:
        return self._wrapped.is_available()

    async def generate_json(self, **kwargs: object) -> SkillLLMResponse:
        if kwargs.get("template_id") == self._template_id and self._failures_left > 0:
            self._failures_left -= 1
            self.timeouts_raised += 1
            raise TimeoutError("simulated upstream timeout")
        return await self._wrapped.generate_json(**kwargs)  # type: ignore[arg-type]

    @property
    def calls(self) -> list[dict]:
        return self._wrapped.calls


class SlowPort:
    """Wraps a port: sleeps before every call, to force queue overlap."""

    def __init__(self, wrapped: ScriptedSkillPort, *, delay: float) -> None:
        self._wrapped = wrapped
        self._delay = delay

    def is_available(self) -> bool:
        return self._wrapped.is_available()

    async def generate_json(self, **kwargs: object) -> SkillLLMResponse:
        await asyncio.sleep(self._delay)
        return await self._wrapped.generate_json(**kwargs)  # type: ignore[arg-type]


async def audit_events(seminar_id: str, *, kind: str | None = None) -> list[dict]:
    from planagent.domain.models import SeminarAuditEventRecord

    async with get_database().session() as session:
        result = await session.execute(
            select(SeminarAuditEventRecord)
            .where(SeminarAuditEventRecord.seminar_id == seminar_id)
            .order_by(SeminarAuditEventRecord.seq)
        )
        rows = list(result.scalars().all())
    return [
        {
            "seq": row.seq,
            "kind": row.kind,
            "model_id": row.model_id,
            "stage": row.stage,
            "detail": row.detail or {},
            "stage_call_id": row.stage_call_id,
        }
        for row in rows
        if kind is None or row.kind == kind
    ]


async def round_rows(seminar_id: str) -> list[SeminarRoundRecord]:
    async with get_database().session() as session:
        result = await session.execute(
            select(SeminarRoundRecord).where(SeminarRoundRecord.seminar_id == seminar_id)
        )
        return list(result.scalars().all())


# --- retries end to end ----------------------------------------------------


async def test_timeout_then_success_completes_the_round_with_attempts_recorded(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    flaky = FlakyPort(
        ScriptedSkillPort(stable_model_script(1)),
        template_id="mckinsey.intake_classify",
        failures=1,
    )
    ports = {
        "model-a": flaky,
        "model-b": ScriptedSkillPort(stable_model_script(1)),
        "chair-1": ScriptedSkillPort({}),
    }
    service = make_service(FakePortFactory(ports))  # type: ignore[arg-type]
    request = make_budget_request(roster_ids=["model-a", "model-b"], max_rounds=1)
    async with get_database().session() as session:
        created = await service.create_seminar(session, run.id, request)
    async with get_database().session() as session:
        read = await service.advance_seminar(session, created.seminar_id)
    assert [item.status for item in read.per_model] == ["completed", "completed"]
    assert flaky.timeouts_raised == 1
    rows = await round_rows(created.seminar_id)
    model_a = next(row for row in rows if row.model_id == "model-a")
    intake = next(s for s in model_a.stages if s["template_id"] == "mckinsey.intake_classify")
    assert intake["attempts"] == 2
    events = await audit_events(created.seminar_id, kind="retry")
    assert len(events) == 1
    assert events[0]["stage"] == "mckinsey.intake_classify"
    assert events[0]["detail"]["error_kind"] == "timeout"
    finished = await audit_events(created.seminar_id, kind="stage_call_finished")
    intake_calls = [
        e
        for e in finished
        if e["stage"] == "mckinsey.intake_classify" and e["model_id"] == "model-a"
    ]
    assert [e["detail"]["outcome"] for e in intake_calls] == ["timeout", "ok"]


async def test_timeout_retry_exhaustion_fails_the_round_as_timeout(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    flaky = FlakyPort(
        ScriptedSkillPort(stable_model_script(1)),
        template_id="mckinsey.intake_classify",
        failures=10,
    )
    ports = {
        "model-a": flaky,
        "model-b": ScriptedSkillPort(stable_model_script(1)),
        "chair-1": ScriptedSkillPort({}),
    }
    service = make_service(FakePortFactory(ports))  # type: ignore[arg-type]
    request = make_budget_request(roster_ids=["model-a", "model-b"], max_rounds=1)
    async with get_database().session() as session:
        created = await service.create_seminar(session, run.id, request)
    async with get_database().session() as session:
        read = await service.advance_seminar(session, created.seminar_id)
    statuses = {item.model_id: item.status for item in read.per_model}
    assert statuses == {"model-a": "failed", "model-b": "completed"}
    assert flaky.timeouts_raised == 3  # 1 initial + 2 retries
    rows = await round_rows(created.seminar_id)
    model_a = next(row for row in rows if row.model_id == "model-a")
    assert model_a.error["kind"] == "timeout"
    assert model_a.error["stage"] == "analysis"
    events = await audit_events(created.seminar_id, kind="retry")
    assert len(events) == 2


async def test_contract_failure_is_not_retried(monkeypatch, tmp_path: Path) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    ports = {
        "model-a": ScriptedSkillPort(failing_analysis_script()),
        "model-b": ScriptedSkillPort(stable_model_script(1)),
        "chair-1": ScriptedSkillPort({}),
    }
    service = make_service(FakePortFactory(ports))
    request = make_budget_request(roster_ids=["model-a", "model-b"], max_rounds=1)
    async with get_database().session() as session:
        created = await service.create_seminar(session, run.id, request)
    async with get_database().session() as session:
        await service.advance_seminar(session, created.seminar_id)
    rows = await round_rows(created.seminar_id)
    model_a = next(row for row in rows if row.model_id == "model-a")
    assert model_a.error["kind"] == "contract"
    assert await audit_events(created.seminar_id, kind="retry") == []
    finished = await audit_events(created.seminar_id, kind="stage_call_finished")
    intake_calls = [
        e
        for e in finished
        if e["stage"] == "mckinsey.intake_classify" and e["model_id"] == "model-a"
    ]
    assert len(intake_calls) == 1


# --- budgets end to end ----------------------------------------------------


async def test_stage_call_budget_stops_the_wave_and_is_recorded(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    ports = {
        "model-a": ScriptedSkillPort(stable_model_script(1)),
        "model-b": ScriptedSkillPort(stable_model_script(1)),
        "chair-1": ScriptedSkillPort({}),
    }
    service = make_service(FakePortFactory(ports))
    request = make_budget_request(
        roster_ids=["model-a", "model-b"], max_rounds=1, max_stage_calls=5
    )
    async with get_database().session() as session:
        created = await service.create_seminar(session, run.id, request)
    async with get_database().session() as session:
        read = await service.advance_seminar(session, created.seminar_id)
    # Both models fail: the 5-call budget cannot cover one 11-stage
    # analysis each, and the failure kind names the budget.
    assert {item.status for item in read.per_model} == {"failed"}
    rows = await round_rows(created.seminar_id)
    assert all(row.error["kind"] == "budget_exhausted" for row in rows)
    finished = await audit_events(created.seminar_id, kind="stage_call_finished")
    assert len(finished) == 5
    exhausted = await audit_events(created.seminar_id, kind="budget_exhausted")
    assert len(exhausted) >= 1
    assert exhausted[0]["detail"]["budget"] == "max_stage_calls"
    assert exhausted[0]["detail"]["limit"] == 5
    async with get_database().session() as session:
        detail = await service.get_seminar_detail(session, created.seminar_id)
    assert detail.diagnosis["error_counts"] == {"budget_exhausted": 2}
    assert detail.budgets["stage_calls_used"] == 5
    assert detail.budgets["stage_calls_remaining"] == 0


async def test_budget_holds_across_waves_via_the_ledger(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    script_a = merge_scripts(*[strategy_team_script(mode="standard") for _ in range(2)])
    script_a["seminar.reflect"] = [reflection_payload() for _ in range(2)]
    script_a["seminar.final_verdict"] = [verdict_payload()]
    script_b = copy.deepcopy(script_a)
    ports = {
        "model-a": ScriptedSkillPort(script_a),
        "model-b": ScriptedSkillPort(script_b),
        "chair-1": ScriptedSkillPort({}),
    }
    service = make_service(FakePortFactory(ports))
    # 24 calls cover wave 1 (2 models x 12 stages) but not wave 2.
    request = make_budget_request(
        roster_ids=["model-a", "model-b"], max_rounds=2, max_stage_calls=24
    )
    async with get_database().session() as session:
        created = await service.create_seminar(session, run.id, request)
    async with get_database().session() as session:
        first = await service.advance_seminar(session, created.seminar_id)
    assert [item.status for item in first.per_model] == ["completed", "completed"]
    async with get_database().session() as session:
        second = await service.advance_seminar(session, created.seminar_id)
    assert {item.status for item in second.per_model} == {"failed"}
    rows = await round_rows(created.seminar_id)
    wave2 = [row for row in rows if row.round_no == 2]
    assert all(row.error["kind"] == "budget_exhausted" for row in wave2)


# --- token accounting end to end --------------------------------------------


async def test_token_accounting_flows_to_stage_records_detail_and_report(
    monkeypatch, tmp_path: Path
) -> None:
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
    request = make_budget_request(roster_ids=["model-a", "model-b"], max_rounds=1)
    async with get_database().session() as session:
        created = await service.create_seminar(session, run.id, request)
    async with get_database().session() as session:
        await service.advance_seminar(session, created.seminar_id)
    # 12 stage calls per model (11 analysis + reflection) at 15 tokens.
    rows = await round_rows(created.seminar_id)
    for row in rows:
        assert row.stages[0]["usage"] == {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        }
        assert row.reflection_stage["usage"]["total_tokens"] == 15
        assert row.stages[0]["attempts"] == 1
        assert row.stages[0]["duration_ms"] >= 0.0
    async with get_database().session() as session:
        detail = await service.get_seminar_detail(session, created.seminar_id)
    assert detail.budgets["tokens_used"] == 24 * 15
    assert detail.budgets["tokens_remaining"] == 1_000_000 - 24 * 15
    assert detail.diagnosis["total_tokens"] == 24 * 15
    assert detail.diagnosis["stage_calls"] == 24
    assert detail.diagnosis["stage_call_attempts"] == 24


# --- synthesize queue --------------------------------------------------------


async def test_concurrent_synthesizes_serialize_into_versions_1_and_2(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    chair_port = SlowPort(ScriptedSkillPort(chair_script(copies=2)), delay=0.2)
    ports = {
        "model-a": ScriptedSkillPort(model_script(2, verdict_a())),
        "model-b": ScriptedSkillPort(model_script(2, verdict_b())),
        "chair-1": chair_port,
    }
    service = make_service(FakePortFactory(ports))  # type: ignore[arg-type]
    seminar_id = await run_to_collecting(
        service, run.id, make_request(roster_ids=["model-a", "model-b"], max_rounds=2)
    )

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


# --- audit log reads ---------------------------------------------------------


async def test_audit_endpoint_lists_events_in_seq_order_with_filters(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    ports = {
        "model-a": ScriptedSkillPort(stable_model_script(1)),
        "model-b": ScriptedSkillPort(stable_model_script(1)),
        "chair-1": ScriptedSkillPort({}),
    }
    service = make_service(FakePortFactory(ports))
    request = make_budget_request(roster_ids=["model-a", "model-b"], max_rounds=1)
    async with get_database().session() as session:
        created = await service.create_seminar(session, run.id, request)
    async with get_database().session() as session:
        await service.advance_seminar(session, created.seminar_id)
        events = await service.list_audit_events(session, created.seminar_id)
    seqs = [event.seq for event in events]
    assert seqs == sorted(seqs)
    assert seqs[0] == 1
    kinds = {event.kind for event in events}
    assert "stage_call_started" in kinds
    assert "stage_call_finished" in kinds
    assert "status_transition" in kinds
    async with get_database().session() as session:
        started = await service.list_audit_events(
            session, created.seminar_id, kind="stage_call_started"
        )
        model_a = await service.list_audit_events(
            session, created.seminar_id, model_id="model-a"
        )
    assert started and all(event.kind == "stage_call_started" for event in started)
    assert model_a and all(event.model_id == "model-a" for event in model_a)
    assert len(started) == 24  # 2 models x 12 stage calls, one start each


async def test_audit_endpoint_rejects_unknown_kind(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    service = make_service(FakePortFactory({"chair-1": ScriptedSkillPort({})}))
    request = make_budget_request(roster_ids=["model-a", "model-b"], max_rounds=1)
    async with get_database().session() as session:
        created = await service.create_seminar(session, run.id, request)
        with pytest.raises(SeminarServiceError) as excinfo:
            await service.list_audit_events(session, created.seminar_id, kind="bogus")
    assert excinfo.value.code == "seminar_audit_unknown_kind"


async def test_refusal_writes_only_the_audit_event(monkeypatch, tmp_path: Path) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    ports = {
        "model-a": ScriptedSkillPort(stable_model_script(1)),
        "model-b": ScriptedSkillPort(stable_model_script(1)),
        "chair-1": ScriptedSkillPort({}),
    }
    service = make_service(FakePortFactory(ports))
    request = make_budget_request(roster_ids=["model-a", "model-b"], max_rounds=1)
    async with get_database().session() as session:
        created = await service.create_seminar(session, run.id, request)
        await service.advance_seminar(session, created.seminar_id)
        with pytest.raises(SeminarServiceError) as excinfo:
            await service.synthesize_seminar(session, created.seminar_id, SynthesizeRequest())
    assert excinfo.value.code == "seminar_no_finals"
    events = await audit_events(created.seminar_id, kind="refusal")
    assert len(events) == 1
    assert events[0]["detail"]["code"] == "seminar_no_finals"
    from tests.test_seminar_synthesis_service import report_rows as _report_rows

    assert await _report_rows() == []


async def test_detail_diagnosis_summarizes_a_failed_wave(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    ports = {
        "model-a": ScriptedSkillPort(failing_analysis_script()),
        "model-b": ScriptedSkillPort(stable_model_script(1)),
        "chair-1": ScriptedSkillPort({}),
    }
    service = make_service(FakePortFactory(ports))
    request = make_budget_request(roster_ids=["model-a", "model-b"], max_rounds=1)
    async with get_database().session() as session:
        created = await service.create_seminar(session, run.id, request)
        await service.advance_seminar(session, created.seminar_id)
        detail = await service.get_seminar_detail(session, created.seminar_id)
    # model-a's contract failure is visible in the diagnosis via the
    # stage_failure audit event (the call itself succeeded — the
    # contract check failed in the stage runner — so the wrapper
    # alone could not surface it). The audit log on its own locates
    # the failure: which model, which stage, which kind.
    assert detail.diagnosis["error_counts"] == {"contract": 1}
    failures = await audit_events(created.seminar_id, kind="stage_failure")
    assert len(failures) == 1
    assert failures[0]["model_id"] == "model-a"
    assert failures[0]["detail"]["error_kind"] == "contract"
    assert detail.diagnosis["stage_calls"] == 13  # 1 + 12
    assert detail.budgets["stage_calls_used"] == 13
    assert detail.diagnosis["total_tokens"] == 0  # scripted port reports no usage
