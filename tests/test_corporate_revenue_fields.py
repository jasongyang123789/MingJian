"""Fix 3 (2026-11-19): revenue/profit state fields in the corporate pack.

The first backtest run showed revenue magnitude could not be expressed:
the corporate pack had no revenue state field, so ``cash`` sat at its
template value (120.0) for the whole run and magnitude could only be
scored on ``market_share``. These tests pin the fix end to end:

- pack level: ``revenue`` / ``profit`` exist with template-consistent
  defaults and no existing field's default changed;
- run level: a ``revenue`` variable + per-tick driver formula produces a
  moving revenue trajectory (not stuck at the default);
- ensemble level: Monte Carlo with metric=``revenue`` returns real,
  non-degenerate P10/P50/P90, and metric=``profit`` is accepted too;
- robustness level: expected shortfall accepts a ``revenue`` ensemble;
- regression: an unknown metric is still refused, and a plain run's
  baseline (cash / market_share) is unchanged.

Same scratch-SQLite + in-memory-bus + empty-LLM-keys pattern as the
Sprint 1-4 tests. With no claims ingested, every tick takes the
``monitor`` fallback (no cash effect), so the no-variable baseline is
exactly predictable.
"""

from __future__ import annotations

import math
import statistics
from pathlib import Path

from fastapi.testclient import TestClient

from planagent.config import reset_settings_cache
from planagent.db import reset_database_cache
from planagent.main import create_app

REVENUE_SET = {
    "name": "revenue case",
    "variables": [
        {
            "id": "revenue",
            "unit": "abstract",
            "distribution": {"type": "triangular", "min": 90, "mode": 100, "max": 130},
            "evidence_ref": "estimate: test",
        },
        {
            "id": "revenue_growth",
            "unit": "ratio",
            "distribution": {"type": "triangular", "min": 0.05, "mode": 0.10, "max": 0.20},
            "evidence_ref": "estimate: test",
        },
    ],
    "formulas": [
        {
            "output": "revenue",
            "tick_driver": True,
            "description": "revenue grows at the sampled rate each tick",
            "expression": {
                "op": "multiply",
                "args": [{"ref": "revenue"}, {"op": "add", "args": [1, {"ref": "revenue_growth"}]}],
            },
        },
    ],
    "internal": {"team": "test"},
}


def build_database_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.resolve().as_posix()}"


def setup_app(monkeypatch, tmp_path: Path, db_name: str = "planagent-revenue.db") -> None:
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


def simulation_payload(**overrides) -> dict:
    payload: dict = {
        "company_id": "revenue-test-co",
        "company_name": "Revenue Test Co",
        "market": "ai",
        "tick_count": 3,
        "seed": 7,
        "actor_template": "ai_model_provider",
    }
    payload.update(overrides)
    return payload


def _snapshots(client: TestClient, run_id: str) -> list[dict]:
    package = client.get(f"/runs/{run_id}/replay-package")
    assert package.status_code == 200, package.text
    return package.json()["package"]["snapshots"]


def _create_revenue_run(client: TestClient, **overrides) -> dict:
    payload = simulation_payload(variable_set=REVENUE_SET)
    payload.update(overrides)
    created = client.post("/simulation/runs", json=payload)
    assert created.status_code == 201, created.text
    return created.json()


