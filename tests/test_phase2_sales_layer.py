"""Phase 2 S-layer tests: snapshot-trajectory extraction and the
snapshot-wired capacity + own-sales computation."""

from __future__ import annotations

import pytest

from planagent.services.splits import (
    SplitStructure,
    SplitValidationError,
    compute_sales_layer,
)
from planagent.services.splits.sales_layer import extract_production_trajectory


def _sagitar_structure() -> SplitStructure:
    """The two-subpopulation Sagitar pattern: outgoing (0.6) + successor
    (0.4) with flipped supplier shares, on a 6-tick schedule."""
    return SplitStructure.model_validate(
        {
            "oems": [
                {
                    "oem_id": "faw-vw",
                    "customer_status": "existing",
                    "nameplates": [
                        {
                            "nameplate_id": "sagitar",
                            "energy": "ICE",
                            "price_band": "10-15",
                            "share": 1.0,
                            "model_year": 2026,
                            "transition_schedule": {
                                "outgoing_generation_id": "gen-out",
                                "successor_generation_id": "gen-new",
                                "start_tick": 1,
                                "duration_ticks": 6,
                            },
                            "generations": [
                                {
                                    "generation_id": "gen-out",
                                    "lifecycle_phase": "phase_out",
                                    "share": 0.6,
                                    "trims": [
                                        {
                                            "trim_id": "mid",
                                            "share": 1.0,
                                            "morphology": "discrete_host",
                                            "fitments": [
                                                {
                                                    "product_id": "P01",
                                                    "fitment_kind": "rate",
                                                    "fitment": 1.0,
                                                    "supplier_id": "ho",
                                                    "supplier_share": 0.9,
                                                    "price": 1200.0,
                                                    "solution_code": "SA8155P",
                                                },
                                                {
                                                    "product_id": "P01",
                                                    "fitment_kind": "rate",
                                                    "fitment": 1.0,
                                                    "supplier_id": "other",
                                                    "supplier_share": 0.1,
                                                    "price": 1200.0,
                                                    "solution_code": "SA8155P",
                                                },
                                                {
                                                    "product_id": "P03",
                                                    "fitment_kind": "rate",
                                                    "fitment": 1.0,
                                                    "supplier_id": "ho",
                                                    "supplier_share": 1.0,
                                                    "price": 800.0,
                                                    "solution_code": "ABT12.9",
                                                },
                                            ],
                                        }
                                    ],
                                },
                                {
                                    "generation_id": "gen-new",
                                    "lifecycle_phase": "ramp",
                                    "share": 0.4,
                                    "trims": [
                                        {
                                            "trim_id": "mid",
                                            "share": 1.0,
                                            "morphology": "discrete_host",
                                            "fitments": [
                                                {
                                                    "product_id": "P01",
                                                    "fitment_kind": "rate",
                                                    "fitment": 1.0,
                                                    "supplier_id": "ho",
                                                    "supplier_share": 0.1,
                                                    "price": 1200.0,
                                                    "solution_code": "SA8295P",
                                                },
                                                {
                                                    "product_id": "P01",
                                                    "fitment_kind": "rate",
                                                    "fitment": 1.0,
                                                    "supplier_id": "other",
                                                    "supplier_share": 0.9,
                                                    "price": 1200.0,
                                                    "solution_code": "SA8295P",
                                                },
                                                {
                                                    "product_id": "P02",
                                                    "fitment_kind": "rate",
                                                    "fitment": 0.8,
                                                    "supplier_id": "ho",
                                                    "supplier_share": 1.0,
                                                    "price": 2500.0,
                                                    "solution_code": "RHP:SA8650",
                                                },
                                                {
                                                    "product_id": "P05",
                                                    "fitment_kind": "count",
                                                    "fitment": 11.0,
                                                    "supplier_id": "ho",
                                                    "supplier_share": 1.0,
                                                    "price": 120.0,
                                                    "solution_code": "11颗组",
                                                },
                                                {
                                                    "product_id": "P03",
                                                    "fitment_kind": "rate",
                                                    "fitment": 1.0,
                                                    "supplier_id": "ho",
                                                    "supplier_share": 1.0,
                                                    "price": 800.0,
                                                    "solution_code": "ABT12.9",
                                                },
                                            ],
                                        }
                                    ],
                                },
                            ],
                        }
                    ],
                }
            ]
        }
    )


