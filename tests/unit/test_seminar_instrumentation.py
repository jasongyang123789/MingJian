"""Instrumented port + budget tracker tests (Sprint 18, design §10.3).

Pins the choke-point behavior: timeout-only retries with fixed
backoff, budget checks before every attempt, audit event pairs per
attempt, and attempt/usage accounting on the returned response. No
database, no network: the wrapped port is scripted.
"""

from __future__ import annotations

import asyncio

import pytest

from planagent.services.seminar.audit import AuditEventKind, AuditRecorder
from planagent.services.seminar.errors import BudgetExhaustedError
from planagent.services.seminar.instrumentation import BudgetTracker, InstrumentedPort
from planagent.services.skills.contracts import SkillEmptyResponseError, SkillTruncatedError
from planagent.services.skills.orchestration import SkillLLMResponse, TokenUsage


class ScriptedPort:
    """A port serving queued outcomes: responses or exceptions."""

    def __init__(self, outcomes: list[SkillLLMResponse | BaseException]) -> None:
        self._outcomes = list(outcomes)
        self.calls = 0
        self.available = True

    def is_available(self) -> bool:
        return self.available

    async def generate_json(self, **kwargs: object) -> SkillLLMResponse:
        self.calls += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _ok_response(*, usage: TokenUsage | None = None) -> SkillLLMResponse:
    return SkillLLMResponse(model="fake", payload={"ok": True}, usage=usage)


def _truncated_response(*, usage: TokenUsage | None = None) -> SkillLLMResponse:
    return SkillLLMResponse(
        model="fake", payload=None, finish_reason="length", usage=usage
    )


def _empty_response() -> SkillLLMResponse:
    # The 2026-11-17 live shape: no content, no finish reason, no usage.
    return SkillLLMResponse(model="fake", payload=None, empty_response=True)


def _malformed_response() -> SkillLLMResponse:
    # Content arrived but did not parse: payload None, no signal.
    return SkillLLMResponse(model="fake", payload=None, finish_reason="stop")


def _port(
    outcomes: list[SkillLLMResponse | BaseException],
    *,
    tracker: BudgetTracker | None = None,
    recorder: AuditRecorder | None = None,
    max_retries: int = 2,
    backoff_seconds: float = 1.0,
    sleeps: list[float] | None = None,
) -> tuple[InstrumentedPort, ScriptedPort, AuditRecorder, BudgetTracker]:
    inner = ScriptedPort(outcomes)
    own_recorder = recorder or AuditRecorder()
    own_tracker = tracker or BudgetTracker(max_stage_calls=200, max_tokens=1_000_000)
    sleep_log = sleeps if sleeps is not None else []

    async def _record_sleep(seconds: float) -> None:
        sleep_log.append(seconds)

    port = InstrumentedPort(
        inner,
        model_id="model-a",
        round_no=1,
        recorder=own_recorder,
        tracker=own_tracker,
        max_retries=max_retries,
        backoff_seconds=backoff_seconds,
        sleep=_record_sleep,
    )
    return port, inner, own_recorder, own_tracker


async def _call(port: InstrumentedPort) -> SkillLLMResponse:
    return await port.generate_json(
        template_id="seminar.reflect",
        system_prompt="system",
        user_content="user",
        max_tokens=100,
    )


async def test_success_first_try_records_one_attempt_pair() -> None:
    port, inner, recorder, tracker = _port([_ok_response()])
    response = await _call(port)
    assert response.attempts == 1
    assert inner.calls == 1
    assert tracker.stage_calls_used == 1
    kinds = [event.kind for event in recorder.pending]
    assert kinds == [
        AuditEventKind.STAGE_CALL_STARTED,
        AuditEventKind.STAGE_CALL_FINISHED,
    ]
    finished = recorder.pending[1]
    assert finished.detail["outcome"] == "ok"
    assert finished.detail["attempt"] == 1
    assert finished.model_id == "model-a"
    assert finished.round_no == 1
    assert finished.stage == "seminar.reflect"
    assert finished.stage_call_id == recorder.pending[0].stage_call_id
    assert finished.detail["duration_ms"] >= 0.0


