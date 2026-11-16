"""Seminar error taxonomy (Sprint 18, design §10.2).

The formal taxonomy S16 deferred: every seminar failure is classified
into exactly one kind, used consistently across round errors,
finalize errors, report absent-model reasons, and audit events. The
kinds:

* ``timeout`` — a stage call exceeded its timeout (including SDK
  internal retries exhausted). The ONLY retryable kind.
* ``contract`` — output arrived but failed contract validation.
  Never retried: the same prompt will most likely fail again.
* ``truncated`` — the provider cut the output at the token cap
  (``finish_reason="length"``), so the JSON is incomplete by
  construction (fix batch 2). Never retried under the current
  policy: retrying the same capped call would truncate again.
  Retry-on-truncation with a raised cap is a follow-up option,
  deliberately NOT implemented here.
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

Queue waits are NOT an error kind: a synthesize request waiting for
the per-seminar lock is recorded as a ``queue_wait`` audit event
(see :mod:`planagent.services.seminar.audit`), and a request that
proceeds after waiting is not a failure.
"""

from __future__ import annotations

import asyncio
from enum import Enum


class ErrorKind(str, Enum):
    """The seminar failure taxonomy (design §10.2, formalized S18)."""

    TIMEOUT = "timeout"
    CONTRACT = "contract"
    TRUNCATED = "truncated"
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
    """True only for timeout errors (design §10.3).

    Contract failures, truncations, unavailability, budget
    exhaustion, and cancellations are never retried.
    """
    return is_timeout_exception(exc)


__all__ = [
    "BudgetExhaustedError",
    "ErrorKind",
    "is_retryable_error",
    "is_timeout_exception",
]
