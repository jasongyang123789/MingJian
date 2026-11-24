"""Opportunity prompts + two-value output (Phase 4, Tracks 9–10; Step 4).

Two explicit, read-only surfaces over SUBMITTED review facts — no run
is created, nothing is stored, no background work (Sprint 9 automation
boundary):

- ``POST /opportunities/review``: the review-time T2–T4 breakout
  prompts (:func:`review_breakout_prompts`). T2 needs post-decision
  actuals, T3 diagnostic fitted values, T4 order data — monitoring
  review and backtest diagnosis call this instead of reaching for the
  individual checks. Every input is optional; a check with missing
  inputs stays silent.
- ``POST /opportunities/two-value``: the two-value output (Ho 2026-11-24
  10:51, corrected 10:55) from paired run outcomes — full outcome plus
  the leg-stripped outcomes from the frozen decomposition. (a) normal
  value + (b) opportunity-leg contribution, separately stated, never
  merged; ``combined_reference`` is the identity ``normal + opportunity
  = full outcome``, a reference, never a forecast. See
  :mod:`planagent.services.variables.opportunity_value` for the exact
  definitions (frozen vs adjusted normal, clean vs apparent
  contributions, interaction, ensemble gap, sizing provenance).

Both calls are pure functions of their input: same facts in, same
output out, in the same order. No DB, no LLM, no network.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from planagent.services.variables.opportunities import (
    BreakoutPrompt,
    FittedStretch,
    review_breakout_prompts,
)
from planagent.services.variables.opportunity_value import (
    TwoValueOutput,
    TwoValueRequest,
    compute_two_value_output,
)

router = APIRouter()


class ReviewRequest(BaseModel):
    """Review-time facts for the T2–T4 checks. All optional."""

    model_config = ConfigDict(extra="forbid")

    period_label: str = ""
    actual_first_year_growth: float | None = None
    modeled_first_year_growth: float | None = None
    fitted: list[FittedStretch] = Field(default_factory=list)
    orders_growth: float | None = None
    orders_to_revenue: float | None = None
    orders_label: str = ""


class ReviewResponse(BaseModel):
    """Review-time breakout prompts, in trigger order (T2, T3s, T4)."""

    model_config = ConfigDict(extra="forbid")

    prompts: list[BreakoutPrompt] = Field(default_factory=list)


@router.post("/opportunities/review", response_model=ReviewResponse)
async def review_opportunities(payload: ReviewRequest) -> ReviewResponse:
    """Run the review-time T2–T4 breakout checks over submitted facts."""
    return ReviewResponse(
        prompts=review_breakout_prompts(
            period_label=payload.period_label,
            actual_first_year_growth=payload.actual_first_year_growth,
            modeled_first_year_growth=payload.modeled_first_year_growth,
            fitted=payload.fitted,
            orders_growth=payload.orders_growth,
            orders_to_revenue=payload.orders_to_revenue,
            orders_label=payload.orders_label,
        )
    )


@router.post("/opportunities/two-value", response_model=TwoValueOutput)
async def two_value_output(payload: TwoValueRequest) -> TwoValueOutput:
    """Compute (a) normal + (b) opportunity from paired run outcomes.

    Paired records must share metric, unit, horizon tick, and (when
    given) seed and trials; a mismatch is a 422, never a silent mix.
    """
    try:
        return compute_two_value_output(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
