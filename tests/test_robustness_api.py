"""API tests for Sprint 4 robustness evaluation + formula graph (PRD D6/D7).

Covers expected shortfall, bootstrap intervals, tornado sensitivity, and
threshold search over stored ensembles; decision-gate registration
(append-only, supersession, pre-registration evidence) and evaluation; and
the formula graph wired into execution (tick-0 state, gate refusals,
template-carried formulas, Monte Carlo lever propagation). Same
scratch-SQLite + in-memory-bus + empty-LLM-keys pattern as the Sprint 1–3
tests.

The evidence-free setup is used deliberately: with no claims ingested,
every tick takes the ``monitor`` fallback (no cash effect), so final cash
equals starting cash exactly. That makes probe outcomes exactly
predictable — the tests verify the machinery, not a forecast.
"""

from __future__ import annotations

import json
import math
import statistics
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from planagent.config import reset_settings_cache
from planagent.db import reset_database_cache
from planagent.main import create_app
from planagent.services.distributions import rng_for_seed, sample_variable_set
from planagent.services.variables import evaluate_formulas
from planagent.services.variables.models import VariableSet

FIXTURES = Path(__file__).resolve().parent / "fixtures"

BOUND_SET = {
    "name": "case",
    "variables": [
        {
            "id": "cash",
            "unit": "k",
            "distribution": {"type": "triangular", "min": 60, "mode": 100, "max": 140},
            "evidence_ref": "estimate: founder judgment",
        },
        {
            "id": "pipeline",
            "unit": "x",
            "distribution": {"type": "normal", "mean": 1.0, "std": 0.1},
            "evidence_ref": "estimate: founder judgment",
        },
        {
            "id": "cac",
            "unit": "yuan",
            "distribution": {"type": "triangular", "min": 8000, "mode": 12000, "max": 20000},
            "evidence_ref": "evidence:q3-report",
        },
    ],
    "internal": {"team": "20 people"},
}


def build_database_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.resolve().as_posix()}"


def disable_openai(monkeypatch) -> None:
    monkeypatch.setenv("PLANAGENT_OPENAI_API_KEY", "")
    monkeypatch.setenv("PLANAGENT_OPENAI_BASE_URL", "")
    monkeypatch.setenv("PLANAGENT_OPENAI_PRIMARY_API_KEY", "")
    monkeypatch.setenv("PLANAGENT_OPENAI_PRIMARY_BASE_URL", "")
    monkeypatch.setenv("PLANAGENT_OPENAI_EXTRACTION_API_KEY", "")
    monkeypatch.setenv("PLANAGENT_OPENAI_EXTRACTION_BASE_URL", "")
    monkeypatch.setenv("PLANAGENT_OPENAI_REPORT_API_KEY", "")
    monkeypatch.setenv("PLANAGENT_OPENAI_REPORT_BASE_URL", "")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def setup_app(monkeypatch, tmp_path: Path, db_name: str = "planagent-robustness.db") -> None:
    monkeypatch.setenv("PLANAGENT_DATABASE_URL", build_database_url(tmp_path / db_name))
    monkeypatch.setenv("PLANAGENT_EVENT_BUS_BACKEND", "memory")
    monkeypatch.setenv("PLANAGENT_INLINE_INGEST_DEFAULT", "true")
    monkeypatch.setenv("PLANAGENT_INLINE_SIMULATION_DEFAULT", "true")
    disable_openai(monkeypatch)
    reset_settings_cache()
    reset_database_cache()


def simulation_payload(**overrides) -> dict:
    payload: dict = {
        "company_id": "robustness-test-co",
        "company_name": "Robustness Test Co",
        "market": "ai",
        "tick_count": 2,
        "seed": 7,
        "actor_template": "default",
    }
    payload.update(overrides)
    return payload


def _snapshots(client: TestClient, run_id: str) -> list[dict]:
    package = client.get(f"/runs/{run_id}/replay-package")
    assert package.status_code == 200
    return package.json()["package"]["snapshots"]


def _create_bound_run(client: TestClient, **overrides) -> dict:
    payload = simulation_payload(variable_set=BOUND_SET)
    payload.update(overrides)
    created = client.post("/simulation/runs", json=payload)
    assert created.status_code == 201, created.text
    return created.json()


