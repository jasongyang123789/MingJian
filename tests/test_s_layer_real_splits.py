"""S-layer real splits: the workbook-derived structure, the stored OEM
mix, and the sales-layer fallback (2026-11-18).

The real structure replaces the simulated splits: Hongqi model x trim
x product rows from workbook V8.5 (152 rows) + 2026 forecast
nameplate/OEM shares. Reconciliation: aggregated capacity over the
Jan-Oct volume base reproduces the workbook's R64 totals exactly
(P01 at the CORRECTED total — the displayed figure includes the known
E-H7 G53 copy-slip overstatement of 3,044,850).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from planagent.config import reset_settings_cache
from planagent.db import get_database, reset_database_cache
from planagent.domain.models import SimulationRun
from planagent.main import create_app
from planagent.services.living_loop.models import ResimulateRequest
from planagent.services.simulation.living_loop import SimulationLivingLoopMixin
from planagent.services.splits import (
    REAL_OEM_SHARES_2026,
    aggregate_capacity,
    aggregate_units,
    build_hongqi_structure,
    build_real_structure,
    evaluate_prompts,
    real_oem_shares,
    validate_oem_shares,
    validate_split_structure,
)
from planagent.services.splits.real_data import JAN_OCT_VOLUMES

# Workbook 红旗-2026 R64 totals (extraction-report §2.1). P01 is the
# CORRECTED total: the workbook's displayed 403,985,550 includes the
# E-H7 G53 copy-slip overstatement (+3,044,850, fixed in the corrected
# copy delivered 2026-11-17).
WORKBOOK_TOTALS = {
    "P01": 400940700.0,
    "P02": 292627657.695,
    "P03": 260430343.2,
    "P04": 86578384.0,
    "P05": 131743360.0,
}

# 2026 forecast volumes (extraction-report §3): the modeled FAW set.
FORECAST_VOLUMES = {
    "faw-vw": 899054,
    "jetta": 80871,
    "hongqi": 300236,
    "faw-toyota": 637097,
}
MODELED_TOTAL = 1917258


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


# --- The real structure ------------------------------------------------------


def test_real_structure_validates_and_counts() -> None:
    structure = build_real_structure()
    result = validate_split_structure(structure)
    assert result.is_valid is True, result.issues
    assert [oem.oem_id for oem in structure.oems] == [
        "hongqi",
        "faw-vw",
        "jetta",
        "faw-toyota",
        "dongfeng-honda",
    ]
    counts = {oem.oem_id: len(oem.nameplates) for oem in structure.oems}
    assert counts == {
        "hongqi": 27,
        "faw-vw": 37,
        "jetta": 8,
        "faw-toyota": 19,
        "dongfeng-honda": 1,
    }
    assert sum(counts.values()) == 92
    detail = next(c for c in result.checks if c.check == "structure").detail
    assert detail == "5 OEM(s), 252 slot(s), 268 row(s)"
    for oem in structure.oems:
        assert sum(n.share for n in oem.nameplates) == pytest.approx(1.0)


def test_real_structure_hongqi_trim_splits() -> None:
    structure = build_real_structure()
    hongqi = _oem(structure, "hongqi")
    h5 = _nameplate(hongqi, "H5 GAS（C100）")
    trims = {t.trim_id: t.share for g in h5.generations for t in g.trims}
    assert trims == {"低配": pytest.approx(0.7), "高配": pytest.approx(0.3)}
    # Within a split trim the P02 fitment is 1.0: the trim IS the
    # sub-population; whole-model P01 rows repeat in both trims.
    low = _trim(h5, "低配")
    assert [(r.solution_code, r.fitment) for r in _rows(low, "P02")] == [
        ("J3 IFC", 1.0)
    ]
    assert [(r.solution_code, r.fitment) for r in _rows(low, "P01")] == [
        ("8155", 1.0)
    ]
    high = _trim(h5, "高配")
    assert [(r.solution_code, r.fitment) for r in _rows(high, "P02")] == [
        ("8620", 1.0)
    ]
    assert [(r.solution_code, r.fitment) for r in _rows(high, "P01")] == [
        ("8155", 1.0)
    ]
    # HS6 keeps its zero-share 低配 trim (the workbook says zero).
    hs6 = _nameplate(hongqi, "HS6 PHEV（P301）")
    assert {t.trim_id: t.share for g in hs6.generations for t in g.trims} == {
        "低配": pytest.approx(0.0),
        "高配": pytest.approx(1.0),
    }
    # Lone 低配 labels at fitment 1.0 are naming artifacts: one trim.
    for model in ("E-HS9 BEV（E115）", "HQ9 GAS（C095）"):
        plate = _nameplate(hongqi, model)
        assert [t.trim_id for g in plate.generations for t in g.trims] == ["全车型"]


def test_real_structure_pinned_workbook_values() -> None:
    structure = build_real_structure()
    hongqi = _oem(structure, "hongqi")
    h5_high = _trim(_nameplate(hongqi, "H5 GAS（C100）"), "高配")
    (p02,) = _rows(h5_high, "P02")
    assert (p02.solution_code, p02.supplier_id, p02.price) == (
        "8620",
        "富赛",
        3164.39,
    )
    # The "/" supplier mark is kept verbatim (J3 IFC names no supplier).
    h5_low = _trim(_nameplate(hongqi, "H5 GAS（C100）"), "低配")
    (p02_low,) = _rows(h5_low, "P02")
    assert (p02_low.solution_code, p02_low.supplier_id, p02_low.price) == (
        "J3 IFC",
        "/",
        400.0,
    )
    # E-H7: two P01 solutions, same supplier, 0.5 each.
    eh7 = _trim(_nameplate(hongqi, "E-H7 BEV（E001）"), "全车型")
    assert [(r.solution_code, r.fitment, r.price) for r in _rows(eh7, "P01")] == [
        ("8155", 0.5, 1650.0),
        ("8397", 0.5, 7950.0),
    ]
    # H9 armrest screen: independent 0.2 penetration (Q7).
    h9 = _trim(_nameplate(hongqi, "H9 GAS（C229）"), "全车型")
    assert [
        (r.solution_code, r.fitment, r.price) for r in _rows(h9, "P03")
    ] == [
        ("仪表12.3inch", 0.5, 1100.0),
        ("中控12.3inch", 0.5, 1100.0),
        ("扶手屏 7inch", 0.2, 712.0),
    ]
    # P-H9 P01 is the Huawei bundle (Q11); P-H9 has no P04/P05 rows.
    ph9 = _trim(_nameplate(hongqi, "P-H9 PHEV（P601/E702）"), "全车型")
    (bundle,) = _rows(ph9, "P01")
    assert (bundle.solution_code, bundle.price_basis, bundle.price) == (
        "华为",
        "bundle",
        6000.0,
    )
    assert _rows(ph9, "P04") == []
    assert _rows(ph9, "P05") == []
    # HS7 PHEV P04: unnamed solution, real fitment/price.
    hs7p = _trim(_nameplate(hongqi, "HS7 PHEV（C206）"), "全车型")
    (p04,) = _rows(hs7p, "P04")
    assert (p04.solution_code, p04.fitment, p04.supplier_id, p04.price) == (
        None,
        1.0,
        "富赛",
        540.0,
    )
    # Multi-supplier P05 cells split 0.5/0.5 (labeled assumption).
    p05_high = _rows(h5_high, "P05")
    assert [(r.supplier_id, r.supplier_share) for r in p05_high] == [
        ("海康", 0.5),
        ("富赛", 0.5),
    ]
    assert {r.solution_code for r in p05_high} == {
        "环视摄像头*4 前视双目摄像头*1 后视摄像头*1"
    }


def test_real_structure_placeholders_contribute_zero() -> None:
    structure = build_real_structure()
    placeholders = []
    for oem in structure.oems:
        for nameplate in oem.nameplates:
            rows = [
                row
                for g in nameplate.generations
                for t in g.trims
                for row in t.fitments
            ]
            if len(rows) == 1 and rows[0].supplier_id == "UNKNOWN":
                placeholders.append((oem.oem_id, nameplate, rows[0]))
    # 64 non-Hongqi forecast models + HS9 PHEV + 1 Dongfeng Honda.
    assert len(placeholders) == 66
    for _oem_id, _plate, row in placeholders:
        assert (row.product_id, row.fitment, row.price) == ("P.O", 0.0, 0.0)
    hongqi = _oem(structure, "hongqi")
    hs9 = _nameplate(hongqi, "HS9 PHEV（P701）")
    assert hs9.share == 0.0
    dfh = _oem(structure, "dongfeng-honda")
    assert dfh.customer_status == "prospect"
    assert [n.nameplate_id for n in dfh.nameplates] == ["待开发车型"]


def test_real_structure_energy_bands_and_generations() -> None:
    structure = build_real_structure()
    hongqi = _oem(structure, "hongqi")
    assert _nameplate(hongqi, "E-QM5 BEV（E111）").energy == "NEV"
    assert _nameplate(hongqi, "H5 GAS（C100）").energy == "ICE"
    toyota = _oem(structure, "faw-toyota")
    # HEV is ICE under the Chinese 新能源 definition (T8).
    assert _nameplate(toyota, "卡罗拉锐放 HEV").energy == "ICE"
    assert _nameplate(toyota, "BZ3 BEV").energy == "NEV"
    vw = _oem(structure, "faw-vw")
    assert _nameplate(vw, "Q4 e-tron").energy == "NEV"
    assert _nameplate(vw, "速腾").energy == "ICE"
    for oem in structure.oems:
        for nameplate in oem.nameplates:
            assert nameplate.price_band == "unknown"
            assert nameplate.model_year == 2026
            assert nameplate.transition_schedule is None
            assert len(nameplate.generations) == 1
            generation = nameplate.generations[0]
            assert (generation.generation_id, generation.lifecycle_phase) == (
                "current",
                "mature",
            )
            for trim in generation.trims:
                assert trim.morphology is None


def test_jan_oct_volumes_base() -> None:
    assert len(JAN_OCT_VOLUMES) == 27
    assert sum(JAN_OCT_VOLUMES.values()) == 213992
    assert JAN_OCT_VOLUMES["国悦 QM7 REEV"] == 487
    assert JAN_OCT_VOLUMES["HS9 PHEV（P701）"] == 0


def test_jan_oct_reconciliation_matches_workbook_totals() -> None:
    """Aggregated capacity over the Jan-Oct base reproduces the
    workbook R64 totals exactly (P01 at the corrected total)."""

    structure = build_hongqi_structure(shares_source="jan_oct_actuals")
    assert validate_split_structure(structure).is_valid is True
    slots = aggregate_units(structure, {"hongqi": 213992.0})
    totals: dict[str, float] = {}
    for row in aggregate_capacity(slots):
        totals[row["product_id"]] = totals.get(row["product_id"], 0.0) + row["capacity"]
    assert totals["P.O"] == 0.0
    for product_id, target in WORKBOOK_TOTALS.items():
        assert totals[product_id] == pytest.approx(target, abs=0.01)


def test_build_hongqi_structure_rejects_unknown_source() -> None:
    with pytest.raises(ValueError, match="Unknown shares_source"):
        build_hongqi_structure(shares_source="2027")


def test_real_structure_prompts_evaluate_without_refusal() -> None:
    """Prompts are diagnostics, never gates: the full real structure
    evaluates, flags the placeholder baskets (R13), and surfaces the
    P-H9 bundle+P03 tension (BUNDLE1)."""

    report = evaluate_prompts(build_real_structure())
    assert [p for p in report.prompts if p.rule_id == "R13"]
    bundle_flags = [p for p in report.prompts if p.rule_id == "BUNDLE1"]
    assert bundle_flags
    assert any("P-H9" in p.path for p in bundle_flags)


# --- Stored OEM shares ---------------------------------------------------------


def test_real_oem_shares_values_and_provenance() -> None:
    shares = real_oem_shares()
    assert shares.source == "faw_volume_forecast_2026"
    assert shares.as_of == "2026"
    for oem_id, volume in FORECAST_VOLUMES.items():
        assert shares.shares[oem_id] == pytest.approx(volume / MODELED_TOTAL)
    assert shares.shares["dongfeng-honda"] == 0.0
    assert sum(shares.shares.values()) == pytest.approx(1.0)
    assert "MODELED FAW set" in (shares.notes or "")
    assert "奔腾" in (shares.notes or "")
    assert "解放" in (shares.notes or "")
    assert REAL_OEM_SHARES_2026.shares == shares.shares
    assert validate_oem_shares(build_real_structure(), shares) == []


# --- API: stored shares + fallback ----------------------------------------------


def build_database_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.resolve().as_posix()}"


def setup_app(monkeypatch, tmp_path: Path, db_name: str = "planagent-real-splits.db") -> None:
    monkeypatch.setenv("PLANAGENT_DATABASE_URL", build_database_url(tmp_path / db_name))
    monkeypatch.setenv("PLANAGENT_EVENT_BUS_BACKEND", "memory")
    monkeypatch.setenv("PLANAGENT_INLINE_INGEST_DEFAULT", "true")
    monkeypatch.setenv("PLANAGENT_INLINE_SIMULATION_DEFAULT", "true")
    monkeypatch.setenv("PLANAGENT_OPENAI_API_KEY", "")
    monkeypatch.setenv("PLANAGENT_OPENAI_BASE_URL", "")
    monkeypatch.setenv("PLANAGENT_OPENAI_PRIMARY_API_KEY", "")
    monkeypatch.setenv("PLANAGENT_OPENAI_PRIMARY_BASE_URL", "")
    monkeypatch.setenv("PLANAGENT_OPENAI_EXTRACTION_API_KEY", "")
    monkeypatch.setenv("PLANAGENT_OPENAI_EXTRACTION_BASE_URL", "")
    monkeypatch.setenv("PLANAGENT_OPENAI_REPORT_API_KEY", "")
    monkeypatch.setenv("PLANAGENT_OPENAI_REPORT_BASE_URL", "")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    reset_settings_cache()
    reset_database_cache()


def automotive_payload(**overrides) -> dict:
    payload: dict = {
        "company_id": "auto-test-oem",
        "company_name": "Auto Test OEM",
        "market": "china-auto",
        "domain_id": "automotive",
        "actor_template": "tier1_supplier",
        "tick_count": 6,
        "seed": 7,
        "variable_template_id": "builtin:automotive",
    }
    payload.update(overrides)
    return payload


def _two_oem_split() -> dict:
    def _oem(oem_id: str, status: str, plate: str) -> dict:
        return {
            "oem_id": oem_id,
            "customer_status": status,
            "nameplates": [
                {
                    "nameplate_id": plate,
                    "energy": "ICE",
                    "price_band": "10-15",
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

    return {"oems": [_oem("oem-a", "existing", "a1"), _oem("oem-b", "existing", "b1")]}


def _stored_shares_payload() -> dict:
    return {
        "shares": {"oem-a": 0.6, "oem-b": 0.4},
        "source": "test-fixture",
        "as_of": "2026",
    }


def _create_run(client: TestClient, **overrides) -> dict:
    created = client.post("/simulation/runs", json=automotive_payload(**overrides))
    assert created.status_code == 201, created.text
    return created.json()


def test_run_creation_stores_oem_shares(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(
            client,
            split_structure=_two_oem_split(),
            oem_production_shares=_stored_shares_payload(),
        )
        response = client.get(f"/runs/{run['id']}/automotive/split-structure")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["oem_production_shares"]["shares"] == {"oem-a": 0.6, "oem-b": 0.4}
        assert body["oem_production_shares"]["source"] == "test-fixture"
        assert body["oem_production_shares"]["as_of"] == "2026"


def test_run_creation_refuses_bad_shares_and_writes_nothing(
    monkeypatch, tmp_path: Path
) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        bad_sum = client.post(
            "/simulation/runs",
            json=automotive_payload(
                split_structure=_two_oem_split(),
                oem_production_shares={
                    "shares": {"oem-a": 0.6, "oem-b": 0.3},
                    "source": "test-fixture",
                },
            ),
        )
        assert bad_sum.status_code == 400
        detail = bad_sum.json()["detail"]
        assert detail["code"] == "split_validation_failed"
        kinds = [issue["kind"] for issue in detail["validation"]["issues"]]
        assert kinds == ["oem_shares_sum"]
        no_structure = client.post(
            "/simulation/runs",
            json=automotive_payload(oem_production_shares=_stored_shares_payload()),
        )
        assert no_structure.status_code == 400
        kinds = [
            issue["kind"]
            for issue in no_structure.json()["detail"]["validation"]["issues"]
        ]
        assert kinds == ["oem_shares_require_split_structure"]
        runs = client.get("/simulation/runs")
        assert runs.json() == []


def test_sales_layer_uses_stored_shares_when_body_omits_them(
    monkeypatch, tmp_path: Path
) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(
            client,
            split_structure=_two_oem_split(),
            oem_production_shares=_stored_shares_payload(),
        )
        explicit = client.post(
            f"/runs/{run['id']}/automotive/sales-layer",
            json={
                "oem_production_shares": {"oem-a": 0.6, "oem-b": 0.4},
                "own_supplier_id": "ho",
            },
        )
        assert explicit.status_code == 200, explicit.text
        stored = client.post(
            f"/runs/{run['id']}/automotive/sales-layer",
            json={"own_supplier_id": "ho"},
        )
        assert stored.status_code == 200, stored.text
        assert stored.json()["summary"] == explicit.json()["summary"]
        assert stored.json()["rows"] == explicit.json()["rows"]
        assumptions = stored.json()["assumptions"]
        assert any("stored input test-fixture (2026)" in a for a in assumptions)


def test_sales_layer_body_shares_override_stored(
    monkeypatch, tmp_path: Path
) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(
            client,
            split_structure=_two_oem_split(),
            oem_production_shares=_stored_shares_payload(),
        )
        overridden = client.post(
            f"/runs/{run['id']}/automotive/sales-layer",
            json={
                "oem_production_shares": {"oem-a": 0.1, "oem-b": 0.9},
                "own_supplier_id": "ho",
            },
        )
        assert overridden.status_code == 200, overridden.text
        assumptions = overridden.json()["assumptions"]
        assert any("caller-supplied" in a for a in assumptions)
        stored = client.post(
            f"/runs/{run['id']}/automotive/sales-layer",
            json={"own_supplier_id": "ho"},
        )
        assert stored.status_code == 200, stored.text
        # The override moved volume from oem-a to oem-b: per-OEM rows differ.
        by_oem = lambda body: {
            row["oem_id"]: row["capacity_value"]
            for row in body["rows"]
            if row["tick"] == 1
        }
        assert by_oem(overridden.json()) != by_oem(stored.json())


def test_sales_layer_without_any_shares_refuses(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client, split_structure=_two_oem_split())
        response = client.post(
            f"/runs/{run['id']}/automotive/sales-layer",
            json={"own_supplier_id": "ho"},
        )
        assert response.status_code == 400, response.text
        assert response.json()["detail"]["code"] == "automotive_oem_shares_required"


def test_living_loop_inherits_stored_shares(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(
            client,
            split_structure=_two_oem_split(),
            oem_production_shares=_stored_shares_payload(),
        )

        async def _build_payload():
            database = get_database()
            await database.ensure_initialized()
            async with database.session() as session:
                baseline = await session.get(SimulationRun, run["id"])
                assert baseline is not None
                payload, _changes = await SimulationLivingLoopMixin(
                )._build_resimulation_payload(
                    session,
                    baseline,
                    datetime(2026, 11, 18, tzinfo=UTC),
                    ResimulateRequest(),
                )
                return payload

        payload = asyncio.run(_build_payload())
        assert payload.oem_production_shares is not None
        assert payload.oem_production_shares.shares == {"oem-a": 0.6, "oem-b": 0.4}
        assert payload.oem_production_shares.source == "test-fixture"
        assert payload.split_structure is not None


def test_real_structure_end_to_end_via_api(monkeypatch, tmp_path: Path) -> None:
    """The full 92-nameplate real structure + stored 2026 mix go through
    run creation, and the S-layer computes from stored shares alone."""

    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        structure = build_real_structure()
        run = _create_run(
            client,
            split_structure=structure.model_dump(mode="json"),
            oem_production_shares=REAL_OEM_SHARES_2026.model_dump(mode="json"),
        )
        fetched = client.get(f"/runs/{run['id']}/automotive/split-structure")
        assert fetched.status_code == 200, fetched.text
        oems = fetched.json()["structure"]["oems"]
        assert sum(len(oem["nameplates"]) for oem in oems) == 92
        assert fetched.json()["oem_production_shares"]["source"] == (
            "faw_volume_forecast_2026"
        )
        computed = client.post(
            f"/runs/{run['id']}/automotive/sales-layer",
            json={"own_supplier_id": "富赛"},
        )
        assert computed.status_code == 200, computed.text
        body = computed.json()
        assert body["summary"]["oem_count"] == 5
        assert body["summary"]["total_capacity_value"] > 0
        assert any(
            "stored input faw_volume_forecast_2026 (2026)" in a
            for a in body["assumptions"]
        )
        assert body["own_sales_basis"] == "supplier_rows"
