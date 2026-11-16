"""Unit tests for the bottom-layer split gates (Phase 1 automotive pack).

Covers the split validator (sum-to-1 gates at every level, the
workbook F02 regression, the Sagitar two-sub-population pattern, the
one-host backstop, empty/duplicate rejection) and the aggregation
helpers (production-volume spine, both S-layer paths, prospect
zeroing, loud failure on missing priors and unpriced slots, and the
generation-transition mix).
"""

from __future__ import annotations

import pytest

from planagent.services.splits import (
    GenerationSplit,
    NameplateSplit,
    OemSplit,
    ProductFitment,
    SplitStructure,
    SplitValidationError,
    TrimSplit,
    aggregate_capacity,
    aggregate_units,
    generation_mix_at_index,
    market_capacity_by_oem_product,
    own_sales_from_supplier_rows,
    own_sales_with_share,
    prior_fitment_rate,
    simulated_supply_share,
    validate_or_raise,
    validate_split_structure,
)

OWN = "ho-supplier"
OTHER = "other-supplier"


def _fitment(
    product_id: str,
    supplier_id: str,
    share: float,
    *,
    fitment: float = 0.8,
    kind: str = "rate",
    price: float | None = 100.0,
) -> ProductFitment:
    return ProductFitment(
        product_id=product_id,
        fitment_kind=kind,  # type: ignore[arg-type]
        fitment=fitment,
        supplier_id=supplier_id,
        supplier_share=share,
        price=price,
    )


def _trim(trim_id: str, share: float, fitments: list[ProductFitment] | None = None) -> TrimSplit:
    if fitments is None:
        fitments = [
            _fitment("P01", OWN, 0.1),
            _fitment("P01", OTHER, 0.9),
        ]
    return TrimSplit(trim_id=trim_id, share=share, fitments=fitments)


def _generation(
    generation_id: str,
    share: float,
    phase: str = "mature",
    trims: list[TrimSplit] | None = None,
) -> GenerationSplit:
    if trims is None:
        trims = [_trim("high", 0.3), _trim("low", 0.7)]
    return GenerationSplit(
        generation_id=generation_id,
        lifecycle_phase=phase,  # type: ignore[arg-type]
        share=share,
        trims=trims,
    )


def _nameplate(
    nameplate_id: str,
    share: float,
    generations: list[GenerationSplit] | None = None,
    *,
    energy: str = "ICE",
    price_band: str = "10-15",
) -> NameplateSplit:
    if generations is None:
        generations = [_generation("gen-1", 1.0)]
    return NameplateSplit(
        nameplate_id=nameplate_id,
        energy=energy,  # type: ignore[arg-type]
        price_band=price_band,
        share=share,
        generations=generations,
    )


def _oem(
    oem_id: str,
    nameplates: list[NameplateSplit] | None = None,
    *,
    customer_status: str = "existing",
) -> OemSplit:
    if nameplates is None:
        nameplates = [_nameplate("sagitar", 1.0)]
    return OemSplit(
        oem_id=oem_id,
        customer_status=customer_status,  # type: ignore[arg-type]
        nameplates=nameplates,
    )


def _valid_structure() -> SplitStructure:
    return SplitStructure(oems=[_oem("faw-vw")])


def _kinds(result) -> list[str]:
    return [issue.kind for issue in result.issues]


# --- Validator: valid structures -------------------------------------------


def test_valid_structure_passes_all_checks() -> None:
    result = validate_split_structure(_valid_structure())
    assert result.is_valid is True
    assert result.issues == []
    assert {check.check for check in result.checks} == {
        "structure",
        "nameplate_shares",
        "generation_shares",
        "trim_shares",
        "supplier_shares",
        "fitments",
    }
    assert all(check.status == "pass" for check in result.checks)
    assert validate_or_raise(_valid_structure()).is_valid is True