def _prospect_structure() -> SplitStructure:
    return SplitStructure.model_validate(
        {
            "oems": [
                {
                    "oem_id": "dongfeng-honda",
                    "customer_status": "prospect",
                    "nameplates": [
                        {
                            "nameplate_id": "cr-v",
                            "energy": "ICE",
                            "price_band": "15-20",
                            "share": 1.0,
                            "generations": [
                                {
                                    "generation_id": "g1",
                                    "lifecycle_phase": "mature",
                                    "share": 1.0,
                                    "trims": [
                                        {
                                            "trim_id": "mid",
                                            "share": 1.0,
                                            "fitments": [
                                                {
                                                    "product_id": "P01",
                                                    "fitment_kind": "rate",
                                                    "fitment": 1.0,
                                                    "supplier_id": "ho",
                                                    "supplier_share": 1.0,
                                                    "price": 1000.0,
                                                }
                                            ],
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ]
        }
    )


# --- Trajectory extraction -------------------------------------------------


def test_extract_trajectory_excludes_tick_zero() -> None:
    trajectory = extract_production_trajectory(
        [
            (0, {"production_volume": 287.8}),
            (1, {"production_volume": 280.0}),
            (2, {"production_volume": 270.0}),
        ]
    )
    assert trajectory == {1: 280.0, 2: 270.0}


def test_extract_trajectory_missing_production_refuses() -> None:
    with pytest.raises(ValueError, match="production_volume"):
        extract_production_trajectory([(1, {"cash": 100.0})])


def test_extract_trajectory_duplicate_tick_refuses() -> None:
    with pytest.raises(ValueError, match="Duplicate snapshot"):
        extract_production_trajectory(
            [(1, {"production_volume": 280.0}), (1, {"production_volume": 280.0})]
        )


def test_extract_trajectory_empty_refuses() -> None:
    with pytest.raises(ValueError, match="no trajectory"):
        extract_production_trajectory([(0, {"production_volume": 287.8})])


# --- Computation -----------------------------------------------------------


def test_compute_single_tick_exact_values() -> None:
    # Tick 1: schedule progress 1/6 interpolates 0.6/0.4 -> 0.5/0.5.
    result = compute_sales_layer(
        _sagitar_structure(),
        {1: 100.0},
        {"faw-vw": 1.0},
        own_supplier_id="ho",
    )
    by_product = {(row.oem_id, row.product_id): row for row in result.rows}
    assert by_product[("faw-vw", "P01")].units == pytest.approx(100.0)
    assert by_product[("faw-vw", "P01")].capacity_value == pytest.approx(120_000.0)
    # Ho: 0.5 x 0.9 + 0.5 x 0.1 = 0.5 of the 100 hosts.
    assert by_product[("faw-vw", "P01")].own_sales == pytest.approx(60_000.0)
    assert by_product[("faw-vw", "P02")].units == pytest.approx(40.0)
    assert by_product[("faw-vw", "P02")].capacity_value == pytest.approx(100_000.0)
    assert by_product[("faw-vw", "P02")].own_sales == pytest.approx(100_000.0)
    assert by_product[("faw-vw", "P05")].units == pytest.approx(550.0)
    assert by_product[("faw-vw", "P05")].capacity_value == pytest.approx(66_000.0)
    assert by_product[("faw-vw", "P03")].capacity_value == pytest.approx(80_000.0)
    assert result.summary.total_capacity_value == pytest.approx(366_000.0)
    assert result.summary.total_own_sales == pytest.approx(306_000.0)
    assert result.summary.tick_count == 1
    assert result.own_sales_basis == "supplier_rows"
    assert result.own_sales_unavailable_reason is None


def test_compute_schedule_moves_mix_over_ticks() -> None:
    result = compute_sales_layer(
        _sagitar_structure(),
        {1: 100.0, 6: 100.0},
        {"faw-vw": 1.0},
        own_supplier_id="ho",
    )
    p02 = [row for row in result.rows if row.product_id == "P02"]
    assert p02[0].units == pytest.approx(40.0)
    assert p02[1].units == pytest.approx(80.0)
    p01_own = [row.own_sales for row in result.rows if row.product_id == "P01"]
    assert p01_own[0] == pytest.approx(60_000.0)
    assert p01_own[1] == pytest.approx(12_000.0)
    assert [tick.production_volume for tick in result.per_tick] == [100.0, 100.0]


def test_compute_production_scales_sales_linearly() -> None:
    base = compute_sales_layer(
        _sagitar_structure(), {1: 100.0}, {"faw-vw": 1.0}, own_supplier_id="ho"
    )
    halved = compute_sales_layer(
        _sagitar_structure(), {1: 50.0}, {"faw-vw": 1.0}, own_supplier_id="ho"
    )
    assert halved.summary.total_capacity_value == pytest.approx(
        base.summary.total_capacity_value / 2
    )
    assert halved.summary.total_own_sales == pytest.approx(base.summary.total_own_sales / 2)


def test_compute_shares_must_cover_and_sum_to_one() -> None:
    structure = _sagitar_structure()
    with pytest.raises(ValueError, match="sum to"):
        compute_sales_layer(structure, {1: 100.0}, {"faw-vw": 0.5})
    with pytest.raises(ValueError, match="unknown OEM"):
        compute_sales_layer(structure, {1: 100.0}, {"faw-vw": 0.5, "nope": 0.5})
    with pytest.raises(ValueError, match="No production share"):
        compute_sales_layer(structure, {1: 100.0}, {})


def test_compute_prospect_capacity_without_sales() -> None:
    result = compute_sales_layer(
        _prospect_structure(),
        {1: 100.0},
        {"dongfeng-honda": 1.0},
        own_supplier_id="ho",
    )
    assert len(result.rows) == 1
    assert result.rows[0].capacity_value == pytest.approx(100_000.0)
    assert result.rows[0].own_sales == 0.0
    assert result.summary.total_own_sales == 0.0


def test_compute_share_attribution_with_default() -> None:
    result = compute_sales_layer(
        _sagitar_structure(),
        {1: 100.0},
        {"faw-vw": 1.0},
        default_supply_share=0.10,
    )
    assert result.own_sales_basis == "supply_share"
    for row in result.rows:
        assert row.own_sales == pytest.approx(row.capacity_value * 0.10)
    assert result.summary.total_own_sales == pytest.approx(36_600.0)


def test_compute_share_attribution_overrides_win_over_default() -> None:
    result = compute_sales_layer(
        _sagitar_structure(),
        {1: 100.0},
        {"faw-vw": 1.0},
        supply_shares={("faw-vw", "P02"): 0.5},
        default_supply_share=0.10,
    )
    by_product = {row.product_id: row for row in result.rows}
    assert by_product["P02"].own_sales == pytest.approx(50_000.0)
    assert by_product["P01"].own_sales == pytest.approx(12_000.0)


def test_compute_no_attribution_leaves_own_sales_null() -> None:
    result = compute_sales_layer(_sagitar_structure(), {1: 100.0}, {"faw-vw": 1.0})
    assert result.own_sales_basis == "unavailable"
    assert result.own_sales_unavailable_reason is not None
    assert "own_supplier_id" in result.own_sales_unavailable_reason
    assert all(row.own_sales is None for row in result.rows)
    assert result.summary.total_own_sales is None
    assert result.summary.total_capacity_value == pytest.approx(366_000.0)


def test_compute_supplier_rows_win_over_shares() -> None:
    result = compute_sales_layer(
        _sagitar_structure(),
        {1: 100.0},
        {"faw-vw": 1.0},
        own_supplier_id="ho",
        default_supply_share=0.10,
    )
    assert result.own_sales_basis == "supplier_rows"
    assert result.summary.total_own_sales == pytest.approx(306_000.0)
    assert any("wins over share attribution" in note for note in result.assumptions)


def test_compute_strict_prices_refuse_unpriced_slots() -> None:
    structure = _sagitar_structure()
    structure.oems[0].nameplates[0].generations[0].trims[0].fitments[0].price = None
    with pytest.raises(ValueError, match="Cannot compute capacity"):
        compute_sales_layer(structure, {1: 100.0}, {"faw-vw": 1.0}, own_supplier_id="ho")


def test_compute_non_strict_skips_unpriced_slots_loudly() -> None:
    structure = _sagitar_structure()
    structure.oems[0].nameplates[0].generations[0].trims[0].fitments[0].price = None
    result = compute_sales_layer(
        structure, {1: 100.0}, {"faw-vw": 1.0}, own_supplier_id="ho", strict_prices=False
    )
    assert len(result.skipped_unpriced_slots) == 1
    assert "P01@ho" in result.skipped_unpriced_slots[0]
    by_product = {row.product_id: row for row in result.rows}
    # Units still computed for the unpriced slot; capacity excludes it.
    assert by_product["P01"].units == pytest.approx(100.0)
    assert by_product["P01"].capacity_value == pytest.approx(120_000.0 - 45.0 * 1200.0)
    # Own sales cover only the priced Ho rows (the successor slot); the
    # skipped slot is disclosed in skipped_unpriced_slots.
    assert by_product["P01"].own_sales == pytest.approx(6_000.0)


def test_compute_invalid_structure_refuses() -> None:
    structure = _sagitar_structure()
    structure.oems[0].nameplates[0].share = 0.5
    with pytest.raises(SplitValidationError):
        compute_sales_layer(structure, {1: 100.0}, {"faw-vw": 1.0})
