"""Tests for Fix 2: inflection/diffusion dynamics (logistic S-curve drivers).

The backtest's constant-growth drivers (``market_share * (1 +
share_growth)``) cannot express disruptive collapse: the simulated bands
never contained Nokia's 40% -> 27% -> 6.4% fall or Blockbuster's
bankruptcy. This fix extends the formula-graph vocabulary with two
binary operators — ``pow`` and ``logistic`` — so a disruptor-adoption
S-curve and its coupling to the incumbent are expressible with the
existing per-tick driver machinery and ordinary sampled variables, with
no new state field, no migration, and no behaviour change when unused.

Canonical recipe (all parameters are ordinary variables; the values
below are SYNTHETIC test parameters, not fitted to any historical case):

- ``disruptor_ceiling`` (K): adoption saturation level, e.g. 0.9.
- ``disruptor_rate`` (r): logistic steepness per tick, e.g. 1.2.
- ``disruptor_midpoint`` (t0): tick at which adoption passes K/2, e.g. 3.0.
- ``disruptor_coupling`` (c): incumbent share lost per tick per unit of
  adoption, e.g. 0.55.
- ``base_growth`` (g): incumbent's underlying growth absent disruption.

Tick drivers, in list order (the adoption driver is a within-tick
intermediate: its output is not a state field, so it is recomputed from
``tick`` every tick and never persisted)::

    disruptor_adoption = logistic(
        disruptor_rate * (tick - disruptor_midpoint), disruptor_ceiling)
    market_share = max(0, market_share
        * (1 + base_growth - disruptor_coupling * disruptor_adoption))

Past the midpoint the incumbent's growth flips negative and accelerates
toward ``1 + g - c*K`` per tick — the collapse. With the values above,
share falls 0.40 -> 0.0926 by tick 5 and -> 0.0035 by tick 10.
"""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from planagent.config import reset_settings_cache
from planagent.db import reset_database_cache
from planagent.main import create_app
from planagent.services.variables.formulas import (
    FormulaEvaluationError,
    evaluate_formulas,
    evaluate_tick_drivers,
    validate_formulas,
)
from planagent.services.variables.models import (
    FormulaDefinition,
    VariableDefinition,
    VariableDistribution,
)

# ---------------------------------------------------------------------------
# Canonical recipe (shared by the pure and API tests).
# ---------------------------------------------------------------------------

#: Synthetic fixed parameters for the collapse tests. NOT historical data.
FIXED_PARAMS = {
    "market_share": 0.40,
    "disruptor_ceiling": 0.9,
    "disruptor_rate": 1.2,
    "disruptor_midpoint": 3.0,
    "disruptor_coupling": 0.55,
    "base_growth": 0.01,
}


def _ref(name: str) -> dict[str, str]:
    return {"ref": name}


def _op(operator: str, left: object, right: object) -> dict[str, object]:
    return {"op": operator, "args": [left, right]}


def adoption_expression() -> dict[str, object]:
    """logistic(rate * (tick - midpoint), ceiling)."""
    return {
        "op": "logistic",
        "args": [
            _op(
                "multiply",
                _ref("disruptor_rate"),
                _op("subtract", _ref("tick"), _ref("disruptor_midpoint")),
            ),
            _ref("disruptor_ceiling"),
        ],
    }


def share_expression() -> dict[str, object]:
    """max(0, market_share * (1 + base_growth - coupling * adoption))."""
    return {
        "op": "max",
        "args": [
            0,
            _op(
                "multiply",
                _ref("market_share"),
                _op(
                    "add",
                    1,
                    _op(
                        "subtract",
                        _ref("base_growth"),
                        _op(
                            "multiply",
                            _ref("disruptor_coupling"),
                            _ref("disruptor_adoption"),
                        ),
                    ),
                ),
            ),
        ],
    }


def diffusion_drivers() -> list[FormulaDefinition]:
    """The two canonical tick drivers, in evaluation order."""
    return [
        FormulaDefinition(
            output="disruptor_adoption", expression=adoption_expression(), tick_driver=True
        ),
        FormulaDefinition(output="market_share", expression=share_expression(), tick_driver=True),
    ]


def legacy_driver() -> FormulaDefinition:
    """The backtest's constant-growth driver, for the no-op comparison."""
    return FormulaDefinition(
        output="market_share",
        expression={
            "op": "min",
            "args": [
                0.85,
                _op("multiply", _ref("market_share"), _op("add", 1, _ref("base_growth"))),
            ],
        },
        tick_driver=True,
    )


