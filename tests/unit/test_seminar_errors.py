"""Error taxonomy tests (Sprint 18, design §10.2).

Pins the formal taxonomy: every failure classifies into exactly one
kind, and ONLY timeouts are retryable. CancelledError classifies as
``cancelled`` for diagnosis but is never retried.
"""

from __future__ import annotations

import asyncio

import httpx
from openai import APITimeoutError

from planagent.services.seminar.engine import classify_error
from planagent.services.seminar.errors import (
    BudgetExhaustedError,
    ErrorKind,
    is_retryable_error,
    is_timeout_exception,
)
from planagent.services.skills.contracts import SkillContractError, SkillTruncatedError
from planagent.services.skills.orchestration import SkillLLMUnavailable


def test_taxonomy_kinds_are_exactly_the_design_set() -> None:
    assert {kind.value for kind in ErrorKind} == {
        "timeout",
        "contract",
        "truncated",
        "unavailable",
        "budget_exhausted",
        "cancelled",
        "error",
    }


def test_classify_error_maps_each_failure_class() -> None:
    assert classify_error(TimeoutError("slow")) == "timeout"
    # asyncio.TimeoutError is an alias of TimeoutError since 3.11;
    # the alias spelling is pinned deliberately.
    assert classify_error(asyncio.TimeoutError()) == "timeout"  # noqa: UP041
    assert (
        classify_error(
            APITimeoutError(request=httpx.Request("POST", "https://example.invalid/v1"))
        )
        == "timeout"
    )
    assert classify_error(SkillContractError("t", [{"loc": (), "msg": "bad"}])) == "contract"
    # Truncation classifies distinctly even though SkillTruncatedError
    # subclasses SkillContractError (fix batch 2): the check order in
    # classify_error is the whole point.
    assert classify_error(SkillTruncatedError("t", max_tokens=8000)) == "truncated"
    assert classify_error(SkillLLMUnavailable("none")) == "unavailable"
    assert (
        classify_error(BudgetExhaustedError(budget="max_tokens", used=10, limit=10))
        == "budget_exhausted"
    )
    assert classify_error(asyncio.CancelledError()) == "cancelled"
    assert classify_error(ValueError("boom")) == "error"
    assert classify_error(RuntimeError("boom")) == "error"


def test_truncation_error_names_truncation_and_the_cap() -> None:
    # The message must name the true cause AND the cap, so a reader of
    # the audit never has to guess why the JSON was incomplete.
    exc = SkillTruncatedError("mckinsey.diagnose", max_tokens=8000)
    assert "truncated" in str(exc)
    assert "8000" in str(exc)
    assert exc.max_tokens == 8000
    assert exc.finish_reason == "length"
    assert exc.template_id == "mckinsey.diagnose"
    # Subclassing is deliberate: existing contract-error handlers
    # (skills 502 mapping, seminar failure isolation) keep catching it.
    assert isinstance(exc, SkillContractError)


def test_only_timeouts_are_retryable() -> None:
    assert is_retryable_error(TimeoutError("slow")) is True
    # Alias spelling pinned deliberately (see above).
    assert is_retryable_error(asyncio.TimeoutError()) is True  # noqa: UP041
    assert (
        is_retryable_error(
            APITimeoutError(request=httpx.Request("POST", "https://example.invalid/v1"))
        )
        is True
    )
    assert is_retryable_error(SkillContractError("t", [{"loc": (), "msg": "bad"}])) is False
    # Truncation is never retried under the current policy: the same
    # capped call would truncate again (fix batch 2).
    assert is_retryable_error(SkillTruncatedError("t", max_tokens=8000)) is False
    assert is_retryable_error(SkillLLMUnavailable("none")) is False
    assert (
        is_retryable_error(BudgetExhaustedError(budget="max_tokens", used=10, limit=10))
        is False
    )
    # Cancelled is classified like a timeout for diagnosis but must
    # never be retried: retrying a cancellation swallows the cancel.
    assert is_retryable_error(asyncio.CancelledError()) is False
    assert is_retryable_error(ValueError("boom")) is False


def test_is_timeout_exception_excludes_cancellation() -> None:
    assert is_timeout_exception(TimeoutError()) is True
    assert is_timeout_exception(asyncio.CancelledError()) is False


def test_budget_exhausted_error_carries_budget_figures() -> None:
    exc = BudgetExhaustedError(budget="max_stage_calls", used=200, limit=200)
    assert exc.budget == "max_stage_calls"
    assert exc.used == 200
    assert exc.limit == 200
    assert "max_stage_calls" in str(exc)
    assert "200" in str(exc)


def test_classify_error_never_returns_unknown_kind() -> None:
    for exc in [TimeoutError(), ValueError(), KeyError(), asyncio.CancelledError()]:
        assert classify_error(exc) in {kind.value for kind in ErrorKind}
