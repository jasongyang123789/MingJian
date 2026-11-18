"""Pure deterministic validation for bottom-layer split structures.

No LLM, no randomness, no I/O. Follows the Sprint 1 MECE-validator
pattern: the run-creation gate refuses an invalid structure before any
row is written, with a distinct error code and the full structured
result. The sum-to-1 gates are the synthesis §C1 MECE decomposition,
extended with the supplier-share and generation dimensions Ho confirmed
on 2026-11-16:

- nameplate shares sum to 1 per OEM;
- generation shares sum to 1 per nameplate (per period);
- trim shares sum to 1 per generation;
- supplier shares sum to 1 per nameplate x generation x trim x
  SOLUTION slot (product + solution code — see below);
- one-host products (P01 cockpit host, P04 comm terminal — a car takes
  exactly one) have a share-weighted fitment sum <= 1 per
  nameplate x generation x trim x PRODUCT (across all solutions of
  the product in the trim).
- (Phase 2) a per-nameplate transition schedule must reference existing
  generations with the right lifecycle phases (outgoing ``phase_out``,
  successor ``ramp``) and the nameplate must carry exactly those two
  generations, so the scheduled mix always sums to 1.

Fitment rates are INDEPENDENT penetrations (Ho 2026-11-16 Q7): each
rate is the share of a model x trim's production volume carrying the
product, and rates across products/solutions need NOT sum to 1. There
is deliberately NO product-level sum gate in this validator — only
range checks on individual rates. Same-function overlap is a prompt
(services/splits/expectations.py), never a refusal.

Solution slots (S-layer real splits, 2026-11-18): the supplier-share
sum gate groups rows by (product, solution code), not by product
alone. Phase 1 defined the slot per product, which assumed one
solution per product per trim. The real workbook splits refute that:
Hongqi H5 carries TWO P03 solutions (instrument + central screen)
from the SAME supplier at full fitment each, and E-H7 carries two P03
solutions from DIFFERENT suppliers — neither is representable under
a per-product slot (the duplicate gate refuses the first, the sum
gate halves the second). Under solution slots, each solution carries
its own supplier split (two suppliers splitting ONE solution still
sum to 1 — the FAW-VW pattern), while different solutions coexist
independently per Q7. Uncoded rows group into one slot per product,
so Phase 1 structures without solution codes validate exactly as
before. The one-host backstop deliberately stays PRODUCT-level: two
full-penetration P01 solutions in one trim would still mean two
hosts per car, so the weighted sum runs across all solutions of the
product in the trim.

The one-host check is load-bearing under solution slots: two
full-penetration solutions of P01/P04 in one trim would each pass
their own slot gate while summing to two hosts per car, so only the
product-level weighted sum catches it. It is also kept because the
synthesis §C1 gate text requires it explicitly. Sub-product variant
exclusivity (e.g. 4G vs 5G T-BOX within P04) is NOT modeled in
Phase 1 — product ids are lines, not variants.

Tolerance is 1e-9 (synthesis §C1). Every issue carries the tree path so
the caller can locate the offending split without guessing.
"""

from __future__ import annotations

import math

from .models import (
    GenerationTransitionSchedule,
    NameplateSplit,
    OemProductionShares,
    SplitCheckRecord,
    SplitStructure,
    SplitValidationIssue,
    SplitValidationResult,
)

#: Absolute tolerance for every sum-to-1 gate (synthesis §C1).
SUM_TOLERANCE = 1e-9

#: Product lines where one car takes exactly one host unit. Design
#: decision (Phase 1, confirm with Ho): P01 cockpit host + P04 comm
#: terminal. P02/P03 aggregate multiple sub-units per car; P05 is
#: count-kind (cameras per vehicle); P.O is a basket.
ONE_HOST_PRODUCTS = frozenset({"P01", "P04"})


class SplitValidationError(ValueError):
    """Raised when a split structure fails validation.

    Mirrors ``MeceValidationError``: the structured result travels with
    the exception so routes can return the repo's dict-detail error
    shape. Subclasses ``ValueError`` so generic handlers still surface
    a readable summary.
    """

    def __init__(self, result: SplitValidationResult) -> None:
        self.result = result
        super().__init__("Split structure failed validation; simulation refused.")


