"""Phase 2 prompt-engine tests: every expectation rule fires, skips,
or stays silent exactly as the verification report + Ho's Q1-Q11
rulings specify. Prompts NEVER refuse and NEVER correct — they flag
and explain."""

from __future__ import annotations

from planagent.services.splits import (
    SplitStructure,
    evaluate_prompts,
    expectation_catalog,
    validate_split_structure,
)


def _row(
    product_id: str,
    fitment: float,
    kind: str = "rate",
    supplier: str = "ho",
    share: float = 1.0,
    price: float | None = 100.0,
    code: str | None = None,
    price_basis: str = "discrete",
) -> dict:
    row: dict = {
        "product_id": product_id,
        "fitment_kind": kind,
        "fitment": fitment,
        "supplier_id": supplier,
        "supplier_share": share,
        "price": price,
        "price_basis": price_basis,
    }
    if code is not None:
        row["solution_code"] = code
    return row


def _structure(
    fitments: list[dict],
    morphology: str | None = None,
    oem_id: str = "faw-vw",
    nameplate_id: str = "sagitar",
    model_year: int | None = 2026,
) -> SplitStructure:
    trim: dict = {"trim_id": "mid", "share": 1.0, "fitments": fitments}
    if morphology is not None:
        trim["morphology"] = morphology
    nameplate: dict = {
        "nameplate_id": nameplate_id,
        "energy": "ICE",
        "price_band": "10-15",
        "share": 1.0,
        "generations": [
            {
                "generation_id": "g1",
                "lifecycle_phase": "mature",
                "share": 1.0,
                "trims": [trim],
            }
        ],
    }
    if model_year is not None:
        nameplate["model_year"] = model_year
    return SplitStructure.model_validate(
        {
            "oems": [
                {"oem_id": oem_id, "customer_status": "existing", "nameplates": [nameplate]}
            ]
        }
    )


def _rule_ids(report, severity: str | None = None) -> list[str]:
    return [
        prompt.rule_id
        for prompt in report.prompts
        if severity is None or prompt.severity == severity
    ]


def _skipped_ids(report) -> list[str]:
    return [record.rule_id for record in report.skipped]


# --- R1 ------------------------------------------------------------------


def test_r1_dc_without_cameras_flags_anomaly() -> None:
    report = evaluate_prompts(_structure([_row("P02", 0.8, code="RHP:SA8650")]))
    assert "R1" in _rule_ids(report, "anomaly")
    prompt = next(p for p in report.prompts if p.rule_id == "R1")
    assert "camera" in prompt.expected_logic.lower()
    assert prompt.likely_explanations


def test_r1_bundle_trim_skips() -> None:
    structure = _structure(
        [_row("P02", 0.8, code="华为ADS", price_basis="bundle")],
    )
    report = evaluate_prompts(structure)
    assert "R1" not in _rule_ids(report)
    assert "R1" in _skipped_ids(report)
    assert "BUNDLE1" not in _rule_ids(report)


def test_r1_dc_with_cameras_passes() -> None:
    report = evaluate_prompts(
        _structure(
            [
                _row("P02", 0.8, code="RHP:SA8650"),
                _row("P05", 11.0, kind="count", code="11颗组"),
            ]
        )
    )
    assert "R1" not in _rule_ids(report)
    assert "R1" in report.rules_evaluated


# --- R2 ------------------------------------------------------------------


def test_r2_ladder_ifc_module_passes() -> None:
    report = evaluate_prompts(
        _structure(
            [
                _row("P02", 0.5, code="IFC"),
                _row("P05", 0.5, code="环视*4"),
            ]
        )
    )
    assert "R2" not in _rule_ids(report)
    assert "R2" in report.rules_evaluated
    assert "EMBED1" in _rule_ids(report, "info")


def test_r2_ladder_8650_off_ladder_flags() -> None:
    report = evaluate_prompts(
        _structure(
            [
                _row("P02", 0.8, code="SA8650"),
                _row("P05", 5.0, kind="count"),
            ]
        )
    )
    assert "R2" in _rule_ids(report, "anomaly")


def test_r2_ladder_8650_year_dependent() -> None:
    # 2026: expected 10, observed 11 is within the ±1 tolerance.
    report_2026 = evaluate_prompts(
        _structure(
            [_row("P02", 0.8, code="SA8650"), _row("P05", 11.0, kind="count")],
            model_year=2026,
        )
    )
    assert "R2" not in _rule_ids(report_2026)
    # 2027: expected 11, observed 9 is outside the tolerance.
    report_2027 = evaluate_prompts(
        _structure(
            [_row("P02", 0.8, code="SA8650"), _row("P05", 9.0, kind="count")],
            model_year=2027,
        )
    )
    assert "R2" in _rule_ids(report_2027, "anomaly")


