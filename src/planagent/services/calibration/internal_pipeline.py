"""Internal-data intake pipeline for calibration (Item 7, 2026-11-20).

Ho's 2026-11-17 ruling stands: internal order-book data is NOT used,
NOT requested, and NOT assumed to arrive. This module is the other
half of that ruling — IF internal data arrives one day, replacing a
SIMULATED value must be mechanical: load a file, validate it, get
overrides out, apply them, re-baseline. No hand-editing of harness
constants, no judgment call hidden in a script.

The pipeline is pure (no I/O, no LLM) and stdlib-only:

* :func:`validate_internal_dataset` — schema + caliber + range +
  hindsight-firewall + duplicate + supply-share-sum checks. Returns a
  report; ``ok`` is False when any ERROR is present. Warnings never
  block, but they are part of the report and must be read.
* :func:`build_replacement_overrides` — validated records →
  ``{parameter_id: distribution}`` plus a manifest. Mechanical: a
  point value becomes ``fixed``; a ``{min, mode, max}`` triple stays
  triangular; a ``{low, high}`` range becomes triangular with the
  midpoint as mode (documented, never silent).
* :func:`apply_overrides_to_variables` — overrides applied to a
  variable list (template or harness case set). Returns a NEW list;
  the input is untouched. Every replaced variable gets its
  ``evidence_ref`` rewritten to ``internal:<source>`` and the manifest
  records old → new. An override naming an unknown variable id fails
  loudly instead of being silently dropped.

What the pipeline deliberately does NOT do
-------------------------------------------
* It does not accept transmission-v3 coefficients: those are fitted
  from the PUBLIC panel (extend the panel, re-run the fit). An
  internal record naming one is an UNKNOWN-PARAMETER error.
* It does not accept downside parameters: no internal series exists
  for the probability of a future downturn. Those are replaced, if
  ever, by an episode catalog / expert panel recorded as judgment.
* It does not accept ``margin_reversion`` / ``margin_adoption`` as raw
  numbers: neither is directly observable. The pipeline accepts a
  FITTED value only when the record carries its fit method and the
  realised series it was fitted on (``fit_record``) — otherwise it is
  rejected as ``unobservable_without_fit``.
* It does not silently fix a dormant channel: replacing
  ``annual_cut_rate`` / ``payment_terms_months`` emits a WARNING that
  no formula reads the variable on e047f50 (gap-audit A2) — the value
  changes, no score moves, until the channel is built.

Decision-time firewall: every record carries ``period_end``; a record
whose period ends AFTER the dataset's ``decision_time`` is rejected.
Post-decision actuals are scoring evidence only — the same firewall
the backtests run under. The ``decision_time`` is the case's decision
time, supplied by the caller (the dataset header alone is not
trusted to set it: the caller passes it explicitly).
"""

from __future__ import annotations

import copy
import math
from typing import Any

#: Internal calibration dataset schema version.
INTERNAL_SCHEMA_VERSION = "internal-calibration/v1"

#: Per-slot supply-share sum tolerance (Ho Part D ruling: shares sum
#: to 1 per model x trim x product slot).
SUPPLY_SHARE_SUM_TOLERANCE = 0.01


class InternalCalibrationError(ValueError):
    """A malformed internal dataset or an unmechanical replacement."""


