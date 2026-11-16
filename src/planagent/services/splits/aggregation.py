"""Pure bottom-up aggregation over split structures (Phase 1).

No LLM, no randomness, no I/O. The single permitted aggregation path
(synthesis §C1 item 5): OEM PRODUCTION volume (the volume spine, Ho
2026-11-16, including Audi) flows down the MECE tree — nameplate share,
generation share, trim share, product fitment, supplier share — and
capacity is units x ASP. No bypass exists: no OEM-total x
industry-average-penetration shortcut, no hand-entered subtotal.

Units and capacity are separate functions on purpose: units need no
prices, while capacity refuses any slot without a price instead of
silently undercounting. Both functions re-validate the structure first,
so direct callers can never silently aggregate an invalid tree.

Two S-layer (own-sales) paths, kept explicit and separate:

- supplier-row attribution: Ho's sales are the capacity of the slots
  whose supplier row IS Ho. Prospects contribute 0 regardless of rows.
- simulated-share attribution: sales = full-market capacity x a supply
  share, defaulting to the simulated industry-average assumption value
  (Ho-authorized) for existing OEMs and 0 for prospects. Used when no
  supplier-row detail exists.

The generation-transition helper turns the engine's
``generation_transition_index`` state value into effective per-nameplate
generation shares for the two-generation (outgoing + successor) pattern.
"""

from __future__ import annotations

import math
from typing import Any

from .models import SplitStructure
from .validator import SplitValidationError, validate_split_structure


def _require_valid(structure: SplitStructure) -> None:
    result = validate_split_structure(structure)
    if not result.is_valid:
        raise SplitValidationError(result)


def aggregate_units(
    structure: SplitStructure,
    oem_production_volumes: dict[str, float],
) -> list[dict[str, Any]]:
    """Per-slot addressable units from OEM PRODUCTION volumes.

    ``oem_production_volumes`` maps OEM id to production volume in the
    caller's unit (e.g. 10k vehicles/month); every OEM in the structure
    must have a volume, or aggregation refuses loudly. Returns one row
    per (nameplate, generation, trim, product, supplier) slot with the
    full share chain recorded, so any row can be audited back to the
    tree. Units are ``V_o x share(nameplate) x share(generation) x
    share(trim) x fitment x supplier_share`` — the same formula for
    rate-kind and count-kind fitments (synthesis §C1 item 5).
    """

    _require_valid(structure)
    for oem in structure.oems:
        volume = oem_production_volumes.get(oem.oem_id)
        if volume is None:
            raise ValueError(
                f"No production volume supplied for OEM {oem.oem_id!r}; "
                "aggregation refuses to assume one."
            )
        if isinstance(volume, bool) or not isinstance(volume, (int, float)):
            # Malformed caller-supplied data, not a programmer type
            # error; this module fails loudly with ValueError for all
            # invalid aggregation inputs.
            raise ValueError(  # noqa: TRY004
                f"Production volume for OEM {oem.oem_id!r} must be a number."
            )
        if not math.isfinite(float(volume)) or float(volume) < 0:
            raise ValueError(f"Production volume for OEM {oem.oem_id!r} must be finite and >= 0.")

    slots: list[dict[str, Any]] = []
    for oem in structure.oems:
        volume = float(oem_production_volumes[oem.oem_id])
        for nameplate in oem.nameplates:
            for generation in nameplate.generations:
                for trim in generation.trims:
                    for row in trim.fitments:
                        units = (
                            volume
                            * nameplate.share
                            * generation.share
                            * trim.share
                            * row.fitment
                            * row.supplier_share
                        )
                        slots.append(
                            {
                                "oem_id": oem.oem_id,
                                "customer_status": oem.customer_status,
                                "nameplate_id": nameplate.nameplate_id,
                                "energy": nameplate.energy,
                                "price_band": nameplate.price_band,
                                "generation_id": generation.generation_id,
                                "lifecycle_phase": generation.lifecycle_phase,
                                "trim_id": trim.trim_id,
                                "product_id": row.product_id,
                                "fitment_kind": row.fitment_kind,
                                "supplier_id": row.supplier_id,
                                "units": units,
                                "price": row.price,
                            }
                        )
    return slots


