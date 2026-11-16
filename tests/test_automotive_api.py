"""API tests for the Phase 1 automotive pack.

Covers automotive run creation (defaults, state fields, per-tick
drivers), the split gate (refusal, zero rows, automotive-only), the
stored split fragment (input-hash identity), the wiring proof (a
consumer-confidence change moves the retail ensemble P50, plus a
same-seed byte-identical rerun), the generation transition, lookup
replaceability through the template mechanism, the C4 policy-cliff
lever, rule triggering with a scaled effect, and replay.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from planagent.config import reset_settings_cache
from planagent.db import reset_database_cache
from planagent.main import create_app
from planagent.services.splits import generation_mix_at_index
from planagent.services.splits.aggregation import prior_fitment_rate
from planagent.services.splits.models import SplitStructure

VALID_SPLIT = {
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
                            "generation_id": "gen-out",
                            "lifecycle_phase": "phase_out",
                            "share": 0.7,
                            "trims": [
                                {
                                    "trim_id": "high",
                                    "share": 1.0,
                                    "fitments": [
                                        {
                                            "product_id": "P01",
                                            "fitment_kind": "rate",
                                            "fitment": 0.8,
                                            "supplier_id": "ho-supplier",
                                            "supplier_share": 0.1,
                                            "price": 100.0,
                                        },
                                        {
                                            "product_id": "P01",
                                            "fitment_kind": "rate",
                                            "fitment": 0.8,
                                            "supplier_id": "other-supplier",
                                            "supplier_share": 0.9,
                                            "price": 100.0,
                                        },
                                    ],
                                }
                            ],
                        },
                        {
                            "generation_id": "gen-new",
                            "lifecycle_phase": "ramp",
                            "share": 0.3,
                            "trims": [
                                {
                                    "trim_id": "high",
                                    "share": 1.0,
                                    "fitments": [
                                        {
                                            "product_id": "P01",
                                            "fitment_kind": "rate",
                                            "fitment": 0.9,
                                            "supplier_id": "ho-supplier",
                                            "supplier_share": 0.5,
                                            "price": 100.0,
                                        },
                                        {
                                            "product_id": "P01",
                                            "fitment_kind": "rate",
                                            "fitment": 0.9,
                                            "supplier_id": "other-supplier",
                                            "supplier_share": 0.5,
                                            "price": 100.0,
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

F02_SPLIT = {
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
                            "generation_id": "gen-1",
                            "lifecycle_phase": "mature",
                            "share": 1.0,
                            "trims": [
                                {
                                    "trim_id": "high",
                                    "share": 1.0,
                                    "fitments": [
                                        {
                                            "product_id": "P01",
                                            "fitment_kind": "rate",
                                            "fitment": 1.0,
                                            "supplier_id": "ho-supplier",
                                            "supplier_share": 1.0,
                                            "price": 100.0,
                                        },
                                        {
                                            "product_id": "P01",
                                            "fitment_kind": "rate",
                                            "fitment": 1.0,
                                            "supplier_id": "other-supplier",
                                            "supplier_share": 1.0,
                                            "price": 100.0,
                                        },
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


def setup_app(monkeypatch, tmp_path: Path, db_name: str = "planagent-automotive.db") -> None:
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


def _snapshots(client: TestClient, run_id: str) -> list[dict]:
    package = client.get(f"/runs/{run_id}/replay-package")
    assert package.status_code == 200, package.text
    return package.json()["package"]["snapshots"]


def _confidence_override(mode: float) -> dict:
    return {
        "name": "confidence-override",
        "variables": [
            {
                "id": "consumer_confidence_proxy",
                "unit": "index",
                "distribution": {
                    "type": "triangular",
                    "min": 0.8,
                    "mode": mode,
                    "max": 1.2,
                },
                "evidence_ref": "test-override",
            }
        ],
    }


def test_automotive_run_defaults_to_twelve_ticks(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        payload = automotive_payload()
        del payload["tick_count"]
        created = client.post("/simulation/runs", json=payload)
        assert created.status_code == 201, created.text
        run = created.json()
        assert run["status"] == "COMPLETED"
        assert run["tick_count"] == 12
        assert len(_snapshots(client, run["id"])) == 13


def test_automotive_run_state_fields_and_drivers(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client)
        assert run["status"] == "COMPLETED"
        assert run["domain_id"] == "automotive"
        snapshots = _snapshots(client, run["id"])
        assert len(snapshots) == 7
        tick_zero = snapshots[0]["state"]
        # Tick 0 carries the pack defaults (fixed-value variables sample
        # to their fixed values; the triangular confidence draw perturbs
        # only the growth rate, not the levels).
        assert tick_zero["production_volume"] == 287.8
        assert tick_zero["sales_volume_retail"] == 197.9
        assert tick_zero["dealer_inventory_coef"] == 1.35
        assert tick_zero["generation_transition_index"] == 0.0
        # Every tick the drivers move the state: the pull-forward stock
        # decays 2%, the transition index climbs 0.05, retail falls
        # under the pull-forward drag, and inventory builds because
        # wholesale exceeds retail.
        for index, snapshot in enumerate(snapshots):
            state = snapshot["state"]
            assert state["generation_transition_index"] == pytest.approx(0.05 * index)
            assert state["pull_forward_stock"] == pytest.approx(1150.0 * (0.98**index))
        retails = [s["state"]["sales_volume_retail"] for s in snapshots]
        assert retails == sorted(retails, reverse=True)
        inventories = [s["state"]["dealer_inventory_coef"] for s in snapshots]
        assert inventories == sorted(inventories)
        productions = [s["state"]["production_volume"] for s in snapshots]
        assert productions == sorted(productions, reverse=True)


def test_split_gate_refuses_f02_and_writes_nothing(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        response = client.post(
            "/simulation/runs", json=automotive_payload(split_structure=F02_SPLIT)
        )
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert detail["code"] == "split_validation_failed"
        assert detail["validation"]["is_valid"] is False
        assert "supplier_shares_sum" in [issue["kind"] for issue in detail["validation"]["issues"]]
        runs = client.get("/simulation/runs")
        assert runs.status_code == 200
        assert runs.json() == []


def test_split_gate_rejects_non_automotive_domain(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        response = client.post(
            "/simulation/runs",
            json={
                "company_id": "corp-co",
                "company_name": "Corp Co",
                "market": "ai",
                "domain_id": "corporate",
                "tick_count": 2,
                "seed": 7,
                "split_structure": VALID_SPLIT,
            },
        )
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert detail["code"] == "split_validation_failed"
        assert detail["validation"]["issues"][0]["kind"] == (
            "split_structure_requires_automotive_domain"
        )
        assert client.get("/simulation/runs").json() == []


def test_split_structure_stored_in_input_hash(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        # decision_time is pinned: it defaults to creation time, which
        # is part of the hashed configuration (Sprint 5 firewall).
        pinned = {"decision_time": "2026-11-16T00:00:00Z"}
        plain = _create_run(client, **pinned)
        with_split = _create_run(client, split_structure=VALID_SPLIT, **pinned)
        assert with_split["status"] == "COMPLETED"
        plain_hash = client.get(f"/runs/{plain['id']}/determinism").json()["input_hash"]
        split_hash = client.get(f"/runs/{with_split['id']}/determinism").json()["input_hash"]
        # The split fragment is part of the run's hashed identity.
        assert plain_hash != split_hash
        again = _create_run(client, split_structure=VALID_SPLIT, **pinned)
        again_hash = client.get(f"/runs/{again['id']}/determinism").json()["input_hash"]
        assert again_hash == split_hash


def test_wiring_proof_confidence_moves_retail_p50(monkeypatch, tmp_path: Path) -> None:
    """Hard acceptance criterion: changing ONE variable distribution
    (the consumer-confidence mode) moves the downstream retail ensemble
    P50 in the expected direction."""
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        base = _create_run(client, variable_set=_confidence_override(1.0))
        high = _create_run(client, variable_set=_confidence_override(1.2))
        base_mc = client.post(
            f"/runs/{base['id']}/monte-carlo",
            json={"trials": 50, "seed": 11, "metric": "sales_volume_retail"},
        )
        assert base_mc.status_code == 201, base_mc.text
        high_mc = client.post(
            f"/runs/{high['id']}/monte-carlo",
            json={"trials": 50, "seed": 11, "metric": "sales_volume_retail"},
        )
        assert high_mc.status_code == 201, high_mc.text
        base_p50 = base_mc.json()["baseline"]["p50"]
        high_p50 = high_mc.json()["baseline"]["p50"]
        # Moving the triangular mode 1.0 -> 1.2 moves its mean from 1.0
        # to 1.0667, adding 0.05 x 0.0667 ~= +0.0033 to the monthly
        # growth rate — roughly +2% retail over 6 ticks. The assertion
        # leaves margin for the drag interaction; the observed move in
        # the verification run was +2.48% (186.87 -> 191.52).
        assert high_p50 > base_p50 * 1.02


def test_same_seed_byte_identical_rerun(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        pinned = {"decision_time": "2026-11-16T00:00:00Z"}
        first = _create_run(client, split_structure=VALID_SPLIT, **pinned)
        second = _create_run(client, split_structure=VALID_SPLIT, **pinned)
        assert first["id"] != second["id"]
        assert _snapshots(client, first["id"]) == _snapshots(client, second["id"])
        first_det = client.get(f"/runs/{first['id']}/determinism").json()
        second_det = client.get(f"/runs/{second['id']}/determinism").json()
        assert first_det["state_hashes"] == second_det["state_hashes"]
        assert first_det["sampled_values"] == second_det["sampled_values"]
        assert first_det["input_hash"] == second_det["input_hash"]


def test_generation_transition_in_snapshots(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client, split_structure=VALID_SPLIT)
        structure = SplitStructure.model_validate(VALID_SPLIT)
        snapshots = _snapshots(client, run["id"])
        mixes = [
            generation_mix_at_index(structure, "t-roc", s["state"]["generation_transition_index"])
            for s in snapshots
        ]
        for mix in mixes:
            assert sum(mix.values()) == pytest.approx(1.0)
        outgoing = [mix["gen-out"] for mix in mixes]
        successor = [mix["gen-new"] for mix in mixes]
        assert outgoing == sorted(outgoing, reverse=True)
        assert successor == sorted(successor)
        assert outgoing[0] == 1.0
        assert outgoing[-1] == pytest.approx(0.7)
        assert successor[-1] == pytest.approx(0.3)


def test_lookup_replaceable_via_stored_template(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        created = client.post(
            "/variable-templates",
            json={
                "name": "custom-lookup",
                "domain_id": "automotive",
                "variables": [],
                "formulas": [],
                "assumption_data": {
                    "fitment_lookup": {"l2_by_price_band": {"<10": 0.5, "20-30": 0.5}}
                },
            },
        )
        assert created.status_code == 201, created.text
        template_id = created.json()["id"]
        # The stored template round-trips its assumption data (migration
        # 0037 column).
        stored = client.get(f"/variable-templates/{template_id}")
        assert stored.status_code == 200
        assert stored.json()["assumption_data"]["fitment_lookup"]["l2_by_price_band"]["<10"] == 0.5

        run = _create_run(
            client,
            variable_template_id=template_id,
            variable_set=_confidence_override(1.0),
        )
        variables = client.get(f"/runs/{run['id']}/variables")
        assert variables.status_code == 200
        bindings = variables.json()["bindings"]
        assert bindings is not None
        # The run's stored bindings carry the replaced lookup, and the
        # consumer reads the replaced value — zero code change.
        assert prior_fitment_rate(bindings["assumption_data"], "l2_by_price_band", "<10") == 0.5


def test_lookup_replaceable_via_inline_variable_set(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        override = _confidence_override(1.0)
        override["assumption_data"] = {"fitment_lookup": {"l2_by_price_band": {"<10": 0.25}}}
        run = _create_run(client, variable_set=override)
        variables = client.get(f"/runs/{run['id']}/variables")
        assert variables.status_code == 200
        bindings = variables.json()["bindings"]
        assert prior_fitment_rate(bindings["assumption_data"], "l2_by_price_band", "<10") == 0.25
        # The builtin template's other series survive the merge (the
        # override replaced only the fitment_lookup top-level key... and
        # the simulated share key is untouched).
        assert bindings["assumption_data"]["supply_share_simulated"]["value"] == 0.10


def test_policy_cliff_lever_lowers_retail_p50(monkeypatch, tmp_path: Path) -> None:
    """C4 policy-cliff family: a 10% purchase-tax lever (vs the 5%
    baseline) cuts the retail ensemble P50 via the level factor."""
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client)
        response = client.post(
            f"/runs/{run['id']}/monte-carlo",
            json={
                "trials": 50,
                "seed": 11,
                "metric": "sales_volume_retail",
                "strategy_levers": {"policy_tax_rate": 0.10},
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        # Level factor 1 + 1.25 x (0.05 - 0.10) = 0.9375, applied once
        # at tick 1: roughly -6% retail. Wide margin for interactions.
        assert body["strategy"]["p50"] < body["baseline"]["p50"] * 0.98


def test_rule_trigger_and_scaled_effect(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        ingested = client.post(
            "/ingest/runs",
            json={
                "requested_by": "automotive-rule-test",
                "items": [
                    {
                        "source_type": "research",
                        "source_url": "https://example.com/demand-surge",
                        "title": "Demand surge lifts retail orders",
                        "content_text": (
                            "A demand surge drove record sales and strong retail "
                            "orders this month, with order books booming across "
                            "dealers."
                        ),
                        "published_at": "2026-01-05T08:00:00Z",
                    }
                ],
            },
        )
        assert ingested.status_code == 201, ingested.text
        # The deterministic extractor lands the claim in review below the
        # 0.62 provisional floor, so the run cannot see it until a
        # reviewer accepts it — the normal evidence workflow.
        items = client.get("/review/items")
        assert items.status_code == 200
        assert len(items.json()) == 1
        accepted = client.post(
            f"/review/items/{items.json()[0]['id']}/accept",
            json={"reviewer_id": "automotive-rule-test"},
        )
        assert accepted.status_code == 200, accepted.text
        run = _create_run(client)
        assert "auto.demand_surge" in run["summary"].get("matched_rules", [])
        determinism = client.get(f"/runs/{run['id']}/determinism").json()
        confidence = determinism["sampled_values"]["consumer_confidence_proxy"]
        trace = client.get(f"/runs/{run['id']}/decision-trace")
        assert trace.status_code == 200
        surge_records = [
            record for record in trace.json() if "auto.demand_surge" in record["policy_rule_ids"]
        ]
        assert surge_records, "expected at least one demand-surge decision record"
        # Tick 1 carries the unescalated effect: base 6.0 x the sampled
        # confidence value, rounded to 4 decimals like every stored
        # effect. Later ticks carry the engine's pre-existing
        # repeated-rule escalation multiplier (x1.15, x1.30 capped),
        # applied equally to the scaled and the fixed effect — so the
        # ratio between the two effects is escalation-invariant and
        # pins the scaling on every tick.
        first = min(surge_records, key=lambda record: record["tick"])
        assert first["expected_effect"]["production_volume"] == pytest.approx(
            6.0 * confidence, abs=1e-4
        )
        assert first["expected_effect"]["dealer_inventory_coef"] == pytest.approx(-0.03)
        expected_ratio = (6.0 * confidence) / -0.03
        for record in surge_records:
            ratio = (
                record["expected_effect"]["production_volume"]
                / record["expected_effect"]["dealer_inventory_coef"]
            )
            assert ratio == pytest.approx(expected_ratio, rel=1e-3)


def test_replay_matches_tick_by_tick(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client, split_structure=VALID_SPLIT)
        replayed = client.post(f"/runs/{run['id']}/replay")
        assert replayed.status_code == 201, replayed.text
        body = replayed.json()
        assert body["match"] is True
        assert body["first_diverging_tick"] is None
        assert _snapshots(client, body["replay_run_id"]) == _snapshots(client, run["id"])