#: Internal parameter specs: the schema of what internal data looks
#: like. ``unit`` is the required unit string; ``caliber`` states the
#: definition (what the number MEANS — the usual source of silent
#: mismatch); ``value_kind`` is ``point`` (a single number → fixed),
#: ``triple`` (``{min, mode, max}`` → triangular) or ``either``;
#: ``range`` is the allowed value interval; ``scope_keys`` lists the
#: extra keys that identify a scoped record (supply_share is per slot).
INTERNAL_PARAMETER_SPECS: dict[str, dict[str, Any]] = {
    "order_intake_rate": {
        "unit": "ratio (annualised new orders / current revenue)",
        "caliber": "Annualised new project orders signed in the decision "
        "year, divided by that year's revenue. Annualised = the order "
        "value as won, not yet delivered.",
        "value_kind": "either",
        "range": (0.0, 5.0),
        "scope_keys": ["case"],
    },
    "order_backlog_opening": {
        "unit": "RMB m",
        "caliber": "Unfulfilled order stock at the decision date: signed "
        "orders not yet delivered as revenue. A STOCK, not a flow.",
        "value_kind": "point",
        "range": (0.0, 1_000_000.0),
        "scope_keys": ["case"],
    },
    "order_intake_flow": {
        "unit": "RMB m per tick",
        "caliber": "New-orders flow per tick at run start: the annualised "
        "new-order flow for the first projected tick. A FLOW, not a stock.",
        "value_kind": "point",
        "range": (0.0, 1_000_000.0),
        "scope_keys": ["case"],
    },
    "backlog_conversion": {
        "unit": "fraction per tick",
        "caliber": "Share of the pre-tick backlog converted to revenue "
        "per tick. Calibratable from realised order-to-revenue lag "
        "(design-in → start-of-production durations) or a realised "
        "conversion series.",
        "value_kind": "either",
        "range": (0.0, 1.0),
        "scope_keys": [],
    },
    "order_decay": {
        "unit": "fraction per tick",
        "caliber": "Per-tick decay of the new-orders flow after a surge "
        "year (mean-reversion of order growth). From the realised "
        "new-orders flow path.",
        "value_kind": "either",
        "range": (0.0, 1.0),
        "scope_keys": [],
    },
    "annual_cut_rate": {
        "unit": "rate per year",
        "caliber": "Executed annual price cuts demanded by OEMs: the "
        "contracted year-down rate actually applied (not the asked "
        "rate). Per OEM/product where available; otherwise the "
        "revenue-weighted average across OEMs.",
        "value_kind": "either",
        "range": (0.0, 0.30),
        "scope_keys": ["oem", "product"],
    },
    "payment_terms_months": {
        "unit": "months",
        "caliber": "Actual payment-terms length: contracted terms by OEM "
        "(n+3+6 structure) or realised days-sales-outstanding / 30. "
        "State which one in source_ref.",
        "value_kind": "either",
        "range": (0.0, 24.0),
        "scope_keys": ["oem"],
    },
    "tier1_gross_margin": {
        "unit": "rate",
        "caliber": "Audited overall gross margin for the decision year "
        "(or the product-line margin where the record scopes it). "
        "Overall margin, NOT net margin — the two must never be mixed.",
        "value_kind": "either",
        "range": (0.0, 0.80),
        "scope_keys": ["product_line"],
    },
    "supply_share": {
        "unit": "share (0-1)",
        "caliber": "Supplier share of a model x trim x product slot: "
        "Ho's own share of that slot's volume. Shares sum to 1 per "
        "slot (Part D ruling). Each record is ONE supplier's share of "
        "the slot — two suppliers splitting a slot are two records "
        "with the same slot scope and different 'supplier' values "
        "(the optional 'supplier' key is part of the record identity; "
        "without it, two records for one slot are duplicates). "
        "Prospects get 0.",
        "value_kind": "point",
        "range": (0.0, 1.0),
        "scope_keys": ["oem", "model", "trim", "product"],
    },
    "margin_longrun": {
        "unit": "rate",
        "caliber": "Mean-reversion anchor for net margin: the documented "
        "two-year-mean rule applied to the audited net-margin history "
        "(decision-year-minus-two-years average). The RULE is part of "
        "the record (fit_record.rule).",
        "value_kind": "point",
        "range": (0.0, 0.30),
        "scope_keys": ["case"],
    },
    "margin_reversion": {
        "unit": "fraction per tick",
        "caliber": "FITTED ONLY: the per-tick reversion speed fitted to "
        "a realised net-margin trajectory (fit_record must name the "
        "method and the series). NOT directly observable; a raw number "
        "without a fit record is rejected.",
        "value_kind": "point",
        "range": (0.0, 1.0),
        "scope_keys": [],
        "requires_fit_record": True,
    },
    "margin_adoption": {
        "unit": "rate per unit adoption",
        "caliber": "FITTED ONLY: the net adoption→margin effect fitted "
        "to a realised adoption-vs-margin panel (fit_record must name "
        "the method and the series). NOT directly observable.",
        "value_kind": "either",
        "range": (-0.10, 0.10),
        "scope_keys": [],
        "requires_fit_record": True,
    },
}

