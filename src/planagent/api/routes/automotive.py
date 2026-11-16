"""Automotive endpoints (Phase 2).

Three read/compute surfaces over stored runs — all explicit, none
backgrounded (Sprint 9 automation boundary):

- ``GET /runs/{id}/automotive/trajectory``: the run's stored snapshot
  states per tick (read-only; unlike the replay package it writes no
  record). Any run status is readable; the response carries the status
  so partial trajectories are never mistaken for complete ones.
- ``POST /runs/{id}/automotive/sales-layer``: the S-layer computation
  wired to the run's simulated production trajectory (Phase 2 item a).
  Requires a COMPLETED automotive run with a stored split structure;
  writes nothing. A policy shock that moves production moves the
  computed sales figures through this call.
- ``POST /automotive/prompts/evaluate``: co-occurrence prompts over a
  submitted split structure, without creating a run. Shape-validated
  only (422 on malformed JSON) — prompts are diagnostics, not gates;
  sum-gate validation remains the run-creation gate's job.
- ``GET /automotive/expectations``: the expectation catalog (rule ids,
  normal logic, strength, scope, evidence) for display.

Error mapping follows the Sprint 9/11 pattern: named ``{"code",
"message"}`` details on 400, ``LookupError``-style 404 for a missing
run.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from planagent.db import get_session
from planagent.domain.enums import SimulationRunStatus
from planagent.domain.models import SimulationRun, StateSnapshotRecord
from planagent.services.splits import (
    PromptReport,
    SalesLayerComputation,
    SplitStructure,
    SplitValidationError,
    compute_sales_layer,
    evaluate_prompts,
    expectation_catalog,
)
from planagent.services.splits.sales_layer import extract_production_trajectory

router = APIRouter()


class TrajectoryPoint(BaseModel):
    """One stored snapshot state (first actor per tick when several)."""

    model_config = ConfigDict(extra="forbid")

    tick: int
    actor_id: str
    state: dict[str, float]


class AutomotiveTrajectoryRead(BaseModel):
    """A run's stored trajectory (read-only, writes nothing)."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    domain_id: str
    run_status: str
    tick_count: int
    multiple_actors: bool
    actor_ids: list[str]
    points: list[TrajectoryPoint]


class SupplyShareOverride(BaseModel):
    """One (OEM, product) supply-share override for share attribution."""

    model_config = ConfigDict(extra="forbid")

    oem_id: str = Field(min_length=1)
    product_id: str = Field(min_length=1)
    share: float = Field(ge=0.0, le=1.0)


class SalesLayerRequest(BaseModel):
    """S-layer computation inputs (the trajectory comes from snapshots)."""

    model_config = ConfigDict(extra="forbid")

    oem_production_shares: dict[str, float] = Field(min_length=1)
    own_supplier_id: str | None = None
    supply_shares: list[SupplyShareOverride] = Field(default_factory=list)
    default_supply_share: float | None = Field(default=None, ge=0.0, le=1.0)
    strict_prices: bool = True


class SalesLayerRead(SalesLayerComputation):
    """The S-layer computation plus the run it was computed from."""

    run_id: str
    domain_id: str
    snapshot_tick_count: int


class PromptsEvaluateRequest(BaseModel):
    """A split structure to evaluate prompts over (no run created)."""

    model_config = ConfigDict(extra="forbid")

    split_structure: SplitStructure
    dms_mandate_on: bool | None = None


def _automotive_error(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=400, detail={"code": code, "message": message})


