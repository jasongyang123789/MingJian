"""API tests for the Sprint 9 living-strategy loop (monitor -> re-simulate).

Covers the full walkthrough on stored data (baseline -> observations ->
trigger firing -> re-simulation with an advanced firewall cutoff ->
distribution-vs-distribution comparison -> recorded decision), a
quiet-round case decided without re-simulation, refused re-simulations
that write zero rows, the iteration state machine, append-only trigger
registration, and honest 400/404 errors.

Same scratch-SQLite + in-memory-bus + empty-LLM-keys pattern as the
Sprint 1-8 tests. The evidence-free setup is deliberate: with no
claims ingested, every tick takes the ``monitor`` fallback, so final
cash equals the sampled starting cash exactly. The baseline and
re-simulation ensembles therefore agree exactly (same bindings, same
ensemble seed, no new evidence) — the tests verify the loop machinery
and its audit trail, not a forecast.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from planagent.config import reset_settings_cache
from planagent.db import reset_database_cache
from planagent.main import create_app

BOUND_SET = {
    "name": "case",
    "variables": [
        {
            "id": "cash",
            "unit": "k",
            "distribution": {"type": "triangular", "min": 60, "mode": 100, "max": 140},
            "evidence_ref": "estimate: founder judgment",
        },
    ],
    "internal": {"team": "20 people"},
}

BASELINE_CUTOFF = "2026-01-01T00:00:00Z"
REVIEW_TIME = "2026-02-01T00:00:00Z"

TRIGGERS = [
    {
        "kind": "threshold",
        "name": "cash-floor",
        "field": "cash",
        "operator": "<",
        "threshold": 70.0,
    },
    {
        "kind": "gate",
        "name": "cash-mean",
        "field": "cash",
        "gate": {
            "name": "cash-mean-gate",
            "metric": "mean",
            "arm": "baseline",
            "operator": "<",
            "threshold": 90.0,
        },
    },
    {
        "kind": "deviation",
        "name": "cash-drift",
        "field": "cash",
        "reference_value": 100.0,
        "tolerance": 20.0,
        "consecutive": 2,
    },
]


def _same_instant(left: str, right: str) -> bool:
    """Compare canonical timestamps as instants (format_cutoff emits
    microseconds; test constants do not)."""

    def parse(value: str) -> datetime:
        return datetime.fromisoformat(value)

    return parse(left) == parse(right)


def build_database_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.resolve().as_posix()}"


def setup_app(monkeypatch, tmp_path: Path, db_name: str = "planagent-loops.db") -> None:
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


def _create_baseline_run(client: TestClient, **overrides) -> dict:
    payload: dict = {
        "company_id": "loop-test-co",
        "company_name": "Loop Test Co",
        "market": "ai",
        "tick_count": 2,
        "seed": 7,
        "actor_template": "default",
        "variable_set": BOUND_SET,
        "decision_time": BASELINE_CUTOFF,
    }
    payload.update(overrides)
    created = client.post("/simulation/runs", json=payload)
    assert created.status_code == 201, created.text
    run = created.json()
    assert run["status"] == "COMPLETED"
    return run


def _create_loop(client: TestClient, run_id: str, **overrides) -> dict:
    payload: dict = {"name": "AI service line", "baseline_run_id": run_id, "triggers": TRIGGERS}
    payload.update(overrides)
    response = client.post("/loops", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _record_observation(client: TestClient, loop_id: str, value: float, observed_at: str) -> dict:
    response = client.post(
        f"/loops/{loop_id}/observations",
        json={"field": "cash", "value": value, "observed_at": observed_at},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _run_ensemble(client: TestClient, run_id: str) -> dict:
    response = client.post(
        f"/runs/{run_id}/monte-carlo",
        json={"trials": 10, "seed": 42, "metric": "cash", "loss_threshold": 90.0},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _run_count(client: TestClient) -> int:
    response = client.get("/simulation/runs")
    assert response.status_code == 200, response.text
    return len(response.json())


# ------------------------------------------------------------- walkthrough


def test_full_loop_walkthrough(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        baseline = _create_baseline_run(client)
        loop = _create_loop(client, baseline["id"])
        assert loop["domain_id"] == "corporate"
        assert len(loop["triggers"]) == 1
        registration = loop["triggers"][0]
        assert registration["status"] == "active"
        assert registration["observation_count_at_registration"] == 0
        assert [item["name"] for item in registration["triggers"]] == [
            "cash-floor",
            "cash-mean",
            "cash-drift",
        ]

        baseline_ensemble = _run_ensemble(client, baseline["id"])

        obs1 = _record_observation(client, loop["id"], 95.0, "2026-01-10T00:00:00Z")
        obs2 = _record_observation(client, loop["id"], 65.0, "2026-01-20T00:00:00Z")
        obs3 = _record_observation(client, loop["id"], 60.0, "2026-01-25T00:00:00Z")

        started = client.post(
            f"/loops/{loop['id']}/iterations",
            json={"decision_time": REVIEW_TIME},
        )
        assert started.status_code == 201, started.text
        iteration = started.json()
        assert iteration["index"] == 0
        assert iteration["state"] == "open"
        assert _same_instant(iteration["previous_cutoff"], BASELINE_CUTOFF)
        assert _same_instant(iteration["decision_time"], REVIEW_TIME)

        evaluated = client.post(f"/loops/{loop['id']}/iterations/{iteration['id']}/evaluate")
        assert evaluated.status_code == 200, evaluated.text
        iteration = evaluated.json()
        assert iteration["state"] == "evaluated"
        assert _same_instant(iteration["window_from"], BASELINE_CUTOFF)
        assert _same_instant(iteration["window_to"], REVIEW_TIME)
        assert iteration["observation_ids"] == [obs1["id"], obs2["id"], obs3["id"]]
        outcomes = {item["name"]: item for item in iteration["trigger_evaluations"]}
        assert outcomes["cash-floor"]["fired"] is True
        assert outcomes["cash-floor"]["observed_value"] == 60.0  # latest in window
        assert outcomes["cash-mean"]["fired"] is True
        assert outcomes["cash-mean"]["observed_value"] == (95.0 + 65.0 + 60.0) / 3
        assert outcomes["cash-drift"]["fired"] is True
        assert outcomes["cash-drift"]["observed_value"] == 40.0  # |60 - 100| deviation
        assert outcomes["cash-drift"]["reference_value"] == 100.0
        assert outcomes["cash-drift"]["consecutive_breaches"] == 2

        resimulated = client.post(
            f"/loops/{loop['id']}/iterations/{iteration['id']}/resimulate", json={}
        )
        assert resimulated.status_code == 200, resimulated.text
        iteration = resimulated.json()
        assert iteration["state"] == "resimulated"
        resim = iteration["resimulation"]
        assert resim["run_id"] != baseline["id"]
        assert _same_instant(resim["previous_cutoff"], BASELINE_CUTOFF)
        assert _same_instant(resim["new_cutoff"], REVIEW_TIME)
        assert resim["previous_input_hash"] != resim["new_input_hash"]
        assert resim["previous_input_hash"].startswith("sha256:")
        assert resim["changes"] == {}
        assert resim["claims_visible"] == 0
        assert resim["claims_excluded"] == 0

        # The new run's own firewall audit agrees: its cutoff is the
        # review time, and its configuration carries the new cutoff.
        audit = client.get(f"/runs/{resim['run_id']}/firewall")
        assert audit.status_code == 200, audit.text
        assert _same_instant(audit.json()["decision_time"], REVIEW_TIME)
        assert audit.json()["cutoff_source"] == "explicit"

        new_ensemble = _run_ensemble(client, resim["run_id"])
        compared = client.post(f"/loops/{loop['id']}/iterations/{iteration['id']}/compare")
        assert compared.status_code == 200, compared.text
        iteration = compared.json()
        assert iteration["state"] == "compared"
        comparison = iteration["comparison"]
        assert comparison["baseline_ensemble_id"] == baseline_ensemble["ensemble_id"]
        assert comparison["new_ensemble_id"] == new_ensemble["ensemble_id"]
        assert comparison["seeds_paired"] is True
        assert comparison["same_seed"] is True
        assert comparison["same_trials"] is True
        assert comparison["evidence_caveat"] is not None
        assert "evidence" in comparison["evidence_caveat"]
        # Same bindings, same ensemble seed, no new evidence: the two
        # distributions agree exactly. That is the honest result.
        for arm_key in ("baseline_arm", "strategy_arm"):
            arm = comparison[arm_key]
            assert arm["delta_p10"] == 0.0
            assert arm["delta_p50"] == 0.0
            assert arm["delta_p90"] == 0.0
            assert arm["delta_p_loss"] == 0.0
        assert comparison["gate_reevaluation"] is None
        assert comparison["threshold_drift"] == []

        decided = client.post(
            f"/loops/{loop['id']}/iterations/{iteration['id']}/decide",
            json={"decision": "continue", "rationale": "Distributions unchanged; hold course."},
        )
        assert decided.status_code == 200, decided.text
        iteration = decided.json()
        assert iteration["state"] == "decided"
        assert iteration["decision"]["decision"] == "continue"
        assert iteration["decision"]["rationale"].startswith("Distributions unchanged")

        timeline = client.get(f"/loops/{loop['id']}/timeline")
        assert timeline.status_code == 200, timeline.text
        body = timeline.json()
        assert body["loop"]["id"] == loop["id"]
        assert len(body["observations"]) == 3
        assert len(body["iterations"]) == 1
        assert body["iterations"][0]["state"] == "decided"

        # The next review starts from the previous review's cutoff.
        second = client.post(
            f"/loops/{loop['id']}/iterations",
            json={"decision_time": "2026-03-01T00:00:00Z"},
        )
        assert second.status_code == 201, second.text
        assert second.json()["index"] == 1
        assert _same_instant(second.json()["previous_cutoff"], REVIEW_TIME)


def test_quiet_round_decided_without_resimulation(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        baseline = _create_baseline_run(client)
        loop = _create_loop(client, baseline["id"], triggers=[TRIGGERS[0]])
        _record_observation(client, loop["id"], 95.0, "2026-01-10T00:00:00Z")
        _record_observation(client, loop["id"], 92.0, "2026-01-20T00:00:00Z")
        started = client.post(
            f"/loops/{loop['id']}/iterations", json={"decision_time": REVIEW_TIME}
        )
        iteration_id = started.json()["id"]

        evaluated = client.post(f"/loops/{loop['id']}/iterations/{iteration_id}/evaluate")
        assert evaluated.status_code == 200, evaluated.text
        outcomes = evaluated.json()["trigger_evaluations"]
        assert len(outcomes) == 1
        assert outcomes[0]["fired"] is False
        assert outcomes[0]["observed_value"] == 92.0
        assert len(outcomes[0]["observation_ids"]) == 2

        # A quiet round needs no re-simulation: decide straight from
        # "evaluated". The quiet evaluation stays on the record.
        decided = client.post(
            f"/loops/{loop['id']}/iterations/{iteration_id}/decide",
            json={"decision": "continue", "rationale": "No trigger fired; no re-run needed."},
        )
        assert decided.status_code == 200, decided.text
        assert decided.json()["state"] == "decided"
        assert decided.json()["resimulation"] is None
        assert decided.json()["comparison"] is None


def test_resimulation_with_explicit_changes_is_recorded(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        baseline = _create_baseline_run(client)
        loop = _create_loop(client, baseline["id"], triggers=[TRIGGERS[0]])
        _record_observation(client, loop["id"], 60.0, "2026-01-10T00:00:00Z")
        started = client.post(
            f"/loops/{loop['id']}/iterations", json={"decision_time": REVIEW_TIME}
        )
        iteration_id = started.json()["id"]
        client.post(f"/loops/{loop['id']}/iterations/{iteration_id}/evaluate")

        resimulated = client.post(
            f"/loops/{loop['id']}/iterations/{iteration_id}/resimulate",
            json={"seed": 99, "tick_count": 3, "note": "Reviewer asked for a longer horizon."},
        )
        assert resimulated.status_code == 200, resimulated.text
        resim = resimulated.json()["resimulation"]
        assert resim["seed"] == 99
        assert resim["tick_count"] == 3
        assert resim["changes"]["seed"] == {"from": 7, "to": 99}
        assert resim["changes"]["tick_count"] == {"from": 2, "to": 3}
        assert resim["changes"]["note"] == "Reviewer asked for a longer horizon."


# ------------------------------------------------------- refused re-simulation


def test_refused_resimulation_writes_zero_rows_and_leaves_iteration_untouched(
    monkeypatch, tmp_path
) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        baseline = _create_baseline_run(client)
        loop = _create_loop(client, baseline["id"], triggers=[TRIGGERS[0]])
        _record_observation(client, loop["id"], 60.0, "2026-01-10T00:00:00Z")
        started = client.post(
            f"/loops/{loop['id']}/iterations", json={"decision_time": REVIEW_TIME}
        )
        iteration_id = started.json()["id"]
        client.post(f"/loops/{loop['id']}/iterations/{iteration_id}/evaluate")
        runs_before = _run_count(client)

        # An invalid override (triangular min above mode) must be
        # refused by the same variable gate that guards hand-created
        # runs — before any row is written.
        refused = client.post(
            f"/loops/{loop['id']}/iterations/{iteration_id}/resimulate",
            json={
                "variable_set": {
                    "name": "bad",
                    "variables": [
                        {
                            "id": "cash",
                            "unit": "k",
                            "distribution": {
                                "type": "triangular",
                                "min": 140,
                                "mode": 100,
                                "max": 140,
                            },
                            "evidence_ref": "estimate: bad",
                        }
                    ],
                }
            },
        )
        assert refused.status_code == 400, refused.text
        assert refused.json()["detail"]["code"] == "variable_validation_failed"
        assert _run_count(client) == runs_before

        iteration = client.get(f"/loops/{loop['id']}/iterations/{iteration_id}").json()
        assert iteration["state"] == "evaluated"
        assert iteration["resimulation"] is None

        # An unknown template id is refused the same way.
        refused_template = client.post(
            f"/loops/{loop['id']}/iterations/{iteration_id}/resimulate",
            json={"variable_template_id": "template:does-not-exist"},
        )
        assert refused_template.status_code == 400, refused_template.text
        assert refused_template.json()["detail"]["code"] == "variable_template_not_found"
        assert _run_count(client) == runs_before

        # The iteration is still usable: a valid re-simulation succeeds.
        resimulated = client.post(
            f"/loops/{loop['id']}/iterations/{iteration_id}/resimulate", json={}
        )
        assert resimulated.status_code == 200, resimulated.text
        assert resimulated.json()["state"] == "resimulated"


# ------------------------------------------------------------ state machine


def test_iteration_state_machine_refusals(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        baseline = _create_baseline_run(client)
        loop = _create_loop(client, baseline["id"], triggers=[])
        started = client.post(
            f"/loops/{loop['id']}/iterations", json={"decision_time": REVIEW_TIME}
        )
        iteration_id = started.json()["id"]

        # No triggers registered: evaluation refuses, naming the gap.
        evaluated = client.post(f"/loops/{loop['id']}/iterations/{iteration_id}/evaluate")
        assert evaluated.status_code == 400, evaluated.text
        assert evaluated.json()["detail"]["code"] == "loop_no_triggers"

        # Out-of-order actions refuse with the current state named.
        resimulated = client.post(
            f"/loops/{loop['id']}/iterations/{iteration_id}/resimulate", json={}
        )
        assert resimulated.status_code == 400
        assert resimulated.json()["detail"]["code"] == "loop_invalid_state"
        compared = client.post(f"/loops/{loop['id']}/iterations/{iteration_id}/compare")
        assert compared.status_code == 400
        assert compared.json()["detail"]["code"] == "loop_invalid_state"
        decided = client.post(
            f"/loops/{loop['id']}/iterations/{iteration_id}/decide",
            json={"decision": "continue", "rationale": "too early"},
        )
        assert decided.status_code == 400
        assert decided.json()["detail"]["code"] == "loop_invalid_state"

        # Only one open iteration per loop.
        second = client.post(
            f"/loops/{loop['id']}/iterations",
            json={"decision_time": "2026-03-01T00:00:00Z"},
        )
        assert second.status_code == 400, second.text
        assert second.json()["detail"]["code"] == "loop_iteration_in_progress"

        # Register triggers, evaluate, then evaluate again: refused.
        registered = client.post(f"/loops/{loop['id']}/triggers", json={"triggers": [TRIGGERS[0]]})
        assert registered.status_code == 201, registered.text
        evaluated = client.post(f"/loops/{loop['id']}/iterations/{iteration_id}/evaluate")
        assert evaluated.status_code == 200, evaluated.text
        evaluated_again = client.post(f"/loops/{loop['id']}/iterations/{iteration_id}/evaluate")
        assert evaluated_again.status_code == 400
        assert evaluated_again.json()["detail"]["code"] == "loop_invalid_state"

        # Decide, then decide again: decided is terminal.
        decided = client.post(
            f"/loops/{loop['id']}/iterations/{iteration_id}/decide",
            json={"decision": "pause", "rationale": "no data in window"},
        )
        assert decided.status_code == 200, decided.text
        decided_again = client.post(
            f"/loops/{loop['id']}/iterations/{iteration_id}/decide",
            json={"decision": "stop", "rationale": "change of mind"},
        )
        assert decided_again.status_code == 400
        assert decided_again.json()["detail"]["code"] == "loop_invalid_state"


def test_decision_time_must_advance_the_cutoff(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        baseline = _create_baseline_run(client)
        loop = _create_loop(client, baseline["id"], triggers=[TRIGGERS[0]])

        # Equal to the baseline cutoff: refused.
        refused = client.post(
            f"/loops/{loop['id']}/iterations", json={"decision_time": BASELINE_CUTOFF}
        )
        assert refused.status_code == 400, refused.text
        assert refused.json()["detail"]["code"] == "loop_cutoff_must_advance"
        # Before the baseline cutoff: refused.
        refused = client.post(
            f"/loops/{loop['id']}/iterations",
            json={"decision_time": "2025-12-01T00:00:00Z"},
        )
        assert refused.status_code == 400
        assert refused.json()["detail"]["code"] == "loop_cutoff_must_advance"


def test_compare_requires_both_ensembles(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        baseline = _create_baseline_run(client)
        loop = _create_loop(client, baseline["id"], triggers=[TRIGGERS[0]])
        _record_observation(client, loop["id"], 60.0, "2026-01-10T00:00:00Z")
        started = client.post(
            f"/loops/{loop['id']}/iterations", json={"decision_time": REVIEW_TIME}
        )
        iteration_id = started.json()["id"]
        client.post(f"/loops/{loop['id']}/iterations/{iteration_id}/evaluate")
        resimulated = client.post(
            f"/loops/{loop['id']}/iterations/{iteration_id}/resimulate", json={}
        )
        assert resimulated.status_code == 200, resimulated.text

        # No baseline ensemble yet.
        compared = client.post(f"/loops/{loop['id']}/iterations/{iteration_id}/compare")
        assert compared.status_code == 400, compared.text
        assert compared.json()["detail"]["code"] == "loop_requires_baseline_ensemble"

        _run_ensemble(client, baseline["id"])

        # Baseline ensemble exists; re-simulation ensemble does not.
        compared = client.post(f"/loops/{loop['id']}/iterations/{iteration_id}/compare")
        assert compared.status_code == 400, compared.text
        assert compared.json()["detail"]["code"] == "loop_requires_resimulation_ensemble"


# ------------------------------------------------------------ registration


def test_trigger_registration_append_only_with_supersede(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        baseline = _create_baseline_run(client)
        loop = _create_loop(client, baseline["id"], triggers=[TRIGGERS[0]])
        first_id = loop["triggers"][0]["id"]
        _record_observation(client, loop["id"], 95.0, "2026-01-10T00:00:00Z")

        second = client.post(
            f"/loops/{loop['id']}/triggers",
            json={"triggers": [TRIGGERS[1]], "supersedes": first_id},
        )
        assert second.status_code == 201, second.text
        assert second.json()["supersedes"] == first_id
        # The pre-registration evidence counts observations visible at
        # registration time: one observation already recorded.
        assert second.json()["observation_count_at_registration"] == 1

        fetched = client.get(f"/loops/{loop['id']}").json()
        assert len(fetched["triggers"]) == 2
        assert fetched["triggers"][0]["status"] == "superseded"
        assert fetched["triggers"][1]["status"] == "active"

        unknown = client.post(
            f"/loops/{loop['id']}/triggers",
            json={"triggers": [TRIGGERS[0]], "supersedes": "registration:missing"},
        )
        assert unknown.status_code == 400, unknown.text
        assert unknown.json()["detail"]["code"] == "loop_unknown_registration"


# ------------------------------------------------------------ honest errors


def test_loop_creation_rejects_unknown_and_derived_runs(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        missing = client.post("/loops", json={"name": "x", "baseline_run_id": "run:missing"})
        assert missing.status_code == 404, missing.text

        baseline = _create_baseline_run(client)
        ensemble = _run_ensemble(client, baseline["id"])
        trial_id = ensemble["trial_run_ids"]["baseline"][0]
        derived = client.post("/loops", json={"name": "x", "baseline_run_id": trial_id})
        assert derived.status_code == 400, derived.text
        assert derived.json()["detail"]["code"] == "loop_derived_run_excluded"


def test_loop_endpoints_404_on_unknown_ids(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        assert client.get("/loops/loop:missing").status_code == 404
        assert client.get("/loops/loop:missing/timeline").status_code == 404
        assert (
            client.post(
                "/loops/loop:missing/observations",
                json={"field": "cash", "value": 1.0, "observed_at": REVIEW_TIME},
            ).status_code
            == 404
        )
        baseline = _create_baseline_run(client)
        loop = _create_loop(client, baseline["id"], triggers=[])
        assert client.get(f"/loops/{loop['id']}/iterations/iteration:missing").status_code == 404


def test_observations_and_triggers_validate_fields(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        baseline = _create_baseline_run(client)
        loop = _create_loop(client, baseline["id"], triggers=[])

        bad_observation = client.post(
            f"/loops/{loop['id']}/observations",
            json={"field": "not_a_state_field", "value": 1.0, "observed_at": REVIEW_TIME},
        )
        assert bad_observation.status_code == 400, bad_observation.text
        assert bad_observation.json()["detail"]["code"] == "loop_unknown_field"

        bad_claim = client.post(
            f"/loops/{loop['id']}/observations",
            json={
                "field": "cash",
                "value": 1.0,
                "observed_at": REVIEW_TIME,
                "source_claim_id": "claim:missing",
            },
        )
        assert bad_claim.status_code == 400, bad_claim.text
        assert bad_claim.json()["detail"]["code"] == "loop_unknown_claim"

        bad_trigger = client.post(
            "/loops",
            json={
                "name": "x",
                "baseline_run_id": baseline["id"],
                "triggers": [
                    {
                        "kind": "threshold",
                        "name": "bad",
                        "field": "not_a_state_field",
                        "operator": "<",
                        "threshold": 1.0,
                    }
                ],
            },
        )
        assert bad_trigger.status_code == 400, bad_trigger.text
        assert bad_trigger.json()["detail"]["code"] == "loop_unknown_field"


def test_list_loops(monkeypatch, tmp_path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        baseline = _create_baseline_run(client)
        _create_loop(client, baseline["id"], name="loop one", triggers=[])
        _create_loop(client, baseline["id"], name="loop two", triggers=[])
        listed = client.get("/loops")
        assert listed.status_code == 200, listed.text
        names = {item["name"] for item in listed.json()}
        assert names == {"loop one", "loop two"}