def _run_drivers(
    drivers: list[FormulaDefinition],
    base_values: dict[str, float],
    initial_share: float,
    ticks: int = 10,
) -> tuple[list[float], list[float]]:
    """Simulate drivers tick by tick, mimicking the executor.

    Only driver outputs naming a state field (here ``market_share``)
    persist; the adoption intermediate is recomputed from ``tick``
    every tick. Returns (share trajectory incl. tick 0, adoption per tick).
    """
    state = {"market_share": initial_share}
    shares = [initial_share]
    adoptions: list[float] = []
    for tick in range(1, ticks + 1):
        updates = evaluate_tick_drivers(drivers, base_values, state, tick)
        adoptions.append(updates.get("disruptor_adoption", float("nan")))
        if "market_share" in updates:
            state["market_share"] = updates["market_share"]
        shares.append(state["market_share"])
    return shares, adoptions


def _var(var_id: str, value: float) -> VariableDefinition:
    return VariableDefinition(
        id=var_id,
        unit="x",
        distribution=VariableDistribution(type="fixed", value=value),
        evidence_ref="estimate: synthetic test",
    )


# ---------------------------------------------------------------------------
# New operators: pure evaluation.
# ---------------------------------------------------------------------------


def test_pow_operator_evaluates() -> None:
    formulas = [
        FormulaDefinition(output="cube", expression=_op("pow", 2, 3)),
        FormulaDefinition(output="root", expression=_op("pow", 9, 0.5)),
        FormulaDefinition(output="zero_pow", expression=_op("pow", 0, 0)),
        FormulaDefinition(output="neg_base", expression=_op("pow", -2, 3)),
        FormulaDefinition(output="neg_exp", expression=_op("pow", 2, -1)),
        FormulaDefinition(output="tick_sq", expression=_op("pow", _ref("tick"), 2)),
    ]
    assert evaluate_tick_drivers(formulas, {}, {}, tick=4) == {
        "cube": 8.0,
        "root": 3.0,
        "zero_pow": 1.0,
        "neg_base": -8.0,
        "neg_exp": 0.5,
        "tick_sq": 16.0,
    }


def test_pow_invalid_domain_fails_loudly() -> None:
    cases = [
        _op("pow", -2, 0.5),  # negative base, non-integer exponent
        _op("pow", 0, -1),  # zero to a negative power
        _op("pow", 10, 400),  # overflow
    ]
    for index, expression in enumerate(cases):
        formulas = [FormulaDefinition(output=f"out{index}", expression=expression)]
        with pytest.raises(FormulaEvaluationError):
            evaluate_formulas(formulas, {})


def test_logistic_operator_values() -> None:
    formulas = [
        FormulaDefinition(output="mid", expression=_op("logistic", 0, 1)),
        FormulaDefinition(output="mid_scaled", expression=_op("logistic", 0, 0.9)),
        FormulaDefinition(output="high", expression=_op("logistic", 20, 2)),
        FormulaDefinition(output="low", expression=_op("logistic", -20, 2)),
        FormulaDefinition(output="zero_ceiling", expression=_op("logistic", 5, 0)),
    ]
    derived = evaluate_formulas(formulas, {})
    assert derived["mid"] == 0.5
    assert derived["mid_scaled"] == 0.45
    assert derived["high"] == pytest.approx(2.0, abs=1e-8)
    assert derived["low"] == pytest.approx(0.0, abs=1e-8)
    assert derived["zero_ceiling"] == 0.0


def test_logistic_is_monotone_bounded_and_overflow_safe() -> None:
    # Monotone in z, bounded by the ceiling, and huge |z| never overflows
    # (the stable form only ever takes exp() of a non-positive argument).
    values = [
        evaluate_formulas([FormulaDefinition(output="a", expression=_op("logistic", z, 0.9))], {})[
            "a"
        ]
        for z in (-1000.0, -10.0, -1.0, 0.0, 1.0, 10.0, 1000.0)
    ]
    assert values == sorted(values)
    assert all(0.0 <= value <= 0.9 for value in values)
    assert values[0] == 0.0
    assert values[-1] == 0.9
    assert values[3] == 0.45


