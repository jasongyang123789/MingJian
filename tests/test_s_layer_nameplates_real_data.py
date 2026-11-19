"""Track 2: the 64 placeholder nameplates replaced with real workbook data.

The four 2026 OEM sheets (一汽大众 / 捷达 / 一汽丰田 / 东风本田) were
extracted from workbook V8.5 (see ``~/workspace/research/strategy-engine/
oem-2026-extract.csv`` and ``generate-oem-2026-tables.py``) and wired
into the S-layer. 47 placeholders are replaced; 19 remain (15 unsourced
FAW-VW models, 3 unsourced FAW-Toyota models, HS9 PHEV).

Pinned values below come from the workbook cells; the reconciliation
targets are the independently computed corrected sheet totals (the
generator re-implements the builder rules from the CSV, so the test
pins the builder against a second implementation, not against itself).
"""

from __future__ import annotations

import pytest

from planagent.services.splits import (
    aggregate_capacity,
    aggregate_units,
    build_real_structure,
    build_sheet_structure,
    evaluate_prompts,
    market_capacity_by_oem_product,
    validate_split_structure,
)
from planagent.services.splits.real_data import SHEET_JAN_OCT_VOLUMES
from planagent.services.splits.real_structure import (
    _slot_fitments,
    _toyota_oem,
)

#: Corrected sheet totals (sheet-volume base, after T9/T10/T11).
#: Each total is the workbook's displayed total adjusted by the
#: documented corrections: 仪表 re-homing (T9, P01<->P03), Case A/B
#: supplier splits (T10), 速腾/探歌 halving (T11), the 揽镜 copy-slip
#: drop (F03), and the VA3 misfill exclusion (Ho Q6).
CORRECTED_SHEET_TOTALS = {
    "faw-vw": {
        "P01": 660824539.73,
        "P02": 266767704.00,
        "P03": 411044298.32,
        "P04": 280984880.00,
        "P05": 150197353.75,
    },
    "jetta": {
        "P01": 57606892.88,
        "P02": 1994552.00,
        "P03": 12765580.00,
        "P04": 0.00,
        "P05": 3154490.40,
    },
    "faw-toyota": {
        "P01": 1251331300.00,
        "P02": 7782740.00,
        "P03": 482098475.00,
        "P04": 405009600.00,
        "P05": 189595600.00,
    },
    "dongfeng-honda": {
        "P01": 240051666.67,
        "P02": 0.00,
        "P03": 232049944.44,
        "P04": 86962166.67,
        "P05": 36007750.00,
    },
}


def _oem(structure, oem_id: str):
    return next(oem for oem in structure.oems if oem.oem_id == oem_id)


def _nameplate(oem, nameplate_id: str):
    return next(n for n in oem.nameplates if n.nameplate_id == nameplate_id)


def _trim(nameplate, trim_id: str):
    return next(
        t for g in nameplate.generations for t in g.trims if t.trim_id == trim_id
    )


def _rows(trim, product_id: str):
    return [row for row in trim.fitments if row.product_id == product_id]


# --- Pinned workbook values --------------------------------------------------


def test_suteng_two_trims_mirrored_host_mix() -> None:
    """速腾: two sub-population trims at 0.5/0.5 (T11) with the host
    mix flipped between them (X9HP 0.1/8155 0.9 vs 0.9/0.1)."""

    vw = _oem(build_real_structure(), "faw-vw")
    suteng = _nameplate(vw, "速腾")
    assert {t.trim_id: t.share for g in suteng.generations for t in g.trims} == {
        "子人群1": 0.5,
        "子人群2": 0.5,
    }
    g1 = _trim(suteng, "子人群1")
    assert [(r.solution_code, r.fitment) for r in _rows(g1, "P01") if "主机" in (r.solution_code or "")] == [
        ("主机：X9HP", 0.1),
        ("主机：8155", 0.9),
    ]
    g2 = _trim(suteng, "子人群2")
    assert [(r.solution_code, r.fitment) for r in _rows(g2, "P01") if "主机" in (r.solution_code or "")] == [
        ("主机：X9HP", 0.9),
        ("主机：8155", 0.1),
    ]