def _issue(kind: str, path: str, message: str) -> SplitValidationIssue:
    return SplitValidationIssue(kind=kind, path=path, message=message)


def _sums_to_one(total: float) -> bool:
    return abs(total - 1.0) <= SUM_TOLERANCE


def _validate_transition_schedule(
    schedule: GenerationTransitionSchedule,
    nameplate: NameplateSplit,
    plate_path: str,
    issues: list[SplitValidationIssue],
) -> None:
    """Structural checks for a per-nameplate transition schedule.

    The schedule interpolates between exactly two generations, so the
    nameplate must carry exactly the outgoing and successor generations
    with the matching lifecycle phases. Anything else refuses loudly:
    a schedule over a three-generation mix has no defined semantics.
    """

    by_id = {generation.generation_id: generation for generation in nameplate.generations}
    outgoing = by_id.get(schedule.outgoing_generation_id)
    successor = by_id.get(schedule.successor_generation_id)
    if outgoing is None:
        issues.append(
            _issue(
                "transition_schedule_unknown_generation",
                plate_path,
                f"Transition schedule references unknown outgoing generation "
                f"{schedule.outgoing_generation_id!r}.",
            )
        )
    elif outgoing.lifecycle_phase != "phase_out":
        issues.append(
            _issue(
                "transition_schedule_phase_mismatch",
                plate_path,
                f"Outgoing generation {schedule.outgoing_generation_id!r} has phase "
                f"{outgoing.lifecycle_phase!r}, not 'phase_out'.",
            )
        )
    if successor is None:
        issues.append(
            _issue(
                "transition_schedule_unknown_generation",
                plate_path,
                f"Transition schedule references unknown successor generation "
                f"{schedule.successor_generation_id!r}.",
            )
        )
    elif successor.lifecycle_phase != "ramp":
        issues.append(
            _issue(
                "transition_schedule_phase_mismatch",
                plate_path,
                f"Successor generation {schedule.successor_generation_id!r} has phase "
                f"{successor.lifecycle_phase!r}, not 'ramp'.",
            )
        )
    if schedule.outgoing_generation_id == schedule.successor_generation_id:
        issues.append(
            _issue(
                "transition_schedule_composition",
                plate_path,
                "Transition schedule names the same generation as outgoing and successor.",
            )
        )
    if len(nameplate.generations) != 2:
        issues.append(
            _issue(
                "transition_schedule_composition",
                plate_path,
                f"Nameplate {nameplate.nameplate_id!r} carries a transition schedule "
                f"but has {len(nameplate.generations)} generations; a schedule "
                "requires exactly the outgoing and successor generations.",
            )
        )