def _run_ensemble(client: TestClient, run_id: str, **overrides) -> dict:
    payload: dict = {
        "trials": 10,
        "seed": 42,
        "metric": "revenue",
        "loss_threshold": 0.0,
    }
    payload.update(overrides)
    response = client.post(f"/runs/{run_id}/monte-carlo", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _trial_values(client: TestClient, ensemble: dict, arm: str) -> list[float]:
    values = []
    for trial_id in ensemble["trial_run_ids"][arm]:
        snapshots = _snapshots(client, trial_id)
        values.append(snapshots[-1]["state"][ensemble["metric"]])
    return values


def _expected_shortfall(values: list[float], alpha: float) -> float:
    ordered = sorted(values)
    cutoff = max(1, math.floor(alpha * len(ordered)))
    return statistics.fmean(ordered[:cutoff])


# ------------------------------------------------------------------ pack level
def test_corporate_pack_has_revenue_and_profit_with_template_defaults() -> None:
    from planagent.simulation.domain_packs import registry

    pack = registry.get("corporate")
    defaults = {field.name: field.default for field in pack.state_fields}
    assert defaults["revenue"] == 100.0
    assert defaults["profit"] == 20.0
    # No existing field's default changed.
    assert defaults["cash"] == 100.0
    assert defaults["market_share"] == 0.05
    assert defaults["gross_margin"] == 0.62
    assert defaults["churn_risk"] == 0.12

    templates = {t.actor_type: t.default_state for t in pack.actor_templates}
    assert templates["ai_model_provider"]["revenue"] == 120.0
    assert templates["ai_model_provider"]["profit"] == 24.0
    assert templates["ai_model_provider"]["cash"] == 120.0
    assert templates["ai_model_provider"]["market_share"] == 0.08
    assert templates["developer_tools_saas"]["revenue"] == 60.0
    assert templates["developer_tools_saas"]["profit"] == 12.0


def test_corporate_builtin_template_exposes_revenue_and_profit(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        preset = client.get("/variable-templates/builtin:corporate")
        assert preset.status_code == 200
        fields = {f["name"]: f["default"] for f in preset.json()["state_fields"]}
        assert fields["revenue"] == 100.0
        assert fields["profit"] == 20.0
        policies = preset.json()["policies"]
        assert policies["revenue"]["preferred_direction"] == "increase"
        assert policies["profit"]["preferred_direction"] == "increase"


# ------------------------------------------------------------------ run level
def test_revenue_driver_moves_revenue_each_tick(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_revenue_run(client)
        assert run["status"] == "COMPLETED"
        snapshots = _snapshots(client, run["id"])
        assert len(snapshots) == 4  # tick 0 + 3 ticks

        tick_zero = snapshots[0]["state"]
        assert 90 <= tick_zero["revenue"] <= 130  # sampled, not the default
        assert tick_zero["profit"] == 24.0  # template default, no driver
        assert tick_zero["cash"] == 120.0  # unchanged baseline behavior

        revenues = [s["state"]["revenue"] for s in snapshots]
        assert revenues == sorted(revenues)  # strictly increasing: growth > 0
        assert revenues[-1] > revenues[0]
        # Each tick multiplies by (1 + g) with g in [0.05, 0.20].
        for before, after in zip(revenues, revenues[1:]):
            assert 1.05 <= after / before <= 1.20


def test_plain_corporate_baseline_is_unchanged(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        created = client.post("/simulation/runs", json=simulation_payload())
        assert created.status_code == 201, created.text
        snapshots = _snapshots(client, created.json()["id"])
        tick_zero = snapshots[0]["state"]
        assert tick_zero["cash"] == 120.0
        assert tick_zero["market_share"] == 0.08
        assert tick_zero["revenue"] == 120.0
        assert tick_zero["profit"] == 24.0
        # No claims, no variables: cash stays exactly at its template value.
        assert all(s["state"]["cash"] == 120.0 for s in snapshots)


# ------------------------------------------------------------------ ensemble + ES
def test_monte_carlo_on_revenue_is_non_degenerate(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_revenue_run(client)
        ensemble = _run_ensemble(client, run["id"])
        assert ensemble["metric"] == "revenue"
        baseline = ensemble["baseline"]
        assert baseline["n"] == 10
        assert baseline["min"] < baseline["max"]
        assert baseline["p10"] < baseline["p90"]
        assert baseline["p10"] <= baseline["p50"] <= baseline["p90"]
        # Cross-check the summary against the trial snapshots (summaries
        # round to 4 decimals; the linear-interpolation p50 of 10 values
        # is their median).
        assert baseline["p50"] == round(
            statistics.median(_trial_values(client, ensemble, "baseline")), 4
        )


def test_monte_carlo_on_profit_is_accepted(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_revenue_run(client)
        ensemble = _run_ensemble(client, run["id"], metric="profit")
        assert ensemble["metric"] == "profit"
        # No profit variable/driver: every trial holds the template value.
        assert ensemble["baseline"]["p50"] == 24.0
        assert ensemble["baseline"]["min"] == ensemble["baseline"]["max"] == 24.0


def test_monte_carlo_on_cash_still_works(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_revenue_run(client)
        ensemble = _run_ensemble(client, run["id"], metric="cash", loss_threshold=90.0)
        assert ensemble["metric"] == "cash"
        assert ensemble["baseline"]["p50"] == 120.0


def test_unknown_metric_is_still_refused(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_revenue_run(client)
        response = client.post(
            f"/runs/{run['id']}/monte-carlo",
            json={"trials": 5, "seed": 42, "metric": "not_a_field", "loss_threshold": 0.0},
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "monte_carlo_unknown_metric"


def test_expected_shortfall_accepts_revenue_ensemble(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_revenue_run(client)
        ensemble = _run_ensemble(client, run["id"])
        baseline = _trial_values(client, ensemble, "baseline")

        response = client.post(
            f"/runs/{run['id']}/robustness/expected-shortfall",
            json={"alpha": 0.1, "tail": "lower"},
        )
        assert response.status_code == 201, response.text
        result = response.json()
        assert result["ensemble_id"] == ensemble["ensemble_id"]
        assert result["metric"] == "revenue"
        assert result["baseline"]["value"] == _expected_shortfall(baseline, 0.1)
        assert result["baseline"]["n"] == 10


# ------------------------------------------------------------------ profit chain
def test_corporate_builtin_template_carries_profit_chain(monkeypatch, tmp_path) -> None:
    """Profit-chain pack (2026-11-20): the corporate template was empty
    (0 variables / 0 formulas); it now carries the same profit chain
    as the automotive template (4 margin variables + 4 formulas).
    A generic run keeps revenue at its actor default and moves profit
    as revenue x net_margin — it does NOT stay at the 24.0 default
    (the sampled margin_base is triangular, not fixed at its 0.20
    mode), so the exact chain path is asserted from the run's sampled
    values instead of the default.
    """
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        preset = client.get("/variable-templates/builtin:corporate")
        assert preset.status_code == 200
        body = preset.json()
        assert [v["id"] for v in body["variables"]] == [
            "margin_base",
            "margin_longrun",
            "margin_reversion",
            "margin_adoption",
        ]
        assert [f["output"] for f in body["formulas"]] == [
            "disruptor_adoption",
            "revenue",
            "net_margin",
            "profit",
        ]
        created = client.post(
            "/simulation/runs",
            json=simulation_payload(
                variable_template_id="builtin:corporate",
                actor_template="ai_model_provider",
            ),
        )
        assert created.status_code == 201, created.text
        run_id = created.json()["id"]
        snapshots = _snapshots(client, run_id)
        assert len(snapshots) == 4  # tick 0 + 3 ticks
        assert snapshots[0]["state"]["revenue"] == 120.0
        assert snapshots[0]["state"]["profit"] == 24.0
        det = client.get(f"/runs/{run_id}/determinism")
        assert det.status_code == 200, det.text
        sampled = det.json()["sampled_values"]
        base = sampled["margin_base"]
        adoption = sampled["margin_adoption"]
        for tick in (1, 2, 3):
            assert snapshots[tick]["state"]["revenue"] == 120.0
            # Drivers round EACH output to 4 decimals, so profit reads
            # the ROUNDED margin, not the full-precision value.
            margin = round(
                min(
                    0.25,
                    max(0.02, base + 0.25 * (0.20 - base) * (tick - 1) + adoption * 0.0),
                ),
                4,
            )
            assert snapshots[tick]["state"]["profit"] == round(
                120.0 * margin, 4
            ), tick
