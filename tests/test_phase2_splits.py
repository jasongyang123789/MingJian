"""Phase 2 unit tests: per-nameplate schedules, new model fields,
schedule gates, the Q7 no-product-sum-gate rule, and the
catalog/alias/morphology data modules."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from planagent.services.splits import (
    KNOWN_DATA_ERRORS,
    MORPHOLOGY_FACTS,
    OEMS_WITHOUT_TBOX,
    PO_SUBPRODUCTS,
    SplitStructure,
    aggregate_units,
    classify_solution,
    dc_platform,
    effective_shares_for_nameplate,
    generation_mix_at_index,
    generation_shares_at_tick,
    is_huawei_solution,
    is_po_basket,
    lookup_known_data_error,
    lookup_morphology_fact,
    parse_camera_count,
    product_line_of,
    structure_with_effective_shares,
    transition_progress,
    validate_split_structure,
)
from planagent.services.splits.models import GenerationTransitionSchedule


def _schedule(start_tick: int = 1, duration_ticks: int = 6) -> dict:
    return {
        "outgoing_generation_id": "gen-out",
        "successor_generation_id": "gen-new",
        "start_tick": start_tick,
        "duration_ticks": duration_ticks,
    }


def _structure(
    out_share: float = 0.6,
    new_share: float = 0.4,
    schedule: dict | None = None,
    extra_generations: list[dict] | None = None,
) -> SplitStructure:
    generations = [
        {
            "generation_id": "gen-out",
            "lifecycle_phase": "phase_out",
            "share": out_share,
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
                            "supplier_share": 1.0,
                            "price": 1000.0,
                            "solution_code": "SA8155P",
                        }
                    ],
                }
            ],
        },
        {
            "generation_id": "gen-new",
            "lifecycle_phase": "ramp",
            "share": new_share,
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
                            "supplier_share": 1.0,
                            "price": 1000.0,
                            "solution_code": "SA8295P",
                        }
                    ],
                }
            ],
        },
    ]
    generations.extend(extra_generations or [])
    nameplate: dict = {
        "nameplate_id": "sagitar",
        "energy": "ICE",
        "price_band": "10-15",
        "share": 1.0,
        "model_year": 2026,
        "generations": generations,
    }
    if schedule is not None:
        nameplate["transition_schedule"] = schedule
    return SplitStructure.model_validate(
        {
            "oems": [
                {
                    "oem_id": "faw-vw",
                    "customer_status": "existing",
                    "nameplates": [nameplate],
                }
            ]
        }
    )


# --- Schedule progress ---------------------------------------------------


def test_transition_progress_boundaries() -> None:
    schedule = GenerationTransitionSchedule.model_validate(_schedule(3, 4))
    assert transition_progress(schedule, 0) == 0.0
    assert transition_progress(schedule, 2) == 0.0
    assert transition_progress(schedule, 3) == pytest.approx(0.25)
    assert transition_progress(schedule, 4) == pytest.approx(0.5)
    assert transition_progress(schedule, 5) == pytest.approx(0.75)
    assert transition_progress(schedule, 6) == 1.0
    assert transition_progress(schedule, 99) == 1.0


def test_generation_shares_interpolate_from_static_shares() -> None:
    structure = _structure(schedule=_schedule(1, 6))
    assert generation_shares_at_tick(structure, "sagitar", 0) == {
        "gen-out": 0.6,
        "gen-new": 0.4,
    }
    tick1 = generation_shares_at_tick(structure, "sagitar", 1)
    assert tick1["gen-out"] == pytest.approx(0.5)
    assert tick1["gen-new"] == pytest.approx(0.5)
    tick6 = generation_shares_at_tick(structure, "sagitar", 6)
    assert tick6["gen-out"] == pytest.approx(0.0)
    assert tick6["gen-new"] == pytest.approx(1.0)
    for tick in range(9):
        shares = generation_shares_at_tick(structure, "sagitar", tick)
        assert sum(shares.values()) == pytest.approx(1.0)


def test_generation_shares_canonical_case_matches_phase1_mix() -> None:
    structure = _structure(out_share=1.0, new_share=0.0, schedule=_schedule(1, 20))
    for tick in (1, 5, 20):
        scheduled = generation_shares_at_tick(structure, "sagitar", tick)
        index = transition_progress(
            GenerationTransitionSchedule.model_validate(_schedule(1, 20)), tick
        )
        phase1 = generation_mix_at_index(structure, "sagitar", index)
        assert scheduled["gen-out"] == pytest.approx(phase1["gen-out"])
        assert scheduled["gen-new"] == pytest.approx(phase1["gen-new"])


def test_unscheduled_nameplate_keeps_static_shares() -> None:
    structure = _structure()
    for tick in (0, 1, 6, 50):
        assert generation_shares_at_tick(structure, "sagitar", tick) == {
            "gen-out": 0.6,
            "gen-new": 0.4,
        }


def test_generation_shares_unknown_and_ambiguous_refuse() -> None:
    structure = _structure()
    with pytest.raises(ValueError, match="No nameplate"):
        generation_shares_at_tick(structure, "nope", 1)


def test_structure_with_effective_shares_preserves_fields_and_validates() -> None:
    structure = _structure(schedule=_schedule(1, 6))
    effective = structure_with_effective_shares(structure, 1)
    nameplate = effective.oems[0].nameplates[0]
    assert [generation.share for generation in nameplate.generations] == pytest.approx([0.5, 0.5])
    # Morphology, solution codes, and price bases survive the copy.
    trim = nameplate.generations[0].trims[0]
    assert trim.morphology == "discrete_host"
    assert trim.fitments[0].solution_code == "SA8155P"
    assert trim.fitments[0].price_basis == "discrete"
    # The original is untouched.
    assert [g.share for g in structure.oems[0].nameplates[0].generations] == [0.6, 0.4]
    assert validate_split_structure(effective).is_valid is True


def test_effective_shares_for_nameplate_object() -> None:
    structure = _structure(schedule=_schedule(2, 2))
    nameplate = structure.oems[0].nameplates[0]
    assert effective_shares_for_nameplate(nameplate, 1) == {"gen-out": 0.6, "gen-new": 0.4}
    assert effective_shares_for_nameplate(nameplate, 2)["gen-out"] == pytest.approx(0.3)
    assert effective_shares_for_nameplate(nameplate, 3)["gen-new"] == pytest.approx(1.0)


# --- Schedule gates ------------------------------------------------------


def test_valid_schedule_passes_all_checks() -> None:
    result = validate_split_structure(_structure(schedule=_schedule()))
    assert result.is_valid is True
    assert result.issues == []
    schedules = next(check for check in result.checks if check.check == "transition_schedules")
    assert schedules.status == "pass"


def test_schedule_unknown_generation_refused() -> None:
    schedule = _schedule()
    schedule["successor_generation_id"] = "gen-missing"
    result = validate_split_structure(_structure(schedule=schedule))
    assert result.is_valid is False
    kinds = [issue.kind for issue in result.issues]
    assert "transition_schedule_unknown_generation" in kinds


def test_schedule_phase_mismatch_refused() -> None:
    schedule = _schedule()
    schedule["outgoing_generation_id"] = "gen-new"
    schedule["successor_generation_id"] = "gen-out"
    result = validate_split_structure(_structure(schedule=schedule))
    assert result.is_valid is False
    kinds = [issue.kind for issue in result.issues]
    assert "transition_schedule_phase_mismatch" in kinds


def test_schedule_same_generation_refused() -> None:
    schedule = _schedule()
    schedule["successor_generation_id"] = "gen-out"
    result = validate_split_structure(_structure(schedule=schedule))
    assert result.is_valid is False
    kinds = [issue.kind for issue in result.issues]
    assert "transition_schedule_composition" in kinds


def test_schedule_three_generations_refused() -> None:
    third = {
        "generation_id": "gen-mid",
        "lifecycle_phase": "mature",
        "share": 0.0,
        "trims": [],
    }
    structure = _structure(
        out_share=0.6,
        new_share=0.4,
        schedule=_schedule(),
        extra_generations=[third],
    )
    result = validate_split_structure(structure)
    assert result.is_valid is False
    kinds = [issue.kind for issue in result.issues]
    assert "transition_schedule_composition" in kinds


def test_schedule_model_rejects_bad_ticks() -> None:
    with pytest.raises(ValidationError):
        GenerationTransitionSchedule.model_validate(_schedule(start_tick=0))
    with pytest.raises(ValidationError):
        GenerationTransitionSchedule.model_validate(_schedule(duration_ticks=0))


def test_morphology_and_price_basis_vocabularies() -> None:
    structure = _structure()
    trim = structure.oems[0].nameplates[0].generations[0].trims[0]
    assert trim.morphology == "discrete_host"
    with pytest.raises(ValidationError):
        SplitStructure.model_validate(
            {
                "oems": [
                    {
                        "oem_id": "x",
                        "customer_status": "existing",
                        "nameplates": [
                            {
                                "nameplate_id": "n",
                                "energy": "ICE",
                                "price_band": "10-15",
                                "share": 1.0,
                                "generations": [
                                    {
                                        "generation_id": "g",
                                        "lifecycle_phase": "mature",
                                        "share": 1.0,
                                        "trims": [
                                            {"trim_id": "t", "share": 1.0, "morphology": "bogus"}
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        )


# --- Q7: fitment rates are independent penetrations ----------------------


def test_fitment_rates_need_not_sum_to_one() -> None:
    """Ho Q7 (2026-11-16): fitment rates are independent penetrations;
    the four-solution P02 block summing to 1.2 is legitimate. No
    product-level sum gate exists — this structure must validate."""
    fitments = [
        {
            "product_id": "P02",
            "fitment_kind": "rate",
            "fitment": 0.3,
            "supplier_id": f"supplier-{index}",
            "supplier_share": 0.25,
            "price": 1000.0,
            "solution_code": code,
        }
        for index, code in enumerate(["MFK:EQ4", "RHP:SA8650", "NGX:J6M", "IDU+DCM"])
    ]
    structure = SplitStructure.model_validate(
        {
            "oems": [
                {
                    "oem_id": "faw-vw",
                    "customer_status": "existing",
                    "nameplates": [
                        {
                            "nameplate_id": "t-roc",
                            "energy": "ICE",
                            "price_band": "15-20",
                            "share": 1.0,
                            "generations": [
                                {
                                    "generation_id": "g1",
                                    "lifecycle_phase": "mature",
                                    "share": 1.0,
                                    "trims": [{"trim_id": "t", "share": 1.0, "fitments": fitments}],
                                }
                            ],
                        }
                    ],
                }
            ]
        }
    )
    assert sum(row["fitment"] for row in fitments) == pytest.approx(1.2)
    assert validate_split_structure(structure).is_valid is True


# --- Catalog -------------------------------------------------------------


def test_po_catalog_granularity_and_lines() -> None:
    assert len(PO_SUBPRODUCTS) == 15
    assert PO_SUBPRODUCTS["HUD_AR"].fitment_kind == "rate"
    assert PO_SUBPRODUCTS["RADAR"].fitment_kind == "count"
    assert PO_SUBPRODUCTS["BODY_DOMAIN"].fitment_kind == "count"
    assert PO_SUBPRODUCTS["AVM"].assumption is True
    assert PO_SUBPRODUCTS["APA"].assumption is True
    assert PO_SUBPRODUCTS["UWB"].assumption is True
    assert PO_SUBPRODUCTS["HUD_AR"].assumption is False
    assert product_line_of("HUD_AR") == "P.O"
    assert product_line_of("AVM") == "P.O"
    assert product_line_of("P01") == "P01"
    assert product_line_of("P.O") == "P.O"
    assert product_line_of("UNKNOWN") is None
    assert is_po_basket("P.O") is True
    assert is_po_basket("HUD_AR") is False


def test_hud_variants_coexist_no_slot_exclusivity() -> None:
    """Ho 2026-11-17 ruling: P-HUD coexists with W/AR-HUD on the same
    vehicle; HUD penetration rates are non-exclusive. The catalog must
    state coexistence (never substitution), and one trim carrying all
    three HUD variants at rates summing above 1 must validate and
    aggregate independently: each variant is its own slot with its
    own rate (Ho Q7), never a share of one HUD slot."""
    for sub_id in ("HUD_AR", "HUD_W", "HUD_P"):
        assert PO_SUBPRODUCTS[sub_id].fitment_kind == "rate"
        assert "substitut" not in PO_SUBPRODUCTS[sub_id].notes.lower()
    assert "coexist" in PO_SUBPRODUCTS["HUD_AR"].notes.lower()
    assert "coexist" in PO_SUBPRODUCTS["HUD_P"].notes.lower()
    fitments = [
        {
            "product_id": sub_id,
            "fitment_kind": "rate",
            "fitment": rate,
            "supplier_id": "ho",
            "supplier_share": 1.0,
            "price": 1000.0,
            "solution_code": "HUD",
        }
        for sub_id, rate in (("HUD_AR", 0.6), ("HUD_W", 0.5), ("HUD_P", 0.4))
    ]
    structure = SplitStructure.model_validate(
        {
            "oems": [
                {
                    "oem_id": "faw-vw",
                    "customer_status": "existing",
                    "nameplates": [
                        {
                            "nameplate_id": "t-roc",
                            "energy": "ICE",
                            "price_band": "15-20",
                            "share": 1.0,
                            "generations": [
                                {
                                    "generation_id": "g1",
                                    "lifecycle_phase": "mature",
                                    "share": 1.0,
                                    "trims": [{"trim_id": "t", "share": 1.0, "fitments": fitments}],
                                }
                            ],
                        }
                    ],
                }
            ]
        }
    )
    assert sum(row["fitment"] for row in fitments) == pytest.approx(1.5)
    assert validate_split_structure(structure).is_valid is True
    slots = aggregate_units(structure, {"faw-vw": 100.0})
    assert [slot["product_id"] for slot in slots] == ["HUD_AR", "HUD_W", "HUD_P"]
    assert [slot["units"] for slot in slots] == pytest.approx([60.0, 50.0, 40.0])


# --- Aliases (Ho Q4) -----------------------------------------------------


def test_alias_same_chip_different_identity_by_line() -> None:
    assert classify_solution("SA8650", "P01").solution_class == "host"
    assert classify_solution("SA8650", "P02").solution_class == "dc"
    assert classify_solution("RHP:SA8650", "P02").solution_class == "dc"


def test_alias_cdd_is_passenger_not_central() -> None:
    assert classify_solution("CDD12.9", "P03").solution_class == "passenger"
    assert classify_solution("CDI10.25", "P03").solution_class == "passenger"
    assert classify_solution("ABT12.9", "P03").solution_class == "central"
    assert classify_solution("FID10.25", "P03").solution_class == "instrument"


def test_alias_dc_markers_win_over_cammod_markers() -> None:
    assert classify_solution("NGX:J6M", "P02").solution_class == "dc"
    assert classify_solution("MFK:EQ4", "P02").solution_class == "cammod"
    assert classify_solution("J6M", "P02").solution_class == "cammod"
    assert classify_solution("MFK(J3)", "P02").solution_class == "cammod"
    assert classify_solution("IDU+DCM", "P02").solution_class == "dc"


def test_alias_unknown_returns_none() -> None:
    assert classify_solution("ZZZ-UNKNOWN", "P02") is None
    assert classify_solution(None, "P01") is None
    assert classify_solution("", "P01") is None
    assert classify_solution("NA", "P01") is None


def test_alias_p01_instrument_and_bundle() -> None:
    assert classify_solution("仪表：10.25寸", "P01").solution_class == "instrument"
    assert classify_solution("华为", "P01").solution_class == "bundle"
    assert classify_solution("主机：8155", "P01").solution_class == "host"
    assert is_huawei_solution("华为ADS") is True
    assert is_huawei_solution("SA8155P") is False


def test_parse_camera_count() -> None:
    assert parse_camera_count("环视*4") == 4
    assert parse_camera_count("前视8M*2；侧视3M*4；环视1M*4；后视1M*1") == 11
    assert parse_camera_count("双目") == 2
    assert parse_camera_count("三目") == 3
    assert parse_camera_count("1M*1") == 1
    assert parse_camera_count("11颗组") == 11
    assert parse_camera_count("摄像头") is None
    assert parse_camera_count("前视+环视") is None
    assert parse_camera_count(None) is None


def test_dc_platform() -> None:
    assert dc_platform("MFK:EQ4") == "ifc"
    assert dc_platform("RHP:SA8650") == "rhp"
    assert dc_platform("SA8620") == "8620"
    assert dc_platform("SA8650") == "8650"
    assert dc_platform("NGX:J6M") == "ngx"
    assert dc_platform("华为") == "huawei"
    assert dc_platform(None) is None
    assert dc_platform("ZZZ") is None


# --- Morphology registry (Ho Q1/Q5/Q9) -----------------------------------


def test_morphology_registry_exact_facts_only() -> None:
    assert lookup_morphology_fact("faw-toyota", "corolla", 2026).morphology == "ivi_one_box"
    assert lookup_morphology_fact("faw-toyota", "corolla", 2027).morphology == "discrete_host"
    assert lookup_morphology_fact("faw-toyota", "corolla", 2028) is None
    assert lookup_morphology_fact("faw-vw", "sagitar", 2026) is None
    assert lookup_morphology_fact("faw-vw", "t-roc", 2026).morphology == "fused"
    assert lookup_morphology_fact("faw-vw", "cc", 2026).morphology == "fused"
    assert lookup_morphology_fact("faw-vw", "cc", 2027) is None
    assert lookup_morphology_fact("faw-toyota", "corolla", None) is None
    assert len(MORPHOLOGY_FACTS) == 9


def test_morphology_registry_id_aliases() -> None:
    assert lookup_morphology_fact("一汽丰田", "卡罗拉", 2026).morphology == "ivi_one_box"
    assert lookup_morphology_fact("faw-vw", "探歌", 2026).morphology == "fused"


def test_known_data_error_scoped_to_va3() -> None:
    assert lookup_known_data_error("jetta", "va3", 2026, "P05") is not None
    assert lookup_known_data_error("jetta", "va7", 2026, "P05") is None
    assert lookup_known_data_error("jetta", "va3", 2027, "P05") is None
    assert lookup_known_data_error("jetta", "va3", 2026, "P03") is None
    assert len(KNOWN_DATA_ERRORS) == 1


def test_jetta_genuinely_has_no_tbox() -> None:
    assert "jetta" in OEMS_WITHOUT_TBOX
    assert "faw-vw" not in OEMS_WITHOUT_TBOX