def _run_ensemble(client: TestClient, run_id: str, **overrides) -> dict:
    payload: dict = {
        "trials": 10,
        "seed": 42,
        "metric": "cash",
        "loss_threshold": 90.0,
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


# ------------------------------------------------------------------ ES
def test_expected_shortfall_matches_trial_values_and_is_stored(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_bound_run(client)
        ensemble = _run_ensemble(client, run["id"], strategy_levers={"cash": 140.0})
        baseline = _trial_values(client, ensemble, "baseline")
        strategy = _trial_values(client, ensemble, "strategy")

        response = client.post(
            f"/runs/{run['id']}/robustness/expected-shortfall",
            json={"alpha": 0.1, "tail": "lower"},
        )
        assert response.status_code == 201, response.text
        result = response.json()
        assert result["ensemble_id"] == ensemble["ensemble_id"]
        assert result["metric"] == "cash"
        assert result["alpha"] == 0.1
        assert result["baseline"]["value"] == _expected_shortfall(baseline, 0.1)
        assert result["baseline"]["tail_count"] == 1
        assert result["baseline"]["n"] == 10
        assert result["strategy"]["value"] == 140.0
        deltas = [s - b for b, s in zip(baseline, strategy)]
        assert result["paired"]["value"] == _expected_shortfall(deltas, 0.1)
        assert result["trial_values_hash"].startswith("sha256:")

        # Recomputation over the same ensemble pins the same input hash.
        again = client.post(
            f"/runs/{run['id']}/robustness/expected-shortfall",
            json={"alpha": 0.1, "tail": "lower"},
        )
        assert again.json()["trial_values_hash"] == result["trial_values_hash"]

        # Upper tail: the mean of the largest values.
        upper = client.post(
            f"/runs/{run['id']}/robustness/expected-shortfall",
            json={"alpha": 0.1, "tail": "upper"},
        )
        assert upper.json()["baseline"]["value"] == max(baseline)

        stored = client.get(f"/runs/{run['id']}/robustness")
        assert stored.status_code == 200
        assert stored.json()["expected_shortfall"]["tail"] == "upper"


def test_robustness_requires_ensemble(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_bound_run(client)
        for path, payload in [
            ("/robustness/expected-shortfall", {"alpha": 0.05}),
            ("/robustness/bootstrap", {"draws": 100}),
            ("/robustness/tornado", {}),
            (
                "/robustness/threshold-search",
                {"variable": "cash", "target": 0.5, "direction": "decreasing"},
            ),
        ]:
            response = client.post(f"/runs/{run['id']}{path}", json=payload)
            assert response.status_code == 400, response.text
            assert response.json()["detail"]["code"] == "robustness_requires_ensemble"

        missing = client.post(
            "/runs/nope/robustness/bootstrap", json={"draws": 100}
        )
        assert missing.status_code == 404
        assert client.get(f"/runs/{run['id']}/robustness").status_code == 404


# ------------------------------------------------------------------ bootstrap
def test_bootstrap_intervals_sane_reproducible_and_stored(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_bound_run(client)
        ensemble = _run_ensemble(client, run["id"])
        baseline = _trial_values(client, ensemble, "baseline")

        first = client.post(
            f"/runs/{run['id']}/robustness/bootstrap",
            json={"draws": 100, "seed": 11, "level": 0.9},
        )
        assert first.status_code == 201, first.text
        result = first.json()
        assert result["ensemble_id"] == ensemble["ensemble_id"]
        assert len(result["baseline"]) == 3
        assert len(result["strategy"]) == 3
        mean_interval = next(i for i in result["baseline"] if i["statistic"] == "mean")
        assert mean_interval["estimate"] == statistics.fmean(baseline)
        assert mean_interval["low"] <= mean_interval["estimate"] <= mean_interval["high"]
        assert mean_interval["method"] == "percentile"
        assert mean_interval["draws"] == 100
        assert mean_interval["level"] == 0.9

        second = client.post(
            f"/runs/{run['id']}/robustness/bootstrap",
            json={"draws": 100, "seed": 11, "level": 0.9},
        )
        assert second.json() == result

        stored = client.get(f"/runs/{run['id']}/robustness")
        assert stored.json()["bootstrap"]["baseline"] == result["baseline"]


def test_bootstrap_default_seed_is_ensemble_seed(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_bound_run(client)
        _run_ensemble(client, run["id"])
        defaulted = client.post(
            f"/runs/{run['id']}/robustness/bootstrap", json={"draws": 100}
        )
        explicit = client.post(
            f"/runs/{run['id']}/robustness/bootstrap", json={"draws": 100, "seed": 42}
        )
        assert defaulted.json() == explicit.json()


def test_bootstrap_api_prefix(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_bound_run(client)
        _run_ensemble(client, run["id"])
        response = client.post(
            f"/api/runs/{run['id']}/robustness/bootstrap", json={"draws": 100}
        )
        assert response.status_code == 201, response.text


# ------------------------------------------------------------------ tornado
def test_tornado_ranks_cash_first_with_exact_probe_outcomes(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_bound_run(client)
        ensemble = _run_ensemble(client, run["id"])

        response = client.post(f"/runs/{run['id']}/robustness/tornado", json={})
        assert response.status_code == 201, response.text
        result = response.json()
        assert result["ensemble_id"] == ensemble["ensemble_id"]
        assert result["metric"] == "cash"
        assert len(result["probe_run_ids"]) == 7  # base + 2 per variable
        rows = result["rows"]
        assert [row["variable"] for row in rows] == ["cash", "pipeline", "cac"]
        cash_row = rows[0]
        # Triangular(60, 100, 140) P10/P90, analytically.
        assert cash_row["low_value"] == pytest.approx(77.88854382)
        assert cash_row["high_value"] == pytest.approx(122.11145618)
        assert cash_row["base_value"] == pytest.approx(100.0)
        # Evidence-free: final cash equals the frozen starting cash.
        assert cash_row["outcome_low"] == pytest.approx(cash_row["low_value"])
        assert cash_row["outcome_high"] == pytest.approx(cash_row["high_value"])
        assert cash_row["outcome_base"] == pytest.approx(100.0)
        assert cash_row["swing"] == pytest.approx(
            cash_row["high_value"] - cash_row["low_value"]
        )
        # Pipeline and cac do not move cash in the evidence-free setup.
        assert rows[1]["swing"] == 0.0
        assert rows[2]["swing"] == 0.0

        stored = client.get(f"/runs/{run['id']}/robustness")
        assert stored.json()["tornado"]["rows"] == rows


def test_tornado_subset_and_unknown_variable(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_bound_run(client)
        _run_ensemble(client, run["id"])
        subset = client.post(
            f"/runs/{run['id']}/robustness/tornado", json={"variables": ["cash"]}
        )
        assert subset.status_code == 201, subset.text
        assert [row["variable"] for row in subset.json()["rows"]] == ["cash"]
        assert len(subset.json()["probe_run_ids"]) == 3

        unknown = client.post(
            f"/runs/{run['id']}/robustness/tornado", json={"variables": ["nope"]}
        )
        assert unknown.status_code == 400
        assert unknown.json()["detail"]["code"] == "robustness_unknown_variable"


# ------------------------------------------------------------------ threshold search
def test_threshold_search_finds_cash_breakpoint(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_bound_run(client)
        _run_ensemble(client, run["id"])
        response = client.post(
            f"/runs/{run['id']}/robustness/threshold-search",
            json={
                "variable": "cash",
                "mode": "p_loss",
                "target": 0.5,
                "direction": "decreasing",
                "trials_per_evaluation": 2,
                "max_iterations": 8,
                "tolerance": 0.5,
            },
        )
        assert response.status_code == 201, response.text
        result = response.json()
        assert result["reachable"] is True
        # p_loss is a step function at the loss threshold (90): frozen cash
        # below 90 loses, above it wins. The search brackets the step.
        assert abs(result["threshold"] - 90.0) < 0.5
        assert result["achieved_statistic"] in (0.0, 1.0)
        assert result["iterations"] == 8
        assert len(result["evaluations"]) == 11
        assert result["bounds"] == [60.0, 140.0]
        assert result["loss_threshold"] == 90.0
        assert all(e["trials"] == 2 for e in result["evaluations"])
        assert all(len(e["probe_run_ids"]) == 2 for e in result["evaluations"])

        stored = client.get(f"/runs/{run['id']}/robustness")
        assert stored.json()["threshold_search"]["threshold"] == result["threshold"]


def test_threshold_search_unreachable_reports_honestly(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_bound_run(client)
        _run_ensemble(client, run["id"])
        response = client.post(
            f"/runs/{run['id']}/robustness/threshold-search",
            json={
                "variable": "cash",
                "mode": "p_loss",
                "target": 0.5,
                "direction": "decreasing",
                "bounds": [100.0, 140.0],
                "trials_per_evaluation": 2,
            },
        )
        assert response.status_code == 201, response.text
        result = response.json()
        assert result["reachable"] is False
        assert result["threshold"] is None
        assert result["achieved_statistic"] is None
        assert result["iterations"] == 0
        assert len(result["evaluations"]) == 2


def test_threshold_search_refusals(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_bound_run(client)
        _run_ensemble(client, run["id"])
        unknown = client.post(
            f"/runs/{run['id']}/robustness/threshold-search",
            json={"variable": "nope", "target": 0.5},
        )
        assert unknown.status_code == 400
        assert unknown.json()["detail"]["code"] == "robustness_unknown_variable"

        # arm_flip with a nonzero target is a shape error (422).
        bad_target = client.post(
            f"/runs/{run['id']}/robustness/threshold-search",
            json={"variable": "cash", "mode": "arm_flip", "target": 0.5},
        )
        assert bad_target.status_code == 422

        # arm_flip over a variable that cannot move the delta is honestly
        # unreachable: with levers the delta is a nonzero constant across
        # evaluations (same seeds), so the target is never bracketed.
        _run_ensemble(client, run["id"], strategy_levers={"cash": 140.0})
        unreachable = client.post(
            f"/runs/{run['id']}/robustness/threshold-search",
            json={
                "variable": "cac",
                "mode": "arm_flip",
                "target": 0.0,
                "trials_per_evaluation": 2,
                "max_iterations": 2,
            },
        )
        assert unreachable.status_code == 201, unreachable.text
        assert unreachable.json()["reachable"] is False
        assert unreachable.json()["threshold"] is None


# ------------------------------------------------------------------ decision gates
def test_gates_pre_registration_supersession_and_evaluation(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_bound_run(client)

        # Registered BEFORE any ensemble exists: pre-registration evidence.
        registered = client.post(
            f"/runs/{run['id']}/decision-gates",
            json={
                "gates": [
                    {"name": "g1_value", "metric": "mean", "operator": ">", "threshold": 0},
                    {
                        "name": "g2_tail",
                        "metric": "expected_shortfall",
                        "operator": ">",
                        "threshold": 50,
                        "alpha": 0.1,
                    },
                    {
                        "name": "g3_confidence",
                        "metric": "p_loss",
                        "operator": "<=",
                        "threshold": 0.5,
                    },
                    {
                        "name": "g4_delta",
                        "metric": "mean_delta",
                        "operator": ">",
                        "threshold": 0,
                        "arm": "paired",
                    },
                ]
            },
        )
        assert registered.status_code == 201, registered.text
        first = registered.json()
        assert first["ensemble_existed_at_registration"] is False
        assert first["ensemble_id"] is None
        assert first["status"] == "active"

        ensemble = _run_ensemble(client, run["id"], strategy_levers={"cash": 140.0})
        baseline = _trial_values(client, ensemble, "baseline")
        strategy = _trial_values(client, ensemble, "strategy")

        evaluated = client.post(f"/runs/{run['id']}/decision-gates/evaluate", json={})
        assert evaluated.status_code == 201, evaluated.text
        evaluation = evaluated.json()
        assert evaluation["registration_id"] == first["id"]
        assert evaluation["pre_registered"] is True
        outcomes = {o["name"]: o for o in evaluation["outcomes"]}
        assert outcomes["g1_value"]["observed"] == statistics.fmean(baseline)
        assert outcomes["g1_value"]["passed"] is True
        assert outcomes["g2_tail"]["observed"] == _expected_shortfall(baseline, 0.1)
        assert outcomes["g2_tail"]["alpha"] == 0.1
        assert outcomes["g3_confidence"]["observed"] == sum(
            1 for v in baseline if v < 90.0
        ) / len(baseline)
        deltas = [s - b for b, s in zip(baseline, strategy)]
        assert outcomes["g4_delta"]["observed"] == statistics.fmean(deltas)
        assert outcomes["g4_delta"]["passed"] is True
        assert evaluation["all_passed"] == all(o["passed"] for o in evaluation["outcomes"])

        # A second registration supersedes the first; both are retained.
        second = client.post(
            f"/runs/{run['id']}/decision-gates",
            json={
                "gates": [
                    {"name": "only", "metric": "mean", "operator": ">", "threshold": 0}
                ],
                "supersedes": first["id"],
            },
        )
        assert second.status_code == 201, second.text
        assert second.json()["ensemble_existed_at_registration"] is True
        assert second.json()["ensemble_id"] == ensemble["ensemble_id"]

        listing = client.get(f"/runs/{run['id']}/decision-gates")
        assert listing.status_code == 200
        registrations = {r["id"]: r for r in listing.json()["registrations"]}
        assert registrations[first["id"]]["status"] == "superseded"
        assert registrations[second.json()["id"]]["status"] == "active"
        assert len(listing.json()["evaluations"]) == 1

        # Evaluating the superseded registration still works explicitly,
        # and it is NOT pre-registered relative to this ensemble.
        again = client.post(
            f"/runs/{run['id']}/decision-gates/evaluate",
            json={"registration_id": first["id"]},
        )
        assert again.json()["pre_registered"] is True  # it predated the ensemble
        second_eval = client.post(
            f"/runs/{run['id']}/decision-gates/evaluate",
            json={"registration_id": second.json()["id"]},
        )
        assert second_eval.json()["pre_registered"] is False


def test_gate_registration_refusals(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_bound_run(client)
        _run_ensemble(client, run["id"])

        # Paired metric with an arm is a shape error (422).
        mismatched = client.post(
            f"/runs/{run['id']}/decision-gates",
            json={
                "gates": [
                    {
                        "name": "bad",
                        "metric": "mean_delta",
                        "operator": ">",
                        "threshold": 0,
                        "arm": "baseline",
                    }
                ]
            },
        )
        assert mismatched.status_code == 422

        # Superseding a registration that does not exist is refused.
        unknown_super = client.post(
            f"/runs/{run['id']}/decision-gates",
            json={
                "gates": [{"name": "g", "metric": "mean", "operator": ">", "threshold": 0}],
                "supersedes": "missing",
            },
        )
        assert unknown_super.status_code == 400
        assert unknown_super.json()["detail"]["code"] == "robustness_unknown_registration"

        # Evaluating with no registrations is refused.
        assert (
            client.post(f"/runs/{run['id']}/decision-gates/evaluate", json={}).status_code
            == 400
        )

        registered = client.post(
            f"/runs/{run['id']}/decision-gates",
            json={"gates": [{"name": "g", "metric": "mean", "operator": ">", "threshold": 0}]},
        )
        assert registered.status_code == 201
        unknown_eval = client.post(
            f"/runs/{run['id']}/decision-gates/evaluate",
            json={"registration_id": "missing"},
        )
        assert unknown_eval.status_code == 400
        assert unknown_eval.json()["detail"]["code"] == "robustness_unknown_registration"

        # Unknown run: 404 on registration and listing.
        assert (
            client.post(
                "/runs/nope/decision-gates",
                json={"gates": [{"name": "g", "metric": "mean", "operator": ">", "threshold": 0}]},
            ).status_code
            == 404
        )
        assert client.get("/runs/nope/decision-gates").status_code == 404
        empty = client.get(f"/runs/{run['id']}/decision-gates")
        assert empty.status_code == 200


# ------------------------------------------------------------------ formula graph
def _golden_set() -> dict:
    return json.loads(
        (FIXTURES / "variable_formula_golden_case.json").read_text(encoding="utf-8")
    )


def test_formulas_drive_tick_zero_state_and_audit(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        golden = _golden_set()
        created = client.post("/simulation/runs", json=simulation_payload(variable_set=golden))
        assert created.status_code == 201, created.text
        run = created.json()

        variable_set = VariableSet.model_validate(golden)
        sampled = sample_variable_set(variable_set, rng_for_seed(7))
        derived = evaluate_formulas(variable_set.formulas, sampled)
        tick_zero = _snapshots(client, run["id"])[0]["state"]
        assert tick_zero["cash"] == derived["cash"]
        assert tick_zero["pipeline"] == derived["pipeline"]

        audit = client.get(f"/runs/{run['id']}/determinism")
        assert audit.status_code == 200
        assert audit.json()["sampled_values"] == sampled
        assert audit.json()["derived_values"] == derived
        assert audit.json()["derived_applied"] == ["cash", "pipeline"]
        assert audit.json()["sampled_applied"] == []

        # An explicit initial_state override still wins over derived values.
        overridden = client.post(
            "/simulation/runs",
            json=simulation_payload(variable_set=golden, initial_state={"cash": 7.0}),
        )
        assert overridden.status_code == 201, overridden.text
        assert _snapshots(client, overridden.json()["id"])[0]["state"]["cash"] == 7.0


def test_formula_gate_refusal_writes_no_rows(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        bad_set = {
            "variables": [
                {
                    "id": "cac",
                    "unit": "yuan",
                    "distribution": {"type": "fixed", "value": 100.0},
                    "evidence_ref": "estimate: test",
                }
            ],
            "formulas": [{"output": "cash", "expression": {"ref": "missing"}}],
        }
        refused = client.post(
            "/simulation/runs", json=simulation_payload(variable_set=bad_set)
        )
        assert refused.status_code == 400, refused.text
        assert refused.json()["detail"]["code"] == "variable_validation_failed"
        issues = refused.json()["detail"]["validation"]["issues"]
        assert any(issue["kind"] == "formula_unknown_ref" for issue in issues)
        listing = client.get("/simulation/runs")
        assert listing.status_code == 200
        assert listing.json() == []


def test_variables_validate_covers_formulas(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        good = client.post("/variables/validate", json=_golden_set())
        assert good.status_code == 200
        assert good.json()["is_valid"] is True
        bad = client.post(
            "/variables/validate",
            json={
                "variables": [
                    {
                        "id": "a",
                        "unit": "x",
                        "distribution": {"type": "fixed", "value": 1.0},
                        "evidence_ref": "estimate: test",
                    }
                ],
                "formulas": [{"output": "b", "expression": {"op": "divide", "args": [1, 0]}}],
            },
        )
        assert bad.status_code == 200
        assert bad.json()["is_valid"] is False
        assert any(
            issue["kind"] == "formula_division_by_zero" for issue in bad.json()["issues"]
        )


def test_template_carried_formulas_apply_to_runs(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        created = client.post(
            "/variable-templates",
            json={
                "name": "Formula template",
                "domain_id": "corporate",
                # Full pack defaults: a template's state_fields replace the
                # pack's, so a partial list would leave a partial state.
                "state_fields": [
                    {"name": "cash", "default": 100.0},
                    {"name": "runway_weeks", "default": 52.0},
                    {"name": "infra_cost_index", "default": 1.0},
                    {"name": "delivery_velocity", "default": 1.0},
                    {"name": "brand_index", "default": 1.0},
                    {"name": "market_share", "default": 0.05},
                    {"name": "team_morale", "default": 1.0},
                    {"name": "pipeline", "default": 1.0},
                    {"name": "active_deployments", "default": 3.0},
                    {"name": "implementation_capacity", "default": 3.0},
                    {"name": "support_load", "default": 0.35},
                    {"name": "reliability_debt", "default": 0.28},
                    {"name": "gross_margin", "default": 0.62},
                    {"name": "nrr", "default": 1.02},
                    {"name": "churn_risk", "default": 0.12},
                ],
                "variables": [
                    {
                        "id": "cac",
                        "unit": "yuan",
                        "distribution": {"type": "fixed", "value": 12000.0},
                        "evidence_ref": "estimate: test",
                    }
                ],
                "formulas": [
                    {
                        "output": "cash",
                        "expression": {
                            "op": "subtract",
                            "args": [140, {"op": "divide", "args": [{"ref": "cac"}, 1000]}],
                        },
                    }
                ],
            },
        )
        assert created.status_code == 201, created.text
        template_id = created.json()["id"]

        fetched = client.get(f"/variable-templates/{template_id}")
        assert fetched.status_code == 200
        assert fetched.json()["formulas"][0]["output"] == "cash"

        run = client.post(
            "/simulation/runs",
            json=simulation_payload(variable_template_id=template_id),
        )
        assert run.status_code == 201, run.text
        assert _snapshots(client, run.json()["id"])[0]["state"]["cash"] == 128.0


def test_formulas_propagate_through_monte_carlo_levers(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        created = client.post(
            "/simulation/runs", json=simulation_payload(variable_set=_golden_set())
        )
        assert created.status_code == 201, created.text
        run = created.json()
        ensemble = _run_ensemble(
            client,
            run["id"],
            strategy_levers={"获客成本 CAC": 20000.0, "研发投入(人月)": 36.0},
        )
        # Strategy arm: cash = 140 - (20000/1000 + 36) = 84 on every trial.
        assert ensemble["strategy"]["p50"] == 84.0
        assert ensemble["strategy"]["p10"] == 84.0
        assert ensemble["strategy"]["p90"] == 84.0
        assert ensemble["baseline"]["p50"] != 84.0
