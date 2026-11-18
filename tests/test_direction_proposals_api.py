"""API tests for option C: LLM-proposed decision directions.

Covers the propose endpoint (grounding validation with
refuse-before-write semantics, no-clobber name skips, 503/502
failure mapping, refusal-before-LLM-call), the accept/reject
review flow, generation from accepted mappings only, and derive's
no-clobber extension to proposal rows. Same scratch-SQLite +
in-memory-bus + empty-LLM-keys pattern as the Sprint 1-14 tests.
The LLM is a scripted port throughout: no live LLM call is ever
made.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from planagent.config import get_settings, reset_settings_cache
from planagent.db import get_database, reset_database_cache
from planagent.domain.models import DirectionMappingRecord, SimulationRun
from planagent.main import create_app
from planagent.services.mece.models import DecompositionTree
from planagent.services.mece.validator import validate_decomposition
from planagent.services.narratives.proposals import PROPOSAL_TEMPLATE_ID
from planagent.services.narratives.service import NarrativeService
from tests.skill_fixtures import ScriptedSkillPort

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

# A tree that exists but does not decompose: the root has no children.
# The MECE validator fails it (empty_tree), so run creation refuses it;
# the empty-tree anchor below is built by rewriting a stored fragment.
EMPTY_TREE = {
    "topic": "Should we launch?",
    "root": {"name": "Should we launch?", "scope": ["demand", "cost"], "children": []},
}


def build_database_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.resolve().as_posix()}"


def setup_app(monkeypatch, tmp_path: Path, db_name: str = "planagent-proposals.db") -> None:
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


def simulation_payload(**overrides) -> dict:
    payload: dict = {
        "company_id": "proposals-test-co",
        "company_name": "Proposals Test Co",
        "market": "ai",
        "tick_count": 4,
        "seed": 7,
        "actor_template": "default",
        "variable_set": BOUND_SET,
    }
    payload.update(overrides)
    return payload


def _create_run(client: TestClient, **overrides) -> dict:
    created = client.post("/simulation/runs", json=simulation_payload(**overrides))
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "COMPLETED"
    return created.json()


def _create_ensemble(client: TestClient, run_id: str, trials: int = 5) -> dict:
    response = client.post(f"/runs/{run_id}/monte-carlo", json={"trials": trials, "metric": "cash"})
    assert response.status_code == 201, response.text
    return response.json()


def _branch(client: TestClient, parent_id: str, cash: float) -> dict:
    branched = client.post(
        f"/scenario/runs/{parent_id}",
        json={"fork_step": 2, "state_overrides": {"cash": cash}},
    )
    assert branched.status_code == 201, branched.text
    return branched.json()


def _proposal(
    run_id: str,
    name: str = "Phased rollout",
    arm: str = "strategy",
    branches: list[str] | None = None,
    variables: list[str] | None = None,
    rationale: str = "The strategy arm beats baseline on P50 with a bounded loss.",
    gates: list[dict] | None = None,
) -> dict:
    return {
        "name": name,
        "source_run_id": run_id,
        "arm": arm,
        "mece_branches": branches if branches is not None else ["Demand"],
        "key_variables": variables if variables is not None else ["cash"],
        "rationale": rationale,
        "gates": gates
        if gates is not None
        else [
            {
                "variable_id": "cash",
                "comparison": ">=",
                "threshold": 90.0,
                "basis": "Anchor baseline P50 of cash is above 90 in the stored ensemble.",
            }
        ],
    }


def _bind_port(app, port: ScriptedSkillPort) -> None:
    """Inject a scripted LLM port (fixture proposals need run ids,
    so the port is bound after the runs exist; the route resolves
    the service from app state on every request)."""
    app.state.narrative_service = NarrativeService(get_settings(), llm_port=port)


def _propose(client: TestClient, run_id: str, payload: dict | None = None):
    if payload is None:
        return client.post(f"/runs/{run_id}/directions/propose")
    return client.post(f"/runs/{run_id}/directions/propose", json=payload)


def _mappings(client: TestClient, run_id: str) -> list[dict]:
    listed = client.get(f"/runs/{run_id}/directions/mappings")
    assert listed.status_code == 200, listed.text
    return listed.json()["mappings"]


async def _repoint_mapping(mapping_id: str, source_run_id: str) -> None:
    database = get_database()
    async with database.session() as session:
        row = await session.get(DirectionMappingRecord, mapping_id)
        assert row is not None
        row.source_run_id = source_run_id
        await session.commit()


async def _rewrite_mece_fragment(run_id: str, decomposition: dict) -> dict:
    """Replace a run's stored MECE fragment, returning the validation dump.

    An empty tree cannot be stored via run creation (the MECE gate
    refuses it), so the empty-tree anchor is built by rewriting the
    fragment of a run created with a valid tree. The validation is
    the real validator output for the rewritten tree, not a
    hand-built record.
    """
    database = get_database()
    async with database.session() as session:
        row = await session.get(SimulationRun, run_id)
        assert row is not None
        tree = DecompositionTree.model_validate(decomposition)
        validation = validate_decomposition(tree).model_dump(mode="json")
        configuration = dict(row.configuration or {})
        fragment = dict(configuration["mece"])
        fragment["decomposition"] = decomposition
        fragment["validation"] = validation
        configuration["mece"] = fragment
        row.configuration = configuration
        await session.commit()
        return validation


def _setup_family(client: TestClient) -> tuple[dict, dict]:
    parent = _create_run(client, decomposition=PASSING_TREE)
    child = _branch(client, parent["id"], 80.0)
    _create_ensemble(client, parent["id"])
    _create_ensemble(client, child["run_id"])
    return parent, child


# ---------------------------------------------------------------------------
# Propose: happy path + provenance
# ---------------------------------------------------------------------------


def test_propose_stores_proposals_awaiting_review(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    app = create_app()
    with TestClient(app) as client:
        parent, child = _setup_family(client)
        port = ScriptedSkillPort(
            {
                PROPOSAL_TEMPLATE_ID: [
                    {
                        "proposals": [
                            _proposal(parent["id"], name="Phased rollout"),
                            _proposal(child["run_id"], name="Go all in", arm="baseline"),
                        ]
                    }
                ]
            }
        )
        _bind_port(app, port)
        response = _propose(client, parent["id"], {})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["template_id"] == "narrative.direction_proposals"
        assert body["template_version"] == "2"
        assert body["model"] == "fixture"
        assert body["proposal_hash"].startswith("sha256:")
        assert body["family_runs_considered"] == 2
        outcomes = body["outcomes"]
        assert [outcome["status"] for outcome in outcomes] == ["stored", "stored"]
        assert [outcome["name"] for outcome in outcomes] == ["Phased rollout", "Go all in"]
        assert all(outcome["mapping_id"] for outcome in outcomes)
        rows = _mappings(client, parent["id"])
        assert len(rows) == 2
        assert [row["position"] for row in rows] == [0, 1]
        assert all(row["origin"] == "llm_proposal" for row in rows)
        assert all(row["status"] == "proposed" for row in rows)
        assert all(row["user_edited"] is False for row in rows)
        assert rows[0]["mece_branches"] == ["Demand"]
        assert rows[0]["deliberation_id"] is None
        record = rows[0]["proposal_record"]
        assert record["rationale"].startswith("The strategy arm beats baseline")
        assert record["key_variables"] == ["cash"]
        assert record["gates"] == [
            {
                "variable_id": "cash",
                "comparison": ">=",
                "threshold": 90.0,
                "basis": "Anchor baseline P50 of cash is above 90 in the stored ensemble.",
            }
        ]
        assert record["model"] == "fixture"
        assert record["template_id"] == "narrative.direction_proposals"
        assert record["template_version"] == "2"
        assert record["proposal_hash"] == body["proposal_hash"]
        # The prompt listed the whole grounding surface and nothing else.
        user_content = port.calls[0]["user_content"]
        assert parent["id"] in user_content
        assert child["run_id"] in user_content
        assert "Demand" in user_content
        assert "cash" in user_content
        # The ensemble metric is named, so a gate basis can cite it.
        assert "P50 of cash" in user_content
        port.assert_exhausted()


def test_propose_same_fixture_same_hash(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    app = create_app()
    with TestClient(app) as client:
        parent, _child = _setup_family(client)
        payload = {"proposals": [_proposal(parent["id"])]}
        port = ScriptedSkillPort({PROPOSAL_TEMPLATE_ID: [payload, dict(payload)]})
        _bind_port(app, port)
        first = _propose(client, parent["id"], {})
        second = _propose(client, parent["id"], {})
        assert first.status_code == 200 and second.status_code == 200
        assert first.json()["proposal_hash"] == second.json()["proposal_hash"]
        assert first.json()["outcomes"][0]["status"] == "stored"
        assert second.json()["outcomes"][0]["status"] == "skipped"
        assert len(_mappings(client, parent["id"])) == 1


def test_propose_with_guidance_passes_it_to_the_prompt(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    app = create_app()
    with TestClient(app) as client:
        parent, _child = _setup_family(client)
        port = ScriptedSkillPort({PROPOSAL_TEMPLATE_ID: [{"proposals": [_proposal(parent["id"])]}]})
        _bind_port(app, port)
        response = _propose(client, parent["id"], {"guidance": "favor caution"})
        assert response.status_code == 200, response.text
        assert "favor caution" in port.calls[0]["user_content"]


def test_propose_without_body_works(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    app = create_app()
    with TestClient(app) as client:
        parent, _child = _setup_family(client)
        port = ScriptedSkillPort({PROPOSAL_TEMPLATE_ID: [{"proposals": [_proposal(parent["id"])]}]})
        _bind_port(app, port)
        response = client.post(f"/runs/{parent['id']}/directions/propose")
        assert response.status_code == 200, response.text
        assert response.json()["outcomes"][0]["status"] == "stored"


# ---------------------------------------------------------------------------
# Propose: grounding refusals (refuse the whole request, write nothing)
# ---------------------------------------------------------------------------


def test_propose_refuses_unknown_mece_branch_and_writes_nothing(
    monkeypatch, tmp_path: Path
) -> None:
    setup_app(monkeypatch, tmp_path)
    app = create_app()
    with TestClient(app) as client:
        parent, _child = _setup_family(client)
        port = ScriptedSkillPort(
            {
                PROPOSAL_TEMPLATE_ID: [
                    {
                        "proposals": [
                            _proposal(parent["id"], name="Grounded"),
                            _proposal(parent["id"], name="Ungrounded", branches=["Nope"]),
                        ]
                    }
                ]
            }
        )
        _bind_port(app, port)
        response = _propose(client, parent["id"], {})
        assert response.status_code == 400, response.text
        detail = response.json()["detail"]
        assert detail["code"] == "direction_proposal_unknown_mece_branch"
        assert "Nope" in detail["message"]
        assert "Demand" in detail["message"]
        # Refuse-all: even the grounded proposal in the set was not stored.
        assert _mappings(client, parent["id"]) == []


def test_propose_refuses_unknown_source_run_and_writes_nothing(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    app = create_app()
    with TestClient(app) as client:
        parent, _child = _setup_family(client)
        port = ScriptedSkillPort(
            {PROPOSAL_TEMPLATE_ID: [{"proposals": [_proposal("run-missing", name="Ghost")]}]}
        )
        _bind_port(app, port)
        response = _propose(client, parent["id"], {})
        assert response.status_code == 400, response.text
        detail = response.json()["detail"]
        assert detail["code"] == "direction_proposal_unknown_source_run"
        assert "run-missing" in detail["message"]
        assert _mappings(client, parent["id"]) == []


def test_propose_refuses_run_outside_the_family(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    app = create_app()
    with TestClient(app) as client:
        parent, _child = _setup_family(client)
        outsider = _create_run(client)
        _create_ensemble(client, outsider["id"])
        port = ScriptedSkillPort(
            {
                PROPOSAL_TEMPLATE_ID: [
                    {"proposals": [_proposal(outsider["id"], name="Outsider direction")]}
                ]
            }
        )
        _bind_port(app, port)
        response = _propose(client, parent["id"], {})
        assert response.status_code == 400, response.text
        assert response.json()["detail"]["code"] == "direction_proposal_unknown_source_run"
        assert _mappings(client, parent["id"]) == []


def test_propose_refuses_ensemble_less_family_run(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    app = create_app()
    with TestClient(app) as client:
        parent = _create_run(client, decomposition=PASSING_TREE)
        child = _branch(client, parent["id"], 80.0)
        _create_ensemble(client, parent["id"])
        port = ScriptedSkillPort(
            {
                PROPOSAL_TEMPLATE_ID: [
                    {"proposals": [_proposal(child["run_id"], name="Child direction")]}
                ]
            }
        )
        _bind_port(app, port)
        response = _propose(client, parent["id"], {})
        assert response.status_code == 400, response.text
        detail = response.json()["detail"]
        assert detail["code"] == "direction_proposal_source_run_no_ensemble"
        assert f"/runs/{child['run_id']}/monte-carlo" in detail["message"]
        assert _mappings(client, parent["id"]) == []


def test_propose_refuses_unknown_variable_and_writes_nothing(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    app = create_app()
    with TestClient(app) as client:
        parent, _child = _setup_family(client)
        port = ScriptedSkillPort(
            {PROPOSAL_TEMPLATE_ID: [{"proposals": [_proposal(parent["id"], variables=["nope"])]}]}
        )
        _bind_port(app, port)
        response = _propose(client, parent["id"], {})
        assert response.status_code == 400, response.text
        detail = response.json()["detail"]
        assert detail["code"] == "direction_proposal_unknown_variable"
        assert "nope" in detail["message"]
        assert "cash" in detail["message"]
        assert _mappings(client, parent["id"]) == []


def test_propose_refuses_unknown_gate_variable_and_writes_nothing(
    monkeypatch, tmp_path: Path
) -> None:
    setup_app(monkeypatch, tmp_path)
    app = create_app()
    with TestClient(app) as client:
        parent, _child = _setup_family(client)
        bad_gate = {
            "variable_id": "nope",
            "comparison": ">=",
            "threshold": 90.0,
            "basis": "Anchor baseline P50 of cash is above 90.",
        }
        port = ScriptedSkillPort(
            {
                PROPOSAL_TEMPLATE_ID: [
                    {
                        "proposals": [
                            _proposal(parent["id"], name="Good direction"),
                            _proposal(parent["id"], name="Bad gate", gates=[bad_gate]),
                        ]
                    }
                ]
            }
        )
        _bind_port(app, port)
        response = _propose(client, parent["id"], {})
        assert response.status_code == 400, response.text
        detail = response.json()["detail"]
        assert detail["code"] == "direction_proposal_unknown_gate_variable"
        assert "nope" in detail["message"]
        assert "cash" in detail["message"]
        # Batch atomicity: the valid proposal is refused with the bad one.
        assert _mappings(client, parent["id"]) == []


def test_propose_refuses_non_finite_gate_threshold_and_writes_nothing(
    monkeypatch, tmp_path: Path
) -> None:
    setup_app(monkeypatch, tmp_path)
    app = create_app()
    with TestClient(app) as client:
        parent, _child = _setup_family(client)
        bad_gate = {
            "variable_id": "cash",
            "comparison": ">=",
            "threshold": float("inf"),
            "basis": "Anchor baseline P50 of cash is above 90.",
        }
        port = ScriptedSkillPort(
            {PROPOSAL_TEMPLATE_ID: [{"proposals": [_proposal(parent["id"], gates=[bad_gate])]}]}
        )
        _bind_port(app, port)
        response = _propose(client, parent["id"], {})
        # A non-finite threshold is malformed output: contract failure.
        assert response.status_code == 502, response.text
        assert response.json()["detail"]["code"] == "direction_propose_contract_failed"
        assert _mappings(client, parent["id"]) == []


def test_propose_refuses_malformed_gate_and_empty_gates_and_writes_nothing(
    monkeypatch, tmp_path: Path
) -> None:
    setup_app(monkeypatch, tmp_path)
    app = create_app()
    with TestClient(app) as client:
        parent, _child = _setup_family(client)
        bad_comparison = {
            "variable_id": "cash",
            "comparison": "~=",
            "threshold": 90.0,
            "basis": "Anchor baseline P50 of cash is above 90.",
        }
        port = ScriptedSkillPort(
            {
                PROPOSAL_TEMPLATE_ID: [
                    {"proposals": [_proposal(parent["id"], gates=[bad_comparison])]},
                    {"proposals": [_proposal(parent["id"], gates=[])]},
                ]
            }
        )
        _bind_port(app, port)
        first = _propose(client, parent["id"], {})
        assert first.status_code == 502, first.text
        assert first.json()["detail"]["code"] == "direction_propose_contract_failed"
        second = _propose(client, parent["id"], {})
        assert second.status_code == 502, second.text
        assert second.json()["detail"]["code"] == "direction_propose_contract_failed"
        assert _mappings(client, parent["id"]) == []
        port.assert_exhausted()


async def _insert_v1_proposal_record(run_id: str, source_run_id: str) -> str:
    """Store a template-v1 proposal row directly: no gates key.

    v1 records predate the gates field; the read path must serve
    them unchanged. Built by direct insert because propose() now
    always writes gates.
    """
    database = get_database()
    async with database.session() as session:
        row = DirectionMappingRecord(
            anchor_run_id=run_id,
            name="Legacy proposal",
            source_run_id=source_run_id,
            arm="strategy",
            mece_branches=["Demand"],
            deliberation_id=None,
            origin="llm_proposal",
            rule_id=None,
            rules_version=None,
            rule_record=None,
            status="proposed",
            proposal_record={
                "rationale": "A v1 proposal, stored before gates existed.",
                "key_variables": ["cash"],
                "model": "fixture",
                "template_id": "narrative.direction_proposals",
                "template_version": "1",
                "proposal_hash": "sha256:legacy",
            },
            user_edited=False,
            position=0,
        )
        session.add(row)
        await session.commit()
        return row.id


def test_v1_proposal_record_without_gates_reads_fine(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    app = create_app()
    with TestClient(app) as client:
        parent, _child = _setup_family(client)
        mapping_id = asyncio.run(_insert_v1_proposal_record(parent["id"], parent["id"]))
        rows = _mappings(client, parent["id"])
        assert len(rows) == 1
        assert rows[0]["id"] == mapping_id
        record = rows[0]["proposal_record"]
        assert record["template_version"] == "1"
        assert "gates" not in record
        assert record["rationale"].startswith("A v1 proposal")


def test_propose_refuses_without_tree_before_calling_llm(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    app = create_app()
    with TestClient(app) as client:
        run = _create_run(client)
        _create_ensemble(client, run["id"])
        port = ScriptedSkillPort({PROPOSAL_TEMPLATE_ID: [{"proposals": [_proposal(run["id"])]}]})
        _bind_port(app, port)
        response = _propose(client, run["id"], {})
        assert response.status_code == 400, response.text
        assert response.json()["detail"]["code"] == "direction_proposal_requires_tree"
        assert port.calls == []
        assert _mappings(client, run["id"]) == []


def test_propose_refuses_empty_tree_before_calling_llm(monkeypatch, tmp_path: Path) -> None:
    """A stored tree with no branches refuses like a missing tree.

    The scripted proposal traces ONLY to the root name. Branch
    collection includes the root, so without the empty-tree refusal
    this vacuous trace would pass grounding and the proposal would
    be stored. The refusal happens before the port is touched.
    """
    setup_app(monkeypatch, tmp_path)
    app = create_app()
    with TestClient(app) as client:
        run = _create_run(client, decomposition=PASSING_TREE)
        _create_ensemble(client, run["id"])
        validation = asyncio.run(_rewrite_mece_fragment(run["id"], EMPTY_TREE))
        assert validation["is_mece"] is False
        assert [issue["kind"] for issue in validation["issues"]] == ["empty_tree"]
        port = ScriptedSkillPort(
            {
                PROPOSAL_TEMPLATE_ID: [
                    {"proposals": [_proposal(run["id"], branches=["Should we launch?"])]}
                ]
            }
        )
        _bind_port(app, port)
        response = _propose(client, run["id"], {})
        assert response.status_code == 400, response.text
        detail = response.json()["detail"]
        assert detail["code"] == "direction_proposal_requires_tree"
        assert "no branches" in detail["message"]
        assert port.calls == []
        assert _mappings(client, run["id"]) == []


def test_propose_refuses_without_ensemble_before_calling_llm(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    app = create_app()
    with TestClient(app) as client:
        run = _create_run(client, decomposition=PASSING_TREE)
        port = ScriptedSkillPort({PROPOSAL_TEMPLATE_ID: [{"proposals": [_proposal(run["id"])]}]})
        _bind_port(app, port)
        response = _propose(client, run["id"], {})
        assert response.status_code == 400, response.text
        assert response.json()["detail"]["code"] == "direction_no_ensemble"
        assert port.calls == []


def test_propose_refuses_noncompleted_anchor(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        created = client.post("/simulation/runs", json=simulation_payload(execution_mode="QUEUED"))
        assert created.status_code == 201, created.text
        response = _propose(client, created.json()["id"], {})
        assert response.status_code == 400, response.text
        assert response.json()["detail"]["code"] == "direction_requires_completed_run"


def test_propose_unknown_run_404(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        assert _propose(client, "no-such-run", {}).status_code == 404


# ---------------------------------------------------------------------------
# Propose: LLM failures (503/502, write nothing)
# ---------------------------------------------------------------------------


def test_propose_unavailable_returns_503_and_writes_nothing(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        parent, _child = _setup_family(client)
        response = _propose(client, parent["id"], {})
        assert response.status_code == 503, response.text
        assert response.json()["detail"]["code"] == "direction_propose_unavailable"
        assert _mappings(client, parent["id"]) == []


def test_propose_contract_failure_returns_502_and_writes_nothing(
    monkeypatch, tmp_path: Path
) -> None:
    setup_app(monkeypatch, tmp_path)
    app = create_app()
    with TestClient(app) as client:
        parent, _child = _setup_family(client)
        port = ScriptedSkillPort({PROPOSAL_TEMPLATE_ID: [{"wrong_key": "nope"}]})
        _bind_port(app, port)
        response = _propose(client, parent["id"], {})
        assert response.status_code == 502, response.text
        assert response.json()["detail"]["code"] == "direction_propose_contract_failed"
        assert _mappings(client, parent["id"]) == []


def test_propose_truncated_returns_502_and_writes_nothing(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    app = create_app()
    with TestClient(app) as client:
        parent, _child = _setup_family(client)
        port = ScriptedSkillPort(
            {PROPOSAL_TEMPLATE_ID: [None]},  # type: ignore[list-item]
            finish_reason_script={PROPOSAL_TEMPLATE_ID: ["length"]},
        )
        _bind_port(app, port)
        response = _propose(client, parent["id"], {})
        assert response.status_code == 502, response.text
        assert response.json()["detail"]["code"] == "direction_propose_truncated"
        assert _mappings(client, parent["id"]) == []


# ---------------------------------------------------------------------------
# No-clobber: proposals never overwrite anything
# ---------------------------------------------------------------------------


def test_propose_never_overwrites_existing_mapping(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    app = create_app()
    with TestClient(app) as client:
        parent, _child = _setup_family(client)
        created = client.post(
            f"/runs/{parent['id']}/directions/mappings",
            json={"name": "Phased rollout", "source_run_id": parent["id"], "arm": "baseline"},
        )
        assert created.status_code == 201, created.text
        port = ScriptedSkillPort(
            {
                PROPOSAL_TEMPLATE_ID: [
                    {
                        "proposals": [
                            _proposal(parent["id"], name="Phased rollout", arm="strategy"),
                            _proposal(parent["id"], name="Fresh direction"),
                        ]
                    }
                ]
            }
        )
        _bind_port(app, port)
        response = _propose(client, parent["id"], {})
        assert response.status_code == 200, response.text
        outcomes = response.json()["outcomes"]
        assert [outcome["status"] for outcome in outcomes] == ["skipped", "stored"]
        assert "already exists" in outcomes[0]["reason"]
        assert outcomes[0]["mapping_id"] is None
        rows = _mappings(client, parent["id"])
        assert len(rows) == 2
        authored = rows[0]
        assert authored["origin"] == "authored"
        assert authored["arm"] == "baseline"
        assert authored["status"] == "active"
        assert rows[1]["name"] == "Fresh direction"


def test_propose_never_overwrites_user_edited_mapping(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    app = create_app()
    with TestClient(app) as client:
        parent, child = _setup_family(client)
        derived = client.post(f"/runs/{parent['id']}/directions/derive")
        assert derived.status_code == 200, derived.text
        highest = next(
            row for row in _mappings(client, parent["id"]) if row["name"] == "Highest P50"
        )
        updated = client.put(
            f"/runs/{parent['id']}/directions/mappings/{highest['id']}",
            json={"source_run_id": child["run_id"], "arm": "strategy"},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["user_edited"] is True
        port = ScriptedSkillPort(
            {
                PROPOSAL_TEMPLATE_ID: [
                    {"proposals": [_proposal(parent["id"], name="Highest P50", arm="baseline")]}
                ]
            }
        )
        _bind_port(app, port)
        response = _propose(client, parent["id"], {})
        assert response.status_code == 200, response.text
        assert response.json()["outcomes"][0]["status"] == "skipped"
        rows = _mappings(client, parent["id"])
        kept = next(row for row in rows if row["name"] == "Highest P50")
        assert kept["source_run_id"] == child["run_id"]
        assert kept["arm"] == "strategy"
        assert kept["user_edited"] is True


def test_derive_skips_proposed_mapping(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    app = create_app()
    with TestClient(app) as client:
        parent, _child = _setup_family(client)
        port = ScriptedSkillPort(
            {
                PROPOSAL_TEMPLATE_ID: [
                    {"proposals": [_proposal(parent["id"], name="Highest P50", arm="strategy")]}
                ]
            }
        )
        _bind_port(app, port)
        proposed = _propose(client, parent["id"], {})
        assert proposed.status_code == 200, proposed.text
        derived = client.post(f"/runs/{parent['id']}/directions/derive")
        assert derived.status_code == 200, derived.text
        highest = next(
            outcome for outcome in derived.json()["outcomes"] if outcome["rule_id"] == "highest_p50"
        )
        assert highest["status"] == "skipped"
        assert "proposed" in highest["reason"]
        rows = _mappings(client, parent["id"])
        kept = next(row for row in rows if row["name"] == "Highest P50")
        assert kept["origin"] == "llm_proposal"
        assert kept["status"] == "proposed"
        assert kept["arm"] == "strategy"


# ---------------------------------------------------------------------------
# Accept / reject / generate
# ---------------------------------------------------------------------------


def test_propose_accept_narrate_end_to_end(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    app = create_app()
    with TestClient(app) as client:
        parent, _child = _setup_family(client)
        port = ScriptedSkillPort({PROPOSAL_TEMPLATE_ID: [{"proposals": [_proposal(parent["id"])]}]})
        _bind_port(app, port)
        proposed = _propose(client, parent["id"], {})
        assert proposed.status_code == 200, proposed.text
        mapping_id = proposed.json()["outcomes"][0]["mapping_id"]
        accepted = client.post(f"/runs/{parent['id']}/directions/mappings/{mapping_id}/accept")
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["status"] == "active"
        assert accepted.json()["origin"] == "llm_proposal"
        assert accepted.json()["user_edited"] is False
        assert accepted.json()["proposal_record"] is not None
        generated = client.post(f"/runs/{parent['id']}/narratives", json={})
        assert generated.status_code == 201, generated.text
        body = generated.json()
        assert body["direction_mapping_ids"] == [mapping_id]
        direction = body["body"]["directions"][0]
        assert direction["name"] == "Phased rollout"
        assert direction["mece_trace"]["branches"][0]["name"] == "Demand"
        assert direction["mece_trace"]["branches"][0]["scope"] == ["demand"]
        again = client.post(f"/runs/{parent['id']}/directions/mappings/{mapping_id}/accept")
        assert again.status_code == 400, again.text
        assert again.json()["detail"]["code"] == "direction_mapping_not_proposed"


def test_generation_ignores_proposed_mappings(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    app = create_app()
    with TestClient(app) as client:
        parent, _child = _setup_family(client)
        port = ScriptedSkillPort({PROPOSAL_TEMPLATE_ID: [{"proposals": [_proposal(parent["id"])]}]})
        _bind_port(app, port)
        proposed = _propose(client, parent["id"], {})
        assert proposed.status_code == 200, proposed.text
        generated = client.post(f"/runs/{parent['id']}/narratives", json={})
        assert generated.status_code == 400, generated.text
        assert generated.json()["detail"]["code"] == "narrative_requires_directions"


def test_reject_mapping_excludes_it_from_generation(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    app = create_app()
    with TestClient(app) as client:
        parent, _child = _setup_family(client)
        port = ScriptedSkillPort({PROPOSAL_TEMPLATE_ID: [{"proposals": [_proposal(parent["id"])]}]})
        _bind_port(app, port)
        proposed = _propose(client, parent["id"], {})
        mapping_id = proposed.json()["outcomes"][0]["mapping_id"]
        rejected = client.post(f"/runs/{parent['id']}/directions/mappings/{mapping_id}/reject")
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["status"] == "rejected"
        assert rejected.json()["proposal_record"] is not None
        generated = client.post(f"/runs/{parent['id']}/narratives", json={})
        assert generated.status_code == 400, generated.text
        assert generated.json()["detail"]["code"] == "narrative_requires_directions"
        again = client.post(f"/runs/{parent['id']}/directions/mappings/{mapping_id}/reject")
        assert again.status_code == 400, again.text
        assert again.json()["detail"]["code"] == "direction_mapping_not_proposed"
        rows = _mappings(client, parent["id"])
        assert len(rows) == 1
        assert rows[0]["status"] == "rejected"


def test_accept_revalidates_stale_references(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    app = create_app()
    with TestClient(app) as client:
        parent, _child = _setup_family(client)
        ensemble_less = _create_run(client)
        port = ScriptedSkillPort({PROPOSAL_TEMPLATE_ID: [{"proposals": [_proposal(parent["id"])]}]})
        _bind_port(app, port)
        proposed = _propose(client, parent["id"], {})
        mapping_id = proposed.json()["outcomes"][0]["mapping_id"]
        asyncio.run(_repoint_mapping(mapping_id, ensemble_less["id"]))
        refused = client.post(f"/runs/{parent['id']}/directions/mappings/{mapping_id}/accept")
        assert refused.status_code == 400, refused.text
        assert refused.json()["detail"]["code"] == "direction_source_run_no_ensemble"
        rows = _mappings(client, parent["id"])
        assert rows[0]["status"] == "proposed"
        asyncio.run(_repoint_mapping(mapping_id, parent["id"]))
        accepted = client.post(f"/runs/{parent['id']}/directions/mappings/{mapping_id}/accept")
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["status"] == "active"


def test_update_proposed_mapping_sets_user_edited_keeps_status(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    app = create_app()
    with TestClient(app) as client:
        parent, _child = _setup_family(client)
        port = ScriptedSkillPort({PROPOSAL_TEMPLATE_ID: [{"proposals": [_proposal(parent["id"])]}]})
        _bind_port(app, port)
        proposed = _propose(client, parent["id"], {})
        mapping_id = proposed.json()["outcomes"][0]["mapping_id"]
        updated = client.put(
            f"/runs/{parent['id']}/directions/mappings/{mapping_id}",
            json={"name": "Phased rollout, edited"},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["user_edited"] is True
        assert updated.json()["status"] == "proposed"
        accepted = client.post(f"/runs/{parent['id']}/directions/mappings/{mapping_id}/accept")
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["name"] == "Phased rollout, edited"


def test_accept_reject_wrong_run_404(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    app = create_app()
    with TestClient(app) as client:
        parent, _child = _setup_family(client)
        other = _create_run(client)
        port = ScriptedSkillPort({PROPOSAL_TEMPLATE_ID: [{"proposals": [_proposal(parent["id"])]}]})
        _bind_port(app, port)
        proposed = _propose(client, parent["id"], {})
        mapping_id = proposed.json()["outcomes"][0]["mapping_id"]
        accept = client.post(f"/runs/{other['id']}/directions/mappings/{mapping_id}/accept")
        assert accept.status_code == 404
        reject = client.post(f"/runs/{other['id']}/directions/mappings/{mapping_id}/reject")
        assert reject.status_code == 404
        rows = _mappings(client, parent["id"])
        assert len(rows) == 1
        assert rows[0]["status"] == "proposed"