def test_valid_supplier_split_01_09_passes() -> None:
    # The legitimate Ho pattern: two suppliers split one slot 0.1/0.9.
    structure = SplitStructure(
        oems=[
            _oem(
                "faw-vw",
                [
                    _nameplate(
                        "sagitar",
                        1.0,
                        [
                            _generation(
                                "gen-1",
                                1.0,
                                trims=[
                                    _trim(
                                        "high",
                                        1.0,
                                        [
                                            _fitment("P01", OWN, 0.1),
                                            _fitment("P01", OTHER, 0.9),
                                        ],
                                    )
                                ],
                            )
                        ],
                    )
                ],
            )
        ]
    )
    assert validate_split_structure(structure).is_valid is True


def test_sagitar_two_subpopulations_pass() -> None:
    # Two sub-populations (trim groups or generations) under one
    # nameplate, each with its own volume weight and its own supplier
    # split — the Sagitar pattern, covered by the sum-to-1 gates.
    structure = SplitStructure(
        oems=[
            _oem(
                "faw-vw",
                [
                    _nameplate(
                        "sagitar",
                        1.0,
                        [
                            _generation(
                                "gen-a",
                                0.6,
                                trims=[
                                    _trim(
                                        "high",
                                        1.0,
                                        [
                                            _fitment("P01", OWN, 0.1),
                                            _fitment("P01", OTHER, 0.9),
                                        ],
                                    )
                                ],
                            ),
                            _generation(
                                "gen-b",
                                0.4,
                                trims=[
                                    _trim(
                                        "high",
                                        1.0,
                                        [
                                            _fitment("P01", OWN, 0.9),
                                            _fitment("P01", OTHER, 0.1),
                                        ],
                                    )
                                ],
                            ),
                        ],
                    )
                ],
            )
        ]
    )
    assert validate_split_structure(structure).is_valid is True


def test_generation_transition_structure_passes() -> None:
    # Outgoing phase_out + successor ramp under one nameplate.
    structure = SplitStructure(
        oems=[
            _oem(
                "faw-vw",
                [
                    _nameplate(
                        "t-roc",
                        1.0,
                        [
                            _generation("gen-out", 0.7, "phase_out"),
                            _generation("gen-new", 0.3, "ramp"),
                        ],
                    )
                ],
            )
        ]
    )
    assert validate_split_structure(structure).is_valid is True


# --- Validator: sum-to-1 gates ---------------------------------------------


def test_f02_regression_supplier_shares_summing_to_two_refused() -> None:
    # Workbook F02: fitment rows summing to 2.0 (two 1.0 rows for one
    # slot) must be refused, not silently double-counted.
    structure = SplitStructure(
        oems=[
            _oem(
                "faw-vw",
                [
                    _nameplate(
                        "sagitar",
                        1.0,
                        [
                            _generation(
                                "gen-1",
                                1.0,
                                trims=[
                                    _trim(
                                        "high",
                                        1.0,
                                        [
                                            _fitment("P01", OWN, 1.0),
                                            _fitment("P01", OTHER, 1.0),
                                        ],
                                    )
                                ],
                            )
                        ],
                    )
                ],
            )
        ]
    )
    result = validate_split_structure(structure)
    assert result.is_valid is False
    assert "supplier_shares_sum" in _kinds(result)
    with pytest.raises(SplitValidationError):
        validate_or_raise(structure)


def test_nameplate_shares_must_sum_to_one() -> None:
    structure = SplitStructure(
        oems=[_oem("faw-vw", [_nameplate("sagitar", 0.6), _nameplate("t-roc", 0.3)])]
    )
    result = validate_split_structure(structure)
    assert result.is_valid is False
    assert "nameplate_shares_sum" in _kinds(result)


def test_generation_shares_must_sum_to_one() -> None:
    structure = SplitStructure(
        oems=[
            _oem(
                "faw-vw",
                [
                    _nameplate(
                        "t-roc",
                        1.0,
                        [
                            _generation("gen-out", 0.7, "phase_out"),
                            _generation("gen-new", 0.2, "ramp"),
                        ],
                    )
                ],
            )
        ]
    )
    result = validate_split_structure(structure)
    assert result.is_valid is False
    assert "generation_shares_sum" in _kinds(result)


