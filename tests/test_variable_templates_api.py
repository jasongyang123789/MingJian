"""API tests for the Sprint 2 variable tables (PRD deltas D2/D3).

Covers the standalone validation endpoint, template CRUD (with built-in
presets read-only), the run-creation binding gate (refusal leaves no run
behind), audit retrieval, preset equivalence (a run with the built-in
corporate preset produces the same snapshots as a run without one,
except profit, which the profit-chain pack moves as revenue x
net_margin), custom template state defaults, and branch inheritance.
Same scratch-SQLite + in-memory-bus + empty-LLM-keys pattern as the
MECE tests.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from planagent.config import reset_settings_cache
from planagent.db import reset_database_cache
from planagent.main import create_app

VALID_SET = {
    "name": "case",
    "variables": [
        {
            "id": "cac",
            "unit": "yuan",
            "distribution": {"type": "triangular", "min": 8000, "mode": 12000, "max": 20000},
            "evidence_ref": "evidence:q3-report",
        },
        {
            "id": "churn",
            "unit": "%",
            "distribution": {"type": "normal", "mean": 12, "std": 3},
            "evidence_ref": "estimate: founder judgment",
        },
    ],
    "internal": {"team": "20 people"},
}

INVALID_SET = {
    "name": "case",
    "variables": [
        {
            "id": "cac",
            "unit": "yuan",
            "distribution": {"type": "triangular", "min": 20000, "mode": 12000, "max": 8000},
            "evidence_ref": "evidence:q3-report",
        },
        {
            "id": "churn",
            "unit": "%",
            "distribution": {"type": "bernoulli", "p": 1.5},
            "evidence_ref": "",
        },
    ],
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


def setup_app(monkeypatch, tmp_path: Path, db_name: str = "planagent-variables.db") -> None:
    monkeypatch.setenv("PLANAGENT_DATABASE_URL", build_database_url(tmp_path / db_name))
    monkeypatch.setenv("PLANAGENT_EVENT_BUS_BACKEND", "memory")
    monkeypatch.setenv("PLANAGENT_INLINE_INGEST_DEFAULT", "true")
    monkeypatch.setenv("PLANAGENT_INLINE_SIMULATION_DEFAULT", "true")
    disable_openai(monkeypatch)
    reset_settings_cache()
    reset_database_cache()


def simulation_payload(**overrides) -> dict:
    payload: dict = {
        "company_id": "variables-test-co",
        "company_name": "Variables Test Co",
        "market": "ai",
        "tick_count": 2,
        "seed": 7,
        # "default" is not a pack actor template, so no actor overlay masks
        # the template state defaults under test.
        "actor_template": "default",
    }
    payload.update(overrides)
    return payload


def test_validate_endpoint_returns_verdict_in_payload(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        valid = client.post("/variables/validate", json=VALID_SET)
        assert valid.status_code == 200
        body = valid.json()
        assert body["is_valid"] is True
        assert body["variable_count"] == 2
        assert body["issues"] == []

        invalid = client.post("/variables/validate", json=INVALID_SET)
        assert invalid.status_code == 200
        body = invalid.json()
        assert body["is_valid"] is False
        assert [issue["kind"] for issue in body["issues"]] == [
            "invalid_bounds",
            "missing_evidence_ref",
            "invalid_probability",
        ]

        prefixed = client.post("/api/variables/validate", json=VALID_SET)
        assert prefixed.status_code == 200
        assert prefixed.json()["is_valid"] is True


def test_template_crud_lifecycle(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        created = client.post(
            "/variable-templates",
            json={
                "name": "Lean SaaS",
                "domain_id": "corporate",
                "description": "Tighter thresholds.",
                "state_fields": [{"name": "cash", "description": "Cash", "default": 80.0}],
                "policies": {
                    "cash": {
                        "preferred_direction": "increase",
                        "alert_threshold": 60.0,
                        "critical_threshold": 30.0,
                    }
                },
                "variables": VALID_SET["variables"],
                "internal": {"team": "20 people"},
            },
        )
        assert created.status_code == 201
        template = created.json()
        assert template["is_builtin"] is False
        assert template["created_at"] is not None
        template_id = template["id"]

        fetched = client.get(f"/variable-templates/{template_id}")
        assert fetched.status_code == 200
        assert fetched.json()["name"] == "Lean SaaS"

        listing = client.get("/variable-templates")
        assert listing.status_code == 200
        ids = [item["id"] for item in listing.json()]
        assert ids[:3] == ["builtin:automotive", "builtin:corporate", "builtin:military"]
        assert template_id in ids

        filtered = client.get("/variable-templates", params={"domain_id": "military"})
        assert [item["id"] for item in filtered.json()] == ["builtin:military"]

        updated = client.put(
            f"/variable-templates/{template_id}",
            json={"name": "Lean SaaS v2", "description": "Updated."},
        )
        assert updated.status_code == 200
        assert updated.json()["name"] == "Lean SaaS v2"
        assert updated.json()["description"] == "Updated."
        # Omitted fields keep their stored values.
        assert updated.json()["state_fields"][0]["default"] == 80.0

        deleted = client.delete(f"/variable-templates/{template_id}")
        assert deleted.status_code == 204
        assert client.get(f"/variable-templates/{template_id}").status_code == 404


def test_template_create_refuses_invalid_variables_and_unknown_domain(
    monkeypatch, tmp_path: Path
) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        refused = client.post(
            "/variable-templates",
            json={"name": "Bad", "domain_id": "corporate", "variables": INVALID_SET["variables"]},
        )
        assert refused.status_code == 400
        detail = refused.json()["detail"]
        assert detail["code"] == "variable_validation_failed"
        assert detail["validation"]["is_valid"] is False

        unknown = client.post(
            "/variable-templates",
            json={"name": "Bad", "domain_id": "no_such_domain"},
        )
        assert unknown.status_code == 400

        # Nothing was stored: only the built-ins list.
        listing = client.get("/variable-templates")
        assert [item["id"] for item in listing.json()] == [
            "builtin:automotive",
            "builtin:corporate",
            "builtin:military",
        ]


def test_builtin_templates_are_read_only(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        preset = client.get("/variable-templates/builtin:corporate")
        assert preset.status_code == 200
        body = preset.json()
        assert body["is_builtin"] is True
        assert len(body["state_fields"]) == 17  # 15 pre-Fix-3 + revenue + profit
        assert len(body["policies"]) == 16  # 14 pre-Fix-3 + revenue + profit
        assert body["created_at"] is None

        assert client.get("/variable-templates/builtin:nope").status_code == 404
        assert client.get("/variable-templates/does-not-exist").status_code == 404

        update = client.put("/variable-templates/builtin:corporate", json={"name": "x"})
        assert update.status_code == 400
        delete = client.delete("/variable-templates/builtin:corporate")
        assert delete.status_code == 400


def test_run_with_builtin_preset_stores_snapshot_for_audit(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        response = client.post(
            "/simulation/runs", json=simulation_payload(variable_template_id="builtin:corporate")
        )
        assert response.status_code == 201
        run_id = response.json()["id"]

        audit = client.get(f"/runs/{run_id}/variables")
        assert audit.status_code == 200
        body = audit.json()
        assert body["run_id"] == run_id
        assert body["template"]["id"] == "builtin:corporate"
        assert body["template"]["is_builtin"] is True
        # Profit-chain pack (2026-11-20): the corporate preset now
        # carries 4 variables + 4 formulas, so a template-only run
        # stores bindings (the template set itself) and a passing
        # validation result. The old "no bindings" expectation was the
        # EMPTY preset, not a property of the audit trail.
        assert body["bindings"] is not None
        assert [v["id"] for v in body["bindings"]["variables"]] == [
            "margin_base",
            "margin_longrun",
            "margin_reversion",
            "margin_adoption",
        ]
        assert [f["output"] for f in body["bindings"]["formulas"]] == [
            "disruptor_adoption",
            "revenue",
            "net_margin",
            "profit",
        ]
        assert body["validation"] is not None
        assert body["validation"]["is_valid"] is True


def test_run_with_inline_bindings_and_template_merge(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        created = client.post(
            "/variable-templates",
            json={
                "name": "Base case",
                "domain_id": "corporate",
                "variables": [
                    {
                        "id": "cac",
                        "unit": "yuan",
                        "distribution": {"type": "fixed", "value": 10000},
                        "evidence_ref": "evidence:base",
                    },
                    {
                        "id": "churn",
                        "unit": "%",
                        "distribution": {"type": "fixed", "value": 10},
                        "evidence_ref": "evidence:base",
                    },
                ],
                "internal": {"team": "base team"},
            },
        )
        assert created.status_code == 201
        template_id = created.json()["id"]

        # Inline set overrides "cac" and adds "nrr"; "churn" comes from the
        # template; internal tables merge with inline winning per key.
        response = client.post(
            "/simulation/runs",
            json=simulation_payload(
                variable_template_id=template_id,
                variable_set={
                    "name": "override",
                    "variables": [
                        {
                            "id": "cac",
                            "unit": "yuan",
                            "distribution": {"type": "fixed", "value": 15000},
                            "evidence_ref": "evidence:override",
                        },
                        {
                            "id": "nrr",
                            "unit": "%",
                            "distribution": {"type": "fixed", "value": 105},
                            "evidence_ref": "evidence:override",
                        },
                    ],
                    "internal": {"team": "override team", "runway": "18m"},
                },
            ),
        )
        assert response.status_code == 201
        run_id = response.json()["id"]

        audit = client.get(f"/runs/{run_id}/variables")
        body = audit.json()
        assert body["template"]["id"] == template_id
        bindings = body["bindings"]
        # Track C (default ON): the canonical downside variables are
        # appended at the end of the merged bindings, after the
        # template/inline variables.
        assert [variable["id"] for variable in bindings["variables"]] == [
            "cac",
            "churn",
            "nrr",
            "downturn_occurs",
            "downturn_depth",
            "downturn_start",
            "downturn_duration",
            "downturn_persistent",
        ]
        by_id = {variable["id"]: variable for variable in bindings["variables"]}
        assert by_id["cac"]["distribution"]["value"] == 15000.0
        assert by_id["cac"]["evidence_ref"] == "evidence:override"
        assert by_id["churn"]["distribution"]["value"] == 10.0
        assert bindings["internal"] == {"team": "override team", "runway": "18m"}
        assert body["validation"]["is_valid"] is True


def test_run_without_bindings_has_no_variables_audit(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        response = client.post("/simulation/runs", json=simulation_payload())
        assert response.status_code == 201
        run_id = response.json()["id"]
        assert client.get(f"/runs/{run_id}/variables").status_code == 404
        assert client.get("/runs/no-such-run/variables").status_code == 404


def test_gate_refusals_create_no_run(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        invalid = client.post("/simulation/runs", json=simulation_payload(variable_set=INVALID_SET))
        assert invalid.status_code == 400
        detail = invalid.json()["detail"]
        assert detail["code"] == "variable_validation_failed"
        assert detail["validation"]["is_valid"] is False

        unknown = client.post(
            "/simulation/runs",
            json=simulation_payload(variable_template_id="no-such-template"),
        )
        assert unknown.status_code == 400
        assert unknown.json()["detail"]["code"] == "variable_template_not_found"

        mismatch = client.post(
            "/simulation/runs",
            json=simulation_payload(variable_template_id="builtin:military"),
        )
        assert mismatch.status_code == 400
        assert mismatch.json()["detail"]["code"] == "variable_template_domain_mismatch"

        # Refusals leave nothing behind: no run row was written.
        runs = client.get("/simulation/runs")
        assert runs.status_code == 200
        assert runs.json() == []


def test_gate_refuses_scope_tags_outside_decomposition(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        outside = dict(VALID_SET)
        outside["variables"] = [
            {
                "id": "risk_var",
                "unit": "score",
                "distribution": {"type": "fixed", "value": 1},
                "evidence_ref": "evidence:x",
                "scope_tags": ["risk"],
            }
        ]
        refused = client.post(
            "/simulation/runs",
            json=simulation_payload(decomposition=PASSING_TREE, variable_set=outside),
        )
        assert refused.status_code == 400
        detail = refused.json()["detail"]
        assert detail["code"] == "variable_validation_failed"
        assert [issue["kind"] for issue in detail["validation"]["issues"]] == [
            "scope_tag_outside_decomposition"
        ]

        inside = dict(VALID_SET)
        inside["variables"] = [
            {
                "id": "demand_var",
                "unit": "score",
                "distribution": {"type": "fixed", "value": 1},
                "evidence_ref": "evidence:x",
                "scope_tags": ["demand"],
            }
        ]
        accepted = client.post(
            "/simulation/runs",
            json=simulation_payload(decomposition=PASSING_TREE, variable_set=inside),
        )
        assert accepted.status_code == 201


def _snapshots(client: TestClient, run_id: str) -> list[dict]:
    package = client.get(f"/runs/{run_id}/replay-package")
    assert package.status_code == 200
    return package.json()["package"]["snapshots"]


def test_preset_equivalence_snapshots_identical(monkeypatch, tmp_path: Path) -> None:
    """Preset equivalence, profit-chain exception (2026-11-20).

    The built-in corporate preset used to add no movement at all, so a
    preset run's snapshots were identical to a plain run's. The
    profit-chain pack gives the preset a profit driver, so the two
    runs now differ in EXACTLY one field — profit — and profit follows
    revenue x net_margin exactly. Every other field is still
    identical, and revenue stays at its default (the template's
    revenue driver is an identity passthrough).
    """
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        plain = client.post("/simulation/runs", json=simulation_payload())
        assert plain.status_code == 201
        preset = client.post(
            "/simulation/runs",
            json=simulation_payload(variable_template_id="builtin:corporate"),
        )
        assert preset.status_code == 201

        plain_snapshots = _snapshots(client, plain.json()["id"])
        preset_snapshots = _snapshots(client, preset.json()["id"])
        assert len(plain_snapshots) == 3  # tick 0 + 2 ticks
        for plain_snap, preset_snap in zip(plain_snapshots, preset_snapshots):
            assert plain_snap["tick"] == preset_snap["tick"]
            for key, value in plain_snap["state"].items():
                if key == "profit":
                    continue
                assert preset_snap["state"][key] == value, key
            assert preset_snap["state"]["revenue"] == 100.0
        # Profit follows the chain exactly, from the run's sampled
        # margin values (determinism endpoint): tick 0 is the untouched
        # default; later ticks revert linearly toward 0.20 with zero
        # adoption in a generic run.
        det = client.get(f"/runs/{preset.json()['id']}/determinism")
        assert det.status_code == 200, det.text
        sampled = det.json()["sampled_values"]
        base = sampled["margin_base"]
        adoption = sampled["margin_adoption"]
        assert preset_snapshots[0]["state"]["profit"] == 20.0
        for tick in (1, 2):
            # Drivers round EACH output to 4 decimals, so profit reads
            # the ROUNDED margin, not the full-precision value.
            margin = round(
                min(
                    0.25,
                    max(0.02, base + 0.25 * (0.20 - base) * (tick - 1) + adoption * 0.0),
                ),
                4,
            )
            assert preset_snapshots[tick]["state"]["profit"] == round(
                100.0 * margin, 4
            ), tick


def test_custom_template_state_defaults_apply_at_tick_zero(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        preset = client.get("/variable-templates/builtin:corporate").json()
        state_fields = [
            dict(field, default=123.0) if field["name"] == "cash" else field
            for field in preset["state_fields"]
        ]
        created = client.post(
            "/variable-templates",
            json={
                "name": "Cash heavy",
                "domain_id": "corporate",
                "state_fields": state_fields,
                "policies": preset["policies"],
            },
        )
        assert created.status_code == 201
        template_id = created.json()["id"]

        templated = client.post(
            "/simulation/runs", json=simulation_payload(variable_template_id=template_id)
        )
        assert templated.status_code == 201
        snapshots = _snapshots(client, templated.json()["id"])
        tick_zero = snapshots[0]["state"]
        assert tick_zero["cash"] == 123.0
        builtin_defaults = {field["name"]: field["default"] for field in preset["state_fields"]}
        for name, default in builtin_defaults.items():
            if name != "cash":
                assert tick_zero[name] == default

        # An explicit initial_state override still wins over the template.
        overridden = client.post(
            "/simulation/runs",
            json=simulation_payload(variable_template_id=template_id, initial_state={"cash": 7.0}),
        )
        assert overridden.status_code == 201
        assert _snapshots(client, overridden.json()["id"])[0]["state"]["cash"] == 7.0


def test_scenario_branch_inherits_parent_template(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        baseline = client.post(
            "/simulation/runs",
            json=simulation_payload(tick_count=4, variable_template_id="builtin:corporate"),
        )
        assert baseline.status_code == 201
        baseline_id = baseline.json()["id"]

        branch = client.post(
            f"/scenario/runs/{baseline_id}",
            json={"fork_step": 2, "tick_count": 2, "probability_band": "medium-high"},
        )
        assert branch.status_code == 201
        branch_run_id = branch.json()["run_id"]

        audit = client.get(f"/runs/{branch_run_id}/variables")
        assert audit.status_code == 200
        assert audit.json()["template"]["id"] == "builtin:corporate"