def validate_split_structure(structure: SplitStructure) -> SplitValidationResult:
    """Validate a split structure, returning a structured result."""

    issues: list[SplitValidationIssue] = []
    slot_count = 0
    row_count = 0

    if not structure.oems:
        issues.append(
            _issue("empty_structure", "", "A split structure must contain at least 1 OEM.")
        )
        return SplitValidationResult(
            is_valid=False,
            checks=[
                SplitCheckRecord(check="structure", status="fail", detail="0 OEM(s)"),
            ],
            issues=issues,
        )

    seen_oems: set[str] = set()
    for oem in structure.oems:
        oem_path = oem.oem_id
        if oem.oem_id in seen_oems:
            issues.append(_issue("duplicate_oem", oem_path, f"Duplicate OEM id {oem.oem_id!r}."))
        seen_oems.add(oem.oem_id)
        if not oem.nameplates:
            issues.append(
                _issue(
                    "empty_nameplates",
                    oem_path,
                    f"OEM {oem.oem_id!r} has no nameplates; volume would aggregate to nothing.",
                )
            )
            continue
        seen_nameplates: set[str] = set()
        nameplate_total = 0.0
        for nameplate in oem.nameplates:
            plate_path = f"{oem_path}.{nameplate.nameplate_id}"
            if nameplate.nameplate_id in seen_nameplates:
                issues.append(
                    _issue(
                        "duplicate_nameplate",
                        plate_path,
                        f"Duplicate nameplate id {nameplate.nameplate_id!r} in OEM {oem.oem_id!r}.",
                    )
                )
            seen_nameplates.add(nameplate.nameplate_id)
            if not 0.0 <= nameplate.share <= 1.0:
                issues.append(
                    _issue(
                        "nameplate_share_out_of_range",
                        plate_path,
                        f"Nameplate share {nameplate.share} is outside [0, 1].",
                    )
                )
            nameplate_total += nameplate.share
            if not nameplate.generations:
                issues.append(
                    _issue(
                        "empty_generations",
                        plate_path,
                        f"Nameplate {nameplate.nameplate_id!r} has no generations.",
                    )
                )
                continue
            seen_generations: set[str] = set()
            generation_total = 0.0
            for generation in nameplate.generations:
                gen_path = f"{plate_path}.{generation.generation_id}"
                if generation.generation_id in seen_generations:
                    issues.append(
                        _issue(
                            "duplicate_generation",
                            gen_path,
                            f"Duplicate generation id {generation.generation_id!r} in "
                            f"nameplate {nameplate.nameplate_id!r}.",
                        )
                    )
                seen_generations.add(generation.generation_id)
                if not 0.0 <= generation.share <= 1.0:
                    issues.append(
                        _issue(
                            "generation_share_out_of_range",
                            gen_path,
                            f"Generation share {generation.share} is outside [0, 1].",
                        )
                    )
                generation_total += generation.share
                if not generation.trims:
                    issues.append(
                        _issue(
                            "empty_trims",
                            gen_path,
                            f"Generation {generation.generation_id!r} has no trims.",
                        )
                    )
                    continue
                seen_trims: set[str] = set()
                trim_total = 0.0
                for trim in generation.trims:
                    trim_path = f"{gen_path}.{trim.trim_id}"
                    if trim.trim_id in seen_trims:
                        issues.append(
                            _issue(
                                "duplicate_trim",
                                trim_path,
                                f"Duplicate trim id {trim.trim_id!r} in "
                                f"generation {generation.generation_id!r}.",
                            )
                        )
                    seen_trims.add(trim.trim_id)
                    if not 0.0 <= trim.share <= 1.0:
                        issues.append(
                            _issue(
                                "trim_share_out_of_range",
                                trim_path,
                                f"Trim share {trim.share} is outside [0, 1].",
                            )
                        )
                    trim_total += trim.share
                    if not trim.fitments:
                        issues.append(
                            _issue(
                                "empty_fitments",
                                trim_path,
                                f"Trim {trim.trim_id!r} has no product rows; its volume "
                                "share would silently aggregate to zero (use P.O for "
                                "untracked products instead of omitting rows).",
                            )
                        )
                        continue
                    # Slot gate: group rows by (product, solution code);
                    # each SOLUTION slot is one supplier split. Different
                    # solutions of one product line coexist independently
                    # (Q7); uncoded rows group into one slot per product.
                    # The one-host backstop below stays product-level.
                    slots: dict[tuple[str, str | None], list] = {}
                    by_product: dict[str, list] = {}
                    seen_supplier_rows: set[tuple[str, str, str | None]] = set()
                    for row in trim.fitments:
                        row_count += 1
                        row_path = f"{trim_path}.{row.product_id}@{row.supplier_id}"
                        key = (row.product_id, row.supplier_id, row.solution_code)
                        if key in seen_supplier_rows:
                            issues.append(
                                _issue(
                                    "duplicate_supplier_slot",
                                    row_path,
                                    f"Supplier {row.supplier_id!r} appears twice for "
                                    f"product {row.product_id!r} solution "
                                    f"{row.solution_code!r} in trim {trim.trim_id!r}; "
                                    "one row per supplier per solution slot.",
                                )
                            )
                        seen_supplier_rows.add(key)
                        if row.fitment_kind == "rate" and not 0.0 <= row.fitment <= 1.0:
                            issues.append(
                                _issue(
                                    "fitment_out_of_range",
                                    row_path,
                                    f"Rate-kind fitment {row.fitment} is outside [0, 1].",
                                )
                            )
                        if row.fitment_kind == "count" and row.fitment < 0.0:
                            issues.append(
                                _issue(
                                    "fitment_negative",
                                    row_path,
                                    f"Count-kind fitment {row.fitment} is negative.",
                                )
                            )
                        if not 0.0 <= row.supplier_share <= 1.0:
                            issues.append(
                                _issue(
                                    "supplier_share_out_of_range",
                                    row_path,
                                    f"Supplier share {row.supplier_share} is outside [0, 1].",
                                )
                            )
                        if row.price is not None and row.price < 0.0:
                            issues.append(
                                _issue(
                                    "price_negative",
                                    row_path,
                                    f"Price {row.price} is negative.",
                                )
                            )
                        slots.setdefault((row.product_id, row.solution_code), []).append(row)
                        by_product.setdefault(row.product_id, []).append(row)
                    for (product_id, solution_code), rows in slots.items():
                        slot_count += 1
                        slot_path = f"{trim_path}.{product_id}"
                        if solution_code is not None:
                            slot_path += f"[{solution_code}]"
                        share_total = sum(row.supplier_share for row in rows)
                        if not _sums_to_one(share_total):
                            issues.append(
                                _issue(
                                    "supplier_shares_sum",
                                    slot_path,
                                    f"Supplier shares for product {product_id!r} solution "
                                    f"{solution_code!r} sum to {share_total}, not 1 "
                                    f"(tolerance {SUM_TOLERANCE}).",
                                )
                            )
                    for product_id, rows in by_product.items():
                        if product_id in ONE_HOST_PRODUCTS:
                            weighted = sum(
                                row.supplier_share * row.fitment
                                for row in rows
                                if row.fitment_kind == "rate"
                            )
                            if weighted > 1.0 + SUM_TOLERANCE:
                                issues.append(
                                    _issue(
                                        "one_host_fitment_exceeded",
                                        f"{trim_path}.{product_id}",
                                        f"One-host product {product_id!r} has a "
                                        f"share-weighted fitment sum of {weighted}, "
                                        "above 1: one car takes one host unit.",
                                    )
                                )
                if not _sums_to_one(trim_total):
                    issues.append(
                        _issue(
                            "trim_shares_sum",
                            gen_path,
                            f"Trim shares in generation {generation.generation_id!r} sum to "
                            f"{trim_total}, not 1 (tolerance {SUM_TOLERANCE}).",
                        )
                    )
            if not _sums_to_one(generation_total):
                issues.append(
                    _issue(
                        "generation_shares_sum",
                        plate_path,
                        f"Generation shares in nameplate {nameplate.nameplate_id!r} sum to "
                        f"{generation_total}, not 1 (tolerance {SUM_TOLERANCE}).",
                    )
                )
            schedule = nameplate.transition_schedule
            if schedule is not None:
                _validate_transition_schedule(schedule, nameplate, plate_path, issues)
        if not _sums_to_one(nameplate_total):
            issues.append(
                _issue(
                    "nameplate_shares_sum",
                    oem_path,
                    f"Nameplate shares in OEM {oem.oem_id!r} sum to {nameplate_total}, "
                    f"not 1 (tolerance {SUM_TOLERANCE}).",
                )
            )

    def _status(kinds: set[str]) -> str:
        return "fail" if any(issue.kind in kinds for issue in issues) else "pass"

    checks = [
        SplitCheckRecord(
            check="structure",
            status=_status(
                {
                    "empty_structure",
                    "empty_nameplates",
                    "empty_generations",
                    "empty_trims",
                    "empty_fitments",
                    "duplicate_oem",
                    "duplicate_nameplate",
                    "duplicate_generation",
                    "duplicate_trim",
                    "duplicate_supplier_slot",
                }
            ),
            detail=f"{len(structure.oems)} OEM(s), {slot_count} slot(s), {row_count} row(s)",
        ),
        SplitCheckRecord(
            check="nameplate_shares",
            status=_status({"nameplate_shares_sum", "nameplate_share_out_of_range"}),
            detail="per-OEM sums",
        ),
        SplitCheckRecord(
            check="generation_shares",
            status=_status({"generation_shares_sum", "generation_share_out_of_range"}),
            detail="per-nameplate sums",
        ),
        SplitCheckRecord(
            check="transition_schedules",
            status=_status(
                {
                    "transition_schedule_unknown_generation",
                    "transition_schedule_phase_mismatch",
                    "transition_schedule_composition",
                }
            ),
            detail="per-nameplate schedule references + composition",
        ),
        SplitCheckRecord(
            check="trim_shares",
            status=_status({"trim_shares_sum", "trim_share_out_of_range"}),
            detail="per-generation sums",
        ),
        SplitCheckRecord(
            check="supplier_shares",
            status=_status({"supplier_shares_sum", "supplier_share_out_of_range"}),
            detail="per-slot sums",
        ),
        SplitCheckRecord(
            check="fitments",
            status=_status(
                {
                    "fitment_out_of_range",
                    "fitment_negative",
                    "one_host_fitment_exceeded",
                    "price_negative",
                }
            ),
            detail="rate/count ranges + one-host rule",
        ),
    ]
    return SplitValidationResult(is_valid=not issues, checks=checks, issues=issues)


