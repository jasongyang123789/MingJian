"""API tests for the Sprint 3 distribution layer (PRD deltas D4/D5).

Covers seeded sampling wired into execution (state-field application +
precedence), paired Monte Carlo (shared draws, levers, stored results,
seed reproducibility), hash-verified replay, the determinism audit
endpoint, golden-run byte-identity, and branch-level variable bindings
with decomposition-branch scope ownership. Same scratch-SQLite +
in-memory-bus + empty-LLM-keys pattern as the Sprint 1/2 tests.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from planagent.config import reset_settings_cache
from planagent.db import reset_database_cache
from planagent.main import create_app
from planagent.services.distributions import rng_for_seed, sample_variable_set
from planagent.services.simulation.downside import default_downside_variables
from planagent.services.variables.models import VariableSet

# Variables named after corporate state fields (cash, pipeline) drive the
# initial state; "cac" is sampled and recorded but matches no state field.
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

PASSING_TREE = {
    "topic": "Should we launch?",
    "root": {
        "name": "Should we launch?",
        "scope": ["demand", "cost"],
        "children": [
            {"name": "Demand", "scope": ["demand"]},
            {"name": "Cost", "scope": ["cost"]},
        ],
    },
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


def setup_app(monkeypatch, tmp_path: Path, db_name: str = "planagent-distributions.db") -> None:
    monkeypatch.setenv("PLANAGENT_DATABASE_URL", build_database_url(tmp_path / db_name))
    monkeypatch.setenv("PLANAGENT_EVENT_BUS_BACKEND", "memory")
    monkeypatch.setenv("PLANAGENT_INLINE_INGEST_DEFAULT", "true")
    monkeypatch.setenv("PLANAGENT_INLINE_SIMULATION_DEFAULT", "true")
    disable_openai(monkeypatch)
    reset_settings_cache()
    reset_database_cache()


def simulation_payload(**overrides) -> dict:
    payload: dict = {
        "company_id": "distributions-test-co",
        "company_name": "Distributions Test Co",
        "market": "ai",
        "tick_count": 2,
        "seed": 7,
        # "default" is not a pack actor template, so no actor overlay masks
        # the sampled state defaults under test.
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


def test_sampling_applies_to_initial_state_and_initial_state_wins(
    monkeypatch, tmp_path: Path
) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_bound_run(client)
        # Track C (default ON): the engine appends the canonical
        # downside variables at the END of the set, so the BOUND_SET
        # draws are byte-identical and the audit gains exactly the five
        # downturn draws. Tick-zero state is untouched (downturn
        # variables match no state field).
        combined = {
            **BOUND_SET,
            "variables": [
                *BOUND_SET["variables"],
                *[var.model_dump(mode="json") for var in default_downside_variables()],
            ],
        }
        expected = sample_variable_set(VariableSet.model_validate(combined), rng_for_seed(7))
        bound_only = sample_variable_set(
            VariableSet.model_validate(BOUND_SET), rng_for_seed(7)
        )
        assert {k: expected[k] for k in bound_only} == bound_only
        tick_zero = _snapshots(client, run["id"])[0]["state"]
        assert tick_zero["cash"] == expected["cash"]
        assert tick_zero["pipeline"] == expected["pipeline"]

        # The determinism audit records every sampled value, including
        # variables that match no state field.
        audit = client.get(f"/runs/{run['id']}/determinism")
        assert audit.status_code == 200
        assert audit.json()["sampled_values"] == expected
        assert audit.json()["sampled_applied"] == ["cash", "pipeline"]

        # An explicit initial_state override still wins over sampling.
        overridden = _create_bound_run(client, initial_state={"cash": 7.0})
        assert _snapshots(client, overridden["id"])[0]["state"]["cash"] == 7.0


def test_golden_run_same_seed_same_inputs_byte_identical(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        # Sprint 5: the hindsight-firewall cutoff enters the input hash
        # (the evidence set is a function of it), so "same inputs" must
        # pin the decision_time explicitly — the creation-time default
        # is wall-clock-dependent and two runs created at different
        # instants legitimately hash differently. With the same
        # explicit cutoff, byte-identity holds exactly as before.
        first = _create_bound_run(client, decision_time="2026-03-01T00:00:00Z")
        second = _create_bound_run(client, decision_time="2026-03-01T00:00:00Z")
        assert first["id"] != second["id"]
        assert _snapshots(client, first["id"]) == _snapshots(client, second["id"])

        first_audit = client.get(f"/runs/{first['id']}/determinism").json()
        second_audit = client.get(f"/runs/{second['id']}/determinism").json()
        assert first_audit["input_hash"] == second_audit["input_hash"]
        assert first_audit["input_hash"].startswith("sha256:")
        assert first_audit["state_hashes"] == second_audit["state_hashes"]


def test_determinism_endpoint_for_run_without_bindings(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        created = client.post("/simulation/runs", json=simulation_payload())
        assert created.status_code == 201
        run_id = created.json()["id"]
        audit = client.get(f"/runs/{run_id}/determinism")
        assert audit.status_code == 200
        body = audit.json()
        assert body["seed"] == 7
        assert body["input_hash"].startswith("sha256:")
        assert sorted(body["state_hashes"]) == ["0", "1", "2"]
        assert body["sampled_values"] == {}
        assert body["sampled_applied"] == []

        missing = client.get("/runs/does-not-exist/determinism")
        assert missing.status_code == 404


def test_replay_matches_and_reports_input_hash_match(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_bound_run(client)
        replayed = client.post(f"/runs/{run['id']}/replay")
        assert replayed.status_code == 201, replayed.text
        body = replayed.json()
        assert body["original_run_id"] == run["id"]
        assert body["replay_run_id"] != run["id"]
        assert body["match"] is True
        assert body["first_diverging_tick"] is None
        assert body["tick_count"] == 3
        assert body["input_hash_match"] is True
        assert body["original_state_hashes"] == body["replay_state_hashes"]

        # The replay run is a real run with identical snapshots.
        assert _snapshots(client, body["replay_run_id"]) == _snapshots(client, run["id"])


def test_replay_requires_completed_run(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        queued = client.post(
            "/simulation/runs",
            json=simulation_payload(execution_mode="QUEUED"),
        )
        assert queued.status_code == 201
        replayed = client.post(f"/runs/{queued.json()['id']}/replay")
        assert replayed.status_code == 400
        assert replayed.json()["detail"]["code"] == "replay_requires_completed_run"

        missing = client.post("/runs/does-not-exist/replay")
        assert missing.status_code == 404


def test_monte_carlo_refusals(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        queued = client.post("/simulation/runs", json=simulation_payload(execution_mode="QUEUED"))
        assert queued.status_code == 201
        refused = client.post(
            f"/runs/{queued.json()['id']}/monte-carlo",
            json={"trials": 5, "metric": "cash"},
        )
        assert refused.status_code == 400
        assert refused.json()["detail"]["code"] == "monte_carlo_requires_completed_run"

        plain = client.post("/simulation/runs", json=simulation_payload())
        assert plain.status_code == 201
        refused = client.post(
            f"/runs/{plain.json()['id']}/monte-carlo", json={"trials": 5, "metric": "cash"}
        )
        assert refused.status_code == 400
        assert refused.json()["detail"]["code"] == "monte_carlo_requires_bindings"

        bound = _create_bound_run(client)
        refused = client.post(
            f"/runs/{bound['id']}/monte-carlo", json={"trials": 5, "metric": "nope"}
        )
        assert refused.status_code == 400
        assert refused.json()["detail"]["code"] == "monte_carlo_unknown_metric"

        refused = client.post(
            f"/runs/{bound['id']}/monte-carlo",
            json={"trials": 5, "metric": "cash", "strategy_levers": {"nope": 1.0}},
        )
        assert refused.status_code == 400
        assert refused.json()["detail"]["code"] == "monte_carlo_unknown_lever"

        invalid = client.post(
            f"/runs/{bound['id']}/monte-carlo", json={"trials": 0, "metric": "cash"}
        )
        assert invalid.status_code == 422
        invalid = client.post(
            f"/runs/{bound['id']}/monte-carlo", json={"trials": 201, "metric": "cash"}
        )
        assert invalid.status_code == 422

        missing = client.post(
            "/runs/does-not-exist/monte-carlo", json={"trials": 5, "metric": "cash"}
        )
        assert missing.status_code == 404


def test_monte_carlo_distributions_pairing_and_storage(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_bound_run(client)
        response = client.post(
            f"/runs/{run['id']}/monte-carlo",
            json={
                "trials": 8,
                "seed": 11,
                "metric": "cash",
                "strategy_levers": {"pipeline": 1.0},
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["base_run_id"] == run["id"]
        assert body["trials"] == 8
        assert body["seed"] == 11
        assert body["metric"] == "cash"
        assert body["strategy_levers"] == {"pipeline": 1.0}
        for arm in ("baseline", "strategy"):
            summary = body[arm]
            assert summary["n"] == 8
            assert summary["p10"] <= summary["p50"] <= summary["p90"]
            assert summary["min"] <= summary["p10"]
            assert summary["max"] >= summary["p90"]
            assert 0.0 <= summary["p_loss"] <= 1.0
        assert body["paired"]["n"] == 8
        assert len(body["trial_run_ids"]["baseline"]) == 8
        assert len(body["trial_run_ids"]["strategy"]) == 8

        # Paired draws: same trial index shares the non-levered draws, and
        # levered variables take the lever value on the strategy arm.
        for index in range(8):
            baseline_audit = client.get(
                f"/runs/{body['trial_run_ids']['baseline'][index]}/determinism"
            ).json()
            strategy_audit = client.get(
                f"/runs/{body['trial_run_ids']['strategy'][index]}/determinism"
            ).json()
            assert (
                baseline_audit["sampled_values"]["cash"] == strategy_audit["sampled_values"]["cash"]
            )
            assert (
                baseline_audit["sampled_values"]["cac"] == strategy_audit["sampled_values"]["cac"]
            )
            assert strategy_audit["sampled_values"]["pipeline"] == 1.0

        # Results are stored on the base run and retrievable.
        stored = client.get(f"/runs/{run['id']}/monte-carlo")
        assert stored.status_code == 200
        assert stored.json() == body

        prefixed = client.get(f"/api/runs/{run['id']}/monte-carlo")
        assert prefixed.status_code == 200
        assert prefixed.json()["ensemble_id"] == body["ensemble_id"]


def test_monte_carlo_acme_baseline_p50_is_pinned(monkeypatch, tmp_path: Path) -> None:
    """Backward-compatibility pin (Phase 2, Track 3): the BOUND_SET Acme
    baseline Monte Carlo (trials 5, seed 42, metric cash) must keep
    P50 exactly 99.8143 — the default-independent sampler path may not
    change the draw stream. Any change to the sampler, draw order, or
    RNG breaks this on purpose."""

    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_bound_run(client)
        response = client.post(
            f"/runs/{run['id']}/monte-carlo",
            json={"trials": 5, "seed": 42, "metric": "cash"},
        )
        assert response.status_code == 201, response.text
        assert response.json()["baseline"]["p50"] == 99.8143


def test_monte_carlo_same_seed_reproduces_identical_results(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_bound_run(client)
        payload = {"trials": 6, "seed": 3, "metric": "cash"}
        first = client.post(f"/runs/{run['id']}/monte-carlo", json=payload)
        second = client.post(f"/runs/{run['id']}/monte-carlo", json=payload)
        assert first.status_code == 201
        assert second.status_code == 201
        # Different ensemble ids and trial rows, identical distributions:
        # trial seeds derive from the requested seed only.
        assert first.json()["ensemble_id"] != second.json()["ensemble_id"]
        assert first.json()["baseline"] == second.json()["baseline"]
        assert first.json()["strategy"] == second.json()["strategy"]
        assert first.json()["paired"] == second.json()["paired"]


def test_branch_variable_override_merges_over_inherited_bindings(
    monkeypatch, tmp_path: Path
) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        baseline = _create_bound_run(client, tick_count=4)
        branch = client.post(
            f"/scenario/runs/{baseline['id']}",
            json={
                "fork_step": 2,
                "variable_set": {
                    "name": "branch",
                    "variables": [
                        {
                            "id": "cash",
                            "unit": "k",
                            "distribution": {"type": "fixed", "value": 55.0},
                            "evidence_ref": "estimate: branch judgment",
                        }
                    ],
                },
            },
        )
        assert branch.status_code == 201, branch.text
        child_run_id = branch.json()["run_id"]
        variables = client.get(f"/runs/{child_run_id}/variables")
        assert variables.status_code == 200
        bindings = {var["id"]: var for var in variables.json()["bindings"]["variables"]}
        # The override wins for cash; the other inherited variables stay —
        # including the canonical downside variables the default (Track C)
        # appended to the parent's bindings.
        cash_distribution = bindings["cash"]["distribution"]
        assert cash_distribution["type"] == "fixed"
        assert cash_distribution["value"] == 55.0
        assert set(bindings) == {
            "cash",
            "pipeline",
            "cac",
            "downturn_occurs",
            "downturn_depth",
            "downturn_start",
            "downturn_duration",
            "downturn_persistent",
        }


def test_branch_override_invalid_refused_with_nothing_created(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        baseline = _create_bound_run(client, tick_count=4)
        refused = client.post(
            f"/scenario/runs/{baseline['id']}",
            json={
                "fork_step": 2,
                "variable_set": {
                    "name": "branch",
                    "variables": [
                        {
                            "id": "cash",
                            "unit": "k",
                            "distribution": {
                                "type": "triangular",
                                "min": 140,
                                "mode": 100,
                                "max": 60,
                            },
                            "evidence_ref": "estimate: branch judgment",
                        }
                    ],
                },
            },
        )
        assert refused.status_code == 400
        detail = refused.json()["detail"]
        assert detail["code"] == "variable_validation_failed"
        assert detail["validation"]["issues"][0]["kind"] == "invalid_bounds"

        compare = client.get(f"/runs/{baseline['id']}/scenario-compare")
        assert compare.status_code == 200
        assert compare.json()["branch_count"] == 0

        unknown_template = client.post(
            f"/scenario/runs/{baseline['id']}",
            json={"fork_step": 2, "variable_template_id": "no-such-template"},
        )
        assert unknown_template.status_code == 400
        assert unknown_template.json()["detail"]["code"] == "variable_template_not_found"


def test_branch_decomposition_scope_ownership(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        # A stored template carrying only demand-scoped variables.
        created = client.post(
            "/variable-templates",
            json={
                "name": "Demand only",
                "domain_id": "corporate",
                "variables": [
                    {
                        "id": "pipeline",
                        "unit": "x",
                        "distribution": {
                            "type": "normal",
                            "mean": 1.0,
                            "std": 0.1,
                        },
                        "evidence_ref": "estimate: test",
                        "scope_tags": ["demand"],
                    }
                ],
            },
        )
        assert created.status_code == 201
        template_id = created.json()["id"]

        baseline = _create_bound_run(
            client,
            tick_count=4,
            decomposition=PASSING_TREE,
        )
        # The template's variables fit the Demand branch scope.
        # Track C: the branch replaces the parent's bindings with the
        # template-only set, so the engine fills the missing canonical
        # downside variables for the inherited default shock — the
        # branch still succeeds (it used to fail loudly with an unbound
        # downside variable before the branch fill was added).
        branch = client.post(
            f"/scenario/runs/{baseline['id']}",
            json={
                "fork_step": 2,
                "variable_template_id": template_id,
                "decomposition_branch": "Should we launch? / Demand",
            },
        )
        assert branch.status_code == 201, branch.text

        # A tag outside the named branch scope refuses the branch: the
        # inherited cost-tagged binding does not fit the Demand branch.
        scoped_set = {
            "name": "scoped",
            "variables": [
                {
                    "id": "cost_driver",
                    "unit": "k",
                    "distribution": {"type": "fixed", "value": 3.0},
                    "evidence_ref": "estimate: test",
                    "scope_tags": ["cost"],
                }
            ],
        }
        refused = client.post(
            f"/scenario/runs/{baseline['id']}",
            json={
                "fork_step": 2,
                "variable_set": scoped_set,
                "decomposition_branch": "Should we launch? / Demand",
            },
        )
        assert refused.status_code == 400
        detail = refused.json()["detail"]
        assert detail["code"] == "variable_validation_failed"
        assert any(
            issue["kind"] == "scope_tag_outside_decomposition"
            for issue in detail["validation"]["issues"]
        )

        # An unknown branch path refuses the branch.
        refused = client.post(
            f"/scenario/runs/{baseline['id']}",
            json={"fork_step": 2, "decomposition_branch": "Should we launch? / Nope"},
        )
        assert refused.status_code == 400

        # A branch path without a parent decomposition refuses the branch.
        plain = _create_bound_run(client, tick_count=4)
        refused = client.post(
            f"/scenario/runs/{plain['id']}",
            json={"fork_step": 2, "decomposition_branch": "Should we launch? / Demand"},
        )
        assert refused.status_code == 400


def test_api_prefix_serves_new_endpoints(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_bound_run(client)
        prefixed = client.get(f"/api/runs/{run['id']}/determinism")
        assert prefixed.status_code == 200
        assert prefixed.json()["run_id"] == run["id"]
        replayed = client.post(f"/api/runs/{run['id']}/replay")
        assert replayed.status_code == 201
        assert replayed.json()["match"] is True
