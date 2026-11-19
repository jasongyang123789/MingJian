"""API tests for arm independent resampling (fix/arm-resample).

Reproduces the first backtest run's finding #1 (report
``research/strategy-engine/backtest-runs-2026-11-19/REPORT.md``):
an override / scenario-branch child run inherited the anchor's
already-sampled variable values, so a Monte Carlo ensemble over
the child collapsed to a degenerate point estimate (P10 = P50 =
P90, all trial values identical) and ``most_robust`` duplicated
``highest_p50`` in all three cases. With ``resample_variables``
on, the child re-draws its non-pinned variables from their own
distributions, deterministically from the run seed, and the arm
ensemble is a real distribution again.

Setup mirrors the backtest's Huawei shape: corporate run, tick
driver ``market_share = min(0.85, market_share * (1 +
share_growth))``, one override pinning ``share_growth`` per arm
at ``fork_step=1``. Same scratch-SQLite + in-memory-bus +
empty-LLM-keys pattern as the option B tests. No live LLM call
is ever made.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from planagent.config import reset_settings_cache
from planagent.db import get_database, reset_database_cache
from planagent.domain.models import SimulationRun, StateSnapshotRecord
from planagent.main import create_app


def _triangular(min_v: float, mode: float, max_v: float) -> dict:
    return {"type": "triangular", "min": min_v, "mode": mode, "max": max_v}


def _growth_driver() -> dict:
    return {
        "output": "market_share",
        "expression": {
            "op": "min",
            "args": [
                {
                    "op": "multiply",
                    "args": [
                        {"ref": "market_share"},
                        {"op": "add", "args": [1, {"ref": "share_growth"}]},
                    ],
                },
                0.85,
            ],
        },
        "description": "Share compounds annually at share_growth; capped at 0.85.",
        "tick_driver": True,
    }


def _risk_driver() -> dict:
    """Driver for the crafted most_robust case: ``risk`` scales a
    symmetric ``swing`` shock, so the risky arm buys upside with
    downside instead of pure upside."""
    return {
        "output": "market_share",
        "expression": {
            "op": "min",
            "args": [
                {
                    "op": "multiply",
                    "args": [
                        {"ref": "market_share"},
                        {
                            "op": "add",
                            "args": [
                                1,
                                {
                                    "op": "add",
                                    "args": [
                                        {"ref": "share_growth"},
                                        {
                                            "op": "multiply",
                                            "args": [{"ref": "risk"}, {"ref": "swing"}],
                                        },
                                    ],
                                },
                            ],
                        },
                    ],
                },
                0.85,
            ],
        },
        "description": "Share compounds at share_growth plus risk-scaled swing.",
        "tick_driver": True,
    }


BOUND_SET = {
    "name": "resample-case",
    "variables": [
        {
            "id": "market_share",
            "unit": "share",
            "distribution": _triangular(0.02, 0.03, 0.05),
            "evidence_ref": "labeled assumption",
        },
        {
            "id": "share_growth",
            "unit": "rate",
            "distribution": _triangular(-0.05, 0.08, 0.25),
            "evidence_ref": "labeled assumption",
        },
    ],
    "formulas": [_growth_driver()],
    "internal": {"note": "backtest-shaped case"},
}

RISK_BOUND_SET = {
    "name": "resample-risk-case",
    "variables": [
        {
            "id": "market_share",
            "unit": "share",
            "distribution": _triangular(0.02, 0.03, 0.05),
            "evidence_ref": "labeled assumption",
        },
        {
            "id": "share_growth",
            "unit": "rate",
            "distribution": _triangular(-0.05, 0.08, 0.25),
            "evidence_ref": "labeled assumption",
        },
        {
            "id": "risk",
            "unit": "x",
            "distribution": _triangular(0.0, 0.5, 1.0),
            "evidence_ref": "labeled assumption",
        },
        {
            "id": "swing",
            "unit": "rate",
            "distribution": _triangular(-0.30, 0.0, 0.10),
            "evidence_ref": "labeled assumption",
        },
    ],
    "formulas": [_risk_driver()],
    "internal": {"note": "crafted robust-vs-p50 case"},
}

LOSS_THRESHOLD = 0.03


def build_database_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.resolve().as_posix()}"


def setup_app(monkeypatch, tmp_path: Path, db_name: str = "planagent-arm-resample.db") -> None:
    monkeypatch.setenv("PLANAGENT_DATABASE_URL", build_database_url(tmp_path / db_name))
    monkeypatch.setenv("PLANAGENT_EVENT_BUS_BACKEND", "memory")
    monkeypatch.setenv("PLANAGENT_INLINE_INGEST_DEFAULT", "true")
    monkeypatch.setenv("PLANAGENT_INLINE_SIMULATION_DEFAULT", "true")
    monkeypatch.setenv("PLANAGENT_OPENAI_API_KEY", "")
    monkeypatch.setenv("PLANAGENT_OPENAI_BASE_URL", "")
    monkeypatch.setenv("PLANAGENT_OPENAI_PRIMARY_API_KEY", "")
    monkeypatch.setenv("PLANAGENT_OPENAI_PRIMARY_BASE_URL", "")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    reset_settings_cache()
    reset_database_cache()


def _anchor_payload(**overrides) -> dict:
    payload: dict = {
        "company_id": "resample-test-co",
        "company_name": "Resample Test Co",
        "market": "telecom-equipment",
        "domain_id": "corporate",
        "actor_template": "ai_model_provider",
        "tick_count": 10,
        "seed": 7,
        "variable_set": BOUND_SET,
    }
    payload.update(overrides)
    return payload


def _create_anchor(client: TestClient, **overrides) -> dict:
    created = client.post("/simulation/runs", json=_anchor_payload(**overrides))
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "COMPLETED"
    return created.json()


def _run_ensemble(client: TestClient, run_id: str, trials: int = 20) -> dict:
    response = client.post(
        f"/runs/{run_id}/monte-carlo",
        json={
            "trials": trials,
            "seed": 42,
            "metric": "market_share",
            "loss_threshold": LOSS_THRESHOLD,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _trial_values(client: TestClient, run_id: str) -> dict:
    response = client.get(f"/runs/{run_id}/monte-carlo/trial-values")
    assert response.status_code == 200, response.text
    return response.json()


def _override(client: TestClient, run_id: str, directions: list[dict]):
    return client.post(f"/runs/{run_id}/directions/override", json={"directions": directions})


def _child_id_by_name(body: dict, name: str) -> str:
    for outcome in body["outcomes"]:
        assert outcome["status"] == "stored", outcome
        if outcome["name"] == name:
            return outcome["child_run_id"]
    raise AssertionError(f"no stored outcome named {name!r} in {body['outcomes']!r}")


async def _read_run_configuration(run_id: str) -> dict:
    database = get_database()
    async with database.session() as session:
        run = await session.get(SimulationRun, run_id)
        assert run is not None
        return dict(run.configuration or {})


async def _read_run_summary(run_id: str) -> dict:
    database = get_database()
    async with database.session() as session:
        run = await session.get(SimulationRun, run_id)
        assert run is not None
        return dict(run.summary or {})


async def _read_snapshot_state(run_id: str, tick: int) -> dict:
    database = get_database()
    async with database.session() as session:
        record = (
            await session.scalars(
                select(StateSnapshotRecord)
                .where(
                    StateSnapshotRecord.run_id == run_id,
                    StateSnapshotRecord.tick == tick,
                )
                .limit(1)
            )
        ).first()
        assert record is not None, f"no snapshot tick {tick} for run {run_id}"
        return dict(record.state)


def _resampled_and_control_children(client: TestClient, anchor_id: str) -> tuple[str, str]:
    """One override request, two arms pinning the same growth: the
    only difference is the resample flag."""
    response = _override(
        client,
        anchor_id,
        [
            {
                "name": "Resampled",
                "overrides": {"share_growth": 0.15},
                "fork_step": 1,
                "resample_variables": True,
            },
            {
                "name": "Control",
                "overrides": {"share_growth": 0.15},
                "fork_step": 1,
            },
        ],
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return (
        _child_id_by_name(body, "Resampled"),
        _child_id_by_name(body, "Control"),
    )


# ---------------------------------------------------------------------------
# Arm ensemble shape: resampled is a distribution, control is degenerate
# ---------------------------------------------------------------------------


def test_resampled_arm_ensemble_is_non_degenerate(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        anchor = _create_anchor(client)
        anchor_ensemble = _run_ensemble(client, anchor["id"])
        # Sanity: the anchor ensemble itself was never degenerate.
        assert anchor_ensemble["baseline"]["p10"] < anchor_ensemble["baseline"]["p90"]

        resampled_id, control_id = _resampled_and_control_children(client, anchor["id"])

        resampled = _run_ensemble(client, resampled_id)
        resampled_values = _trial_values(client, resampled_id)["baseline"]
        assert len(resampled_values) == 20
        assert len(set(resampled_values)) > 1, "resampled trials must not be identical"
        assert resampled["baseline"]["p10"] < resampled["baseline"]["p50"]
        assert resampled["baseline"]["p50"] < resampled["baseline"]["p90"]
        # The flag is stored on the child's scenario fragment.
        configuration = asyncio.run(_read_run_configuration(resampled_id))
        assert configuration["scenario"]["resample_variables"] is True

        control = _run_ensemble(client, control_id)
        control_values = _trial_values(client, control_id)["baseline"]
        assert len(set(control_values)) == 1, "control trials must stay degenerate (pre-fix)"
        assert control["baseline"]["p10"] == control["baseline"]["p50"]
        assert control["baseline"]["p50"] == control["baseline"]["p90"]
        configuration = asyncio.run(_read_run_configuration(control_id))
        assert configuration["scenario"]["resample_variables"] is False


def test_resampled_arm_ensemble_is_deterministic(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        anchor = _create_anchor(client)
        resampled_id, _control_id = _resampled_and_control_children(client, anchor["id"])

        first = _run_ensemble(client, resampled_id)
        first_values = _trial_values(client, resampled_id)["baseline"]
        second = _run_ensemble(client, resampled_id)
        second_values = _trial_values(client, resampled_id)["baseline"]
        assert first_values == second_values
        assert first["baseline"] == second["baseline"]


def test_pinned_values_are_exact_under_resampling(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        anchor = _create_anchor(client)
        response = _override(
            client,
            anchor["id"],
            [
                {
                    "name": "Pinned growth",
                    "overrides": {"share_growth": 0.15},
                    "fork_step": 1,
                    "resample_variables": True,
                },
                {
                    "name": "Pinned share",
                    "overrides": {"market_share": 0.04},
                    "fork_step": 1,
                    "resample_variables": True,
                },
            ],
        )
        assert response.status_code == 201, response.text
        body = response.json()
        growth_child = _child_id_by_name(body, "Pinned growth")
        share_child = _child_id_by_name(body, "Pinned share")

        # A pinned driver variable samples at exactly its pinned value.
        summary = asyncio.run(_read_run_summary(growth_child))
        sampled = summary["determinism"]["sampled_values"]
        assert sampled["share_growth"] == 0.15
        # ... while the non-pinned variable was re-drawn from its own
        # distribution instead of keeping the forked value.
        fork_state = asyncio.run(_read_snapshot_state(anchor["id"], 1))
        assert sampled["market_share"] != fork_state["market_share"]
        tick0 = asyncio.run(_read_snapshot_state(growth_child, 0))
        assert tick0["market_share"] == sampled["market_share"]

        # A pinned STATE-field variable lands exactly, beating both
        # the fork snapshot and the re-draw.
        tick0 = asyncio.run(_read_snapshot_state(share_child, 0))
        assert tick0["market_share"] == 0.04
        summary = asyncio.run(_read_run_summary(share_child))
        assert summary["determinism"]["sampled_values"]["market_share"] == 0.04
        # The non-pinned driver variable still re-draws per seed.
        assert summary["determinism"]["sampled_values"]["share_growth"] != 0.15


# ---------------------------------------------------------------------------
# most_robust adds independent information again
# ---------------------------------------------------------------------------


def test_most_robust_can_differ_from_highest_p50(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        anchor = _create_anchor(client, variable_set=RISK_BOUND_SET)
        _run_ensemble(client, anchor["id"])
        response = _override(
            client,
            anchor["id"],
            [
                {
                    "name": "Safe",
                    "overrides": {"share_growth": 0.05, "risk": 0.0},
                    "fork_step": 1,
                    "resample_variables": True,
                },
                {
                    "name": "Risky",
                    "overrides": {"share_growth": 0.15, "risk": 1.0},
                    "fork_step": 1,
                    "resample_variables": True,
                },
            ],
        )
        assert response.status_code == 201, response.text
        body = response.json()
        safe_id = _child_id_by_name(body, "Safe")
        risky_id = _child_id_by_name(body, "Risky")

        safe = _run_ensemble(client, safe_id)
        risky = _run_ensemble(client, risky_id)
        # Both arms are real distributions now.
        assert safe["baseline"]["p10"] < safe["baseline"]["p90"]
        assert risky["baseline"]["p10"] < risky["baseline"]["p90"]
        # The risky arm wins on the median but loses on loss probability:
        # its worst case dips below the threshold; the safe arm never does.
        assert risky["baseline"]["p50"] > safe["baseline"]["p50"]
        assert safe["baseline"]["p_loss"] == 0.0
        assert risky["baseline"]["p_loss"] > safe["baseline"]["p_loss"]

        derived = client.post(f"/runs/{anchor['id']}/directions/derive")
        assert derived.status_code == 200, derived.text
        outcomes = {item["rule_id"]: item for item in derived.json()["outcomes"]}
        highest = outcomes["highest_p50"]
        robust = outcomes["most_robust"]
        assert highest["status"] == "produced", highest
        assert robust["status"] == "produced", robust
        assert highest["source_run_id"] == risky_id
        assert robust["source_run_id"] == safe_id
        assert highest["source_run_id"] != robust["source_run_id"]
