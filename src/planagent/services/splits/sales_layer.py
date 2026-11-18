"""S-layer computation wired to engine snapshots (Phase 2, item a).

Phase 1 left S-layer aggregation as pure helpers taking volumes as
arguments. This module wires them to the run: given a validated split
structure and the run's simulated PRODUCTION TRAJECTORY (read from
stored snapshots by the API layer), it computes monthly capacity and
own sales per (tick, OEM, product) automatically. A policy shock that
moves production moves the computed sales figures through the same
call — the whole chain is one deterministic computation over stored
snapshots, with no scheduler, worker, or background work (Sprint 9
automation boundary: the computation runs only when explicitly
requested over a COMPLETED run).

Volume spine: OEM PRODUCTION volume including Audi (Ho 2026-11-16);
the caller supplies the per-OEM production shares (which must sum
to 1) because the engine simulates the total, not the OEM split.
Per-nameplate generation schedules (see :mod:`schedules`) apply the
effective generation mix at each tick; unscheduled nameplates keep
their static shares.

Own-sales attribution follows Phase 1's two explicit paths:

- supplier-row attribution (``own_supplier_id``): Ho's sales are the
  capacity of the slots whose supplier row IS Ho; prospects are 0.
- simulated-share attribution (``supply_shares`` / ``default_share``):
  sales = full-market capacity x supply share; prospects are 0.

When neither attribution input is supplied, own sales are ``None``
with the reason recorded — never silently zero, never silently the
market total. When both are supplied, supplier-row attribution wins
(the finer-grained evidence) and the choice is recorded.

Prices: ``strict_prices=True`` (default) refuses the whole
computation on the first unpriced slot (Phase 1 loud-failure
discipline). With ``strict_prices=False`` unpriced slots are
skipped from capacity (units still computed) and listed in
``skipped_unpriced_slots``.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping

from pydantic import BaseModel, ConfigDict, Field

from .aggregation import (
    aggregate_capacity,
    aggregate_units,
    market_capacity_by_oem_product,
    own_sales_from_supplier_rows,
    own_sales_with_share,
)
from .models import SplitStructure
from .schedules import structure_with_effective_shares
from .validator import oem_share_issues, validate_or_raise


class SalesLayerRow(BaseModel):
    """One computed S-layer row: one (tick, OEM, product) cell."""

    model_config = ConfigDict(extra="forbid")

    tick: int
    oem_id: str
    product_id: str
    units: float
    capacity_value: float
    own_sales: float | None


class SalesLayerTickTotal(BaseModel):
    """Per-tick totals across OEMs and products."""

    model_config = ConfigDict(extra="forbid")

    tick: int
    production_volume: float
    units: float
    capacity_value: float
    own_sales: float | None


class SalesLayerSummary(BaseModel):
    """Totals across the whole trajectory."""

    model_config = ConfigDict(extra="forbid")

    total_units: float
    total_capacity_value: float
    total_own_sales: float | None
    tick_count: int
    oem_count: int
    product_count: int


class SalesLayerComputation(BaseModel):
    """The full S-layer computation over a run's production trajectory."""

    model_config = ConfigDict(extra="forbid")

    rows: list[SalesLayerRow] = Field(default_factory=list)
    per_tick: list[SalesLayerTickTotal] = Field(default_factory=list)
    summary: SalesLayerSummary
    production_trajectory: list[dict[str, float]] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    skipped_unpriced_slots: list[str] = Field(default_factory=list)
    own_sales_basis: str
    own_sales_unavailable_reason: str | None = None


def extract_production_trajectory(
    tick_states: Iterable[tuple[int, Mapping[str, object]]],
) -> dict[int, float]:
    """Production volumes per tick from snapshot (tick, state) pairs.

    Tick 0 is the initial state, not a monthly flow, and is excluded.
    Every tick >= 1 must carry a finite, non-negative
    ``production_volume``; duplicates or missing values refuse loudly.
    """

    trajectory: dict[int, float] = {}
    for tick, state in tick_states:
        if tick == 0:
            continue
        if tick in trajectory:
            raise ValueError(f"Duplicate snapshot for tick {tick}; snapshots are corrupt.")
        value = state.get("production_volume")
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) < 0
        ):
            raise ValueError(
                f"Snapshot at tick {tick} has no usable production_volume: {value!r}."
            )
        trajectory[tick] = float(value)
    if not trajectory:
        raise ValueError("No tick >= 1 snapshots found; the run produced no trajectory.")
    return trajectory