def test_new_operators_validate_and_unknown_operator_still_rejected() -> None:
    variables = [_var("a", 2.0), _var("b", 3.0)]
    issues, _ = validate_formulas(
        variables,
        [
            FormulaDefinition(output="p", expression=_op("pow", _ref("a"), _ref("b"))),
            FormulaDefinition(output="l", expression=_op("logistic", _ref("a"), _ref("b"))),
        ],
    )
    assert issues == []
    issues, _ = validate_formulas(
        variables,
        [FormulaDefinition(output="bad", expression={"op": "power", "args": [1, 2]})],
    )
    assert [issue.kind for issue in issues] == ["formula_unknown_operator"]
    for expression in (
        {"op": "pow", "args": [1]},
        {"op": "logistic", "args": [1, 2, 3]},
    ):
        issues, _ = validate_formulas(
            variables, [FormulaDefinition(output="arity", expression=expression)]
        )
        assert [issue.kind for issue in issues] == ["formula_wrong_arity"]


# ---------------------------------------------------------------------------
# Canonical recipe: pure tick-driver behaviour.
# ---------------------------------------------------------------------------


def test_diffusion_recipe_validates() -> None:
    variables = [_var(var_id, value) for var_id, value in FIXED_PARAMS.items()]
    issues, _ = validate_formulas(variables, diffusion_drivers())
    assert issues == []


def test_adoption_curve_is_s_shaped() -> None:
    _, adoptions = _run_drivers(diffusion_drivers(), FIXED_PARAMS, 0.40)
    # Monotone increasing, bounded by the ceiling, midpoint at tick 3.
    assert adoptions == sorted(adoptions)
    assert all(0.0 < value < 0.9 for value in adoptions)
    assert adoptions[2] == pytest.approx(0.45)  # tick 3 == midpoint -> K/2
    assert adoptions[0] == pytest.approx(0.0749, abs=1e-4)
    assert adoptions[4] == pytest.approx(0.8251, abs=1e-4)
    assert adoptions[9] == pytest.approx(0.8998, abs=1e-4)


def test_diffusion_recipe_collapses_within_five_ticks() -> None:
    shares, _ = _run_drivers(diffusion_drivers(), FIXED_PARAMS, 0.40)
    assert shares[0] == 0.40
    assert shares[5] < 0.10  # 0.40 -> ~0.0926 by tick 5
    assert shares[10] < 0.01
    assert all(later < earlier for earlier, later in itertools.pairwise(shares))


def test_midpoint_and_rate_move_the_inflection_as_expected() -> None:
    late = {**FIXED_PARAMS, "disruptor_midpoint": 5.0}
    fast = {**FIXED_PARAMS, "disruptor_rate": 2.0}
    base_shares, _ = _run_drivers(diffusion_drivers(), FIXED_PARAMS, 0.40)
    late_shares, _ = _run_drivers(diffusion_drivers(), late, 0.40)
    fast_shares, _ = _run_drivers(diffusion_drivers(), fast, 0.40)
    # Later midpoint delays the collapse; a steeper rate brings it forward.
    assert late_shares[5] > base_shares[5]
    assert fast_shares[5] < base_shares[5]
    # All three still collapse eventually: the mechanism is timing, not fate.
    assert late_shares[10] < 0.10
    assert fast_shares[10] < 0.01


def test_zero_ceiling_is_exactly_the_legacy_constant_growth_driver() -> None:
    """No behaviour change when the feature is unused.

    With ceiling 0 the adoption is 0 every tick, so the diffusion recipe
    must reproduce the backtest's constant-growth driver tick for tick
    (same per-tick rounding included).
    """
    inert = {**FIXED_PARAMS, "disruptor_ceiling": 0.0}
    diffusion_shares, _ = _run_drivers(diffusion_drivers(), inert, 0.40)
    legacy_shares, _ = _run_drivers([legacy_driver()], FIXED_PARAMS, 0.40)
    assert diffusion_shares == legacy_shares
    assert diffusion_shares[-1] == pytest.approx(0.40 * 1.01**10, abs=1e-4)


def test_zero_coupling_is_exactly_the_legacy_driver() -> None:
    inert = {**FIXED_PARAMS, "disruptor_coupling": 0.0}
    diffusion_shares, _ = _run_drivers(diffusion_drivers(), inert, 0.40)
    legacy_shares, _ = _run_drivers([legacy_driver()], FIXED_PARAMS, 0.40)
    assert diffusion_shares == legacy_shares