def test_trim_shares_must_sum_to_one() -> None:
    structure = SplitStructure(
        oems=[
            _oem(
                "faw-vw",
                [
                    _nameplate(
                        "sagitar",
                        1.0,
                        [_generation("gen-1", 1.0, trims=[_trim("high", 0.3), _trim("low", 0.6)])],
                    )
                ],
            )
        ]
    )
    result = validate_split_structure(structure)
    assert result.is_valid is False
    assert "trim_shares_sum" in _kinds(result)


def test_shares_out_of_range_refused() -> None:
    structure = SplitStructure(oems=[_oem("faw-vw", [_nameplate("sagitar", 1.2)])])
    assert "nameplate_share_out_of_range" in _kinds(validate_split_structure(structure))


def test_rate_fitment_above_one_refused() -> None:
    structure = SplitStructure(
        oems=[
            _oem(
                "faw-vw",
                [
                    _nameplate(
                        "sagitar",
                        1.0,
                        [
                            _generation(
                                "gen-1",
                                1.0,
                                trims=[
                                    _trim("high", 1.0, [_fitment("P01", OWN, 1.0, fitment=1.5)])
                                ],
                            )
                        ],
                    )
                ],
            )
        ]
    )
    assert "fitment_out_of_range" in _kinds(validate_split_structure(structure))


def test_count_fitment_above_one_allowed() -> None:
    # Cameras per car: a count, not a rate.
    structure = SplitStructure(
        oems=[
            _oem(
                "faw-vw",
                [
                    _nameplate(
                        "sagitar",
                        1.0,
                        [
                            _generation(
                                "gen-1",
                                1.0,
                                trims=[
                                    _trim(
                                        "high",
                                        1.0,
                                        [_fitment("P05", OWN, 1.0, fitment=5.58, kind="count")],
                                    )
                                ],
                            )
                        ],
                    )
                ],
            )
        ]
    )
    assert validate_split_structure(structure).is_valid is True


def test_one_host_backstop_fires() -> None:
    # Shares 0.6/0.6 with full fitment: the supplier gate fires, and the
    # one-host backstop fires too (weighted fitment 1.2 > 1).
    structure = SplitStructure(
        oems=[
            _oem(
                "faw-vw",
                [
                    _nameplate(
                        "sagitar",
                        1.0,
                        [
                            _generation(
                                "gen-1",
                                1.0,
                                trims=[
                                    _trim(
                                        "high",
                                        1.0,
                                        [
                                            _fitment("P01", OWN, 0.6, fitment=1.0),
                                            _fitment("P01", OTHER, 0.6, fitment=1.0),
                                        ],
                                    )
                                ],
                            )
                        ],
                    )
                ],
            )
        ]
    )
    kinds = _kinds(validate_split_structure(structure))
    assert "supplier_shares_sum" in kinds
    assert "one_host_fitment_exceeded" in kinds


def test_empty_structures_refused() -> None:
    assert "empty_structure" in _kinds(validate_split_structure(SplitStructure(oems=[])))
    assert "empty_nameplates" in _kinds(
        validate_split_structure(SplitStructure(oems=[_oem("faw-vw", [])]))
    )
    assert "empty_generations" in _kinds(
        validate_split_structure(
            SplitStructure(oems=[_oem("faw-vw", [_nameplate("sagitar", 1.0, [])])])
        )
    )
    assert "empty_trims" in _kinds(
        validate_split_structure(
            SplitStructure(
                oems=[
                    _oem("faw-vw", [_nameplate("sagitar", 1.0, [_generation("g", 1.0, trims=[])])])
                ]
            )
        )
    )
    assert "empty_fitments" in _kinds(
        validate_split_structure(
            SplitStructure(
                oems=[
                    _oem(
                        "faw-vw",
                        [
                            _nameplate(
                                "sagitar",
                                1.0,
                                [_generation("g", 1.0, trims=[_trim("high", 1.0, [])])],
                            )
                        ],
                    )
                ]
            )
        )
    )


