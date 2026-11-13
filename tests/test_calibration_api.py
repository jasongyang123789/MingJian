"""API tests for Sprint 5 calibration loop + hindsight firewall (PRD D8).

Covers the decision-time evidence cutoff (exclusion, inclusive
boundary, creation-time default, replay honoring the cutoff, legacy
no-fragment runs, cutoff inside the input hash), the firewall audit
endpoint, policy-threshold fits (new template version, prior untouched,
shrinkage, determinism, builtin source, error cases), and rule-weight
fits (association fit, unmatched rules keep priors, explicit apply with
application events, error cases). Same scratch-SQLite + in-memory-bus +
empty-LLM-keys pattern as the Sprint 1–4 tests.

The evidence-free setup is used deliberately for the policy fits: with
no claims ingested, every tick takes the ``monitor`` fallback (no cash
effect), so final cash equals starting cash exactly and the fitted
thresholds are exactly predictable — the tests verify the machinery,
not a forecast.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from planagent.config import reset_settings_cache
from planagent.db import get_database, reset_database_cache
from planagent.domain.models import Claim, EvidenceItem, SimulationRun
from planagent.main import create_app


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


def setup_app(monkeypatch, tmp_path: Path, db_name: str = "planagent-calibration.db") -> None:
    monkeypatch.setenv("PLANAGENT_DATABASE_URL", build_database_url(tmp_path / db_name))
    monkeypatch.setenv("PLANAGENT_EVENT_BUS_BACKEND", "memory")
    monkeypatch.setenv("PLANAGENT_INLINE_INGEST_DEFAULT", "true")
    monkeypatch.setenv("PLANAGENT_INLINE_SIMULATION_DEFAULT", "true")
    disable_openai(monkeypatch)
    reset_settings_cache()
    reset_database_cache()


def simulation_payload(**overrides) -> dict:
    payload: dict = {
        "company_id": "calibration-test-co",
        "company_name": "Calibration Test Co",
        "market": "ai",
        "tick_count": 2,
        "seed": 7,
        "actor_template": "default",
    }
    payload.update(overrides)
    return payload


def create_run(client: TestClient, **overrides) -> dict:
    created = client.post("/simulation/runs", json=simulation_payload(**overrides))
    assert created.status_code == 201, created.text
    return created.json()


async def seed_claims(specs: list[tuple[str, str, datetime]]) -> None:
    """Seed ACCEPTED claims with explicit ingestion timestamps.

    Each spec is (suffix, statement, created_at). Statements name the
    test company so subject matching selects them.
    """

    database = get_database()
    async with database.session() as session:
        records = []
        for suffix, statement, created_at in specs:
            evidence = EvidenceItem(
                id=f"evidence-{suffix}",
                normalized_item_id=f"normalized-{suffix}",
                evidence_type="test",
                title=f"Evidence {suffix}",
                summary=statement,
                body_text=statement,
                source_url=f"https://example.com/{suffix}",
                confidence=0.95,
                provenance={"test": True},
            )
            claim = Claim(
                id=f"claim-{suffix}",
                evidence_item_id=evidence.id,
                subject="Calibration Test Co",
                predicate="reported",
                object_text=statement,
                statement=statement,
                confidence=0.95,
                status="ACCEPTED",
                requires_review=False,
                created_at=created_at,
            )
            records.extend([evidence, claim])
        session.add_all(records)
        await session.commit()


def create_template(client: TestClient, **overrides) -> dict:
    payload: dict = {
        "name": "Calibration Template",
        "domain_id": "corporate",
        "description": "Thresholds to calibrate.",
        "state_fields": [{"name": "cash", "description": "Cash", "default": 100.0}],
        "policies": {
            "cash": {
                "preferred_direction": "increase",
                "alert_threshold": 50.0,
                "critical_threshold": 25.0,
            }
        },
        "variables": [],
        "internal": {},
    }
    payload.update(overrides)
    created = client.post("/variable-templates", json=payload)
    assert created.status_code == 201, created.text
    return created.json()


# ---------------------------------------------------------------- firewall


def test_firewall_excludes_post_decision_claims(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        asyncio.run(
            seed_claims(
                [
                    ("early-1", "Calibration Test Co raised a seed round.", datetime(2026, 1, 10)),
                    ("early-2", "Calibration Test Co hired engineers.", datetime(2026, 2, 10)),
                    ("late-1", "Calibration Test Co faced a GPU cost increase.", datetime(2026, 4, 10)),
                    ("late-2", "Calibration Test Co shipped a new release.", datetime(2026, 5, 10)),
                ]
            )
        )
        run = create_run(client, decision_time="2026-03-01T00:00:00Z")
        summary = run["summary"]
        assert summary["evidence_count"] == 2
        assert summary["evidence_statements"] == [
            "Calibration Test Co raised a seed round.",
            "Calibration Test Co hired engineers.",
        ]
        determinism = summary["determinism"]
        assert determinism["decision_time"] == "2026-03-01T00:00:00.000000Z"
        assert determinism["cutoff_source"] == "explicit"
        assert determinism["firewall_active"] is True

        audit = client.get(f"/runs/{run['id']}/firewall")
        assert audit.status_code == 200
        body = audit.json()
        assert body["decision_time"] == "2026-03-01T00:00:00.000000Z"
        assert body["cutoff_source"] == "explicit"
        assert body["firewall_active"] is True
        assert body["included_claim_ids"] == ["claim-early-1", "claim-early-2"]
        assert body["excluded_claim_ids"] == ["claim-late-1", "claim-late-2"]


def test_firewall_boundary_claim_at_decision_time_is_visible(
    monkeypatch, tmp_path: Path
) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        asyncio.run(
            seed_claims(
                [
                    (
                        "boundary",
                        "Calibration Test Co announced results.",
                        datetime(2026, 3, 1, 0, 0, 0),
                    )
                ]
            )
        )
        run = create_run(client, decision_time="2026-03-01T00:00:00Z")
        assert run["summary"]["evidence_count"] == 1
        assert run["summary"]["evidence_statements"] == [
            "Calibration Test Co announced results."
        ]
        audit = client.get(f"/runs/{run['id']}/firewall")
        assert audit.json()["included_claim_ids"] == ["claim-boundary"]
        assert audit.json()["excluded_claim_ids"] == []


def test_firewall_creation_time_default(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        asyncio.run(
            seed_claims(
                [("old", "Calibration Test Co raised a seed round.", datetime(2026, 1, 10))]
            )
        )
        run = create_run(client)
        determinism = run["summary"]["determinism"]
        assert determinism["cutoff_source"] == "creation_time"
        assert determinism["firewall_active"] is True
        decision_time = datetime.fromisoformat(
            determinism["decision_time"].replace("Z", "+00:00")
        ).replace(tzinfo=None)
        created_at = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00")).replace(
            tzinfo=None
        )
        assert abs(decision_time - created_at) < timedelta(seconds=60)

        # A claim ingested after the run was created is outside the
        # default cutoff even though the audit recomputes live.
        asyncio.run(
            seed_claims(
                [("future", "Calibration Test Co faced a GPU cost increase.", datetime(2030, 1, 1))]
            )
        )
        audit = client.get(f"/runs/{run['id']}/firewall")
        assert audit.status_code == 200
        body = audit.json()
        assert body["cutoff_source"] == "creation_time"
        assert body["included_claim_ids"] == ["claim-old"]
        assert body["excluded_claim_ids"] == ["claim-future"]


def test_firewall_replay_honors_cutoff(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        asyncio.run(
            seed_claims(
                [("early", "Calibration Test Co raised a seed round.", datetime(2026, 1, 10))]
            )
        )
        run = create_run(client, decision_time="2026-03-01T00:00:00Z")
        asyncio.run(
            seed_claims(
                [("late", "Calibration Test Co faced a GPU cost increase.", datetime(2026, 4, 10))]
            )
        )
        replay = client.post(f"/runs/{run['id']}/replay")
        assert replay.status_code == 201, replay.text
        body = replay.json()
        assert body["match"] is True
        assert body["first_diverging_tick"] is None
        assert body["input_hash_match"] is True

        # The replay row inherited the original cutoff.
        audit = client.get(f"/runs/{body['replay_run_id']}/firewall")
        assert audit.json()["decision_time"] == "2026-03-01T00:00:00.000000Z"
        assert audit.json()["cutoff_source"] == "explicit"
        assert audit.json()["excluded_claim_ids"] == ["claim-late"]


def test_firewall_audit_legacy_run_without_fragment(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        asyncio.run(
            seed_claims(
                [("only", "Calibration Test Co raised a seed round.", datetime(2026, 1, 10))]
            )
        )
        run = create_run(client, decision_time="2026-03-01T00:00:00Z")

        async def strip_fragment() -> None:
            database = get_database()
            async with database.session() as session:
                row = await session.get(SimulationRun, run["id"])
                assert row is not None
                configuration = dict(row.configuration or {})
                configuration.pop("hindsight_firewall", None)
                row.configuration = configuration
                await session.commit()

        asyncio.run(strip_fragment())
        audit = client.get(f"/runs/{run['id']}/firewall")
        assert audit.status_code == 200
        body = audit.json()
        assert body["decision_time"] is None
        assert body["cutoff_source"] is None
        assert body["firewall_active"] is False
        assert body["included_claim_ids"] == ["claim-only"]
        assert body["excluded_claim_ids"] == []

        missing = client.get("/runs/no-such-run/firewall")
        assert missing.status_code == 404


def test_firewall_cutoff_enters_input_hash(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        first = create_run(client, decision_time="2026-03-01T00:00:00Z")
        second = create_run(client, decision_time="2026-03-01T00:00:00Z")
        third = create_run(client, decision_time="2026-04-01T00:00:00Z")

        def input_hash(run_id: str) -> str | None:
            response = client.get(f"/runs/{run_id}/determinism")
            assert response.status_code == 200
            return response.json()["input_hash"]

        assert input_hash(first["id"]) == input_hash(second["id"])
        assert input_hash(first["id"]) != input_hash(third["id"])


# ---------------------------------------------------------------- policy fits


def _bound_runs(client: TestClient, template_id: str, cash_values: list[float]) -> list[dict]:
    return [
        create_run(
            client,
            variable_template_id=template_id,
            initial_state={"cash": cash},
        )
        for cash in cash_values
    ]


def test_policy_fit_creates_new_template_version(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        template = create_template(client)
        runs = _bound_runs(client, template["id"], [80.0, 90.0, 100.0, 110.0])
        for run, cash in zip(runs, [80.0, 90.0, 100.0, 110.0]):
            assert run["summary"]["final_state"]["cash"] == pytest.approx(cash)

        fitted = client.post(
            "/calibration/policy-fit",
            json={
                "template_id": template["id"],
                "ridge_strength": 1.0,
                "seed": 7,
                "bootstrap_draws": 20,
            },
        )
        assert fitted.status_code == 201, fitted.text
        body = fitted.json()
        assert body["kind"] == "policy_thresholds"
        assert body["domain_id"] == "corporate"
        assert body["source_template_id"] == template["id"]
        assert body["calibrated_template_id"] != template["id"]
        assert body["source_run_ids"] == [run["id"] for run in runs]
        assert body["n_observations"] == 4
        assert body["inputs_hash"].startswith("sha256:")
        change = body["changes"]["metrics"]["cash"]
        assert change["prior_alert_threshold"] == 50.0
        assert change["fitted_alert_threshold"] == pytest.approx(86.0)
        assert change["fitted_critical_threshold"] == pytest.approx(52.5)
        assert change["unchanged_reason"] is None
        assert change["n_observations"] == 4

        calibrated = client.get(f"/variable-templates/{body['calibrated_template_id']}")
        assert calibrated.status_code == 200
        policies = calibrated.json()["policies"]
        assert policies["cash"]["alert_threshold"] == pytest.approx(86.0)
        assert policies["cash"]["critical_threshold"] == pytest.approx(52.5)
        assert "(calibrated)" in calibrated.json()["name"]

        source = client.get(f"/variable-templates/{template['id']}")
        assert source.json()["policies"]["cash"]["alert_threshold"] == 50.0
        assert source.json()["policies"]["cash"]["critical_threshold"] == 25.0

        fetched = client.get(f"/calibration/fits/{body['id']}")
        assert fetched.status_code == 200
        assert fetched.json()["inputs_hash"] == body["inputs_hash"]


def test_policy_fit_shrinkage_and_determinism(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        template = create_template(client)
        _bound_runs(client, template["id"], [80.0, 90.0, 100.0, 110.0])

        def fit(ridge_strength: float) -> dict:
            response = client.post(
                "/calibration/policy-fit",
                json={
                    "template_id": template["id"],
                    "ridge_strength": ridge_strength,
                    "seed": 7,
                    "bootstrap_draws": 20,
                },
            )
            assert response.status_code == 201, response.text
            return response.json()

        strong = fit(1e6)
        assert strong["changes"]["metrics"]["cash"]["fitted_alert_threshold"] == pytest.approx(
            50.0, abs=0.01
        )
        weak = fit(1e-6)
        assert weak["changes"]["metrics"]["cash"]["fitted_alert_threshold"] == pytest.approx(
            95.0, abs=0.01
        )
        first = fit(5.0)
        second = fit(5.0)
        assert first["id"] != second["id"]
        assert first["changes"] == second["changes"]
        assert first["inputs_hash"] == second["inputs_hash"]


def test_policy_fit_insufficient_observations_keeps_priors(
    monkeypatch, tmp_path: Path
) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        template = create_template(client)
        _bound_runs(client, template["id"], [80.0])
        fitted = client.post(
            "/calibration/policy-fit",
            json={"template_id": template["id"], "bootstrap_draws": 10},
        )
        assert fitted.status_code == 201, fitted.text
        change = fitted.json()["changes"]["metrics"]["cash"]
        assert change["unchanged_reason"] == "insufficient_observations"
        assert change["fitted_alert_threshold"] == 50.0
        assert change["fitted_critical_threshold"] == 25.0
        calibrated = client.get(f"/variable-templates/{fitted.json()['calibrated_template_id']}")
        assert calibrated.json()["policies"]["cash"]["alert_threshold"] == 50.0


def test_policy_fit_errors(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        missing = client.post(
            "/calibration/policy-fit", json={"template_id": "no-such-template"}
        )
        assert missing.status_code == 404

        template = create_template(client)
        empty = client.post("/calibration/policy-fit", json={"template_id": template["id"]})
        assert empty.status_code == 400
        assert empty.json()["detail"]["code"] == "insufficient_observations"

        runs = _bound_runs(client, template["id"], [80.0, 90.0, 100.0])
        unknown_run = client.post(
            "/calibration/policy-fit",
            json={"template_id": template["id"], "source_run_ids": ["no-such-run"]},
        )
        assert unknown_run.status_code == 404

        subset = client.post(
            "/calibration/policy-fit",
            json={
                "template_id": template["id"],
                "source_run_ids": [runs[0]["id"], runs[2]["id"]],
                "bootstrap_draws": 10,
            },
        )
        assert subset.status_code == 201
        assert subset.json()["source_run_ids"] == [runs[0]["id"], runs[2]["id"]]

        replay = client.post(f"/runs/{runs[0]['id']}/replay")
        assert replay.status_code == 201
        derived = client.post(
            "/calibration/policy-fit",
            json={
                "template_id": template["id"],
                "source_run_ids": [replay.json()["replay_run_id"]],
            },
        )
        assert derived.status_code == 400
        assert derived.json()["detail"]["code"] == "derived_run_excluded"


def test_policy_fit_builtin_template_source(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        # Runs with no template binding execute against the pack
        # defaults, which is what the builtin template synthesizes.
        for cash in (80.0, 90.0, 100.0, 110.0):
            create_run(client, initial_state={"cash": cash})
        fitted = client.post(
            "/calibration/policy-fit",
            json={
                "template_id": "builtin:corporate",
                "ridge_strength": 1.0,
                "seed": 7,
                "bootstrap_draws": 10,
            },
        )
        assert fitted.status_code == 201, fitted.text
        body = fitted.json()
        assert body["source_template_id"] == "builtin:corporate"
        assert body["n_observations"] == 4
        assert body["changes"]["metrics"]["cash"]["fitted_alert_threshold"] == pytest.approx(86.0)
        calibrated = client.get(f"/variable-templates/{body['calibrated_template_id']}")
        assert calibrated.status_code == 200
        assert calibrated.json()["is_builtin"] is False


# ---------------------------------------------------------------- rule-weight fits


def test_rule_weight_fit_and_apply(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        asyncio.run(
            seed_claims(
                [
                    (
                        "cost",
                        "Calibration Test Co faced a GPU cost increase.",
                        datetime(2026, 1, 10),
                    ),
                    (
                        "ship",
                        "Calibration Test Co will ship a launch release.",
                        datetime(2026, 1, 11),
                    ),
                ]
            )
        )
        create_run(client, tick_count=2, initial_state={"cash": 100.0})
        create_run(client, tick_count=3, initial_state={"cash": 110.0})
        create_run(client, tick_count=4, initial_state={"cash": 120.0})

        fitted = client.post(
            "/calibration/rule-weight-fit",
            json={
                "domain_id": "corporate",
                "metric": "cash",
                "ridge_strength": 5.0,
                "seed": 7,
                "bootstrap_draws": 20,
            },
        )
        assert fitted.status_code == 201, fitted.text
        body = fitted.json()
        assert body["kind"] == "rule_weights"
        assert body["metric"] == "cash"
        assert body["n_observations"] == 3
        assert body["loo_rmse"] is not None
        assert "association_note" in body["changes"]
        rules = body["changes"]["rules"]
        assert "corp.cost_pressure" in rules
        assert "corp.ship_momentum" in rules
        assert any(change["total_matches"] > 0 for change in rules.values())
        for change in rules.values():
            if change["total_matches"] == 0:
                assert change["fitted_weight"] == pytest.approx(change["prior_weight"])
                assert change["prior_weight"] == pytest.approx(1.0)
            assert change["fitted_weight"] >= 0.0

        # The fit alone changes nothing in the registry; the explicit
        # apply step does, and records the event on the fit.
        applied = client.post(f"/calibration/fits/{body['id']}/apply-rule-weights")
        assert applied.status_code == 201, applied.text
        events = applied.json()["application"]["events"]
        assert len(events) == 1
        assert all(weight == 1.0 for weight in events[0]["previous_weights"].values())
        for rule_id, change in rules.items():
            assert events[0]["applied_weights"][rule_id] == pytest.approx(
                min(2.0, max(0.0, change["fitted_weight"])), abs=1e-4
            )

        applied_again = client.post(f"/calibration/fits/{body['id']}/apply-rule-weights")
        assert len(applied_again.json()["application"]["events"]) == 2

        listing = client.get("/calibration/fits", params={"kind": "rule_weights"})
        assert listing.status_code == 200
        assert [item["id"] for item in listing.json()] == [body["id"]]


def test_rule_weight_fit_determinism(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        asyncio.run(
            seed_claims(
                [
                    (
                        "cost",
                        "Calibration Test Co faced a GPU cost increase.",
                        datetime(2026, 1, 10),
                    )
                ]
            )
        )
        create_run(client, tick_count=2, initial_state={"cash": 100.0})
        create_run(client, tick_count=3, initial_state={"cash": 110.0})
        create_run(client, tick_count=4, initial_state={"cash": 120.0})
        payload = {
            "domain_id": "corporate",
            "metric": "cash",
            "ridge_strength": 5.0,
            "seed": 7,
            "bootstrap_draws": 20,
        }
        first = client.post("/calibration/rule-weight-fit", json=payload)
        second = client.post("/calibration/rule-weight-fit", json=payload)
        assert first.status_code == 201 and second.status_code == 201
        assert first.json()["changes"] == second.json()["changes"]
        assert first.json()["inputs_hash"] == second.json()["inputs_hash"]
        assert first.json()["id"] != second.json()["id"]


def test_rule_weight_fit_errors(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        unknown_domain = client.post(
            "/calibration/rule-weight-fit",
            json={"domain_id": "nope", "metric": "cash"},
        )
        assert unknown_domain.status_code == 400
        assert unknown_domain.json()["detail"]["code"] == "unknown_domain"

        unknown_metric = client.post(
            "/calibration/rule-weight-fit",
            json={"domain_id": "corporate", "metric": "nope"},
        )
        assert unknown_metric.status_code == 400
        assert unknown_metric.json()["detail"]["code"] == "unknown_metric"

        create_run(client, initial_state={"cash": 100.0})
        too_few = client.post(
            "/calibration/rule-weight-fit",
            json={"domain_id": "corporate", "metric": "cash"},
        )
        assert too_few.status_code == 400
        assert too_few.json()["detail"]["code"] == "insufficient_observations"

        unknown_run = client.post(
            "/calibration/rule-weight-fit",
            json={
                "domain_id": "corporate",
                "metric": "cash",
                "source_run_ids": ["no-such-run"],
            },
        )
        assert unknown_run.status_code == 404

        missing_fit = client.get("/calibration/fits/no-such-fit")
        assert missing_fit.status_code == 404
        missing_apply = client.post("/calibration/fits/no-such-fit/apply-rule-weights")
        assert missing_apply.status_code == 404


def test_apply_rule_weights_rejects_policy_fit(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        template = create_template(client)
        _bound_runs(client, template["id"], [80.0, 90.0, 100.0])
        fitted = client.post(
            "/calibration/policy-fit",
            json={"template_id": template["id"], "bootstrap_draws": 10},
        )
        assert fitted.status_code == 201
        applied = client.post(
            f"/calibration/fits/{fitted.json()['id']}/apply-rule-weights"
        )
        assert applied.status_code == 400
        assert applied.json()["detail"]["code"] == "wrong_fit_kind"