# ---------------------------------------------------------------------------
# Engine level: real runs + ensemble through the API (scratch SQLite).
# ---------------------------------------------------------------------------


def _setup_app(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(
        "PLANAGENT_DATABASE_URL", f"sqlite+aiosqlite:///{(tmp_path / 'diffusion.db').as_posix()}"
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


def _diffusion_variable_set(*, sampled: bool) -> dict:
    """The canonical recipe as a run-creation variable set.

    Fixed params for the collapse run; triangular diffusion params for
    the ensemble run. Values are synthetic test parameters.
    """

    def dist(var_id: str, fixed_value: float, triangular: dict | None = None) -> dict:
        if sampled and triangular is not None:
            return {"type": "triangular", **triangular}
        return {"type": "fixed", "value": fixed_value}

    return {
        "name": "diffusion case",
        "variables": [
            _variable_entry("market_share", dist("market_share", 0.40)),
            _variable_entry(
                "disruptor_ceiling",
                dist("disruptor_ceiling", 0.9, {"min": 0.7, "mode": 0.9, "max": 0.95}),
            ),
            _variable_entry(
                "disruptor_rate",
                dist("disruptor_rate", 1.2, {"min": 0.8, "mode": 1.2, "max": 1.6}),
            ),
            _variable_entry(
                "disruptor_midpoint",
                dist("disruptor_midpoint", 3.0, {"min": 2.0, "mode": 3.0, "max": 4.0}),
            ),
            _variable_entry("disruptor_coupling", dist("disruptor_coupling", 0.55)),
            _variable_entry("base_growth", dist("base_growth", 0.01)),
        ],
        "formulas": [
            {
                "output": "disruptor_adoption",
                "expression": adoption_expression(),
                "tick_driver": True,
            },
            {"output": "market_share", "expression": share_expression(), "tick_driver": True},
        ],
    }


def _create_run(client: TestClient, variable_set: dict) -> dict:
    created = client.post(
        "/simulation/runs",
        json={
            "company_id": "diffusion-test-co",
            "company_name": "Diffusion Test Co",
            "market": "ai",
            "tick_count": 10,
            "seed": 7,
            "actor_template": "default",
            "variable_set": variable_set,
        },
    )
    assert created.status_code == 201, created.text
    return created.json()


def _share_trajectory(client: TestClient, run_id: str) -> list[float]:
    package = client.get(f"/runs/{run_id}/replay-package")
    assert package.status_code == 200, package.text
    return [snap["state"]["market_share"] for snap in package.json()["package"]["snapshots"]]


def test_engine_run_collapses_and_control_does_not(monkeypatch, tmp_path: Path) -> None:
    _setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client, _diffusion_variable_set(sampled=False))
        shares = _share_trajectory(client, run["id"])
        assert len(shares) == 11  # tick 0 + 10 ticks
        assert shares[0] == 0.40
        assert shares[5] < 0.10
        assert shares[10] < 0.01

        # Control: same recipe with the ceiling at 0 must not collapse —
        # the incumbent just grows at base_growth.
        control_set = _diffusion_variable_set(sampled=False)
        control_set["variables"][1]["distribution"] = {"type": "fixed", "value": 0.0}
        control = _create_run(client, control_set)
        control_shares = _share_trajectory(client, control["id"])
        assert control_shares[10] > 0.40
        assert control_shares == pytest.approx(
            [round(0.40 * 1.01**tick, 4) for tick in range(11)], abs=5e-4
        )


def test_ensemble_over_diffusion_params_is_a_nondegenerate_collapse_band(
    monkeypatch, tmp_path: Path
) -> None:
    _setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client, _diffusion_variable_set(sampled=True))
        response = client.post(
            f"/runs/{run['id']}/monte-carlo",
            json={"trials": 20, "seed": 42, "metric": "market_share"},
        )
        assert response.status_code == 201, response.text
        baseline = response.json()["baseline"]
        assert baseline["n"] == 20
        # Non-degenerate: sampled diffusion params spread the outcomes.
        assert baseline["p10"] < baseline["p90"]
        assert baseline["min"] < baseline["max"]
        # The whole band collapses: even the slowest sampled corner
        # (ceiling 0.7, rate 0.8, midpoint 4.0) ends near 0.02, so the
        # band contains — in fact, is contained in — collapse territory.
        assert baseline["max"] < 0.10
        assert baseline["p50"] < 0.05
        assert baseline["min"] >= 0.0