def test_troc_two_generations() -> None:
    """探歌: generation transition (T11) — X9HP phases out, 8155 ramps
    in, at 0.5/0.5 with no transition schedule (no timing data)."""

    vw = _oem(build_real_structure(), "faw-vw")
    troc = _nameplate(vw, "探歌")
    assert [(g.generation_id, g.lifecycle_phase, g.share) for g in troc.generations] == [
        ("prev", "phase_out", 0.5),
        ("current", "ramp", 0.5),
    ]
    assert troc.transition_schedule is None
    prev = troc.generations[0].trims[0]
    current = troc.generations[1].trims[0]
    assert [r.solution_code for r in _rows(prev, "P01")] == ["主机：X9HP"]
    assert [r.solution_code for r in _rows(current, "P01")] == ["主机：8155"]


def test_instrument_rehomed_to_p03() -> None:
    """T9: no P01 row anywhere in VW/Toyota/DFH names an instrument;
    the 仪表 rows sit in P03 with fitment/supplier/price unchanged."""

    structure = build_real_structure()
    for oem_id in ("faw-vw", "faw-toyota", "dongfeng-honda"):
        oem = _oem(structure, oem_id)
        for nameplate in oem.nameplates:
            for generation in nameplate.generations:
                for trim in generation.trims:
                    assert not [
                        r
                        for r in _rows(trim, "P01")
                        if r.solution_code and "仪表" in r.solution_code
                    ]
    vw = _oem(structure, "faw-vw")
    suteng = _trim(_nameplate(vw, "速腾"), "子人群1")
    assert [(r.solution_code, r.fitment, r.supplier_id, r.price) for r in _rows(suteng, "P03") if "仪表" in (r.solution_code or "")] == [
        ("仪表：10.25寸(AM 62方案)", 0.15, "富赛", 608.0),
        ("仪表：10.25寸(IMAX8方案)", 0.25, "伟世通", 1216.0),
    ]


def test_toyota_case_a_supplier_splits() -> None:
    """T10 Case A: unequal fitments are the suppliers' shares — the
    slot fitment is their sum (1.0) and each share is fitment/sum."""

    toyota = _oem(build_real_structure(), "faw-toyota")
    corolla = _trim(_nameplate(toyota, "卡罗拉 Long HEV"), "全车型")
    # 仪表8.8液晶 0.35/0.65, re-homed to P03 (T9).
    assert [(r.fitment, r.supplier_id, r.supplier_share, r.price) for r in _rows(corolla, "P03")] == [
        (1.0, "伟世通", 0.35, 700.0),
        (1.0, "富赛", 0.65, 950.0),
    ]
    rav4 = _trim(_nameplate(toyota, "荣放 GAS"), "全车型")
    assert [(r.fitment, r.supplier_id, r.supplier_share, r.price) for r in _rows(rav4, "P01") if r.solution_code == "SA8155P"] == [
        (1.0, "富赛", 0.74, 3300.0),
        (1.0, "航盛", 0.26, 1500.0),
    ]
    ruifang = _trim(_nameplate(toyota, "卡罗拉锐放 GAS"), "全车型")
    assert [(r.supplier_id, r.supplier_share) for r in _rows(ruifang, "P01") if r.solution_code == "SA8155P"] == [
        ("富赛", 0.01),
        ("航盛", 0.99),
    ]


