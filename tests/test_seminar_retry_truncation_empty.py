"""Seminar retry-on-truncation/empty-response tests (retry track).

End to end at the service level: truncated and empty upstream
responses retry under the same max-2 + fixed-backoff + audit
treatment as timeouts, while malformed content never retries.
Fake ports only — no live LLM calls.
"""

from __future__ import annotations

from pathlib import Path

from planagent.db import get_database
from planagent.services.seminar.models import SynthesizeRequest
from tests.skill_fixtures import ScriptedSkillPort, load_fixture
from tests.test_seminar_hardening import audit_events, make_budget_request, round_rows
from tests.test_seminar_service import (
    FakePortFactory,
    make_request,
    make_run,
    make_service,
    setup_db,
    stable_model_script,
)
from tests.test_seminar_synthesis_service import (
    chair_script,
    cluster_payload,
    model_script,
    run_to_collecting,
    verdict_a,
    verdict_b,
)

INTAKE = "mckinsey.intake_classify"


def _intake_script(
    payloads: list,
    *,
    finish_reasons: list | None = None,
    empty_flags: list | None = None,
) -> ScriptedSkillPort:
    """A one-round model script whose intake answers the given queue."""
    script = stable_model_script(1)
    script[INTAKE] = payloads
    kwargs: dict = {}
    if finish_reasons is not None:
        kwargs["finish_reason_script"] = {INTAKE: finish_reasons}
    if empty_flags is not None:
        kwargs["empty_response_script"] = {INTAKE: empty_flags}
    return ScriptedSkillPort(script, **kwargs)


def _intake_fixture() -> dict:
    return load_fixture("intake_classify")


async def _advance_once(service, run_id, request):
    async with get_database().session() as session:
        created = await service.create_seminar(session, run_id, request)
    async with get_database().session() as session:
        read = await service.advance_seminar(session, created.seminar_id)
    return created.seminar_id, read