async def test_timeout_retries_then_succeeds_with_backoff() -> None:
    sleeps: list[float] = []
    port, inner, recorder, _ = _port(
        [TimeoutError("slow"), TimeoutError("slow"), _ok_response()],
        backoff_seconds=1.0,
        sleeps=sleeps,
    )
    response = await _call(port)
    assert response.attempts == 3
    assert inner.calls == 3
    assert sleeps == [1.0, 1.0]
    kinds = [event.kind for event in recorder.pending]
    assert kinds == [
        AuditEventKind.STAGE_CALL_STARTED,
        AuditEventKind.STAGE_CALL_FINISHED,
        AuditEventKind.RETRY,
        AuditEventKind.STAGE_CALL_STARTED,
        AuditEventKind.STAGE_CALL_FINISHED,
        AuditEventKind.RETRY,
        AuditEventKind.STAGE_CALL_STARTED,
        AuditEventKind.STAGE_CALL_FINISHED,
    ]
    finished = [event for event in recorder.pending if event.kind == "stage_call_finished"]
    assert [event.detail["outcome"] for event in finished] == ["timeout", "timeout", "ok"]
    assert [event.detail["attempt"] for event in finished] == [1, 2, 3]
    assert len({event.stage_call_id for event in recorder.pending}) == 1
    retries = [event for event in recorder.pending if event.kind == "retry"]
    assert retries[0].detail["next_attempt"] == 2
    assert retries[1].detail["next_attempt"] == 3
    assert retries[0].detail["error_kind"] == "timeout"


async def test_timeout_retry_exhaustion_raises_after_three_attempts() -> None:
    port, inner, recorder, tracker = _port(
        [TimeoutError("slow")] * 4, max_retries=2, backoff_seconds=0.0
    )
    with pytest.raises(TimeoutError):
        await _call(port)
    assert inner.calls == 3
    assert tracker.stage_calls_used == 3
    finished = [event for event in recorder.pending if event.kind == "stage_call_finished"]
    assert len(finished) == 3
    assert all(event.detail["outcome"] == "timeout" for event in finished)
    assert len([e for e in recorder.pending if e.kind == "retry"]) == 2


async def test_zero_retries_means_one_attempt() -> None:
    port, inner, recorder, _ = _port(
        [TimeoutError("slow"), _ok_response()], max_retries=0, backoff_seconds=0.0
    )
    with pytest.raises(TimeoutError):
        await _call(port)
    assert inner.calls == 1
    assert not [e for e in recorder.pending if e.kind == "retry"]


async def test_generic_exception_is_never_retried() -> None:
    port, inner, recorder, _ = _port([ValueError("boom"), _ok_response()])
    with pytest.raises(ValueError):
        await _call(port)
    assert inner.calls == 1
    assert not [e for e in recorder.pending if e.kind == "retry"]
    finished = [e for e in recorder.pending if e.kind == "stage_call_finished"]
    assert finished[0].detail["outcome"] == "error"


async def test_cancellation_is_never_retried() -> None:
    port, inner, recorder, _ = _port([asyncio.CancelledError(), _ok_response()])
    with pytest.raises(asyncio.CancelledError):
        await _call(port)
    assert inner.calls == 1
    assert not [e for e in recorder.pending if e.kind == "retry"]
    finished = [e for e in recorder.pending if e.kind == "stage_call_finished"]
    assert finished[0].detail["outcome"] == "cancelled"


async def test_empty_payload_is_not_retried_by_the_wrapper() -> None:
    # A returned response (even with payload None) means the CALL
    # succeeded; contract failure is the stage runner's business.
    port, inner, recorder, _ = _port(
        [SkillLLMResponse(model="fake", payload=None), _ok_response()]
    )
    response = await _call(port)
    assert response.payload is None
    assert inner.calls == 1
    assert not [e for e in recorder.pending if e.kind == "retry"]


async def test_usage_is_recorded_on_finished_events_and_tracker() -> None:
    usage = TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    port, _, recorder, tracker = _port([_ok_response(usage=usage)])
    response = await _call(port)
    assert response.usage == usage
    assert tracker.tokens_used == 15
    finished = [e for e in recorder.pending if e.kind == "stage_call_finished"]
    assert finished[0].detail["usage"] == {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
    }
    assert finished[0].detail["budget"]["tokens_used"] == 15