def validate_or_raise(structure: SplitStructure) -> SplitValidationResult:
    """Validate a structure, raising :class:`SplitValidationError` on failure."""

    result = validate_split_structure(structure)
    if not result.is_valid:
        raise SplitValidationError(result)
    return result


def oem_share_issues(
    oem_ids: set[str], shares: dict[str, float]
) -> list[tuple[str, str]]:
    """``(kind, message)`` issues for an OEM-mix map against an OEM set.

    Shared by the run-creation gate (structured issues via
    :func:`validate_oem_shares`) and the S-layer computation (first
    issue raised as ``ValueError`` by ``sales_layer._validate_shares``)
    so the two paths can never disagree on the rules. Check order
    matches the Phase 2 behavior: unknown OEMs, then missing OEMs,
    then per-share ranges (dict order), then the sum — the sum check
    is skipped when a range issue exists, since the total cannot be
    trusted then.
    """

    issues: list[tuple[str, str]] = []
    unknown = sorted(set(shares) - oem_ids)
    if unknown:
        issues.append(
            (
                "oem_shares_unknown_oem",
                f"OEM production shares name unknown OEMs: {unknown}.",
            )
        )
    missing = sorted(oem_ids - set(shares))
    if missing:
        issues.append(
            (
                "oem_shares_missing_oem",
                (
                    f"No production share supplied for OEMs {missing}; "
                    "the S-layer refuses to assume one."
                ),
            )
        )
    total = 0.0
    range_ok = True
    for oem_id, share in shares.items():
        if (
            isinstance(share, bool)
            or not isinstance(share, (int, float))
            or not math.isfinite(float(share))
            or not 0.0 <= float(share) <= 1.0
        ):
            issues.append(
                (
                    "oem_shares_out_of_range",
                    f"Production share for OEM {oem_id!r} must be a number in [0, 1].",
                )
            )
            range_ok = False
        else:
            total += float(share)
    if range_ok and abs(total - 1.0) > SUM_TOLERANCE:
        issues.append(
            (
                "oem_shares_sum",
                f"OEM production shares sum to {total}, not 1 (tolerance {SUM_TOLERANCE}).",
            )
        )
    return issues


def validate_oem_shares(
    structure: SplitStructure, shares: OemProductionShares
) -> list[SplitValidationIssue]:
    """Structured OEM-share issues for the run-creation gate.

    The stored mix must cover exactly the structure's OEMs, with every
    value in [0, 1] and the total at 1 (tolerance 1e-9). Returns []
    when the mix is acceptable; the caller refuses run creation on any
    issue, mirroring the split-structure gate.
    """

    oem_ids = {oem.oem_id for oem in structure.oems}
    return [
        _issue(kind, "", message)
        for kind, message in oem_share_issues(oem_ids, shares.shares)
    ]
