"""Profit-chain tick-0 initial consistency (fix/blindspot-2015-seam).

The defect (blindspot Step 2-ON report §6): the 2015 B profit mode
path drops at tick 1 (383.27 -> 375.57) because tick-0 profit is an
independently sampled initial (triangular(300, 358.87, 420)) while
ticks 1+ are profit = revenue x net_margin (tick-1 margin 8.34% vs
the initial's implied 10.76%). Two profit definitions meet at the
tick-0/tick-1 boundary. The fix (engine-level, in ``_execute_run``):
when the mounted profit tick driver READS ``net_margin``, tick-0
profit is derived as revenue(0) x margin_base — the decision-year
margin — instead of the sampled draw. The sampled draw is retained
(the sampling stream is untouched) but no longer seeds the initial
state.

Tests lock: the automotive R&D identity, the corporate margin_base,
the decoupled-driver control (untouched), revenue bit-identity (no
sampling-stream shift), the explicit-overlay guard (fork-point
preservation), and the generic run (no sampled profit, default kept).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from planagent.config import get_settings, reset_settings_cache
from planagent.db import get_database, reset_database_cache
from planagent.main import create_app


def build_database_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.resolve().as_posix()}"


def setup_app(monkeypatch, tmp_path: Path, db_name: str = "planagent-profit-initial.db") -> None:
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


def _fixed(variable_id: str, value: float) -> dict:
    return {
        "id": variable_id,
        "unit": "test",
        "distribution": {"type": "fixed", "value": value},
        "evidence_ref": "test: fixed for determinism",
    }


def _revenue_growth_driver() -> dict:
    return {
        "output": "revenue",
        "expression": {
            "op": "max",
            "args": [
                0,
                {
                    "op": "multiply",
                    "args": [
                        {"ref": "revenue"},
                        {"op": "add", "args": [1, {"ref": "revenue_growth"}]},
                    ],
                },
            ],
        },
        "description": "test: revenue grows at revenue_growth",
        "tick_driver": True,
    }


def _profit_growth_driver() -> dict:
    """Decoupled profit driver (pre-migration shape): evolves profit
    from its sampled initial, never reads net_margin."""
    return {
        "output": "profit",
        "expression": {
            "op": "max",
            "args": [
                0,
                {
                    "op": "multiply",
                    "args": [
                        {"ref": "profit"},
                        {"op": "add", "args": [1, {"ref": "profit_growth"}]},
                    ],
                },
            ],
        },
        "description": "test: decoupled profit growth (no net_margin read)",
        "tick_driver": True,
    }


def _chain_case_set() -> dict:
    """Minimal 2015-B-shaped automotive case: the sampled profit
    (383.27) disagrees with the R&D margin identity (0.2696 - 0.076
    - 0.0958 = 0.0978), which is exactly the Step 2-ON seam. Fixed
    values throughout, so the trajectory is deterministic. The
    profit_growth variable is retained but unread (migration
    precedent): deleting it would shift the sampling stream."""
    variables = [
        _fixed("revenue", 3560.56),
        _fixed("revenue_growth", 0.10),
        _fixed("profit", 383.27),
        _fixed("profit_growth", 0.12),
        _fixed("gross_base", 0.2696),
        _fixed("rd_base", 0.076),
        _fixed("other_share", 0.0958),
    ]
    return {
        "name": "profit-initial-chain",
        "variables": variables,
        "formulas": [_revenue_growth_driver()],
    }


def _decoupled_case_set() -> dict:
    """Same variables as the chain case, but the profit driver is the
    decoupled growth driver: no net_margin read, so the sampled
    initial must stand."""
    case = _chain_case_set()
    case["name"] = "profit-initial-decoupled"
    case["formulas"] = [_revenue_growth_driver(), _profit_growth_driver()]
    return case


def _corporate_case_set() -> dict:
    """Minimal corporate case: margin_base is the sampled
    decision-year margin; tick-0 profit must be revenue x it."""
    variables = [
        _fixed("revenue", 950.0),
        _fixed("profit", 290.0),
        _fixed("margin_base", 0.1318),
        _fixed("margin_longrun", 0.1318),
    ]
    return {"name": "profit-initial-corporate", "variables": variables, "formulas": []}


def _create_run(
    client: TestClient,
    case_set: dict | None,
    domain_id: str = "automotive",
    actor_template: str = "tier1_supplier",
    template_id: str = "builtin:automotive",
    tick_count: int = 5,
    initial_state: dict | None = None,
) -> dict:
    payload: dict = {
        "company_id": "profit-initial-test",
        "company_name": "Profit Initial Test",
        "market": "auto-electronics-china",
        "domain_id": domain_id,
        "actor_template": actor_template,
        "tick_count": tick_count,
        "seed": 7,
        "decision_time": "2015-12-31T00:00:00Z",
        "variable_template_id": template_id,
        # Track C default is downside ON; these unit tests assert
        # clean driver arithmetic, so they explicitly opt out
        # (``downside: null``). The ON interaction is covered by the
        # four-case rerun, not here.
        "downside": None,
    }
    if case_set is not None:
        payload["variable_set"] = case_set
    if initial_state is not None:
        payload["initial_state"] = initial_state
    created = client.post("/simulation/runs", json=payload)
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "COMPLETED"
    return created.json()


def _replay_package(client: TestClient, run_id: str) -> dict:
    response = client.get(f"/runs/{run_id}/replay-package")
    assert response.status_code == 200, response.text
    pkg = response.json()["package"]
    if isinstance(pkg, str):
        pkg = json.loads(pkg)
    return pkg


def _trajectory(client: TestClient, run_id: str) -> dict[int, dict]:
    pkg = _replay_package(client, run_id)
    return {s["tick"]: s["state"] for s in pkg["snapshots"]}


def _determinism(client: TestClient, run_id: str) -> dict:
    pkg = _replay_package(client, run_id)
    return pkg["run"]["summary"]["determinism"]


@pytest.fixture()
def client(monkeypatch, tmp_path: Path) -> TestClient:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as test_client:
        yield test_client


def test_profit_initial_uses_path_margin_automotive(client: TestClient) -> None:
    """The seam case: tick-0 profit is revenue x the R&D identity,
    not the sampled 383.27; the draw is retained but not applied."""
    created = _create_run(client, _chain_case_set())
    traj = _trajectory(client, created["id"])
    assert traj[0]["revenue"] == pytest.approx(3560.56)
    assert traj[0]["profit"] == pytest.approx(3560.56 * 0.0978, abs=1e-6)
    assert traj[0]["profit"] / traj[0]["revenue"] == pytest.approx(0.0978, abs=1e-9)
    # The sampled initial (383.27) no longer seeds the state.
    assert traj[0]["profit"] != pytest.approx(383.27)
    # Revenue still grows from its own initial (stream untouched).
    assert traj[1]["revenue"] == pytest.approx(3560.56 * 1.10)
    det = _determinism(client, created["id"])
    derivation = det["profit_initial_derivation"]
    assert derivation is not None
    assert derivation["margin_source"] == "rd_identity"
    assert derivation["margin"] == pytest.approx(0.0978)
    assert derivation["revenue"] == pytest.approx(3560.56)
    assert derivation["profit"] == pytest.approx(3560.56 * 0.0978, abs=1e-6)
    assert det["sampled_values"]["profit"] == pytest.approx(383.27)
    assert "profit" not in det["sampled_applied"]


def test_profit_initial_uses_margin_base_corporate(client: TestClient) -> None:
    """Corporate template: tick-0 profit is revenue x margin_base."""
    created = _create_run(
        client,
        _corporate_case_set(),
        domain_id="corporate",
        actor_template="ai_model_provider",
        template_id="builtin:corporate",
    )
    traj = _trajectory(client, created["id"])
    assert traj[0]["revenue"] == pytest.approx(950.0)
    assert traj[0]["profit"] == pytest.approx(950.0 * 0.1318, abs=1e-6)
    assert traj[0]["profit"] != pytest.approx(290.0)
    det = _determinism(client, created["id"])
    derivation = det["profit_initial_derivation"]
    assert derivation is not None
    assert derivation["margin_source"] == "margin_base"
    assert derivation["margin"] == pytest.approx(0.1318)
    assert det["sampled_values"]["profit"] == pytest.approx(290.0)
    assert "profit" not in det["sampled_applied"]


def test_decoupled_profit_driver_keeps_sampled_initial(client: TestClient) -> None:
    """A profit driver that does not read net_margin is not
    chain-mounted: the sampled initial stands, derivation is None."""
    created = _create_run(client, _decoupled_case_set())
    traj = _trajectory(client, created["id"])
    assert traj[0]["profit"] == pytest.approx(383.27)
    det = _determinism(client, created["id"])
    assert det["profit_initial_derivation"] is None
    assert "profit" in det["sampled_applied"]
    # The decoupled driver still evolves profit from the sampled initial.
    assert traj[1]["profit"] == pytest.approx(383.27 * 1.12)


def test_revenue_trajectory_identical_with_and_without_chain(client: TestClient) -> None:
    """The fix moves no sampling draw: revenue is bit-identical
    between the chain run and the decoupled run on the same variables
    and seed, and the sampled values agree exactly."""
    chain = _create_run(client, _chain_case_set())
    decoupled = _create_run(client, _decoupled_case_set())
    chain_traj = _trajectory(client, chain["id"])
    decoupled_traj = _trajectory(client, decoupled["id"])
    for tick in chain_traj:
        assert chain_traj[tick]["revenue"] == decoupled_traj[tick]["revenue"]
    chain_det = _determinism(client, chain["id"])
    decoupled_det = _determinism(client, decoupled["id"])
    assert chain_det["sampled_values"] == decoupled_det["sampled_values"]
    # Only the tick-0 profit differs; ticks 1+ follow the same path
    # definition (revenue x net_margin vs growth from the sampled
    # initial differ by construction — the comparison is revenue).
    assert chain_traj[0]["profit"] != decoupled_traj[0]["profit"]


def test_explicit_initial_state_profit_is_preserved(client: TestClient) -> None:
    """An explicit initial_state profit is a deliberate override
    (e.g. a non-resampling fork's evolved state): the derivation
    skips it and the overlay value stands."""
    created = _create_run(client, _chain_case_set(), initial_state={"profit": 500.0})
    traj = _trajectory(client, created["id"])
    assert traj[0]["profit"] == pytest.approx(500.0)
    det = _determinism(client, created["id"])
    assert det["profit_initial_derivation"] is None
    assert "profit" in det["sampled_applied"]


def test_generic_run_without_sampled_profit_keeps_default(client: TestClient) -> None:
    """No case profit variable, no derivation: a generic automotive
    run keeps the template's profit default (20.0)."""
    created = _create_run(client, None)
    traj = _trajectory(client, created["id"])
    assert traj[0]["profit"] == pytest.approx(20.0)
    det = _determinism(client, created["id"])
    assert det["profit_initial_derivation"] is None