async def test_stage_call_budget_blocks_before_the_call_runs() -> None:
    tracker = BudgetTracker(max_stage_calls=2, max_tokens=1_000_000)
    port, inner, recorder, _ = _port([_ok_response()] * 4, tracker=tracker)
    await _call(port)
    await _call(port)
    with pytest.raises(BudgetExhaustedError) as excinfo:
        await _call(port)
    assert excinfo.value.budget == "max_stage_calls"
    assert excinfo.value.used == 2
    assert excinfo.value.limit == 2
    assert inner.calls == 2
    exhausted = [e for e in recorder.pending if e.kind == "budget_exhausted"]
    assert len(exhausted) == 1
    assert exhausted[0].detail["budget"] == "max_stage_calls"
    assert exhausted[0].detail["used"] == 2


async def test_retry_attempts_consume_stage_call_budget() -> None:
    tracker = BudgetTracker(max_stage_calls=2, max_tokens=1_000_000)
    port, inner, _, _ = _port(
        [TimeoutError("slow"), _ok_response(), _ok_response()],
        tracker=tracker,
        backoff_seconds=0.0,
    )
    response = await _call(port)
    assert response.attempts == 2
    assert inner.calls == 2
    with pytest.raises(BudgetExhaustedError):
        await _call(port)
    assert inner.calls == 2


async def test_token_budget_blocks_the_call_after_the_limit_is_reached() -> None:
    tracker = BudgetTracker(max_stage_calls=200, max_tokens=1000)
    usage = TokenUsage(prompt_tokens=600, completion_tokens=0, total_tokens=600)
    port, inner, _, _ = _port([_ok_response(usage=usage)] * 3, tracker=tracker)
    await _call(port)  # 600 used; under the limit at check time
    await _call(port)  # 1200 used; the call itself still ran
    with pytest.raises(BudgetExhaustedError) as excinfo:
        await _call(port)
    assert excinfo.value.budget == "max_tokens"
    assert excinfo.value.used == 1200
    assert inner.calls == 2


async def test_budget_check_runs_before_each_retry_attempt() -> None:
    tracker = BudgetTracker(max_stage_calls=1, max_tokens=1_000_000)
    port, inner, recorder, _ = _port(
        [TimeoutError("slow"), _ok_response()], tracker=tracker, backoff_seconds=0.0
    )
    # Attempt 1 times out (budget now used up); the retry is blocked
    # by the budget instead of running.
    with pytest.raises(BudgetExhaustedError):
        await _call(port)
    assert inner.calls == 1
    assert [e.kind for e in recorder.pending].count("budget_exhausted") == 1


def test_tracker_position_reports_remaining() -> None:
    tracker = BudgetTracker(max_stage_calls=10, max_tokens=100, stage_calls_used=3, tokens_used=40)
    assert tracker.position() == {
        "stage_calls_used": 3,
        "stage_calls_remaining": 7,
        "tokens_used": 40,
        "tokens_remaining": 60,
    }
    tracker.record_completed_call(total_tokens=70)
    assert tracker.position()["tokens_remaining"] == 0


def test_tracker_check_allows_calls_within_budget() -> None:
    tracker = BudgetTracker(max_stage_calls=1, max_tokens=100)
    tracker.check_before_call()  # must not raise
    tracker.record_completed_call(total_tokens=0)
    with pytest.raises(BudgetExhaustedError):
        tracker.check_before_call()


async def test_finished_detail_records_the_port_reported_finish_reason() -> None:
    # Fix batch 2: the stage_call_finished detail carries finish_reason
    # when the port reports it, so a truncated call is visible in the
    # audit even before the stage runner classifies it.
    port, _, recorder, _ = _port(
        [SkillLLMResponse(model="fake", payload={"ok": True}, finish_reason="stop")]
    )
    response = await _call(port)
    assert response.finish_reason == "stop"
    finished = recorder.pending[1]
    assert finished.detail["finish_reason"] == "stop"