#: Parameters whose variable has no formula reader on e047f50 — the
#: replacement changes the value but no score (gap-audit A2).
DORMANT_PARAMETERS: frozenset[str] = frozenset(
    {"annual_cut_rate", "payment_terms_months"}
)

#: Parameters that are fitted values, never raw internal numbers.
FIT_ONLY_PARAMETERS: frozenset[str] = frozenset(
    {"margin_reversion", "margin_adoption"}
)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check_distribution(
    value: Any, spec: dict[str, Any], where: str, errors: list[str]
) -> dict[str, Any] | None:
    """Validate one record's value; return the distribution, or None."""

    kind = spec["value_kind"]
    low, high = spec["range"]
    if _is_number(value):
        if kind == "triple":
            errors.append(f"{where}: expected a {{min, mode, max}} triple, got a number.")
            return None
        number = float(value)
        if not math.isfinite(number):
            errors.append(f"{where}: value is not finite.")
            return None
        if not low <= number <= high:
            errors.append(f"{where}: value {number} outside allowed range [{low}, {high}].")
            return None
        return {"type": "fixed", "value": number}
    if isinstance(value, dict):
        keys = set(value)
        if keys == {"min", "mode", "max"}:
            if kind == "point":
                errors.append(f"{where}: expected a point value, got a triple.")
                return None
            parts = [value["min"], value["mode"], value["max"]]
            if not all(_is_number(part) for part in parts):
                errors.append(f"{where}: triple parts must be numbers.")
                return None
            lo, mode, hi = (float(part) for part in parts)
            if not all(math.isfinite(part) for part in (lo, mode, hi)):
                errors.append(f"{where}: triple parts must be finite.")
                return None
            if not lo <= mode <= hi:
                errors.append(f"{where}: triple must satisfy min <= mode <= max.")
                return None
            if not (low <= lo and hi <= high):
                errors.append(
                    f"{where}: triple [{lo}, {mode}, {hi}] outside allowed range "
                    f"[{low}, {high}]."
                )
                return None
            return {"type": "triangular", "min": lo, "mode": mode, "max": hi}
        if keys == {"low", "high"}:
            if kind == "point":
                errors.append(f"{where}: expected a point value, got a range.")
                return None
            low_v, high_v = value["low"], value["high"]
            if not all(_is_number(part) for part in (low_v, high_v)):
                errors.append(f"{where}: range bounds must be numbers.")
                return None
            low_v, high_v = float(low_v), float(high_v)
            if not low_v <= high_v:
                errors.append(f"{where}: range must satisfy low <= high.")
                return None
            if not (low <= low_v and high_v <= high):
                errors.append(
                    f"{where}: range [{low_v}, {high_v}] outside allowed range "
                    f"[{low}, {high}]."
                )
                return None
            # Documented rule: a [low, high] range becomes triangular
            # with the midpoint as mode. Never silent — the manifest
            # records the conversion.
            return {
                "type": "triangular",
                "min": low_v,
                "mode": (low_v + high_v) / 2.0,
                "max": high_v,
            }
        errors.append(f"{where}: value must be a number, a {{min, mode, max}} triple, "
                      "or a {low, high} range.")
        return None
    errors.append(f"{where}: value must be a number or a distribution object.")
    return None