def test_jetta_and_dfh_case_b_supplier_splits() -> None:
    """T10 Case B: equal fitments repeat the slot rate with an equal
    supplier split (A7)."""

    jetta = _oem(build_real_structure(), "jetta")
    vs5 = _trim(_nameplate(jetta, "Jetta VS5"), "全车型")
    assert [(r.fitment, r.supplier_id, r.supplier_share, r.price) for r in _rows(vs5, "P05")] == [
        (0.8, "舜宇", 0.5, 70.0),
        (0.8, "日盈", 0.5, 67.0),
    ]
    dfh = _oem(build_real_structure(), "dongfeng-honda")
    civic = _trim(_nameplate(dfh, "思域"), "全车型")
    assert [(r.fitment, r.supplier_id, r.supplier_share, r.price) for r in _rows(civic, "P05")] == [
        (0.5, "海康", 0.5, 450.0),
        (0.5, "保隆", 0.5, 450.0),
    ]


def test_jetta_exclusions_and_kept_rows() -> None:
    """Ho Q6 (VA3 misfill excluded) vs Q9 (M6 inspected individually
    and kept); Ho Q10 (Jetta has no T-BOX); J03's TBD row excluded."""

    jetta = _oem(build_real_structure(), "jetta")
    va3 = _nameplate(jetta, "Jetta VA3")
    assert {r.product_id for g in va3.generations for t in g.trims for r in t.fitments} == {"P01"}
    m6 = _trim(_nameplate(jetta, "Jetta M6（J01）"), "全车型")
    # The 11-camera group (2+4+4+1) survives: M6 is the new J01
    # platform with a full P02/P03/P05 set, and the row persists in 2027.
    assert any(
        r.fitment == 0.1 and r.price == 160.0 and "前视8M*2" in (r.solution_code or "")
        for r in _rows(m6, "P05")
    )
    j03 = _nameplate(jetta, "捷达 J03")
    assert {r.product_id for g in j03.generations for t in g.trims for r in t.fitments} == {"P01", "P05"}
    for nameplate in jetta.nameplates:
        assert not [
            r for g in nameplate.generations for t in g.trims for r in t.fitments
            if r.product_id == "P04"
        ]


def test_lanjing_single_rhp_after_copy_slip_drop() -> None:
    """F03: 揽镜 PA's R80 P02 RHP row repeats R76 identically and is
    dropped at generation — exactly one RHP row remains."""

    vw = _oem(build_real_structure(), "faw-vw")
    lanjing = _trim(_nameplate(vw, "揽镜 PA"), "全车型")
    assert [(r.solution_code, r.fitment) for r in _rows(lanjing, "P02")] == [
        ("MFK: EQ4", 0.3),
        ("RHP: SA8650(不含license)", 0.3),
    ]


def test_zero_fitment_rows_kept_and_zero_volume_models_real() -> None:
    """The workbook's zero-fitment rows stay (like HS6's zero-share
    trim); zero-volume forecast models carry real trees, not
    placeholders."""

    vw = _oem(build_real_structure(), "faw-vw")
    suteng_s = _trim(_nameplate(vw, "速腾 S"), "全车型")
    assert ("ABT12.9带滑条", 0.0) in [
        (r.solution_code, r.fitment) for r in _rows(suteng_s, "P03")
    ]
    for nameplate_id in (
        "B NB（CSP）",
        "B SUV（CSP）",
        "C-CUV(CMP)天津",
        "A SUV(MQB)青岛（探岳S-探歌升级版）",
    ):
        nameplate = _nameplate(vw, nameplate_id)
        assert nameplate.share == 0.0
        assert any(
            r.supplier_id != "UNKNOWN"
            for g in nameplate.generations
            for t in g.trims
            for r in t.fitments
        )
    jetta = _oem(build_real_structure(), "jetta")
    for nameplate_id in ("捷达 J02", "捷达 J03"):
        nameplate = _nameplate(jetta, nameplate_id)
        assert nameplate.share == 0.0
        assert any(
            r.supplier_id != "UNKNOWN"
            for g in nameplate.generations
            for t in g.trims
            for r in t.fitments
        )