def test_r2_tolerance_one_camera_is_not_an_anomaly() -> None:
    report = evaluate_prompts(
        _structure(
            [_row("P02", 0.8, code="SA8620"), _row("P05", 6.0, kind="count")],
        )
    )
    assert "R2" not in _rule_ids(report)
    report_off = evaluate_prompts(
        _structure(
            [_row("P02", 0.8, code="SA8620"), _row("P05", 5.0, kind="count")],
        )
    )
    assert "R2" in _rule_ids(report_off, "anomaly")


def test_r2_uncountable_labels_skip() -> None:
    report = evaluate_prompts(
        _structure(
            [_row("P02", 0.8, code="RHP:SA8650"), _row("P05", 0.5, code="摄像头")],
        )
    )
    assert "R2" not in _rule_ids(report)
    assert "R2" in _skipped_ids(report)


def test_r2_va3_known_error_excluded_from_ladder() -> None:
    report = evaluate_prompts(
        _structure(
            [_row("P05", 0.1, code="前视8M*2；侧视3M*4；环视1M*4；后视1M*1", price=160.0)],
            oem_id="jetta",
            nameplate_id="va3",
            model_year=2026,
        )
    )
    assert "KNOWN_ERROR" in _rule_ids(report, "info")
    assert "R2" in _skipped_ids(report)
    assert "R2" not in _rule_ids(report, "anomaly")


# --- R3/R4/R5 ------------------------------------------------------------


def test_r3_integrated_with_central_screen_flags() -> None:
    report = evaluate_prompts(
        _structure(
            [_row("P01", 1.0, code="SA8155P"), _row("P03", 1.0, code="ABT12.9")],
            morphology="ivi_one_box",
        )
    )
    assert "R3" in _rule_ids(report, "anomaly")


def test_r3_fused_without_central_passes() -> None:
    report = evaluate_prompts(
        _structure([_row("P01", 1.0, code="主机：8155")], morphology="fused")
    )
    assert "R3" not in _rule_ids(report)


def test_r4_discrete_host_without_central_flags() -> None:
    report = evaluate_prompts(
        _structure([_row("P01", 1.0, code="SA8155P")], morphology="discrete_host")
    )
    assert "R4" in _rule_ids(report, "anomaly")


def test_r4_no_morphology_skips() -> None:
    report = evaluate_prompts(_structure([_row("P01", 1.0, code="SA8155P")]))
    assert "R3" in _skipped_ids(report)
    assert "R4" in _skipped_ids(report)
    assert "R3" not in _rule_ids(report)
    assert "R4" not in _rule_ids(report)


def test_r5_registry_mismatch_flags() -> None:
    report = evaluate_prompts(
        _structure(
            [_row("P01", 1.0, code="SA8155P")],
            morphology="discrete_host",
            oem_id="faw-toyota",
            nameplate_id="corolla",
            model_year=2026,
        )
    )
    assert "R5" in _rule_ids(report, "anomaly")
    prompt = next(p for p in report.prompts if p.rule_id == "R5")
    assert "ivi_one_box" in prompt.observed


def test_r5_registry_match_passes() -> None:
    report = evaluate_prompts(
        _structure(
            [_row("P01", 1.0, code="SA8155P", price_basis="includes_screen")],
            morphology="ivi_one_box",
            oem_id="faw-toyota",
            nameplate_id="corolla",
            model_year=2026,
        )
    )
    assert "R5" not in _rule_ids(report)
    assert "R5" in report.rules_evaluated


def test_r5_no_fact_skips_without_generalizing() -> None:
    report = evaluate_prompts(
        _structure([_row("P01", 1.0, code="SA8155P")], morphology="discrete_host")
    )
    assert "R5" in _skipped_ids(report)


# --- R6/X3/X4 ------------------------------------------------------------


def test_r6_overlap_is_a_prompt_not_a_refusal() -> None:
    structure = _structure(
        [
            _row("P02", 0.6, code="RHP:SA8650", supplier="s1", share=0.5),
            _row("P02", 0.6, code="NGX:J6M", supplier="s2", share=0.5),
        ]
    )
    # The structure itself is VALID (Ho Q7: independent penetrations).
    assert validate_split_structure(structure).is_valid is True
    report = evaluate_prompts(structure)
    assert "R6" in _rule_ids(report, "anomaly")
    assert "X4" in _rule_ids(report, "anomaly")


def test_x3_dc_plus_module_flags() -> None:
    report = evaluate_prompts(
        _structure(
            [
                _row("P02", 0.5, code="RHP:SA8650", supplier="s1", share=0.5),
                _row("P02", 0.5, code="MFK:EQ4", supplier="s2", share=0.5),
            ]
        )
    )
    assert "X3" in _rule_ids(report, "anomaly")