def _entry_covered_by(entry: dict[str, Any], records: list[dict[str, Any]]) -> bool:
    """Does any validated record cover this registry entry?

    The entry's ``internal_field`` must match the record's parameter,
    and when the entry id carries a case suffix (``.../desay-2020``)
    the record's ``case`` scope must equal that suffix.
    """

    field = entry.get("internal_field")
    entry_id = entry["id"]
    suffix = entry_id.split("/", 1)[1] if "/" in entry_id else None
    for record in records:
        if record["parameter_id"] != field:
            continue
        if suffix is None:
            return True
        if record.get("scope", {}).get("case") == suffix:
            return True
    return False


def validate_internal_dataset(
    data: Any, *, decision_time: str
) -> dict[str, Any]:
    """Validate an internal calibration dataset (dict, already parsed).

    ``decision_time`` is the case's decision time (``YYYY-MM-DD``):
    every record's ``period_end`` must be on or before it (hindsight
    firewall). Returns a report dict: ``ok`` (no ERRORs), ``errors``,
    ``warnings``, ``records`` (validated records with distributions),
    ``coverage`` (registry SIMULATED entries covered / still open),
    and ``decision_time``.
    """

    errors: list[str] = []
    warnings: list[str] = []
    validated: list[dict[str, Any]] = []

    if not isinstance(data, dict):
        return {
            "ok": False,
            "errors": ["dataset must be a JSON object."],
            "warnings": warnings,
            "records": [],
            "coverage": {"covered": [], "still_simulated": []},
            "decision_time": decision_time,
        }
    if data.get("schema_version") != INTERNAL_SCHEMA_VERSION:
        errors.append(
            "schema_version must be "
            f"{INTERNAL_SCHEMA_VERSION!r}; got {data.get('schema_version')!r}."
        )
    if not isinstance(data.get("source"), str) or not data["source"]:
        errors.append("source must be a non-empty string (who supplied this file).")
    if not isinstance(data.get("decision_time"), str) or not data["decision_time"]:
        errors.append("decision_time must be a non-empty YYYY-MM-DD string.")
    elif data["decision_time"] != decision_time:
        errors.append(
            "header decision_time "
            f"{data['decision_time']!r} does not match the caller's decision_time "
            f"{decision_time!r} — the header alone never sets the firewall."
        )
    records = data.get("records")
    if not isinstance(records, list) or not records:
        errors.append("records must be a non-empty list.")
        records = records if isinstance(records, list) else []

    seen: set[tuple[str, ...]] = set()
    for index, record in enumerate(records):
        where = f"records[{index}]"
        if not isinstance(record, dict):
            errors.append(f"{where}: each record must be an object.")
            continue
        parameter_id = record.get("parameter_id")
        if not isinstance(parameter_id, str) or not parameter_id:
            errors.append(f"{where}: parameter_id must be a non-empty string.")
            continue
        spec = INTERNAL_PARAMETER_SPECS.get(parameter_id)
        if spec is None:
            errors.append(
                f"{where}: unknown parameter_id {parameter_id!r}. Known ids: "
                f"{sorted(INTERNAL_PARAMETER_SPECS)}. Transmission-v3 "
                "coefficients and downside parameters are NOT internal-data "
                "parameters (see the module docstring)."
            )
            continue
        # Scope key: the record's identity for duplicate detection.
        scope = tuple(
            (key, record.get(key)) for key in spec["scope_keys"]
        )
        # supply_share split semantics (Part D ruling): two suppliers
        # splitting one slot are two records with the SAME slot scope.
        # The optional 'supplier' key is part of the identity, so a
        # split passes duplicate detection and is arbitrated by the
        # per-slot sum check instead; the same supplier twice (or two
        # supplier-less records for one slot) is still a duplicate.
        identity_extra: tuple[tuple[str, Any], ...] = ()
        if parameter_id == "supply_share":
            supplier = record.get("supplier")
            if supplier is not None:
                if not isinstance(supplier, str) or not supplier:
                    errors.append(
                        f"{where}: 'supplier', when present, must be a "
                        "non-empty string."
                    )
                else:
                    identity_extra = (("supplier", supplier),)
        identity = (parameter_id,) + scope + identity_extra
        if identity in seen:
            errors.append(f"{where}: duplicate record for {parameter_id} scope {dict(scope)}.")
            continue
        seen.add(identity)
        # Scope keys must be present and non-empty strings where required.
        for key in spec["scope_keys"]:
            if not isinstance(record.get(key), str) or not record[key]:
                errors.append(f"{where}: scope key {key!r} is required for {parameter_id}.")
        # Unit must match the spec exactly — unit mismatch is the
        # classic silent-caliber error (e.g. % vs fraction, RMB vs
        # RMB 10k).
        if record.get("unit") != spec["unit"]:
            errors.append(
                f"{where}: unit for {parameter_id} must be {spec['unit']!r}; "
                f"got {record.get('unit')!r}."
            )
        # Hindsight firewall: the record's period must end on or
        # before the decision time.
        period_end = record.get("period_end")
        if not isinstance(period_end, str) or not period_end:
            errors.append(f"{where}: period_end (YYYY-MM-DD) is required.")
        elif period_end > decision_time:
            errors.append(
                f"{where}: period_end {period_end} is AFTER decision_time "
                f"{decision_time} — post-decision actuals are scoring "
                "evidence only, never calibration input."
            )
        if not isinstance(record.get("source_ref"), str) or not record.get("source_ref"):
            errors.append(f"{where}: source_ref is required (audit trail per record).")
        if spec.get("requires_fit_record") and not isinstance(record.get("fit_record"), dict):
            errors.append(
                f"{where}: {parameter_id} is FIT-ONLY — the record must carry "
                "a fit_record {method, series} naming how the value was "
                "fitted to a realised series. A raw number is rejected."
            )
        distribution = _check_distribution(record.get("value"), spec, where, errors)
        if distribution is None:
            continue
        validated.append(
            {
                "parameter_id": parameter_id,
                "distribution": distribution,
                "unit": spec["unit"],
                "period_end": period_end,
                "source_ref": record.get("source_ref"),
                "scope": dict(scope),
                "fit_record": record.get("fit_record"),
                "raw_value": record.get("value"),
            }
        )
        if parameter_id in DORMANT_PARAMETERS:
            warnings.append(
                f"{where}: {parameter_id} is DORMANT on e047f50 — no formula "
                "reads this variable (gap-audit A2). The replacement "
                "changes the value but NO score until the transmission "
                "channel is built."
            )

    # Cross-checks (warnings, never errors — they flag a human review).
    by_id: dict[str, list[dict[str, Any]]] = {}
    for record in validated:
        by_id.setdefault(record["parameter_id"], []).append(record)
    intake_rates = by_id.get("order_intake_rate", [])
    intake_flows = by_id.get("order_intake_flow", [])
    if intake_rates and intake_flows:
        for rate in intake_rates:
            for flow in intake_flows:
                if rate["scope"].get("case") != flow["scope"].get("case"):
                    continue
                rate_mode = rate["distribution"].get("mode", rate["distribution"].get("value"))
                flow_value = flow["distribution"].get("value")
                if rate_mode is None or flow_value is None:
                    continue
                # The flow should be ~ rate x revenue; without revenue
                # in the dataset we can only check the ORDER of
                # magnitude via the opening book when present — so this
                # check stays a soft note, not a ratio test.
                warnings.append(
                    "cross-check: order_intake_rate and order_intake_flow "
                    "are both supplied for case "
                    f"{rate['scope'].get('case')!r}; confirm flow ≈ rate × "
                    "decision-year revenue before applying (the pipeline "
                    "cannot verify the ratio without a revenue record)."
                )
    books = by_id.get("order_backlog_opening", [])
    for book in books:
        for flow in intake_flows:
            if book["scope"].get("case") != flow["scope"].get("case"):
                continue
            book_value = book["distribution"].get("value")
            flow_value = flow["distribution"].get("value")
            if book_value is None or flow_value is None or flow_value == 0:
                continue
            ratio = book_value / flow_value
            if not 0.5 <= ratio <= 2.0:
                warnings.append(
                    "cross-check: order_backlog_opening / order_intake_flow "
                    f"= {ratio:.2f} for case {book['scope'].get('case')!r} "
                    "(expected ~0.5–2.0 for a one-year-of-intake proxy "
                    "replacement — check the stock/flow caliber)."
                )

    # Supply-share sum check: shares must sum to 1 per slot.
    share_slots: dict[tuple[str, str, str, str], float] = {}
    for record in by_id.get("supply_share", []):
        key = (
            record["scope"].get("oem", ""),
            record["scope"].get("model", ""),
            record["scope"].get("trim", ""),
            record["scope"].get("product", ""),
        )
        share_slots[key] = share_slots.get(key, 0.0) + float(
            record["distribution"]["value"]
        )
    for key, total in sorted(share_slots.items()):
        if abs(total - 1.0) > SUPPLY_SHARE_SUM_TOLERANCE:
            errors.append(
                f"supply_share records for slot {key} sum to {total:.4f}, "
                "not 1.0 (Part D ruling: supplier shares sum to 1 per "
                "model x trim x product slot)."
            )

    # Coverage: which SIMULATED registry entries does this dataset cover?
    # Coverage is per CASE, not per parameter: a desay-2020 intake-rate
    # record covers order_intake_rate/desay-2020 only — it must NOT
    # also "cover" the desay-2015 entry (a 2020 figure is not 2015
    # evidence), and it never covers the template generic (a case
    # value is not a global number). Entries without a '/'-suffixed
    # case id (backlog_conversion, supply_share_simulated, ...) are
    # covered by any record of their parameter.
    from planagent.services.calibration.registry import registry_entries

    covered: list[str] = []
    still: list[str] = []
    for entry in registry_entries():
        if entry["status"] != "simulated":
            continue
        field = entry.get("internal_field")
        if field and _entry_covered_by(entry, validated):
            covered.append(entry["id"])
        else:
            still.append(entry["id"])

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "records": validated,
        "coverage": {"covered": sorted(set(covered)), "still_simulated": sorted(set(still))},
        "decision_time": decision_time,
    }