def test_toyota_family_trees_identical_across_members() -> None:
    """T12: each family trim tree applies verbatim to every member
    forecast model (shares differ — they come from the forecast)."""

    toyota = _oem(build_real_structure(), "faw-toyota")
    members = [
        _nameplate(toyota, "卡罗拉 Long HEV"),
        _nameplate(toyota, "卡罗拉 GAS 1.2T"),
        _nameplate(toyota, "卡罗拉 Long GAS"),
    ]
    dumps = [m.model_dump(mode="json")["generations"] for m in members]
    assert dumps[0] == dumps[1] == dumps[2]
    assert {m.nameplate_id for m in members} == {
        "卡罗拉 Long HEV",
        "卡罗拉 GAS 1.2T",
        "卡罗拉 Long GAS",
    }
    # BZ5 is sheet-only: rows exist, but it is not a forecast model.
    assert not [n for n in toyota.nameplates if n.nameplate_id == "BZ5"]


# --- Coverage and refusals ---------------------------------------------------


def test_sheet_volumes_base() -> None:
    assert sum(SHEET_JAN_OCT_VOLUMES["faw-vw"].values()) == pytest.approx(466868.1556, abs=0.01)
    assert sum(SHEET_JAN_OCT_VOLUMES["jetta"].values()) == 64468
    assert sum(SHEET_JAN_OCT_VOLUMES["faw-toyota"].values()) == 510277
    assert sum(SHEET_JAN_OCT_VOLUMES["dongfeng-honda"].values()) == pytest.approx(160034.4444, abs=0.01)


def test_prompts_flag_exactly_the_19_placeholders() -> None:
    report = evaluate_prompts(build_real_structure())
    r13 = [p for p in report.prompts if p.rule_id == "R13"]
    assert len(r13) == 19


def test_build_sheet_structure_rejects_unknown_oem() -> None:
    with pytest.raises(ValueError, match="Unknown oem_id"):
        build_sheet_structure("one-automobile")


def test_toyota_builder_refuses_unmapped_forecast_model() -> None:
    from planagent.services.splits.real_structure import _forecast_volumes_by_oem

    volumes = _forecast_volumes_by_oem()["faw-toyota"]
    tampered = dict(volumes)
    del tampered["卡罗拉 Long HEV"]
    with pytest.raises(ValueError, match="without forecast volumes"):
        _toyota_oem(tampered)


def test_slot_fitments_refuse_over_one_split_and_duplicates() -> None:
    # Case A sum over 1.0 refuses (unequal fitments: 0.6 + 0.7 = 1.3).
    with pytest.raises(ValueError, match="sum to .* \\(> 1\\)"):
        _slot_fitments(
            [
                ("M", "P01", "全车型", "default", "S", 0.6, "A", 100.0),
                ("M", "P01", "全车型", "default", "S", 0.7, "B", 100.0),
            ]
        )
    # A repeated (product, solution, supplier) pair refuses.
    with pytest.raises(ValueError, match="Duplicate \\(product, solution, supplier\\)"):
        _slot_fitments(
            [
                ("M", "P01", "全车型", "default", "S", 0.5, "A", 100.0),
                ("M", "P01", "全车型", "default", "S", 0.5, "A", 100.0),
            ]
        )


# --- Reconciliation ----------------------------------------------------------


@pytest.mark.parametrize("oem_id", ["faw-vw", "jetta", "faw-toyota", "dongfeng-honda"])
def test_sheet_reconciliation_matches_corrected_totals(oem_id: str) -> None:
    """Aggregated capacity over the sheet Jan-Oct base reproduces the
    corrected workbook totals exactly (abs tol 0.01)."""

    structure = build_sheet_structure(oem_id)
    assert validate_split_structure(structure).is_valid is True
    total = sum(SHEET_JAN_OCT_VOLUMES[oem_id].values())
    slots = aggregate_capacity(aggregate_units(structure, {oem_id: total}))
    totals = market_capacity_by_oem_product(slots)
    for product_id, target in CORRECTED_SHEET_TOTALS[oem_id].items():
        assert totals.get((oem_id, product_id), 0.0) == pytest.approx(target, abs=0.01)