def test_duplicate_ids_refused() -> None:
    dup_oem = SplitStructure(oems=[_oem("faw-vw"), _oem("faw-vw")])
    assert "duplicate_oem" in _kinds(validate_split_structure(dup_oem))
    dup_plate = SplitStructure(
        oems=[_oem("faw-vw", [_nameplate("sagitar", 0.5), _nameplate("sagitar", 0.5)])]
    )
    assert "duplicate_nameplate" in _kinds(validate_split_structure(dup_plate))
    dup_supplier = SplitStructure(
        oems=[
            _oem(
                "faw-vw",
                [
                    _nameplate(
                        "sagitar",
                        1.0,
                        [
                            _generation(
                                "g",
                                1.0,
                                trims=[
                                    _trim(
                                        "high",
                                        1.0,
                                        [
                                            _fitment("P01", OWN, 0.5),
                                            _fitment("P01", OWN, 0.5),
                                        ],
                                    )
                                ],
                            )
                        ],
                    )
                ],
            )
        ]
    )
    assert "duplicate_supplier_slot" in _kinds(validate_split_structure(dup_supplier))


# --- Aggregation ------------------------------------------------------------


def test_aggregate_units_production_spine_math() -> None:
    structure = _valid_structure()
    slots = aggregate_units(structure, {"faw-vw": 100.0})
    # high trim (0.3) x fitment 0.8 x supplier 0.1 = 2.4; x 0.9 = 21.6.
    # low trim (0.7) x 0.8 x 0.1 = 5.6; x 0.9 = 50.4.
    by_key = {(s["trim_id"], s["supplier_id"]): s["units"] for s in slots}
    assert by_key == {
        ("high", OWN): pytest.approx(2.4),
        ("high", OTHER): pytest.approx(21.6),
        ("low", OWN): pytest.approx(5.6),
        ("low", OTHER): pytest.approx(50.4),
    }
    assert sum(s["units"] for s in slots) == pytest.approx(80.0)


def test_aggregate_units_missing_volume_refuses() -> None:
    with pytest.raises(ValueError, match="No production volume"):
        aggregate_units(_valid_structure(), {})


def test_aggregate_units_invalid_structure_refuses() -> None:
    bad = SplitStructure(oems=[])
    with pytest.raises(SplitValidationError):
        aggregate_units(bad, {})


def test_capacity_and_market_totals() -> None:
    slots = aggregate_capacity(aggregate_units(_valid_structure(), {"faw-vw": 100.0}))
    assert all("capacity" in slot for slot in slots)
    totals = market_capacity_by_oem_product(slots)
    # 80 units x price 100.
    assert totals == {("faw-vw", "P01"): pytest.approx(8000.0)}


def test_aggregate_capacity_unpriced_slot_refuses() -> None:
    structure = SplitStructure(
        oems=[
            _oem(
                "faw-vw",
                [
                    _nameplate(
                        "sagitar",
                        1.0,
                        [
                            _generation(
                                "g",
                                1.0,
                                trims=[
                                    _trim(
                                        "high",
                                        1.0,
                                        [_fitment("P01", OWN, 1.0, price=None)],
                                    )
                                ],
                            )
                        ],
                    )
                ],
            )
        ]
    )
    assert validate_split_structure(structure).is_valid is True
    with pytest.raises(ValueError, match="Cannot compute capacity"):
        aggregate_capacity(aggregate_units(structure, {"faw-vw": 100.0}))


def test_own_sales_from_supplier_rows() -> None:
    slots = aggregate_capacity(aggregate_units(_valid_structure(), {"faw-vw": 100.0}))
    own = own_sales_from_supplier_rows(slots, OWN)
    # Own units 2.4 + 5.6 = 8.0 x price 100.
    assert own == {("faw-vw", "P01"): pytest.approx(800.0)}