def build_replacement_overrides(
    validation_report: dict[str, Any], *, source: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Build mechanical overrides from a VALIDATED dataset.

    ``validation_report`` must be the output of
    :func:`validate_internal_dataset` with ``ok`` True — otherwise
    :class:`InternalCalibrationError` is raised. Returns
    ``(overrides, manifest)`` where overrides maps UNSCOPED variable id
    → distribution (directly applicable by
    :func:`apply_overrides_to_variables`). SCOPED records (supply_share
    per slot, annual_cut per OEM, …) are NOT put in overrides: a scoped
    record has no single variable to replace, and silently applying it
    to every variable of that id would be wrong. Scoped records appear
    in the manifest with ``route`` naming their own replacement route
    (S-layer overrides / assumption data / case-level binding) and
    ``applied`` False — the caller routes them explicitly.
    """

    if not validation_report.get("ok"):
        raise InternalCalibrationError(
            "Cannot build overrides from a failed validation: "
            f"{validation_report.get('errors')}"
        )
    overrides: dict[str, Any] = {}
    manifest: list[dict[str, Any]] = []
    for record in validation_report["records"]:
        parameter_id = record["parameter_id"]
        scope = record.get("scope") or {}
        row = {
            "parameter_id": parameter_id,
            "scope": scope,
            "key": parameter_id,
            "new": copy.deepcopy(record["distribution"]),
            "evidence_ref": f"internal:{source} ({record.get('period_end')})",
            "source_ref": record.get("source_ref"),
            "converted_from_range": isinstance(record.get("raw_value"), dict)
            and set(record["raw_value"]) == {"low", "high"},
        }
        if scope:
            # Scoped record: no bare-variable replacement exists.
            row["applied"] = False
            row["route"] = _scoped_route(parameter_id)
            manifest.append(row)
            continue
        overrides[parameter_id] = copy.deepcopy(record["distribution"])
        row["applied"] = True
        row["route"] = "variable_override"
        manifest.append(row)
    return overrides, manifest


#: Replacement routes for scoped records (no bare variable exists).
SCOPED_ROUTES: dict[str, str] = {
    "supply_share": "S-layer: per-slot overrides via the automotive API "
    "(supply_shares / default_supply_share) or TEMPLATE_ASSUMPTION_DATA "
    "supply_share_simulated replacement; validate the per-slot sum (=1) "
    "before applying.",
    "annual_cut_rate": "case-level: bind the executed per-OEM rate as a "
    "case variable (or the revenue-weighted average as the template "
    "variable) — after the annual-cut → price/margin channel exists "
    "(gap-audit A2); until then the value is recorded, no score moves.",
    "payment_terms_months": "case-level: bind the per-OEM terms as a "
    "case variable — after the terms → cash-occupancy channel exists "
    "(gap-audit A2).",
    "tier1_gross_margin": "case-level: bind the product-line margin as "
    "a case variable, or the audited overall margin as the template "
    "variable.",
}


def _scoped_route(parameter_id: str) -> str:
    return SCOPED_ROUTES.get(
        parameter_id,
        "case-level: bind as a scoped case variable (no bare-variable route).",
    )


def apply_overrides_to_variables(
    variables: list[dict[str, Any]],
    overrides: dict[str, Any],
    manifest: list[dict[str, Any]] | None = None,
    *,
    source: str = "",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply overrides to a variable list; return ``(new_list, manifest)``.

    The input list is NOT mutated. Each override key is a bare variable
    id (scoped records never reach this function — see
    :func:`build_replacement_overrides`). An override naming a variable
    id that is NOT in the list fails loudly instead of being silently
    dropped. Every replaced variable gets its ``evidence_ref``
    rewritten to the internal source.
    """

    new_variables = copy.deepcopy(variables)
    by_id: dict[str, list[int]] = {}
    for index, var in enumerate(new_variables):
        by_id.setdefault(var["id"], []).append(index)
    applied: list[dict[str, Any]] = []
    for key, distribution in overrides.items():
        if ":" in key:
            raise InternalCalibrationError(
                f"Override {key!r} is scoped — scoped records have their "
                "own route (see build_replacement_overrides) and must "
                "never be applied to a bare variable list."
            )
        parameter_id = key
        if parameter_id not in by_id:
            raise InternalCalibrationError(
                f"Override {key!r} names variable {parameter_id!r}, which "
                "is not in this variable list — refusing (a dropped "
                "replacement must never pass silently)."
            )
        for index in by_id[parameter_id]:
            old = copy.deepcopy(new_variables[index].get("distribution"))
            new_variables[index]["distribution"] = copy.deepcopy(distribution)
            new_variables[index]["evidence_ref"] = (
                f"internal:{source}" if source else "internal:replaced"
            )
            applied.append(
                {
                    "variable_id": parameter_id,
                    "old": old,
                    "new": copy.deepcopy(distribution),
                    "key": key,
                }
            )
    if manifest is not None:
        for row in manifest:
            matches = [a for a in applied if a["key"] == row["key"]]
            row["old"] = matches[0]["old"] if matches else None
            row["applied"] = bool(matches)
    return new_variables, applied


__all__ = [
    "DORMANT_PARAMETERS",
    "FIT_ONLY_PARAMETERS",
    "INTERNAL_PARAMETER_SPECS",
    "INTERNAL_SCHEMA_VERSION",
    "SUPPLY_SHARE_SUM_TOLERANCE",
    "InternalCalibrationError",
    "apply_overrides_to_variables",
    "build_replacement_overrides",
    "validate_internal_dataset",
]
