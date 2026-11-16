"""Phase 2 automotive API tests: trajectory + snapshot-wired S-layer +
prompt endpoints, transmission-link levers, and the dual track.

Setup helpers mirror tests/test_automotive_api.py (isolated SQLite
app per test, inline simulation, no network, no live LLM).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from planagent.config import reset_settings_cache
from planagent.db import reset_database_cache
from planagent.main import create_app

PHASE2_SPLIT = {
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

PROSPECT_SPLIT = {
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


def build_database_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.resolve().as_posix()}"


def setup_app(monkeypatch, tmp_path: Path, db_name: str = "planagent-phase2.db") -> None:
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


def _create_run(client: TestClient, **overrides) -> dict:
    created = client.post("/simulation/runs", json=automotive_payload(**overrides))
    assert created.status_code == 201, created.text
    return created.json()


def _fixed_override(variable_id: str, value: float) -> dict:
    return {
        "name": f"{variable_id}-override",
        "variables": [
            {
                "id": variable_id,
                "unit": "test",
                "distribution": {"type": "fixed", "value": value},
                "evidence_ref": "test-override",
            }
        ],
    }


def _sales_layer(client: TestClient, run_id: str, **overrides) -> dict:
    payload: dict = {"oem_production_shares": {"faw-vw": 1.0}, "own_supplier_id": "ho"}
    payload.update(overrides)
    response = client.post(f"/runs/{run_id}/automotive/sales-layer", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


# --- Trajectory ------------------------------------------------------------


def test_trajectory_endpoint_reads_stored_snapshots(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client, split_structure=PHASE2_SPLIT)
        response = client.get(f"/runs/{run['id']}/automotive/trajectory")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["run_status"] == "COMPLETED"
        assert body["tick_count"] == 6
        assert body["multiple_actors"] is False
        assert len(body["points"]) == 7
        assert [point["tick"] for point in body["points"]] == [0, 1, 2, 3, 4, 5, 6]
        tick_zero = body["points"][0]["state"]
        assert tick_zero["production_volume"] == 287.8
        assert tick_zero["sales_volume_retail"] == 197.9
        assert tick_zero["nev_production_volume"] == 137.86
        assert tick_zero["ice_production_volume"] == 149.94
        assert tick_zero["nev_retail_volume"] == 94.79
        assert tick_zero["ice_retail_volume"] == 103.11
        # Read-only and idempotent: a second read returns the same body.
        again = client.get(f"/runs/{run['id']}/automotive/trajectory")
        assert again.json() == body


def test_trajectory_rejects_non_automotive_and_missing(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        created = client.post(
            "/simulation/runs",
            json={
                "company_id": "corp-co",
                "company_name": "Corp Co",
                "market": "ai",
                "domain_id": "corporate",
                "tick_count": 2,
                "seed": 7,
            },
        )
        assert created.status_code == 201, created.text
        response = client.get(f"/runs/{created.json()['id']}/automotive/trajectory")
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "automotive_domain_required"
        missing = client.get("/runs/does-not-exist/automotive/trajectory")
        assert missing.status_code == 404


def test_split_structure_endpoint_round_trips(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client, split_structure=PHASE2_SPLIT)
        response = client.get(f"/runs/{run['id']}/automotive/split-structure")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["run_id"] == run["id"]
        assert body["structure"]["oems"][0]["oem_id"] == "faw-vw"
        assert body["structure"]["oems"][0]["nameplates"][0]["nameplate_id"] == "sagitar"
        assert body["validation"]["is_valid"] is True
        plain = _create_run(client)
        missing = client.get(f"/runs/{plain['id']}/automotive/split-structure")
        assert missing.status_code == 400
        assert missing.json()["detail"]["code"] == "automotive_no_split_structure"


def test_dual_track_splits_sum_to_spine_every_tick(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client, split_structure=PHASE2_SPLIT)
        points = client.get(f"/runs/{run['id']}/automotive/trajectory").json()["points"]
        penetrations = []
        for point in points:
            state = point["state"]
            assert state["nev_production_volume"] + state["ice_production_volume"] == pytest.approx(
                state["production_volume"]
            )
            assert state["nev_retail_volume"] + state["ice_retail_volume"] == pytest.approx(
                state["sales_volume_retail"]
            )
            penetrations.append(state["nev_penetration"])
        assert penetrations == sorted(penetrations)
        assert penetrations[0] == pytest.approx(0.479)
        assert penetrations[-1] == pytest.approx(0.479 + 6 * 0.002)


# --- Transmission links ----------------------------------------------------


def test_lpr_easing_moves_retail_up(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        base = _create_run(client, split_structure=PHASE2_SPLIT)
        eased = _create_run(
            client,
            split_structure=PHASE2_SPLIT,
            variable_set=_fixed_override("lpr_proxy", 0.9),
        )
        base_retail = client.get(f"/runs/{base['id']}/automotive/trajectory").json()["points"][-1][
            "state"
        ]["sales_volume_retail"]
        eased_retail = client.get(f"/runs/{eased['id']}/automotive/trajectory").json()["points"][
            -1
        ]["state"]["sales_volume_retail"]
        assert eased_retail > base_retail * 1.03


def test_material_shock_moves_price_up_and_margin_down(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        base = _create_run(client, split_structure=PHASE2_SPLIT)
        shocked = _create_run(
            client,
            split_structure=PHASE2_SPLIT,
            variable_set=_fixed_override("material_cost_index", 1.2),
        )
        base_state = client.get(f"/runs/{base['id']}/automotive/trajectory").json()["points"][-1][
            "state"
        ]
        shocked_state = client.get(f"/runs/{shocked['id']}/automotive/trajectory").json()["points"][
            -1
        ]["state"]
        assert shocked_state["price_index"] > 1.04
        assert shocked_state["price_index"] > base_state["price_index"]
        assert shocked_state["tier1_gross_margin"] < base_state["tier1_gross_margin"]


def test_tax_level_factor_exact_at_tick_one(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        base = _create_run(client, split_structure=PHASE2_SPLIT)
        taxed = _create_run(
            client,
            split_structure=PHASE2_SPLIT,
            variable_set=_fixed_override("policy_tax_rate", 0.10),
        )
        base_tick1 = client.get(f"/runs/{base['id']}/automotive/trajectory").json()["points"][1][
            "state"
        ]["sales_volume_retail"]
        taxed_tick1 = client.get(f"/runs/{taxed['id']}/automotive/trajectory").json()["points"][1][
            "state"
        ]["sales_volume_retail"]
        # Level factor 1 + 1.25 x (0.05 - 0.10) = 0.9375, applied once.
        assert taxed_tick1 / base_tick1 == pytest.approx(0.9375, rel=1e-6)


# --- S-layer wiring (acceptance) -------------------------------------------


def test_sales_layer_end_to_end_shock_moves_production_and_sales(
    monkeypatch, tmp_path: Path
) -> None:
    """Ho's acceptance chain: shock -> production change -> sales change,
    the whole chain automatic. A chip-supply shock (0.8) cuts the
    production spine, and the computed sales figures follow."""
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        base = _create_run(client, split_structure=PHASE2_SPLIT)
        shocked = _create_run(
            client,
            split_structure=PHASE2_SPLIT,
            variable_set=_fixed_override("chip_supply_index", 0.8),
        )
        base_layer = _sales_layer(client, base["id"])
        shocked_layer = _sales_layer(client, shocked["id"])
        base_prod = [tick["production_volume"] for tick in base_layer["per_tick"]]
        shocked_prod = [tick["production_volume"] for tick in shocked_layer["per_tick"]]
        assert len(base_prod) == 6
        for shocked_tick, base_tick in zip(shocked_prod, base_prod):
            assert shocked_tick < base_tick
        assert shocked_prod[-1] < base_prod[-1] * 0.7
        # The S-layer reads the same trajectory the endpoint serves.
        trajectory = client.get(f"/runs/{base['id']}/automotive/trajectory").json()["points"]
        trajectory_prod = [point["state"]["production_volume"] for point in trajectory[1:]]
        assert base_prod == pytest.approx(trajectory_prod)
        # Sales follow production down.
        assert base_layer["summary"]["total_own_sales"] > 0
        assert shocked_layer["summary"]["total_own_sales"] < (
            base_layer["summary"]["total_own_sales"] * 0.75
        )
        assert shocked_layer["summary"]["total_capacity_value"] < (
            base_layer["summary"]["total_capacity_value"] * 0.75
        )
        assert base_layer["snapshot_tick_count"] == 6
        assert base_layer["own_sales_basis"] == "supplier_rows"


def test_sales_layer_schedule_ramps_successor_mix(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client, split_structure=PHASE2_SPLIT)
        layer = _sales_layer(client, run["id"])
        p02_units = [
            row["units"] for row in layer["rows"] if row["product_id"] == "P02"
        ]
        assert len(p02_units) == 6
        # Successor share 0.5 -> 1.0 across the schedule doubles the
        # P02 units even as production eases down.
        assert p02_units[-1] > p02_units[0] * 1.5
        assert p02_units == sorted(p02_units)


def test_sales_layer_is_deterministic(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client, split_structure=PHASE2_SPLIT)
        first = _sales_layer(client, run["id"])
        second = _sales_layer(client, run["id"])
        assert first == second


def test_sales_layer_requires_split_and_valid_shares(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        plain = _create_run(client)
        response = client.post(
            f"/runs/{plain['id']}/automotive/sales-layer",
            json={"oem_production_shares": {"faw-vw": 1.0}},
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "automotive_no_split_structure"
        run = _create_run(client, split_structure=PHASE2_SPLIT)
        bad_shares = client.post(
            f"/runs/{run['id']}/automotive/sales-layer",
            json={"oem_production_shares": {"faw-vw": 0.5}},
        )
        assert bad_shares.status_code == 400
        assert bad_shares.json()["detail"]["code"] == "automotive_invalid_oem_shares"
        missing = client.post(
            "/runs/does-not-exist/automotive/sales-layer",
            json={"oem_production_shares": {"faw-vw": 1.0}},
        )
        assert missing.status_code == 404


def test_sales_layer_no_attribution_nulls_own_sales(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client, split_structure=PHASE2_SPLIT)
        response = client.post(
            f"/runs/{run['id']}/automotive/sales-layer",
            json={"oem_production_shares": {"faw-vw": 1.0}},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["own_sales_basis"] == "unavailable"
        assert body["own_sales_unavailable_reason"]
        assert all(row["own_sales"] is None for row in body["rows"])
        assert body["summary"]["total_own_sales"] is None
        assert body["summary"]["total_capacity_value"] > 0


def test_sales_layer_prospect_zero_own_sales(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client, split_structure=PROSPECT_SPLIT)
        body = _sales_layer(
            client, run["id"], oem_production_shares={"dongfeng-honda": 1.0}
        )
        assert body["summary"]["total_capacity_value"] > 0
        assert body["summary"]["total_own_sales"] == 0.0
        assert all(row["own_sales"] == 0.0 for row in body["rows"])


def test_sales_layer_share_attribution(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client, split_structure=PHASE2_SPLIT)
        body = _sales_layer(
            client,
            run["id"],
            own_supplier_id=None,
            default_supply_share=0.10,
        )
        assert body["own_sales_basis"] == "supply_share"
        assert body["summary"]["total_own_sales"] == pytest.approx(
            body["summary"]["total_capacity_value"] * 0.10
        )


# --- Prompt endpoints ------------------------------------------------------


def test_prompts_evaluate_endpoint(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        structure = {
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
                                                    "product_id": "P02",
                                                    "fitment_kind": "rate",
                                                    "fitment": 0.8,
                                                    "supplier_id": "ho",
                                                    "supplier_share": 1.0,
                                                    "price": 2500.0,
                                                    "solution_code": "RHP:SA8650",
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
        response = client.post(
            "/automotive/prompts/evaluate", json={"split_structure": structure}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        rule_ids = [prompt["rule_id"] for prompt in body["prompts"]]
        assert "R1" in rule_ids
        assert body["anomaly_count"] >= 1
        prompt = next(p for p in body["prompts"] if p["rule_id"] == "R1")
        assert prompt["severity"] == "anomaly"
        assert prompt["expected_logic"]
        assert prompt["likely_explanations"]
        # Malformed shape -> 422, not a prompt report.
        bad = dict(structure)
        bad["oems"][0]["nameplates"][0]["generations"][0]["trims"][0]["morphology"] = "bogus"
        rejected = client.post("/automotive/prompts/evaluate", json={"split_structure": bad})
        assert rejected.status_code == 422


def test_expectations_endpoint(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        response = client.get("/automotive/expectations")
        assert response.status_code == 200, response.text
        catalog = response.json()
        assert len(catalog) == 22
        by_id = {entry["id"]: entry for entry in catalog}
        assert by_id["R1"]["evaluated"] is True
        assert by_id["AVM1"]["evaluated"] is True
        assert by_id["R11"]["evaluated"] is False
        assert by_id["R2"]["normal_logic"]