async def _load_automotive_run(session: AsyncSession, run_id: str) -> SimulationRun:
    run = await session.get(SimulationRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Simulation run {run_id} was not found.")
    if run.domain_id != "automotive":
        raise _automotive_error(
            "automotive_domain_required",
            f"Run {run_id} has domain {run.domain_id!r}; automotive endpoints require 'automotive'.",
        )
    return run


async def _load_snapshots(
    session: AsyncSession, run_id: str
) -> list[StateSnapshotRecord]:
    return list(
        (
            await session.scalars(
                select(StateSnapshotRecord)
                .where(StateSnapshotRecord.run_id == run_id)
                .order_by(StateSnapshotRecord.tick.asc(), StateSnapshotRecord.actor_id.asc())
            )
        ).all()
    )


def _group_by_tick(
    snapshots: list[StateSnapshotRecord],
) -> list[tuple[int, dict[str, object]]]:
    """One (tick, state) per tick, refusing disagreeing same-tick states.

    Automotive runs carry one actor, hence one snapshot per tick. When
    several actors share a tick, their production volumes must agree;
    the first actor's full state represents the tick.
    """

    grouped: dict[int, list[StateSnapshotRecord]] = {}
    for snapshot in snapshots:
        grouped.setdefault(snapshot.tick, []).append(snapshot)
    tick_states: list[tuple[int, dict[str, object]]] = []
    for tick in sorted(grouped):
        records = grouped[tick]
        productions = {record.state.get("production_volume") for record in records}
        if len(productions) > 1:
            raise _automotive_error(
                "automotive_corrupt_snapshots",
                f"Snapshots at tick {tick} disagree on production_volume: {sorted(productions, key=str)}.",
            )
        tick_states.append((tick, records[0].state))
    return tick_states


def _sales_layer_error(exc: ValueError) -> HTTPException:
    message = str(exc)
    if message.startswith("Cannot compute capacity"):
        code = "automotive_unpriced_slot"
    elif "production share" in message or "production shares" in message:
        code = "automotive_invalid_oem_shares"
    elif "Supply share" in message or "supply share" in message:
        code = "automotive_invalid_supply_shares"
    elif "snapshot" in message or "trajectory" in message.lower():
        code = "automotive_corrupt_snapshots"
    else:
        code = "automotive_sales_layer_failed"
    return HTTPException(status_code=400, detail={"code": code, "message": message})


@router.get("/runs/{run_id}/automotive/trajectory", response_model=AutomotiveTrajectoryRead)
async def get_automotive_trajectory(
    run_id: str,
    session: AsyncSession = Depends(get_session),
) -> AutomotiveTrajectoryRead:
    run = await _load_automotive_run(session, run_id)
    snapshots = await _load_snapshots(session, run_id)
    if not snapshots:
        raise _automotive_error(
            "automotive_no_snapshots",
            f"Run {run_id} has no stored snapshots yet.",
        )
    tick_states = _group_by_tick(snapshots)
    actor_ids = sorted({snapshot.actor_id for snapshot in snapshots})
    try:
        points = [
            TrajectoryPoint(
                tick=tick,
                actor_id=next(
                    snapshot.actor_id for snapshot in snapshots if snapshot.tick == tick
                ),
                state={key: float(value) for key, value in state.items()},
            )
            for tick, state in tick_states
        ]
    except (TypeError, ValueError) as exc:
        raise _automotive_error(
            "automotive_corrupt_snapshots",
            f"Run {run_id} carries a non-numeric snapshot state value: {exc}",
        ) from exc
    return AutomotiveTrajectoryRead(
        run_id=run.id,
        domain_id=run.domain_id,
        run_status=run.status,
        tick_count=run.tick_count,
        multiple_actors=len(actor_ids) > 1,
        actor_ids=actor_ids,
        points=points,
    )


@router.post("/runs/{run_id}/automotive/sales-layer", response_model=SalesLayerRead)
async def compute_automotive_sales_layer(
    run_id: str,
    payload: SalesLayerRequest,
    session: AsyncSession = Depends(get_session),
) -> SalesLayerRead:
    run = await _load_automotive_run(session, run_id)
    if run.status != SimulationRunStatus.COMPLETED.value:
        raise _automotive_error(
            "automotive_run_not_completed",
            f"Run {run_id} has status {run.status!r}; the S-layer requires a COMPLETED run.",
        )
    configuration = run.configuration or {}
    fragment = configuration.get("split_structure")
    if fragment is None:
        raise _automotive_error(
            "automotive_no_split_structure",
            f"Run {run_id} carries no split structure; attach one at run creation.",
        )
    if not isinstance(fragment, dict) or "structure" not in fragment:
        raise _automotive_error(
            "automotive_corrupt_split_fragment",
            f"Run {run_id} carries a malformed split-structure fragment.",
        )
    try:
        structure = SplitStructure.model_validate(fragment["structure"])
    except ValueError as exc:
        raise _automotive_error(
            "automotive_corrupt_split_fragment",
            f"Run {run_id} carries a split structure that no longer parses: {exc}",
        ) from exc
    snapshots = await _load_snapshots(session, run_id)
    if not snapshots:
        raise _automotive_error(
            "automotive_no_snapshots",
            f"Run {run_id} has no stored snapshots.",
        )
    tick_states = _group_by_tick(snapshots)
    try:
        trajectory = extract_production_trajectory(tick_states)
        computation = compute_sales_layer(
            structure,
            trajectory,
            dict(payload.oem_production_shares),
            own_supplier_id=payload.own_supplier_id,
            supply_shares={
                (override.oem_id, override.product_id): override.share
                for override in payload.supply_shares
            }
            or None,
            default_supply_share=payload.default_supply_share,
            strict_prices=payload.strict_prices,
        )
    except SplitValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "split_validation_failed",
                "message": "Stored split structure failed validation; S-layer refused.",
                "validation": exc.result.model_dump(mode="json"),
            },
        ) from exc
    except ValueError as exc:
        raise _sales_layer_error(exc) from exc
    return SalesLayerRead(
        **computation.model_dump(),
        run_id=run.id,
        domain_id=run.domain_id,
        snapshot_tick_count=len(trajectory),
    )


@router.post("/automotive/prompts/evaluate", response_model=PromptReport)
async def evaluate_automotive_prompts(payload: PromptsEvaluateRequest) -> PromptReport:
    return evaluate_prompts(payload.split_structure, dms_mandate_on=payload.dms_mandate_on)


@router.get("/automotive/expectations")
async def get_automotive_expectations() -> list[dict]:
    return expectation_catalog()