async def test_finished_detail_records_null_finish_reason_when_unreported() -> None:
    # Ports that do not report a finish reason (older fakes, providers
    # without the field) record null — absence, not a fabricated value.
    port, _, recorder, _ = _port([_ok_response()])
    await _call(port)
    finished = recorder.pending[1]
    assert finished.detail["finish_reason"] is None


# --- Response-level retries (retry track) ----------------------------------
# Truncation and empty responses surface as RETURNED responses with
# payload None, not exceptions — the wrapper retries them on their
# signals, under the same max-2 + fixed-backoff + audit treatment as
# timeouts. Malformed content never retries.


async def test_truncated_response_retries_then_succeeds_with_backoff() -> None:
    sleeps: list[float] = []
    port, inner, recorder, _ = _port(
        [_truncated_response(), _ok_response()],
        backoff_seconds=1.0,
        sleeps=sleeps,
    )
    response = await _call(port)
    assert response.attempts == 2
    assert response.payload == {"ok": True}
    assert inner.calls == 2
    assert sleeps == [1.0]
    finished = [e for e in recorder.pending if e.kind == "stage_call_finished"]
    assert [e.detail["outcome"] for e in finished] == ["truncated", "ok"]
    retries = [e for e in recorder.pending if e.kind == "retry"]
    assert len(retries) == 1
    assert retries[0].detail["error_kind"] == "truncated"
    assert retries[0].detail["next_attempt"] == 2
    # The retry reason names the truncation and the requested cap.
    assert "truncated" in retries[0].detail["error_message"]
    assert "100" in retries[0].detail["error_message"]


async def test_empty_response_retries_then_succeeds() -> None:
    sleeps: list[float] = []
    port, inner, recorder, _ = _port(
        [_empty_response(), _ok_response()],
        backoff_seconds=1.0,
        sleeps=sleeps,
    )
    response = await _call(port)
    assert response.attempts == 2
    assert response.payload == {"ok": True}
    assert inner.calls == 2
    assert sleeps == [1.0]
    finished = [e for e in recorder.pending if e.kind == "stage_call_finished"]
    assert [e.detail["outcome"] for e in finished] == ["empty_response", "ok"]
    retries = [e for e in recorder.pending if e.kind == "retry"]
    assert len(retries) == 1
    assert retries[0].detail["error_kind"] == "empty_response"
    assert "empty response" in retries[0].detail["error_message"]


async def test_truncated_response_exhaustion_returns_last_response() -> None:
    port, inner, recorder, tracker = _port(
        [_truncated_response()] * 4, max_retries=2, backoff_seconds=0.0
    )
    # Exhaustion returns the last unusable response (it does not
    # raise): the stage runner raises the truncation error.
    response = await _call(port)
    assert response.payload is None
    assert response.attempts == 3
    assert inner.calls == 3
    assert tracker.stage_calls_used == 3
    finished = [e for e in recorder.pending if e.kind == "stage_call_finished"]
    assert len(finished) == 3
    assert all(e.detail["outcome"] == "truncated" for e in finished)
    assert len([e for e in recorder.pending if e.kind == "retry"]) == 2


async def test_empty_response_exhaustion_returns_last_response() -> None:
    port, inner, recorder, _ = _port(
        [_empty_response()] * 4, max_retries=2, backoff_seconds=0.0
    )
    response = await _call(port)
    assert response.payload is None
    assert response.empty_response is True
    assert response.attempts == 3
    assert inner.calls == 3
    finished = [e for e in recorder.pending if e.kind == "stage_call_finished"]
    assert all(e.detail["outcome"] == "empty_response" for e in finished)
    retries = [e for e in recorder.pending if e.kind == "retry"]
    assert len(retries) == 2
    assert all(e.detail["error_kind"] == "empty_response" for e in retries)


async def test_malformed_response_is_not_retried_and_records_contract_outcome() -> None:
    # Payload None with neither signal: content arrived but did not
    # parse. Never retried; the finished outcome names the contract
    # failure the stage runner is about to raise.
    port, inner, recorder, _ = _port([_malformed_response(), _ok_response()])
    response = await _call(port)
    assert response.payload is None
    assert inner.calls == 1
    assert not [e for e in recorder.pending if e.kind == "retry"]
    finished = [e for e in recorder.pending if e.kind == "stage_call_finished"]
    assert finished[0].detail["outcome"] == "contract"


