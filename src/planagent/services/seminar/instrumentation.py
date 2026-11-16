"""Stage-call instrumentation (Sprint 18): retries, budgets, audit.

:class:`InstrumentedPort` wraps any :class:`SkillLLMPort` and is the
single choke point for every seminar stage call — analysis stages
(via ``run_stage``), reflection, verdict, cluster, and synthesize all
flow through ``generate_json``. It provides, in one place:

* **Timeout-only retries** (design §10.3): a stage call that raises
  a timeout is retried up to ``max_retries`` times with a fixed
  backoff. Contract failures, unavailability, budget exhaustion, and
  cancellations are never retried. Every attempt is recorded.
* **Budgets** (design §10.3): before every ATTEMPT, the shared
  :class:`BudgetTracker` is checked — stage-call count and tokens
  consumed so far, seeded from the audit ledger at operation start
  so budgets hold across waves. A tripped budget raises
  :class:`BudgetExhaustedError` before the call runs, and the
  exhaustion is recorded. Token usage is only known AFTER a call
  returns, so a call that pushes usage over the token limit still
  completes; the NEXT call is blocked. This is the honest
  check-before-call semantic: the guard never invents a prediction.
* **Audit observation**: every attempt writes a
  ``stage_call_started`` / ``stage_call_finished`` event pair (plus
  a ``retry`` event when a retry is scheduled) into the shared
  :class:`~planagent.services.seminar.audit.AuditRecorder`, with
  duration, token usage, outcome, and the budget position. The
  recorder flushes with the operation's state change.
* **Attempt accounting**: the returned response carries
  ``attempts`` (total attempts the logical call took) and the
  port-reported ``usage``, so stage runners can store both on the
  :class:`StageRecord`.

The wrapper is synchronous between the budget check and the wrapped
call: within one event loop, no other task can interleave between
"check" and "call", so concurrent models in one wave cannot
overshoot the budget past one in-flight call each. The tracker is
shared across all models of one operation (one wave / finalize /
synthesize), and seeded from the persisted audit ledger, so the
budget is per-seminar, not per-wave.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace

from planagent.domain.models import generate_id
from planagent.services.seminar.audit import AuditEventKind, AuditRecorder
from planagent.services.seminar.errors import (
    BudgetExhaustedError,
    ErrorKind,
    is_retryable_error,
)
from planagent.services.skills.orchestration import SkillLLMPort, SkillLLMResponse


@dataclass
class BudgetTracker:
    """Per-seminar budget state for one operation.

    Seeded from the audit ledger (calls + tokens consumed by earlier
    operations) and mutated as this operation's calls complete, so
    concurrent models in one wave share one budget position.
    """

    max_stage_calls: int
    max_tokens: int
    stage_calls_used: int = 0
    tokens_used: int = 0

    def check_before_call(self) -> None:
        """Raise before a call that would exceed a budget.

        The stage-call check counts the call about to run; the token
        check blocks only when already-consumed tokens have reached
        the limit (a call's own tokens are unknowable beforehand).
        """
        if self.stage_calls_used + 1 > self.max_stage_calls:
            raise BudgetExhaustedError(
                budget="max_stage_calls",
                used=self.stage_calls_used,
                limit=self.max_stage_calls,
            )
        if self.tokens_used >= self.max_tokens:
            raise BudgetExhaustedError(
                budget="max_tokens",
                used=self.tokens_used,
                limit=self.max_tokens,
            )

    def record_completed_call(self, *, total_tokens: int) -> None:
        """Account one finished attempt (success or failure).

        Attempts that fail still consumed a call (and possibly
        tokens, when the port reports them).
        """
        self.stage_calls_used += 1
        self.tokens_used += max(0, total_tokens)

    def position(self) -> dict[str, int]:
        return {
            "stage_calls_used": self.stage_calls_used,
            "stage_calls_remaining": max(0, self.max_stage_calls - self.stage_calls_used),
            "tokens_used": self.tokens_used,
            "tokens_remaining": max(0, self.max_tokens - self.tokens_used),
        }


class InstrumentedPort:
    """A SkillLLMPort wrapper adding retries, budgets, and audit."""

    def __init__(
        self,
        wrapped: SkillLLMPort,
        *,
        model_id: str,
        round_no: int | None,
        recorder: AuditRecorder,
        tracker: BudgetTracker,
        max_retries: int = 2,
        backoff_seconds: float = 1.0,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._wrapped = wrapped
        self._model_id = model_id
        self._round_no = round_no
        self._recorder = recorder
        self._tracker = tracker
        self._max_retries = max_retries
        self._backoff_seconds = backoff_seconds
        self._sleep = sleep or asyncio.sleep

    def is_available(self) -> bool:
        return self._wrapped.is_available()

    async def generate_json(
        self,
        *,
        template_id: str,
        system_prompt: str,
        user_content: str,
        max_tokens: int,
    ) -> SkillLLMResponse:
        stage_call_id = generate_id()
        for attempt in range(1, self._max_retries + 2):
            try:
                self._tracker.check_before_call()
            except BudgetExhaustedError as exc:
                self._recorder.record(
                    AuditEventKind.BUDGET_EXHAUSTED,
                    model_id=self._model_id,
                    stage=template_id,
                    detail={
                        "budget": exc.budget,
                        "used": exc.used,
                        "limit": exc.limit,
                        "stage_call_id": stage_call_id,
                        "attempt": attempt,
                    },
                    round_no=self._round_no,
                    stage_call_id=stage_call_id,
                )
                raise
            self._recorder.record(
                AuditEventKind.STAGE_CALL_STARTED,
                model_id=self._model_id,
                stage=template_id,
                detail={"stage_call_id": stage_call_id, "attempt": attempt},
                round_no=self._round_no,
                stage_call_id=stage_call_id,
            )
            started = time.monotonic()
            try:
                response = await self._wrapped.generate_json(
                    template_id=template_id,
                    system_prompt=system_prompt,
                    user_content=user_content,
                    max_tokens=max_tokens,
                )
            except BaseException as exc:  # noqa: BLE001 — outcome recorded, then re-raised
                duration_ms = (time.monotonic() - started) * 1000.0
                outcome = _outcome_of(exc)
                self._tracker.record_completed_call(total_tokens=0)
                self._recorder.record(
                    AuditEventKind.STAGE_CALL_FINISHED,
                    model_id=self._model_id,
                    stage=template_id,
                    detail={
                        "stage_call_id": stage_call_id,
                        "attempt": attempt,
                        "duration_ms": duration_ms,
                        "outcome": outcome,
                        "error_message": str(exc)[:300],
                        "budget": self._tracker.position(),
                    },
                    round_no=self._round_no,
                    stage_call_id=stage_call_id,
                )
                if is_retryable_error(exc) and attempt <= self._max_retries:
                    self._recorder.record(
                        AuditEventKind.RETRY,
                        model_id=self._model_id,
                        stage=template_id,
                        detail={
                            "stage_call_id": stage_call_id,
                            "attempt": attempt,
                            "next_attempt": attempt + 1,
                            "backoff_seconds": self._backoff_seconds,
                            "error_kind": ErrorKind.TIMEOUT.value,
                            "error_message": str(exc)[:300],
                        },
                        round_no=self._round_no,
                        stage_call_id=stage_call_id,
                    )
                    await self._sleep(self._backoff_seconds)
                    continue
                raise
            duration_ms = (time.monotonic() - started) * 1000.0
            usage = response.usage.to_dict() if response.usage is not None else None
            total_tokens = int(response.usage.total_tokens) if response.usage is not None else 0
            self._tracker.record_completed_call(total_tokens=total_tokens)
            self._recorder.record(
                AuditEventKind.STAGE_CALL_FINISHED,
                model_id=self._model_id,
                stage=template_id,
                detail={
                    "stage_call_id": stage_call_id,
                    "attempt": attempt,
                    "duration_ms": duration_ms,
                    "outcome": "ok",
                    "usage": usage,
                    "budget": self._tracker.position(),
                },
                round_no=self._round_no,
                stage_call_id=stage_call_id,
            )
            return replace(response, attempts=attempt)
        # Unreachable: the loop either returns or raises on every path.
        raise RuntimeError("InstrumentedPort retry loop fell through without returning.")


def _outcome_of(exc: BaseException) -> str:
    if isinstance(exc, asyncio.CancelledError):
        return ErrorKind.CANCELLED.value
    if is_retryable_error(exc):
        return ErrorKind.TIMEOUT.value
    if isinstance(exc, BudgetExhaustedError):
        return ErrorKind.BUDGET_EXHAUSTED.value
    return ErrorKind.ERROR.value


__all__ = ["BudgetTracker", "InstrumentedPort"]
