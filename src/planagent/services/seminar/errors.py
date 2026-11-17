"""Seminar error taxonomy (Sprint 18, design §10.2).

The formal taxonomy S16 deferred: every seminar failure is classified
into exactly one kind, used consistently across round errors,
finalize errors, report absent-model reasons, and audit events. The
kinds:

* ``timeout`` — a stage call exceeded its timeout (including SDK
  internal retries exhausted). Retryable.
* ``contract`` — output arrived but failed contract validation, or
  arrived malformed (non-empty content that did not parse). Never
  retried: the same prompt will most likely fail again.
* ``truncated`` — the provider cut the output at the token cap
  (``finish_reason="length"``), so the JSON is incomplete by
  construction (fix batch 2). Retryable (retry track): sampling
  variance may produce an output that fits the cap on a re-call;
  the retry is bounded (max 2, budget-checked, audited) and
  exhaustion still classifies as ``truncated``.
* ``empty_response`` — the upstream returned no content at all
  (no choices, or empty/whitespace-only content), as the port
  affirmatively reports it (retry track; the 2026-11-17 live
  failure). Retryable: a transient upstream gap, not a property
  of the prompt. A bare payload-None response with no signal is
  NOT this kind — it stays ``contract``.
* ``unavailable`` — no endpoint configured / auth failure / 5xx
  collapsed by the port into an empty response. Never retried.
* ``budget_exhausted`` — a seminar budget (stage calls or tokens)
  blocked the call before it ran. Never retried; recorded, never
  silent.
* ``cancelled`` — the caller cancelled, or the engine wait timed
  out. Classified like a timeout for diagnosis, but NEVER retried:
  retrying a cancellation would swallow the cancel.
* ``error`` — anything else (an unexpected exception). Never
  retried; the message is preserved for diagnosis.

Retryable kinds are ``timeout``, ``truncated``, and
``empty_response`` — see :func:`is_retryable_error`. The retry
wrapper retries both raised failures of these kinds AND returned
responses carrying their signals (``finish_reason="length"``,
``empty_response``); malformed content is never retried.

Queue waits are NOT an error kind: a synthesize request waiting for
the per-seminar lock is recorded as a ``queue_wait`` audit event
(see :mod:`planagent.services.seminar.audit`), and a request that
proceeds after waiting is not a failure.
"""

from __future__ import annotations

import asyncio
from enum import Enum

from planagent.services.skills.contracts import SkillEmptyResponseError, SkillTruncatedError


class ErrorKind(str, Enum):
    """The seminar failure taxonomy (design §10.2, formalized S18)."""

    TIMEOUT = "timeout"
    CONTRACT = "contract"
    TRUNCATED = "truncated"
    EMPTY_RESPONSE = "empty_response"
    UNAVAILABLE = "unavailable"
    BUDGET_EXHAUSTED = "budget_exhausted"
    CANCELLED = "cancelled"
    ERROR = "error"


class BudgetExhaustedError(RuntimeError):
    """A seminar budget blocked a stage call before it ran.

    Raised by the budget guard (see
    :mod:`planagent.services.seminar.instrumentation`) carrying which
    budget tripped and the used/limit figures, so the audit event and
    the round error can both name the exact cause.
    """

    def __init__(self, *, budget: str, used: int, limit: int) -> None:
        self.budget = budget
        self.used = used
        self.limit = limit
        super().__init__(
            f"Seminar budget exhausted: {budget} used {used} of {limit}; "
            "the stage call was not made."
        )


def is_timeout_exception(exc: BaseException) -> bool:
    """True when an exception is a timeout (retryable).

    Covers stdlib/asyncio timeouts and the OpenAI SDK timeout error.
    ``CancelledError`` is deliberately NOT a timeout here: it
    classifies as ``cancelled`` for diagnosis but must never be
    retried.
    """
    if isinstance(exc, asyncio.CancelledError):
        return False
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return True
    # The OpenAI SDK timeout error; imported lazily so this module
    # stays importable without the SDK on the path in principle, and
    # matched by class name so a differently-imported SDK class still
    # classifies. APITimeoutError does not inherit TimeoutError.
    return type(exc).__name__ == "APITimeoutError"


def is_retryable_error(exc: BaseException) -> bool:
    """True for the retryable failure kinds (design §10.3, retry track).

    Timeouts, truncations, and empty upstream responses are retried:
    all three are transient — a re-call may succeed. Contract
    failures (malformed content), unavailability, budget exhaustion,
    and cancellations are never retried.
    """
    if is_timeout_exception(exc):
        return True
    # Truncation and empty-response errors are distinct classes (both
    # subclass SkillContractError, so they must be matched before any
    # plain-contract check by callers that distinguish them).
    return isinstance(exc, (SkillTruncatedError, SkillEmptyResponseError))


__all__ = [
    "BudgetExhaustedError",
    "ErrorKind",
    "is_retryable_error",
    "is_timeout_exception",
]