async def test_budget_check_runs_before_each_response_retry() -> None:
    tracker = BudgetTracker(max_stage_calls=1, max_tokens=1_000_000)
    port, inner, recorder, _ = _port(
        [_truncated_response(), _ok_response()], tracker=tracker, backoff_seconds=0.0
    )
    # Attempt 1 truncates (budget now used up); the retry is blocked
    # by the budget instead of running — same as the timeout case.
    with pytest.raises(BudgetExhaustedError):
        await _call(port)
    assert inner.calls == 1
    assert [e.kind for e in recorder.pending].count("budget_exhausted") == 1
    # The retry was scheduled (its reason recorded) before the budget
    # check blocked it.
    retries = [e for e in recorder.pending if e.kind == "retry"]
    assert len(retries) == 1
    assert retries[0].detail["error_kind"] == "truncated"


async def test_raised_truncation_error_is_retried_with_true_kind() -> None:
    # Defense in depth: a wrapped port that RAISES the truncation
    # error retries, and the audit names truncation, not timeout.
    port, inner, recorder, _ = _port(
        [SkillTruncatedError("t", max_tokens=8000), _ok_response()],
        backoff_seconds=0.0,
    )
    response = await _call(port)
    assert response.attempts == 2
    assert inner.calls == 2
    finished = [e for e in recorder.pending if e.kind == "stage_call_finished"]
    assert [e.detail["outcome"] for e in finished] == ["truncated", "ok"]
    retries = [e for e in recorder.pending if e.kind == "retry"]
    assert retries[0].detail["error_kind"] == "truncated"


async def test_raised_empty_response_error_is_retried_with_true_kind() -> None:
    port, inner, recorder, _ = _port(
        [SkillEmptyResponseError("t"), _ok_response()],
        backoff_seconds=0.0,
    )
    response = await _call(port)
    assert response.attempts == 2
    assert inner.calls == 2
    finished = [e for e in recorder.pending if e.kind == "stage_call_finished"]
    assert [e.detail["outcome"] for e in finished] == ["empty_response", "ok"]
    retries = [e for e in recorder.pending if e.kind == "retry"]
    assert retries[0].detail["error_kind"] == "empty_response"


async def test_truncated_attempt_usage_is_accounted_in_the_budget() -> None:
    usage = TokenUsage(prompt_tokens=100, completion_tokens=8000, total_tokens=8100)
    tracker = BudgetTracker(max_stage_calls=200, max_tokens=1_000_000)
    port, _, recorder, _ = _port(
        [_truncated_response(usage=usage), _ok_response(usage=usage)],
        tracker=tracker,
        backoff_seconds=0.0,
    )
    await _call(port)
    # Both attempts consumed tokens, including the truncated one.
    assert tracker.tokens_used == 2 * 8100
    finished = [e for e in recorder.pending if e.kind == "stage_call_finished"]
    assert finished[0].detail["usage"]["completion_tokens"] == 8000
    assert finished[0].detail["budget"]["tokens_used"] == 8100


async def test_finished_detail_records_empty_response_flag() -> None:
    port, _, recorder, _ = _port([_empty_response(), _ok_response()], backoff_seconds=0.0)
    await _call(port)
    finished = [e for e in recorder.pending if e.kind == "stage_call_finished"]
    assert finished[0].detail["empty_response"] is True
    assert finished[1].detail["empty_response"] is False


async def test_mixed_timeout_then_truncated_retries_with_per_attempt_kinds() -> None:
    # The kinds compose in one loop: each attempt's retry event names
    # its own reason.
    port, inner, recorder, _ = _port(
        [TimeoutError("slow"), _truncated_response(), _ok_response()],
        backoff_seconds=0.0,
    )
    response = await _call(port)
    assert response.attempts == 3
    assert inner.calls == 3
    finished = [e for e in recorder.pending if e.kind == "stage_call_finished"]
    assert [e.detail["outcome"] for e in finished] == ["timeout", "truncated", "ok"]
    retries = [e for e in recorder.pending if e.kind == "retry"]
    assert [e.detail["error_kind"] for e in retries] == ["timeout", "truncated"]