async def test_empty_response_then_success_completes_the_round(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    ports = {
        "model-a": _intake_script(
            [None, _intake_fixture()],  # type: ignore[list-item]
            empty_flags=[True, False],
        ),
        "model-b": ScriptedSkillPort(stable_model_script(1)),
        "chair-1": ScriptedSkillPort({}),
    }
    service = make_service(FakePortFactory(ports))
    request = make_budget_request(roster_ids=["model-a", "model-b"], max_rounds=1)
    seminar_id, read = await _advance_once(service, run.id, request)
    assert [item.status for item in read.per_model] == ["completed", "completed"]
    rows = await round_rows(seminar_id)
    model_a = next(row for row in rows if row.model_id == "model-a")
    intake = next(s for s in model_a.stages if s["template_id"] == INTAKE)
    assert intake["attempts"] == 2
    events = await audit_events(seminar_id, kind="retry")
    assert len(events) == 1
    assert events[0]["stage"] == INTAKE
    assert events[0]["detail"]["error_kind"] == "empty_response"
    assert "empty response" in events[0]["detail"]["error_message"]
    finished = await audit_events(seminar_id, kind="stage_call_finished")
    intake_calls = [
        e for e in finished if e["stage"] == INTAKE and e["model_id"] == "model-a"
    ]
    assert [e["detail"]["outcome"] for e in intake_calls] == ["empty_response", "ok"]


async def test_truncated_response_then_success_completes_the_round(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    ports = {
        "model-a": _intake_script(
            [None, _intake_fixture()],  # type: ignore[list-item]
            finish_reasons=["length", None],
        ),
        "model-b": ScriptedSkillPort(stable_model_script(1)),
        "chair-1": ScriptedSkillPort({}),
    }
    service = make_service(FakePortFactory(ports))
    request = make_budget_request(roster_ids=["model-a", "model-b"], max_rounds=1)
    seminar_id, read = await _advance_once(service, run.id, request)
    assert [item.status for item in read.per_model] == ["completed", "completed"]
    rows = await round_rows(seminar_id)
    model_a = next(row for row in rows if row.model_id == "model-a")
    intake = next(s for s in model_a.stages if s["template_id"] == INTAKE)
    assert intake["attempts"] == 2
    events = await audit_events(seminar_id, kind="retry")
    assert len(events) == 1
    assert events[0]["detail"]["error_kind"] == "truncated"
    finished = await audit_events(seminar_id, kind="stage_call_finished")
    intake_calls = [
        e for e in finished if e["stage"] == INTAKE and e["model_id"] == "model-a"
    ]
    assert [e["detail"]["outcome"] for e in intake_calls] == ["truncated", "ok"]


async def test_empty_response_exhaustion_fails_the_round_as_empty_response(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    ports = {
        "model-a": _intake_script(
            [None, None, None],  # type: ignore[list-item]
            empty_flags=[True, True, True],
        ),
        "model-b": ScriptedSkillPort(stable_model_script(1)),
        "chair-1": ScriptedSkillPort({}),
    }
    service = make_service(FakePortFactory(ports))
    request = make_budget_request(roster_ids=["model-a", "model-b"], max_rounds=1)
    seminar_id, read = await _advance_once(service, run.id, request)
    statuses = {item.model_id: item.status for item in read.per_model}
    assert statuses == {"model-a": "failed", "model-b": "completed"}
    rows = await round_rows(seminar_id)
    model_a = next(row for row in rows if row.model_id == "model-a")
    assert model_a.error["kind"] == "empty_response"
    assert model_a.error["stage"] == "analysis"
    assert "empty response" in model_a.error["message"]
    events = await audit_events(seminar_id, kind="retry")
    assert len(events) == 2  # 1 initial + 2 retries, then exhaustion
    assert all(e["detail"]["error_kind"] == "empty_response" for e in events)
    finished = await audit_events(seminar_id, kind="stage_call_finished")
    intake_calls = [
        e for e in finished if e["stage"] == INTAKE and e["model_id"] == "model-a"
    ]
    assert len(intake_calls) == 3


async def test_truncated_response_exhaustion_fails_the_round_as_truncated(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    ports = {
        "model-a": _intake_script(
            [None, None, None],  # type: ignore[list-item]
            finish_reasons=["length", "length", "length"],
        ),
        "model-b": ScriptedSkillPort(stable_model_script(1)),
        "chair-1": ScriptedSkillPort({}),
    }
    service = make_service(FakePortFactory(ports))
    request = make_budget_request(roster_ids=["model-a", "model-b"], max_rounds=1)
    seminar_id, read = await _advance_once(service, run.id, request)
    statuses = {item.model_id: item.status for item in read.per_model}
    assert statuses == {"model-a": "failed", "model-b": "completed"}
    rows = await round_rows(seminar_id)
    model_a = next(row for row in rows if row.model_id == "model-a")
    assert model_a.error["kind"] == "truncated"
    assert model_a.error["stage"] == "analysis"
    events = await audit_events(seminar_id, kind="retry")
    assert len(events) == 2
    assert all(e["detail"]["error_kind"] == "truncated" for e in events)


async def test_malformed_response_is_not_retried(monkeypatch, tmp_path: Path) -> None:
    # Payload None with NEITHER signal: content arrived but did not
    # parse. The distinction from the empty case is the port's
    # affirmative signal — without it, no retry, kind contract.
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    ports = {
        "model-a": _intake_script([None]),  # type: ignore[list-item]
        "model-b": ScriptedSkillPort(stable_model_script(1)),
        "chair-1": ScriptedSkillPort({}),
    }
    service = make_service(FakePortFactory(ports))
    request = make_budget_request(roster_ids=["model-a", "model-b"], max_rounds=1)
    seminar_id, _ = await _advance_once(service, run.id, request)
    rows = await round_rows(seminar_id)
    model_a = next(row for row in rows if row.model_id == "model-a")
    assert model_a.error["kind"] == "contract"
    assert await audit_events(seminar_id, kind="retry") == []
    finished = await audit_events(seminar_id, kind="stage_call_finished")
    intake_calls = [
        e for e in finished if e["stage"] == INTAKE and e["model_id"] == "model-a"
    ]
    assert len(intake_calls) == 1
    assert intake_calls[0]["detail"]["outcome"] == "contract"


async def test_budget_exhausted_blocks_a_scheduled_response_retry(
    monkeypatch, tmp_path: Path
) -> None:
    # The token budget trips on model-a's own first attempt: the
    # truncated intake call reports 100 tokens against a 100-token
    # budget, so the scheduled retry is blocked by the budget check
    # before it runs — the round fails budget_exhausted, and the
    # retry event still records why a retry was scheduled. Model-b
    # reports no usage, so only model-a's facts are asserted (wave
    # interleaving makes model-b's counts non-deterministic).
    from planagent.services.skills.orchestration import TokenUsage

    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    script = stable_model_script(1)
    script[INTAKE] = [None, _intake_fixture()]  # type: ignore[list-item]
    usage = TokenUsage(prompt_tokens=0, completion_tokens=100, total_tokens=100)
    ports = {
        "model-a": ScriptedSkillPort(
            script,
            finish_reason_script={INTAKE: ["length", None]},
            usage_script={INTAKE: [usage, usage]},
        ),
        "model-b": ScriptedSkillPort(stable_model_script(1)),
        "chair-1": ScriptedSkillPort({}),
    }
    service = make_service(FakePortFactory(ports))
    request = make_budget_request(
        roster_ids=["model-a", "model-b"], max_rounds=1, max_tokens=100
    )
    seminar_id, _ = await _advance_once(service, run.id, request)
    rows = await round_rows(seminar_id)
    model_a = next(row for row in rows if row.model_id == "model-a")
    assert model_a.error["kind"] == "budget_exhausted"
    finished = await audit_events(seminar_id, kind="stage_call_finished")
    intake_calls = [
        e for e in finished if e["stage"] == INTAKE and e["model_id"] == "model-a"
    ]
    assert len(intake_calls) == 1  # the retry never ran
    assert intake_calls[0]["detail"]["outcome"] == "truncated"
    exhausted = await audit_events(seminar_id, kind="budget_exhausted")
    assert len(exhausted) >= 1
    assert exhausted[0]["detail"]["budget"] == "max_tokens"
    retries = await audit_events(seminar_id, kind="retry")
    model_a_retries = [e for e in retries if e["model_id"] == "model-a"]
    assert len(model_a_retries) == 1
    assert model_a_retries[0]["detail"]["error_kind"] == "truncated"


async def test_chair_cluster_stage_retries_an_empty_response(
    monkeypatch, tmp_path: Path
) -> None:
    # The chair stages share the instrumented choke point, so the
    # cluster stage retries an empty response the same way a wave
    # stage does — and the synthesis still completes.
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    chair = chair_script(copies=1)
    chair["seminar.cluster"] = [None, cluster_payload()]  # type: ignore[list-item]
    chair_port = ScriptedSkillPort(
        chair, empty_response_script={"seminar.cluster": [True, False]}
    )
    ports = {
        "model-a": ScriptedSkillPort(model_script(2, verdict_a())),
        "model-b": ScriptedSkillPort(model_script(2, verdict_b())),
        "chair-1": chair_port,
    }
    service = make_service(FakePortFactory(ports))  # type: ignore[arg-type]
    seminar_id = await run_to_collecting(
        service, run.id, make_request(roster_ids=["model-a", "model-b"], max_rounds=2)
    )
    async with get_database().session() as session:
        result = await service.synthesize_seminar(session, seminar_id, SynthesizeRequest())
    assert result.version == 1
    retries = await audit_events(seminar_id, kind="retry")
    assert len(retries) == 1
    assert retries[0]["stage"] == "seminar.cluster"
    assert retries[0]["detail"]["error_kind"] == "empty_response"
    finished = await audit_events(seminar_id, kind="stage_call_finished")
    cluster_calls = [e for e in finished if e["stage"] == "seminar.cluster"]
    assert [e["detail"]["outcome"] for e in cluster_calls] == ["empty_response", "ok"]
    async with get_database().session() as session:
        detail = await service.get_seminar_detail(session, seminar_id)
    assert detail.status == "reported"
    assert len(detail.reports) == 1
