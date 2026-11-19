"""Tests for the opt-in downside mechanism (fix/downside-mechanism).

Growth-coupled diffusion only computes "how fast it grows": a growth
case's ensemble can never decline, so both Desay anchors report p_loss
0.0. The downside mechanism adds a cyclical downturn shock (plus an
optional persistent reversal) as ordinary sampled variables + a
``downside`` configuration fragment, applied after the tick drivers.
Default OFF: with no fragment, runs behave exactly as before.

Synthetic test parameters throughout — NOT fitted to any historical
case. The Desay verification (real parameters, real scores) lives in
the research directory, not here.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from planagent.config import reset_settings_cache
from planagent.db import reset_database_cache
from planagent.main import create_app
from planagent.services.simulation.downside import (
    DownsideError,
    resolve_downside,
)

# ---------------------------------------------------------------------------
# Pure resolution + window shape.
# ---------------------------------------------------------------------------

_SAMPLED = {
    "downturn_occurs": 1.0,
    "downturn_depth": 0.20,
    "downturn_start": 3.0,
    "downturn_duration": 2.0,
}
_FIELDS = {"revenue", "profit"}


def _enabled_config(**overrides) -> dict:
    fragment = {"enabled": True, "fields": ["revenue", "profit"]}
    fragment.update(overrides)
    return {"downside": fragment}


def test_disabled_by_default() -> None:
    assert resolve_downside({}, _SAMPLED, _FIELDS) is None
    assert resolve_downside({"downside": {"enabled": False}}, _SAMPLED, _FIELDS) is None
    assert resolve_downside(None, _SAMPLED, _FIELDS) is None


def test_window_is_a_bump_peaking_at_depth() -> None:
    state = resolve_downside(_enabled_config(), _SAMPLED, _FIELDS)
    assert state is not None
    factors = [state.factor(tick) for tick in range(1, 8)]
    # ~1 well before the window, exactly 1-depth at the centred tick,
    # back to ~1 well after; never outside (0, 1].
    assert factors[0] > 0.99
    assert factors[3] == pytest.approx(0.80, abs=1e-4)
    assert factors[6] > 0.99
    assert all(0.0 < factor <= 1.0 for factor in factors)
    assert min(factors) == factors[3]


def test_no_occurrence_means_no_shock() -> None:
    sampled = {**_SAMPLED, "downturn_occurs": 0.0}
    state = resolve_downside(_enabled_config(), sampled, _FIELDS)
    assert state is not None
    assert state.factors(5) == {"1": 1.0, "2": 1.0, "3": 1.0, "4": 1.0, "5": 1.0}


def test_persistent_mode_stays_down() -> None:
    sampled = {**_SAMPLED, "downturn_persistent": 1.0}
    state = resolve_downside(
        _enabled_config(persistent_variable="downturn_persistent"), sampled, _FIELDS
    )
    assert state is not None
    factors = [state.factor(tick) for tick in range(1, 8)]
    assert factors[0] > 0.99
    assert factors[-1] == pytest.approx(0.80, abs=1e-3)
    assert all(factors[i + 1] <= factors[i] for i in range(len(factors) - 1))


def test_persistent_defaults_to_pure_cycle() -> None:
    state = resolve_downside(_enabled_config(), _SAMPLED, _FIELDS)
    assert state is not None
    assert state.persistent == 0.0


def test_fractional_occurs_scales_the_shock() -> None:
    # A strategy lever may scale the occurrence weight: half the depth.
    sampled = {**_SAMPLED, "downturn_occurs": 0.5}
    state = resolve_downside(_enabled_config(), sampled, _FIELDS)
    assert state is not None
    assert state.factor(4) == pytest.approx(0.90, abs=1e-4)


def test_misconfiguration_fails_loudly() -> None:
    with pytest.raises(DownsideError, match="not bound"):
        resolve_downside(_enabled_config(), {"downturn_depth": 0.2}, _FIELDS)
    with pytest.raises(DownsideError, match="no state field"):
        resolve_downside(_enabled_config(fields=["nope"]), _SAMPLED, _FIELDS)
    with pytest.raises(DownsideError, match="non-empty 'fields'"):
        resolve_downside(_enabled_config(fields=[]), _SAMPLED, _FIELDS)
    with pytest.raises(DownsideError, match="must lie in \\[0, 1\\)"):
        resolve_downside(
            _enabled_config(), {**_SAMPLED, "downturn_depth": 1.0}, _FIELDS
        )
    with pytest.raises(DownsideError, match="must be positive"):
        resolve_downside(
            _enabled_config(), {**_SAMPLED, "downturn_duration": 0.0}, _FIELDS
        )
    with pytest.raises(DownsideError, match="must lie in \\[0, 1\\]"):
        resolve_downside(
            _enabled_config(), {**_SAMPLED, "downturn_occurs": 1.5}, _FIELDS
        )
    with pytest.raises(DownsideError, match="not bound"):
        resolve_downside(
            _enabled_config(persistent_variable="downturn_persistent"),
            _SAMPLED,
            _FIELDS,
        )


# ---------------------------------------------------------------------------
# Engine level: real runs + ensemble through the API (scratch SQLite).
# ---------------------------------------------------------------------------


def _setup_app(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(
        "PLANAGENT_DATABASE_URL", f"sqlite+aiosqlite:///{(tmp_path / 'downside.db').as_posix()}"
    )
    monkeypatch.setenv("PLANAGENT_EVENT_BUS_BACKEND", "memory")
    monkeypatch.setenv("PLANAGENT_INLINE_INGEST_DEFAULT", "true")
    monkeypatch.setenv("PLANAGENT_INLINE_SIMULATION_DEFAULT", "true")
    for key in (
        "PLANAGENT_OPENAI_API_KEY",
        "PLANAGENT_OPENAI_BASE_URL",
        "PLANAGENT_OPENAI_PRIMARY_API_KEY",
        "PLANAGENT_OPENAI_PRIMARY_BASE_URL",
        "PLANAGENT_OPENAI_EXTRACTION_API_KEY",
        "PLANAGENT_OPENAI_EXTRACTION_BASE_URL",
        "PLANAGENT_OPENAI_REPORT_API_KEY",
        "PLANAGENT_OPENAI_REPORT_BASE_URL",
    ):
        monkeypatch.setenv(key, "")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    reset_settings_cache()
    reset_database_cache()


def _variable_entry(var_id: str, distribution: dict) -> dict:
    return {
        "id": var_id,
        "unit": "x",
        "distribution": distribution,
        "evidence_ref": "estimate: synthetic test",
    }


def _growth_variable_set(*, downside: dict | None, sampled: bool = False) -> dict:
    """Constant 10%/tick revenue growth, with optional downside variables.

    Downside variables are APPENDED, so the pre-existing draws are
    untouched by their presence. Fixed values pin the shock for the
    shape test; triangular/Bernoulli draws drive the ensemble test.
    """

    def dist(fixed_value: float, triangular: dict | None = None) -> dict:
        if sampled and triangular is not None:
            return {"type": "triangular", **triangular}
        return {"type": "fixed", "value": fixed_value}

    variables = [
        _variable_entry("revenue", {"type": "fixed", "value": 1000.0}),
        _variable_entry("revenue_growth", {"type": "fixed", "value": 0.10}),
    ]
    if downside is not None:
        variables.extend(
            [
                _variable_entry(
                    "downturn_occurs",
                    {"type": "bernoulli", "p": 0.5}
                    if sampled
                    else {"type": "fixed", "value": 1.0},
                ),
                _variable_entry(
                    "downturn_depth",
                    dist(0.25, {"min": 0.05, "mode": 0.20, "max": 0.35}),
                ),
                _variable_entry(
                    "downturn_start",
                    dist(3.0, {"min": 2.0, "mode": 3.0, "max": 4.0}),
                ),
                _variable_entry(
                    "downturn_duration",
                    dist(2.0, {"min": 1.0, "mode": 2.0, "max": 3.0}),
                ),
            ]
        )
    return {
        "name": "downside case",
        "variables": variables,
        "formulas": [
            {
                "output": "revenue",
                "expression": {
                    "op": "multiply",
                    "args": [
                        {"ref": "revenue"},
                        {"op": "add", "args": [1, {"ref": "revenue_growth"}]},
                    ],
                },
                "tick_driver": True,
            },
        ],
    }


_DOWNSIDE_FRAGMENT = {
    "enabled": True,
    "fields": ["revenue"],
    "label": "LABELED ASSUMPTION — synthetic test shock",
}


def _create_run(
    client: TestClient, variable_set: dict, downside: dict | None = None
) -> dict:
    payload = {
        "company_id": "downside-test-co",
        "company_name": "Downside Test Co",
        "market": "ai",
        "tick_count": 7,
        "seed": 7,
        "actor_template": "default",
        "variable_set": variable_set,
    }
    if downside is not None:
        payload["downside"] = downside
    created = client.post("/simulation/runs", json=payload)
    assert created.status_code == 201, created.text
    return created.json()


def _revenue_trajectory(client: TestClient, run_id: str) -> list[float]:
    package = client.get(f"/runs/{run_id}/replay-package")
    assert package.status_code == 200, package.text
    return [snap["state"]["revenue"] for snap in package.json()["package"]["snapshots"]]


def test_downturn_dip_shape_and_off_control(monkeypatch, tmp_path: Path) -> None:
    _setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        # Shock on: fixed depth 0.25, window ticks 3-4. Growth is 10%/tick,
        # so the shocked ticks must actually fall: (1.10 * 0.75 - 1) < 0.
        shocked = _create_run(
            client,
            _growth_variable_set(downside=_DOWNSIDE_FRAGMENT),
            downside=_DOWNSIDE_FRAGMENT,
        )
        revenues = _revenue_trajectory(client, shocked["id"])
        assert len(revenues) == 8  # tick 0 + 7 ticks
        assert revenues[0] == 1000.0
        assert revenues[1] > revenues[0]  # pre-window growth
        assert revenues[4] < revenues[3]  # the dip: trajectory is not smooth growth
        assert revenues[3] < revenues[2]
        assert revenues[5] < revenues[4]  # still falling while the window recedes
        # Recovery begins once the window has receded enough — but the
        # scar persists: growth resumes from the lower base.
        assert revenues[6] > revenues[5]
        assert revenues[7] > revenues[6]
        assert revenues[7] < 1000.0 * 1.10**7

        # Control: same recipe, no fragment — smooth 10% growth.
        control = _create_run(client, _growth_variable_set(downside=None))
        control_revenues = _revenue_trajectory(client, control["id"])
        assert control_revenues == pytest.approx(
            [round(1000.0 * 1.10**tick, 4) for tick in range(8)], abs=5e-4
        )
        assert all(
            later > earlier for earlier, later in zip(control_revenues, control_revenues[1:])
        )


def test_downside_off_is_identical_to_no_fragment(monkeypatch, tmp_path: Path) -> None:
    _setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        absent = _create_run(client, _growth_variable_set(downside=None))
        absent_revenues = _revenue_trajectory(client, absent["id"])

        disabled = _create_run(
            client,
            _growth_variable_set(downside=None),
            downside={"enabled": False, "fields": ["revenue"]},
        )
        assert _revenue_trajectory(client, disabled["id"]) == absent_revenues

        # Enabled but never occurring (Bernoulli p=0 via fixed 0): also identical.
        no_occurs_set = _growth_variable_set(downside=_DOWNSIDE_FRAGMENT)
        no_occurs_set["variables"][2]["distribution"] = {"type": "fixed", "value": 0.0}
        no_occurs = _create_run(client, no_occurs_set, downside=_DOWNSIDE_FRAGMENT)
        assert _revenue_trajectory(client, no_occurs["id"]) == absent_revenues


def test_monte_carlo_decline_probability(monkeypatch, tmp_path: Path) -> None:
    _setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(
            client,
            _growth_variable_set(downside=_DOWNSIDE_FRAGMENT, sampled=True),
            downside=_DOWNSIDE_FRAGMENT,
        )
        response = client.post(
            f"/runs/{run['id']}/monte-carlo",
            json={"trials": 20, "seed": 42, "metric": "revenue", "loss_threshold": 1000.0},
        )
        assert response.status_code == 201, response.text
        ensemble = response.json()
        assert 0.0 < ensemble["baseline"]["decline_probability"] <= 1.0
        assert 0.0 <= ensemble["baseline"]["p_loss"] <= 1.0
        # The lower tail widens: the minimum trial ends below the
        # no-shock path's minimum (all trials grow at 10% without shock).
        assert ensemble["baseline"]["min"] < round(1000.0 * 1.10**7, 4)

        # Control: same recipe without the mechanism — nothing ever declines.
        control = _create_run(
            client, _growth_variable_set(downside=None, sampled=True)
        )
        control_response = client.post(
            f"/runs/{control['id']}/monte-carlo",
            json={"trials": 20, "seed": 42, "metric": "revenue", "loss_threshold": 1000.0},
        )
        assert control_response.status_code == 201, control_response.text
        assert control_response.json()["baseline"]["decline_probability"] == 0.0


def test_enabled_without_bound_variables_fails_loudly(monkeypatch, tmp_path: Path) -> None:
    _setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        created = client.post(
            "/simulation/runs",
            json={
                "company_id": "downside-test-co",
                "company_name": "Downside Test Co",
                "market": "ai",
                "tick_count": 7,
                "seed": 7,
                "actor_template": "default",
                "variable_set": _growth_variable_set(downside=None),
                "downside": _DOWNSIDE_FRAGMENT,
            },
        )
        # The run must not silently execute without its shock: creation
        # fails instead (same loud failure as a broken tick driver).
        assert created.status_code != 201, created.text