def test_r6_supplier_splits_do_not_double_count() -> None:
    # Same solution, two suppliers: the slot penetration is 0.6, not 1.2.
    report = evaluate_prompts(
        _structure(
            [
                _row("P02", 0.6, code="RHP:SA8650", supplier="s1", share=0.1),
                _row("P02", 0.6, code="RHP:SA8650", supplier="s2", share=0.9),
            ]
        )
    )
    assert "R6" not in _rule_ids(report)


# --- R7/X5 ---------------------------------------------------------------


def test_r7_central_overlap_excludes_passenger_screens() -> None:
    report = evaluate_prompts(
        _structure(
            [
                _row("P03", 0.6, code="ABT12.9", supplier="s1", share=0.5),
                _row("P03", 0.6, code="CDD12.9", supplier="s2", share=0.5),
            ]
        )
    )
    # ABT 0.6 + CDD 0.6 = 1.2 is legitimate coexistence (Ho Q3).
    assert "R7" not in _rule_ids(report)


def test_r7_two_central_variants_overlap_flags() -> None:
    report = evaluate_prompts(
        _structure(
            [
                _row("P03", 0.6, code="ABT12.9", supplier="s1", share=0.5),
                _row("P03", 0.6, code="ABT15.6", supplier="s2", share=0.5),
            ]
        )
    )
    assert "R7" in _rule_ids(report, "anomaly")


# --- R8/R9/R10 -----------------------------------------------------------


def test_r8_instrument_row_under_p01_flags() -> None:
    report = evaluate_prompts(_structure([_row("P01", 1.0, code="仪表：10.25寸")]))
    assert "R8" in _rule_ids(report, "anomaly")


def test_r9_4g_5g_overlap_flags() -> None:
    report = evaluate_prompts(
        _structure(
            [
                _row("P04", 0.6, code="4G：ConMod", supplier="s1", share=0.5),
                _row("P04", 0.6, code="5G：OCU4", supplier="s2", share=0.5),
            ]
        )
    )
    assert "R9" in _rule_ids(report, "anomaly")
    report_ok = evaluate_prompts(
        _structure(
            [
                _row("P04", 0.6, code="4G：ConMod", supplier="s1", share=0.5),
                _row("P04", 0.4, code="5G：OCU4", supplier="s2", share=0.5),
            ]
        )
    )
    assert "R9" not in _rule_ids(report_ok)


def test_r10_high_cameras_without_compute_flags() -> None:
    report = evaluate_prompts(_structure([_row("P05", 8.0, kind="count")]))
    assert "R10" in _rule_ids(report, "anomaly")
    report_ok = evaluate_prompts(
        _structure(
            [_row("P02", 0.8, code="RHP:SA8650"), _row("P05", 8.0, kind="count")],
        )
    )
    assert "R10" not in _rule_ids(report_ok)


# --- R11/R12/R13/X1/X2 ---------------------------------------------------


def test_catalog_only_rules_always_skipped() -> None:
    report = evaluate_prompts(_structure([_row("P01", 1.0, code="SA8155P")]))
    skipped = _skipped_ids(report)
    assert "R11" in skipped
    assert "X1" in skipped
    assert "X2" in skipped


def test_r12_dms_context_note() -> None:
    report = evaluate_prompts(
        _structure([_row("P01", 1.0, code="SA8155P")]), dms_mandate_on=True
    )
    assert "R12" in _rule_ids(report, "info")
    report_off = evaluate_prompts(
        _structure([_row("P01", 1.0, code="SA8155P")]), dms_mandate_on=False
    )
    assert "R12" in _skipped_ids(report_off)


def test_r13_bare_po_basket_flags_for_decomposition() -> None:
    report = evaluate_prompts(_structure([_row("P.O", 0.2, code="P.O")]))
    assert "R13" in _rule_ids(report, "anomaly")
    prompt = next(p for p in report.prompts if p.rule_id == "R13")
    assert "HUD_AR" in prompt.expected_logic
    report_ok = evaluate_prompts(_structure([_row("HUD_AR", 0.2, code="HUD")]))
    assert "R13" not in _rule_ids(report_ok)


def test_hud_variants_coexisting_draw_no_overlap_prompt() -> None:
    """Ho 2026-11-17 ruling: P-HUD coexists with W/AR-HUD on the same
    vehicle; no prompt treats HUD variants as mutually exclusive. A
    trim carrying all three variants at rates summing above 1 draws
    no anomaly prompt (the substitution prompts R6/R7/R9 cover
    P02/P03/P04 only; no HUD overlap rule exists)."""
    report = evaluate_prompts(
        _structure(
            [
                _row("HUD_AR", 0.6, code="HUD"),
                _row("HUD_W", 0.5, code="HUD"),
                _row("HUD_P", 0.4, code="HUD"),
            ]
        )
    )
    assert report.anomaly_count == 0
    assert all("HUD" not in prompt.title for prompt in report.prompts)