def test_own_sales_with_share_and_prospect_zero() -> None:
    structure = SplitStructure(
        oems=[
            _oem("faw-vw"),
            _oem("dongfeng-honda", customer_status="prospect"),
        ]
    )
    slots = aggregate_capacity(
        aggregate_units(structure, {"faw-vw": 100.0, "dongfeng-honda": 50.0})
    )
    totals = market_capacity_by_oem_product(slots)
    # Prospect market capacity is computed (40 units x 100)...
    assert totals[("dongfeng-honda", "P01")] == pytest.approx(4000.0)
    # ...but prospect own sales are always 0, even with a default share.
    sales = own_sales_with_share(totals, structure, default_share=0.10)
    assert sales[("dongfeng-honda", "P01")] == 0.0
    assert sales[("faw-vw", "P01")] == pytest.approx(800.0)
    # Per-pair overrides beat the default.
    sales = own_sales_with_share(
        totals, structure, supply_shares={("faw-vw", "P01"): 0.5}, default_share=0.10
    )
    assert sales[("faw-vw", "P01")] == pytest.approx(4000.0)
    with pytest.raises(ValueError, match="outside"):
        own_sales_with_share(totals, structure, default_share=1.5)


def test_prospect_supplier_rows_contribute_zero() -> None:
    structure = SplitStructure(oems=[_oem("dongfeng-honda", customer_status="prospect")])
    slots = aggregate_capacity(aggregate_units(structure, {"dongfeng-honda": 50.0}))
    assert own_sales_from_supplier_rows(slots, OWN) == {}


def test_prior_fitment_rate_lookup_and_missing_cell() -> None:
    data = {"fitment_lookup": {"l2_by_price_band": {"<10": 0.111, "20-30": 0.693}}}
    assert prior_fitment_rate(data, "l2_by_price_band", "20-30") == 0.693
    with pytest.raises(ValueError, match="no cell"):
        prior_fitment_rate(data, "l2_by_price_band", "30-40")
    with pytest.raises(ValueError, match="no series"):
        prior_fitment_rate(data, "nope", "<10")
    with pytest.raises(ValueError, match="no 'fitment_lookup'"):
        prior_fitment_rate({}, "l2_by_price_band", "<10")
    with pytest.raises(ValueError, match="outside"):
        prior_fitment_rate(
            {"fitment_lookup": {"l2_by_price_band": {"<10": 1.5}}}, "l2_by_price_band", "<10"
        )


def test_simulated_supply_share() -> None:
    assert simulated_supply_share({"supply_share_simulated": {"value": 0.10}}) == 0.10
    with pytest.raises(ValueError, match="no 'supply_share_simulated"):
        simulated_supply_share({})
    with pytest.raises(ValueError, match="outside"):
        simulated_supply_share({"supply_share_simulated": {"value": 2.0}})


def test_generation_mix_at_index() -> None:
    structure = SplitStructure(
        oems=[
            _oem(
                "faw-vw",
                [
                    _nameplate(
                        "t-roc",
                        1.0,
                        [
                            _generation("gen-out", 0.5, "phase_out"),
                            _generation("gen-new", 0.5, "ramp"),
                        ],
                    )
                ],
            )
        ]
    )
    assert generation_mix_at_index(structure, "t-roc", 0.0) == {"gen-out": 1.0, "gen-new": 0.0}
    assert generation_mix_at_index(structure, "t-roc", 0.3) == {"gen-out": 0.7, "gen-new": 0.3}
    assert generation_mix_at_index(structure, "t-roc", 1.0) == {"gen-out": 0.0, "gen-new": 1.0}
    mix = generation_mix_at_index(structure, "t-roc", 0.45)
    assert sum(mix.values()) == pytest.approx(1.0)
    with pytest.raises(ValueError, match="Transition index"):
        generation_mix_at_index(structure, "t-roc", 1.5)
    with pytest.raises(ValueError, match="No nameplate"):
        generation_mix_at_index(structure, "nope", 0.5)


def test_generation_mix_rejects_other_compositions() -> None:
    # A single mature generation has no transition pattern.
    with pytest.raises(ValueError, match="exactly one phase_out"):
        generation_mix_at_index(_valid_structure(), "sagitar", 0.5)