def compute_sales_layer(
    structure: SplitStructure,
    production_by_tick: dict[int, float],
    oem_production_shares: dict[str, float],
    *,
    own_supplier_id: str | None = None,
    supply_shares: dict[tuple[str, str], float] | None = None,
    default_supply_share: float | None = None,
    strict_prices: bool = True,
    shares_source: str = "caller-supplied",
) -> SalesLayerComputation:
    """Compute monthly capacity + own sales over a production trajectory.

    ``production_by_tick`` maps 1-based ticks to total OEM production
    volume (the engine's ``production_volume`` state, 10k vehicles /
    month). ``oem_production_shares`` maps every OEM in the structure
    to its share of that total and must sum to 1. ``shares_source`` is
    the provenance label recorded in the assumptions list: the default
    ``"caller-supplied"`` preserves the Phase 2 wording; the route
    passes a stored-input label when the shares came from the run's
    stored fragment.
    """

    validate_or_raise(structure)
    _validate_shares(structure, oem_production_shares)
    _validate_trajectory(production_by_tick)

    overrides = dict(supply_shares or {})
    for key, share in overrides.items():
        if not 0.0 <= float(share) <= 1.0:
            raise ValueError(f"Supply share for {key} is outside [0, 1]: {share}.")
    if default_supply_share is not None and not 0.0 <= float(default_supply_share) <= 1.0:
        raise ValueError(f"Default supply share is outside [0, 1]: {default_supply_share}.")

    if own_supplier_id is not None:
        basis = "supplier_rows"
        unavailable_reason = None
    elif overrides or default_supply_share is not None:
        basis = "supply_share"
        unavailable_reason = None
    else:
        basis = "unavailable"
        unavailable_reason = (
            "No supplier attribution supplied: pass own_supplier_id for supplier-row "
            "attribution or supply_shares/default_supply_share for share attribution."
        )

    statuses = {oem.oem_id: oem.customer_status for oem in structure.oems}
    rows: list[SalesLayerRow] = []
    per_tick: list[SalesLayerTickTotal] = []
    skipped_slots: list[str] = []
    products_seen: set[str] = set()

    for tick in sorted(production_by_tick):
        production = float(production_by_tick[tick])
        effective = structure_with_effective_shares(structure, tick)
        oem_volumes = {
            oem_id: production * share for oem_id, share in oem_production_shares.items()
        }
        slots = aggregate_units(effective, oem_volumes)
        units_by_key: dict[tuple[str, str], float] = {}
        for slot in slots:
            key = (slot["oem_id"], slot["product_id"])
            units_by_key[key] = units_by_key.get(key, 0.0) + float(slot["units"])
            products_seen.add(slot["product_id"])
        if strict_prices:
            priced = aggregate_capacity(slots)
        else:
            priced = []
            for slot in slots:
                if slot.get("price") is None:
                    skipped_slots.append(
                        f"tick {tick}: {slot['oem_id']}.{slot['nameplate_id']}."
                        f"{slot['generation_id']}.{slot['trim_id']}."
                        f"{slot['product_id']}@{slot['supplier_id']}"
                    )
                else:
                    priced.append({**slot, "capacity": float(slot["units"]) * float(slot["price"])})
        capacity_by_key = market_capacity_by_oem_product(priced)
        if basis == "supplier_rows":
            assert own_supplier_id is not None
            own_by_key = own_sales_from_supplier_rows(priced, own_supplier_id)
            # Keys absent from the supplier-row result are 0: Ho
            # supplies nothing there (prospects included, by rule).
            own_by_key = {
                key: own_by_key.get(key, 0.0) for key in capacity_by_key
            }
        elif basis == "supply_share":
            own_by_key = own_sales_with_share(
                capacity_by_key,
                structure,
                supply_shares=overrides or None,
                default_share=float(default_supply_share or 0.0),
            )
        else:
            own_by_key = {}

        tick_units = 0.0
        tick_capacity = 0.0
        tick_own: float | None = 0.0 if basis != "unavailable" else None
        for key in sorted(set(units_by_key) | set(capacity_by_key)):
            units = units_by_key.get(key, 0.0)
            capacity = capacity_by_key.get(key, 0.0)
            own = own_by_key.get(key) if basis != "unavailable" else None
            rows.append(
                SalesLayerRow(
                    tick=tick,
                    oem_id=key[0],
                    product_id=key[1],
                    units=units,
                    capacity_value=capacity,
                    own_sales=own,
                )
            )
            tick_units += units
            tick_capacity += capacity
            if tick_own is not None and own is not None:
                tick_own += own
        per_tick.append(
            SalesLayerTickTotal(
                tick=tick,
                production_volume=production,
                units=tick_units,
                capacity_value=tick_capacity,
                own_sales=tick_own,
            )
        )

    total_own: float | None = None
    if basis != "unavailable":
        total_own = sum(
            row.own_sales for row in rows if row.own_sales is not None
        )
    assumptions = [
        f"Volume spine: OEM PRODUCTION volume including Audi (Ho 2026-11-16); the engine simulates the total, per-OEM shares are {shares_source} and sum to 1.",
        "Per-nameplate generation schedules apply the effective generation mix at each tick; unscheduled nameplates keep static shares.",
        f"Own-sales basis: {basis}."
        + (
            " Supplier-row attribution wins over share attribution when both are supplied."
            if own_supplier_id is not None and (overrides or default_supply_share is not None)
            else ""
        ),
        "Prospect OEMs contribute 0 own sales regardless of attribution path.",
        f"Prices: {'strict (any unpriced slot refuses the computation)' if strict_prices else 'non-strict (unpriced slots skipped from capacity, listed in skipped_unpriced_slots)'}; units never need prices.",
        f"Customer statuses: {', '.join(f'{oem_id}={status}' for oem_id, status in sorted(statuses.items()))}.",
    ]
    return SalesLayerComputation(
        rows=rows,
        per_tick=per_tick,
        summary=SalesLayerSummary(
            total_units=sum(row.units for row in rows),
            total_capacity_value=sum(row.capacity_value for row in rows),
            total_own_sales=total_own,
            tick_count=len(production_by_tick),
            oem_count=len(structure.oems),
            product_count=len(products_seen),
        ),
        production_trajectory=[
            {"tick": float(tick), "production_volume": float(production_by_tick[tick])}
            for tick in sorted(production_by_tick)
        ],
        assumptions=assumptions,
        skipped_unpriced_slots=skipped_slots,
        own_sales_basis=basis,
        own_sales_unavailable_reason=unavailable_reason,
    )


def _validate_shares(structure: SplitStructure, shares: dict[str, float]) -> None:
    # Shared rules with the run-creation gate (validator.oem_share_issues);
    # the first issue surfaces as ValueError, preserving the Phase 2
    # messages the route's error-code mapping keys on.
    oem_ids = {oem.oem_id for oem in structure.oems}
    issues = oem_share_issues(oem_ids, shares)
    if issues:
        raise ValueError(issues[0][1])


def _validate_trajectory(production_by_tick: dict[int, float]) -> None:
    if not production_by_tick:
        raise ValueError("Production trajectory is empty; at least one tick >= 1 is required.")
    for tick, volume in production_by_tick.items():
        if isinstance(tick, bool) or not isinstance(tick, int) or tick < 1:
            raise ValueError(f"Trajectory ticks must be integers >= 1; got {tick!r}.")
        if (
            isinstance(volume, bool)
            or not isinstance(volume, (int, float))
            or not math.isfinite(float(volume))
            or float(volume) < 0
        ):
            raise ValueError(f"Production volume at tick {tick} must be finite and >= 0.")