def aggregate_capacity(slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach capacity (units x ASP) to aggregated slot rows.

    Refuses loudly on the first slot without a price: a partial capacity
    total would silently undercount. Returns new row dicts (the input
    rows are not mutated) with a ``capacity`` key.
    """

    priced: list[dict[str, Any]] = []
    for slot in slots:
        price = slot.get("price")
        if price is None:
            raise ValueError(
                "Cannot compute capacity: slot "
                f"{slot['oem_id']}.{slot['nameplate_id']}.{slot['generation_id']}."
                f"{slot['trim_id']}.{slot['product_id']}@{slot['supplier_id']} "
                "has no price (ASP). Supply prices or aggregate units only."
            )
        priced.append({**slot, "capacity": float(slot["units"]) * float(price)})
    return priced


def market_capacity_by_oem_product(
    slots: list[dict[str, Any]],
) -> dict[tuple[str, str], float]:
    """Full-market capacity per (OEM, product), summed over ALL suppliers.

    The input rows must carry ``capacity`` (see :func:`aggregate_capacity`).
    This is the C(o,p) of synthesis §C1 item 6: the whole addressable
    market for that OEM x product, before any supply-share attribution.
    """

    totals: dict[tuple[str, str], float] = {}
    for slot in slots:
        if "capacity" not in slot:
            raise ValueError("Slot rows must carry capacity; run aggregate_capacity first.")
        key = (slot["oem_id"], slot["product_id"])
        totals[key] = totals.get(key, 0.0) + float(slot["capacity"])
    return totals


def own_sales_from_supplier_rows(
    slots: list[dict[str, Any]],
    own_supplier_id: str,
) -> dict[tuple[str, str], float]:
    """Own sales from explicit supplier rows: capacity of Ho's own slots.

    Prospects contribute 0 even if rows name Ho's supplier id — a
    prospect has no supply relationship yet (Ho 2026-11-16). Rows must
    carry ``capacity``.
    """

    totals: dict[tuple[str, str], float] = {}
    for slot in slots:
        if "capacity" not in slot:
            raise ValueError("Slot rows must carry capacity; run aggregate_capacity first.")
        if slot["customer_status"] == "prospect":
            continue
        if slot["supplier_id"] != own_supplier_id:
            continue
        key = (slot["oem_id"], slot["product_id"])
        totals[key] = totals.get(key, 0.0) + float(slot["capacity"])
    return totals


def own_sales_with_share(
    capacity_by_oem_product: dict[tuple[str, str], float],
    structure: SplitStructure,
    supply_shares: dict[tuple[str, str], float] | None = None,
    default_share: float = 0.0,
) -> dict[tuple[str, str], float]:
    """Own sales as full-market capacity x supply share (S-layer formula).

    ``supply_shares`` overrides per (OEM, product); pairs without an
    override use ``default_share`` (the simulated industry-average
    assumption value when the caller passes it). Prospects always get 0,
    never the default. Shares outside [0, 1] refuse loudly.
    """

    statuses = {oem.oem_id: oem.customer_status for oem in structure.oems}
    overrides = dict(supply_shares or {})
    for key, share in overrides.items():
        if not 0.0 <= float(share) <= 1.0:
            raise ValueError(f"Supply share for {key} is outside [0, 1]: {share}.")
    if not 0.0 <= float(default_share) <= 1.0:
        raise ValueError(f"Default supply share is outside [0, 1]: {default_share}.")
    sales: dict[tuple[str, str], float] = {}
    for key, capacity in capacity_by_oem_product.items():
        if statuses.get(key[0]) == "prospect":
            sales[key] = 0.0
            continue
        share = float(overrides.get(key, default_share))
        sales[key] = capacity * share
    return sales


def prior_fitment_rate(
    assumption_data: dict[str, Any],
    series: str,
    key: str,
) -> float:
    """One fitment-prior cell from template assumption data.

    Looks up ``assumption_data["fitment_lookup"][series][key]``. Fails
    loudly on a missing lookup, series, or cell — the lookup holds
    exactly the published B2 cells, and a missing cell means the
    research publishes no prior for that band, which must never be
    silently interpolated. The returned rate is validated to [0, 1].
    """

    lookup = assumption_data.get("fitment_lookup")
    if not isinstance(lookup, dict):
        raise ValueError(  # noqa: TRY004 — malformed assumption data; see above.
            "Assumption data carries no 'fitment_lookup' mapping."
        )
    series_values = lookup.get(series)
    if not isinstance(series_values, dict):
        raise ValueError(  # noqa: TRY004 — malformed assumption data; see above.
            f"Fitment lookup has no series {series!r}."
        )
    if key not in series_values:
        raise ValueError(f"Fitment lookup series {series!r} has no cell for {key!r}.")
    rate = series_values[key]
    if isinstance(rate, bool) or not isinstance(rate, (int, float)):
        raise ValueError(  # noqa: TRY004 — malformed assumption data; see above.
            f"Fitment lookup cell {series!r}[{key!r}] is not a number."
        )
    rate = float(rate)
    if not math.isfinite(rate) or not 0.0 <= rate <= 1.0:
        raise ValueError(f"Fitment lookup cell {series!r}[{key!r}] is outside [0, 1]: {rate}.")
    return rate


def simulated_supply_share(assumption_data: dict[str, Any]) -> float:
    """The simulated industry-average supply share from assumption data.

    Reads ``assumption_data["supply_share_simulated"]["value"]`` and
    validates it to [0, 1]. Fails loudly when the entry is absent or
    malformed — callers must pass assumption data that carries it.
    """

    entry = assumption_data.get("supply_share_simulated")
    if not isinstance(entry, dict) or "value" not in entry:
        raise ValueError("Assumption data carries no 'supply_share_simulated.value'.")
    share = entry["value"]
    if isinstance(share, bool) or not isinstance(share, (int, float)):
        raise ValueError(  # noqa: TRY004 — malformed assumption data; see above.
            "Simulated supply share is not a number."
        )
    share = float(share)
    if not math.isfinite(share) or not 0.0 <= share <= 1.0:
        raise ValueError(f"Simulated supply share is outside [0, 1]: {share}.")
    return share


def generation_mix_at_index(
    structure: SplitStructure,
    nameplate_id: str,
    transition_index: float,
) -> dict[str, float]:
    """Effective generation shares for a nameplate at a transition index.

    The two-generation pattern: the ``phase_out`` generation holds
    ``1 - index`` and the ``ramp`` generation holds ``index`` — the
    shares always sum to 1, and the outgoing generation phases out
    while the successor ramps as the engine's
    ``generation_transition_index`` advances. Requires exactly one
    ``phase_out`` and exactly one ``ramp`` generation on the nameplate;
    any other lifecycle composition (or a missing/ambiguous nameplate,
    or an index outside [0, 1]) refuses loudly — per-nameplate
    schedules beyond this pattern are Phase 2.
    """

    if (
        isinstance(transition_index, bool)
        or not isinstance(transition_index, (int, float))
        or not math.isfinite(float(transition_index))
        or not 0.0 <= float(transition_index) <= 1.0
    ):
        raise ValueError(
            f"Transition index must be a finite number in [0, 1]: {transition_index!r}."
        )
    index = float(transition_index)
    matches = [
        nameplate
        for oem in structure.oems
        for nameplate in oem.nameplates
        if nameplate.nameplate_id == nameplate_id
    ]
    if not matches:
        raise ValueError(f"No nameplate {nameplate_id!r} in the split structure.")
    if len(matches) > 1:
        raise ValueError(f"Nameplate {nameplate_id!r} appears in {len(matches)} OEMs; ambiguous.")
    outgoing = [g for g in matches[0].generations if g.lifecycle_phase == "phase_out"]
    successor = [g for g in matches[0].generations if g.lifecycle_phase == "ramp"]
    if len(outgoing) != 1 or len(successor) != 1:
        raise ValueError(
            f"Nameplate {nameplate_id!r} needs exactly one phase_out and one ramp "
            f"generation for the transition pattern; found {len(outgoing)} phase_out "
            f"and {len(successor)} ramp."
        )
    return {
        outgoing[0].generation_id: round(1.0 - index, 4),
        successor[0].generation_id: round(index, 4),
    }