# --- AVM1 / BUNDLE1 / SCREEN1 / EMBED1 -----------------------------------


def test_avm_pairing_one_directional() -> None:
    report = evaluate_prompts(_structure([_row("AVM", 0.3, code="AVM")]))
    assert "AVM1" in _rule_ids(report, "anomaly")
    report_ok = evaluate_prompts(
        _structure([_row("AVM", 0.3, code="AVM"), _row("P05", 0.3, code="环视*4")])
    )
    assert "AVM1" not in _rule_ids(report_ok)
    # Reverse does not hold: surround group without AVM is fine.
    report_reverse = evaluate_prompts(_structure([_row("P05", 0.3, code="环视*4")]))
    assert "AVM1" not in _rule_ids(report_reverse)


def test_bundle_labeling_and_separate_rows() -> None:
    report = evaluate_prompts(
        _structure([_row("P01", 1.0, code="华为ADS", price_basis="discrete")])
    )
    assert "BUNDLE1" in _rule_ids(report, "anomaly")
    report_rows = evaluate_prompts(
        _structure(
            [
                _row("P01", 1.0, code="华为ADS", price_basis="bundle"),
                _row("P03", 1.0, code="ABT12.9"),
            ]
        )
    )
    assert "BUNDLE1" in _rule_ids(report_rows, "anomaly")
    report_ok = evaluate_prompts(
        _structure([_row("P01", 1.0, code="华为ADS", price_basis="bundle")])
    )
    assert "BUNDLE1" not in _rule_ids(report_ok)


def test_screen1_one_box_asp_labeling() -> None:
    report = evaluate_prompts(
        _structure(
            [_row("P01", 1.0, code="SA8155P", price_basis="discrete")],
            morphology="ivi_one_box",
        )
    )
    assert "SCREEN1" in _rule_ids(report, "anomaly")
    report_ok = evaluate_prompts(
        _structure(
            [_row("P01", 1.0, code="SA8155P", price_basis="includes_screen")],
            morphology="ivi_one_box",
        )
    )
    assert "SCREEN1" not in _rule_ids(report_ok)


def test_embed1_accounting_note() -> None:
    report = evaluate_prompts(_structure([_row("P02", 0.5, code="MFK:EQ4")]))
    assert "EMBED1" in _rule_ids(report, "info")
    report_none = evaluate_prompts(_structure([_row("P02", 0.5, code="RHP:SA8650")]))
    assert "EMBED1" not in _rule_ids(report_none)


def test_jetta_missing_p04_is_never_flagged() -> None:
    report = evaluate_prompts(
        _structure(
            [_row("P01", 1.0, code="SA8155P"), _row("P03", 1.0, code="ABT12.9")],
            oem_id="jetta",
            nameplate_id="va7",
        )
    )
    for prompt in report.prompts:
        assert "T-BOX" not in prompt.title
        assert "P04" not in prompt.title


# --- Engine properties ---------------------------------------------------


def test_prompts_never_refuse_invalid_structures() -> None:
    structure = _structure([_row("P02", 0.8, code="RHP:SA8650")])
    structure.oems[0].nameplates[0].share = 0.5  # breaks the sum gate
    assert validate_split_structure(structure).is_valid is False
    report = evaluate_prompts(structure)
    assert "R1" in _rule_ids(report, "anomaly")


def test_prompt_evaluation_is_deterministic() -> None:
    structure = _structure(
        [
            _row("P02", 0.8, code="RHP:SA8650"),
            _row("P01", 1.0, code="仪表：10.25寸"),
        ]
    )
    first = evaluate_prompts(structure)
    second = evaluate_prompts(structure)
    assert first.model_dump() == second.model_dump()


def test_expectation_catalog_completeness() -> None:
    catalog = expectation_catalog()
    ids = {entry["id"] for entry in catalog}
    assert ids == (
        {f"R{index}" for index in range(1, 14)}
        | {f"X{index}" for index in range(1, 6)}
        | {"AVM1", "BUNDLE1", "SCREEN1", "EMBED1"}
    )
    assert len(catalog) == 22
    by_id = {entry["id"]: entry for entry in catalog}
    assert by_id["R11"]["evaluated"] is False
    assert by_id["X1"]["evaluated"] is False
    assert by_id["X2"]["evaluated"] is False
    assert by_id["R1"]["evaluated"] is True
    for entry in catalog:
        assert entry["evidence_ref"]
        assert entry["scope"]
        assert entry["normal_logic"]
