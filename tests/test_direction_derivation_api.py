"""API tests for Sprint 14 direction derivation + persisted mappings.

Covers derivation over real scenario families (rule selection
verified against the stored ensemble summaries read back through
the API), the no-clobber rule for user-edited mappings, mapping
CRUD with refuse-before-write validation, narrative generation
from stored mappings (inline definitions win; cap 4; mapping ids
pinned), and narrative generation on robustness/gates-enriched
runs (fix batch 1: the Sprint 13 refusal is fixed, with
corrupt-fragment refusal preserved). Same scratch-SQLite +
in-memory-bus + empty-LLM-keys pattern as the Sprint 1-13 tests.
No live LLM call is ever made.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from planagent.config import reset_settings_cache
from planagent.db import get_database, reset_database_cache
from planagent.domain.models import SimulationRun
from planagent.main import create_app
from planagent.services.simulation.robustness import (
    DECISION_GATES_SUMMARY_KEY,
    ROBUSTNESS_SUMMARY_KEY,
)

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


def build_database_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.resolve().as_posix()}"


def setup_app(monkeypatch, tmp_path: Path, db_name: str = "planagent-directions.db") -> None:
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
        "company_id": "directions-test-co",
        "company_name": "Directions Test Co",
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


def _register_gates(client: TestClient, run_id: str) -> dict:
    registered = client.post(
        f"/runs/{run_id}/decision-gates",
        json={
            "gates": [
                {"name": "g1_value", "metric": "mean", "operator": ">", "threshold": 0},
            ]
        },
    )
    assert registered.status_code == 201, registered.text
    return registered.json()


async def _set_summary_fragment(run_id: str, key: str, value: object) -> None:
    """Replace one top-level summary key by direct DB write.

    Writers only ever store valid fragments, so corrupt-fragment
    cases need direct manipulation (same pattern as the monitoring
    corrupt-registration test).
    """
    database = get_database()
    async with database.session() as session:
        row = await session.get(SimulationRun, run_id)
        assert row is not None
        row.summary = {**(row.summary or {}), key: value}
        await session.commit()


async def _add_robustness_sub_fragment(run_id: str, key: str, value: object) -> None:
    database = get_database()
    async with database.session() as session:
        row = await session.get(SimulationRun, run_id)
        assert row is not None
        summary = dict(row.summary or {})
        fragment = dict(summary.get(ROBUSTNESS_SUMMARY_KEY) or {})
        fragment[key] = value
        summary[ROBUSTNESS_SUMMARY_KEY] = fragment
        row.summary = summary
        await session.commit()


def _generate(client: TestClient, run_id: str, payload: dict) -> dict:
    response = client.post(f"/runs/{run_id}/narratives", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _narrative_count(client: TestClient, run_id: str) -> int:
    listed = client.get(f"/runs/{run_id}/narratives")
    assert listed.status_code == 200, listed.text
    return len(listed.json()["narratives"])


def _branch(client: TestClient, parent_id: str, cash: float) -> dict:
    branched = client.post(
        f"/scenario/runs/{parent_id}",
        json={"fork_step": 2, "state_overrides": {"cash": cash}},
    )
    assert branched.status_code == 201, branched.text
    return branched.json()


def _expected_rule_picks(anchor_id: str, summaries: dict) -> dict:
    """Apply the documented v1 rules to summaries read back via API.

    ``summaries`` maps run id -> {"baseline": {...}, "strategy":
    {...}, "es": {"baseline": value, "strategy": value, "alpha": a}
    | None}. Returns {rule_id: (status, run_id, arm)} after dedup.
    The pure unit tests pin the rules themselves; this helper only
    checks the API path applies them to real stored data.
    """
    candidates = []
    for run_id, data in summaries.items():
        for arm in ("baseline", "strategy"):
            summary = data[arm]
            es = data["es"][arm] if data["es"] else None
            candidates.append(
                {
                    "run_id": run_id,
                    "arm": arm,
                    "p50": summary["p50"],
                    "p_loss": summary["p_loss"],
                    "es": es,
                }
            )

    def highest_key(candidate: dict) -> tuple:
        return (-candidate["p50"], candidate["p_loss"], candidate["run_id"], candidate["arm"])

    def robust_key(candidate: dict) -> tuple:
        return (
            candidate["p_loss"],
            0 if candidate["es"] is not None else 1,
            -candidate["es"] if candidate["es"] is not None else 0.0,
            -candidate["p50"],
            candidate["run_id"],
            candidate["arm"],
        )

    picks = {
        "highest_p50": min(candidates, key=highest_key),
        "most_robust": min(candidates, key=robust_key),
        "baseline_control": next(
            c for c in candidates if c["run_id"] == anchor_id and c["arm"] == "baseline"
        ),
    }
    taken: dict[tuple[str, str], str] = {}
    expected: dict[str, tuple[str, str, str]] = {}
    for rule_id in ("highest_p50", "most_robust", "baseline_control"):
        pick = picks[rule_id]
        pair = (pick["run_id"], pick["arm"])
        if pair in taken:
            expected[rule_id] = ("duplicate", pick["run_id"], pick["arm"])
        else:
            taken[pair] = rule_id
            expected[rule_id] = ("produced", pick["run_id"], pick["arm"])
    return expected


def _derive(client: TestClient, run_id: str):
    return client.post(f"/runs/{run_id}/directions/derive")


def _list_mappings(client: TestClient, run_id: str) -> dict:
    response = client.get(f"/runs/{run_id}/directions/mappings")
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Derivation
# ---------------------------------------------------------------------------


def test_derive_writes_mappings_from_family(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        parent = _create_run(client, decomposition=PASSING_TREE)
        children = [_branch(client, parent["id"], 80.0), _branch(client, parent["id"], 120.0)]
        summaries = {}
        for run_id in [parent["id"], *[branch["run_id"] for branch in children]]:
            ensemble = _create_ensemble(client, run_id)
            summaries[run_id] = {
                "baseline": ensemble["baseline"],
                "strategy": ensemble["strategy"],
                "es": None,
            }
        response = _derive(client, parent["id"])
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["rules_version"] == "derivation-rules-v1"
        assert body["derivation_hash"].startswith("sha256:")
        assert body["family_size"] == 3
        assert body["candidates_considered"] == 6
        assert [o["rule_id"] for o in body["outcomes"]] == [
            "highest_p50",
            "most_robust",
            "baseline_control",
        ]
        expected = _expected_rule_picks(parent["id"], summaries)
        for outcome in body["outcomes"]:
            status, run_id, arm = expected[outcome["rule_id"]]
            assert outcome["status"] == status
            assert outcome["source_run_id"] == run_id
            assert outcome["arm"] == arm
        produced = [o for o in body["outcomes"] if o["status"] == "produced"]
        mappings = body["mappings"]
        assert len(mappings) == len(produced)
        assert [m["position"] for m in mappings] == list(range(len(mappings)))
        for mapping, outcome in zip(mappings, produced):
            assert mapping["name"] == outcome["direction_name"]
            assert mapping["source_run_id"] == outcome["source_run_id"]
            assert mapping["arm"] == outcome["arm"]
            assert mapping["origin"] == "derived"
            assert mapping["rule_id"] == outcome["rule_id"]
            assert mapping["rules_version"] == "derivation-rules-v1"
            assert mapping["rule_record"]["derivation_hash"] == body["derivation_hash"]
            assert mapping["user_edited"] is False
        # Second derive: byte-identical derivation, same mapping rows.
        again = _derive(client, parent["id"])
        assert again.status_code == 200, again.text
        assert again.json()["derivation_hash"] == body["derivation_hash"]
        assert [m["id"] for m in again.json()["mappings"]] == [m["id"] for m in mappings]


def test_derive_refuses_without_ensemble_and_writes_nothing(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client)
        response = _derive(client, run["id"])
        assert response.status_code == 400, response.text
        detail = response.json()["detail"]
        assert detail["code"] == "direction_no_ensemble"
        assert f"/runs/{run['id']}/monte-carlo" in detail["message"]
        assert _list_mappings(client, run["id"])["mappings"] == []


def test_derive_refuses_noncompleted_anchor(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        created = client.post("/simulation/runs", json=simulation_payload(execution_mode="QUEUED"))
        assert created.status_code == 201, created.text
        response = _derive(client, created.json()["id"])
        assert response.status_code == 400, response.text
        assert response.json()["detail"]["code"] == "direction_requires_completed_run"


def test_derive_unknown_run_404(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        assert _derive(client, "no-such-run").status_code == 404


def test_derive_uses_lower_tail_shortfall(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client)
        ensemble = _create_ensemble(client, run["id"])
        es = client.post(
            f"/runs/{run['id']}/robustness/expected-shortfall",
            json={"alpha": 0.1, "tail": "lower"},
        )
        assert es.status_code == 201, es.text
        es_body = es.json()
        summaries = {
            run["id"]: {
                "baseline": ensemble["baseline"],
                "strategy": ensemble["strategy"],
                "es": {
                    "baseline": es_body["baseline"]["value"],
                    "strategy": es_body["strategy"]["value"],
                    "alpha": 0.1,
                },
            }
        }
        # Derivation must SUCCEED on the enriched run: it reads the
        # expected_shortfall sub-fragment directly (see the fix-batch-1
        # tests below for the narrative side of the same shape rule).
        response = _derive(client, run["id"])
        assert response.status_code == 200, response.text
        body = response.json()
        robust = next(o for o in body["outcomes"] if o["rule_id"] == "most_robust")
        expected = _expected_rule_picks(run["id"], summaries)
        status, run_id, arm = expected["most_robust"]
        assert robust["status"] == status
        assert robust["source_run_id"] == run_id
        assert robust["arm"] == arm
        assert robust["expected_shortfall"] == es_body[arm]["value"]
        assert robust["expected_shortfall_alpha"] == 0.1


def test_derive_ignores_upper_tail_shortfall(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client)
        _create_ensemble(client, run["id"])
        es = client.post(
            f"/runs/{run['id']}/robustness/expected-shortfall",
            json={"alpha": 0.1, "tail": "upper"},
        )
        assert es.status_code == 201, es.text
        response = _derive(client, run["id"])
        assert response.status_code == 200, response.text
        robust = next(o for o in response.json()["outcomes"] if o["rule_id"] == "most_robust")
        assert robust["expected_shortfall"] is None
        assert robust["expected_shortfall_alpha"] is None


# ---------------------------------------------------------------------------
# No-clobber rule
# ---------------------------------------------------------------------------


def test_derive_never_overwrites_user_edited_mapping(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client)
        _create_ensemble(client, run["id"])
        first = _derive(client, run["id"])
        assert first.status_code == 200, first.text
        mapping = next(m for m in first.json()["mappings"] if m["name"] == "Highest P50")
        other_arm = "strategy" if mapping["arm"] == "baseline" else "baseline"
        edited = client.put(
            f"/runs/{run['id']}/directions/mappings/{mapping['id']}",
            json={"arm": other_arm},
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["user_edited"] is True
        assert edited.json()["arm"] == other_arm
        second = _derive(client, run["id"])
        assert second.status_code == 200, second.text
        outcome = next(o for o in second.json()["outcomes"] if o["rule_id"] == "highest_p50")
        assert outcome["status"] == "skipped"
        assert "user-edited" in outcome["reason"]
        kept = next(m for m in second.json()["mappings"] if m["id"] == mapping["id"])
        assert kept["arm"] == other_arm
        assert kept["user_edited"] is True


def test_derive_recreates_freed_name_after_rename(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client)
        _create_ensemble(client, run["id"])
        first = _derive(client, run["id"])
        assert first.status_code == 200, first.text
        assert first.json()["mappings"], first.text
        freed = first.json()["mappings"][0]
        renamed = client.put(
            f"/runs/{run['id']}/directions/mappings/{freed['id']}",
            json={"name": "Renamed by hand"},
        )
        assert renamed.status_code == 200, renamed.text
        second = _derive(client, run["id"])
        assert second.status_code == 200, second.text
        names = [m["name"] for m in second.json()["mappings"]]
        assert "Renamed by hand" in names
        assert freed["name"] in names
        assert len(names) == len(set(names))


# ---------------------------------------------------------------------------
# Mapping CRUD
# ---------------------------------------------------------------------------


def test_create_mapping_and_name_conflict(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client, decomposition=PASSING_TREE)
        _create_ensemble(client, run["id"])
        created = client.post(
            f"/runs/{run['id']}/directions/mappings",
            json={"name": "Go all in", "source_run_id": run["id"], "mece_branches": ["Demand"]},
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["origin"] == "authored"
        assert body["user_edited"] is False
        assert body["position"] == 0
        assert body["rule_id"] is None
        conflict = client.post(
            f"/runs/{run['id']}/directions/mappings",
            json={"name": "Go all in", "source_run_id": run["id"]},
        )
        assert conflict.status_code == 400, conflict.text
        assert conflict.json()["detail"]["code"] == "direction_mapping_name_conflict"
        assert len(_list_mappings(client, run["id"])["mappings"]) == 1


def test_create_mapping_refusals(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client, decomposition=PASSING_TREE)
        _create_ensemble(client, run["id"])
        queued = client.post("/simulation/runs", json=simulation_payload(execution_mode="QUEUED"))
        assert queued.status_code == 201, queued.text
        bare = _create_run(client)
        cases = [
            ({"name": "A", "source_run_id": "no-such-run"}, "direction_unknown_source_run"),
            (
                {"name": "B", "source_run_id": queued.json()["id"]},
                "direction_source_run_not_completed",
            ),
            (
                {"name": "C", "source_run_id": bare["id"]},
                "direction_source_run_no_ensemble",
            ),
            (
                {"name": "D", "source_run_id": run["id"], "mece_branches": ["Nope"]},
                "direction_unknown_mece_branch",
            ),
            (
                {"name": "E", "source_run_id": run["id"], "deliberation_id": "no-such-delib"},
                "direction_deliberation_not_found",
            ),
        ]
        for payload, code in cases:
            response = client.post(f"/runs/{run['id']}/directions/mappings", json=payload)
            assert response.status_code == 400, response.text
            assert response.json()["detail"]["code"] == code
        assert _list_mappings(client, run["id"])["mappings"] == []
        # Branches without a tree: the bare run has no decomposition.
        _create_ensemble(client, bare["id"])
        response = client.post(
            f"/runs/{bare['id']}/directions/mappings",
            json={"name": "F", "source_run_id": bare["id"], "mece_branches": ["Demand"]},
        )
        assert response.status_code == 400, response.text
        assert response.json()["detail"]["code"] == "direction_mece_branches_without_tree"


def test_update_mapping_sets_user_edited_and_revalidates(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client, decomposition=PASSING_TREE)
        other = _create_run(client)
        _create_ensemble(client, run["id"])
        _create_ensemble(client, other["id"])
        created = client.post(
            f"/runs/{run['id']}/directions/mappings",
            json={"name": "Original", "source_run_id": run["id"]},
        )
        assert created.status_code == 201, created.text
        mapping_id = created.json()["id"]
        client.post(
            f"/runs/{run['id']}/directions/mappings",
            json={"name": "Taken", "source_run_id": run["id"]},
        )
        updated = client.put(
            f"/runs/{run['id']}/directions/mappings/{mapping_id}",
            json={"name": "Renamed", "source_run_id": other["id"], "arm": "strategy"},
        )
        assert updated.status_code == 200, updated.text
        body = updated.json()
        assert body["name"] == "Renamed"
        assert body["source_run_id"] == other["id"]
        assert body["arm"] == "strategy"
        assert body["user_edited"] is True
        conflict = client.put(
            f"/runs/{run['id']}/directions/mappings/{mapping_id}", json={"name": "Taken"}
        )
        assert conflict.status_code == 400, conflict.text
        assert conflict.json()["detail"]["code"] == "direction_mapping_name_conflict"
        bad_branch = client.put(
            f"/runs/{run['id']}/directions/mappings/{mapping_id}",
            json={"mece_branches": ["Nope"]},
        )
        assert bad_branch.status_code == 400, bad_branch.text
        assert bad_branch.json()["detail"]["code"] == "direction_unknown_mece_branch"
        unchanged = _list_mappings(client, run["id"])["mappings"]
        kept = next(m for m in unchanged if m["id"] == mapping_id)
        assert kept["name"] == "Renamed"
        assert kept["mece_branches"] == []


def test_mapping_wrong_run_404(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client)
        other = _create_run(client)
        _create_ensemble(client, run["id"])
        created = client.post(
            f"/runs/{run['id']}/directions/mappings",
            json={"name": "Mine", "source_run_id": run["id"]},
        )
        mapping_id = created.json()["id"]
        base = f"/runs/{other['id']}/directions/mappings/{mapping_id}"
        assert client.put(base, json={"name": "Nope"}).status_code == 404
        assert client.delete(base).status_code == 404
        assert len(_list_mappings(client, run["id"])["mappings"]) == 1


# ---------------------------------------------------------------------------
# Generation from mappings
# ---------------------------------------------------------------------------


def test_generate_from_mappings_uses_position_order_and_caps_at_four(
    monkeypatch, tmp_path: Path
) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client, decomposition=PASSING_TREE)
        _create_ensemble(client, run["id"])
        ids = []
        for index in range(5):
            created = client.post(
                f"/runs/{run['id']}/directions/mappings",
                json={"name": f"M{index}", "source_run_id": run["id"]},
            )
            assert created.status_code == 201, created.text
            ids.append(created.json()["id"])
        response = client.post(f"/runs/{run['id']}/narratives", json={"topic": "From mappings"})
        assert response.status_code == 201, response.text
        body = response.json()
        assert len(body["body"]["directions"]) == 4
        assert body["direction_mapping_ids"] == ids[:4]
        listed = client.get(f"/runs/{run['id']}/narratives").json()
        assert listed["narratives"][0]["direction_mapping_ids"] == ids[:4]


def test_generate_with_null_directions_uses_mappings(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client)
        _create_ensemble(client, run["id"])
        created = client.post(
            f"/runs/{run['id']}/directions/mappings",
            json={"name": "Stored", "source_run_id": run["id"]},
        )
        assert created.status_code == 201, created.text
        response = client.post(f"/runs/{run['id']}/narratives", json={"directions": None})
        assert response.status_code == 201, response.text
        assert response.json()["direction_mapping_ids"] == [created.json()["id"]]


def test_generate_inline_definitions_win_over_mappings(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client)
        _create_ensemble(client, run["id"])
        client.post(
            f"/runs/{run['id']}/directions/mappings",
            json={"name": "Stored", "source_run_id": run["id"]},
        )
        response = client.post(
            f"/runs/{run['id']}/narratives",
            json={
                "directions": [{"name": "Inline", "source_run_id": run["id"], "arm": "strategy"}]
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert [d["name"] for d in body["body"]["directions"]] == ["Inline"]
        assert body["direction_mapping_ids"] == []


def test_generate_without_directions_or_mappings_refuses(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client)
        _create_ensemble(client, run["id"])
        response = client.post(f"/runs/{run['id']}/narratives", json={})
        assert response.status_code == 400, response.text
        detail = response.json()["detail"]
        assert detail["code"] == "narrative_requires_directions"
        assert f"/runs/{run['id']}/directions/derive" in detail["message"]


def test_delete_mapping_leaves_narratives_untouched(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client)
        _create_ensemble(client, run["id"])
        created = client.post(
            f"/runs/{run['id']}/directions/mappings",
            json={"name": "Stored", "source_run_id": run["id"]},
        )
        mapping_id = created.json()["id"]
        generated = client.post(f"/runs/{run['id']}/narratives", json={})
        assert generated.status_code == 201, generated.text
        content_hash = generated.json()["content_hash"]
        deleted = client.delete(f"/runs/{run['id']}/directions/mappings/{mapping_id}")
        assert deleted.status_code == 204, deleted.text
        assert deleted.content == b""
        assert _list_mappings(client, run["id"])["mappings"] == []
        listed = client.get(f"/runs/{run['id']}/narratives").json()
        assert len(listed["narratives"]) == 1
        assert listed["narratives"][0]["content_hash"] == content_hash
        assert listed["narratives"][0]["direction_mapping_ids"] == [mapping_id]


# ---------------------------------------------------------------------------
# Narrative generation on enriched runs (fix batch 1)
# ---------------------------------------------------------------------------


def test_generate_succeeds_on_tornado_enriched_run(monkeypatch, tmp_path: Path) -> None:
    """Fix batch 1: the Sprint 13 refusal is fixed.

    Verified 2026-11-16 over real HTTP (see
    ~/workspace/verification/backend-integration-2026-11-16/REPORT.md
    §5): generation refused any run with tornado/gates analysis
    because ``_assemble_direction`` validated the raw stored
    fragments against read models requiring a top-level ``run_id``
    the writers never store. The fix validates each sub-fragment
    on its own model (the services' own read-path precedent) and
    injects ``run_id``.
    """
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client)
        ensemble = _create_ensemble(client, run["id"])
        tornado = client.post(f"/runs/{run['id']}/robustness/tornado", json={})
        assert tornado.status_code == 201, tornado.text
        body = _generate(
            client,
            run["id"],
            {"directions": [{"name": "D", "source_run_id": run["id"]}]},
        )
        assert body["version"] == 1
        direction = body["body"]["directions"][0]
        assert direction["name"] == "D"
        drivers = direction["drivers"]
        assert len(drivers["rows"]) == 1
        assert drivers["rows"][0]["variable"] == "cash"
        assert drivers["ensemble_id"] == ensemble["ensemble_id"]


def test_generate_succeeds_on_gates_enriched_run(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client)
        _create_ensemble(client, run["id"])
        _register_gates(client, run["id"])
        body = _generate(
            client,
            run["id"],
            {"directions": [{"name": "D", "source_run_id": run["id"]}]},
        )
        signals = body["body"]["directions"][0]["signals"]
        gate_signals = [s for s in signals if s["kind"] == "decision_gate"]
        assert len(gate_signals) == 1
        assert gate_signals[0]["name"] == "g1_value"
        assert gate_signals[0]["provenance"] == "computed"
        assert "not yet evaluated" in gate_signals[0]["text"]


def test_generate_succeeds_on_fully_enriched_run(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client)
        _create_ensemble(client, run["id"])
        tornado = client.post(f"/runs/{run['id']}/robustness/tornado", json={})
        assert tornado.status_code == 201, tornado.text
        shortfall = client.post(
            f"/runs/{run['id']}/robustness/expected-shortfall", json={"alpha": 0.05}
        )
        assert shortfall.status_code == 201, shortfall.text
        bootstrap = client.post(f"/runs/{run['id']}/robustness/bootstrap", json={"draws": 100})
        assert bootstrap.status_code == 201, bootstrap.text
        search = client.post(
            f"/runs/{run['id']}/robustness/threshold-search",
            json={
                "variable": "cash",
                "mode": "p_loss",
                "target": 0.5,
                "direction": "decreasing",
                "trials_per_evaluation": 2,
                "max_iterations": 2,
            },
        )
        assert search.status_code == 201, search.text
        _register_gates(client, run["id"])
        body = _generate(
            client,
            run["id"],
            {"directions": [{"name": "D", "source_run_id": run["id"]}]},
        )
        direction = body["body"]["directions"][0]
        assert len(direction["drivers"]["rows"]) == 1
        kinds = [s["kind"] for s in direction["signals"]]
        assert "decision_gate" in kinds
        assert "threshold_search" in kinds


def test_generate_from_mappings_succeeds_on_enriched_run(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client)
        _create_ensemble(client, run["id"])
        tornado = client.post(f"/runs/{run['id']}/robustness/tornado", json={})
        assert tornado.status_code == 201, tornado.text
        derived = client.post(f"/runs/{run['id']}/directions/derive")
        assert derived.status_code == 200, derived.text
        mapping_ids = [m["id"] for m in derived.json()["mappings"]]
        assert mapping_ids
        body = _generate(client, run["id"], {"topic": "From mappings"})
        assert body["direction_mapping_ids"] == mapping_ids[:4]
        assert len(body["body"]["directions"]) == len(mapping_ids[:4])


def test_generate_ignores_unknown_robustness_keys(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client)
        _create_ensemble(client, run["id"])
        tornado = client.post(f"/runs/{run['id']}/robustness/tornado", json={})
        assert tornado.status_code == 201, tornado.text
        asyncio.run(_add_robustness_sub_fragment(run["id"], "future_analysis", {"x": 1}))
        body = _generate(
            client,
            run["id"],
            {"directions": [{"name": "D", "source_run_id": run["id"]}]},
        )
        assert len(body["body"]["directions"][0]["drivers"]["rows"]) == 1


def _assert_corrupt_refusal(client: TestClient, run_id: str, fragment_name: str) -> None:
    response = client.post(
        f"/runs/{run_id}/narratives",
        json={"directions": [{"name": "D", "source_run_id": run_id}]},
    )
    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "narrative_corrupt_fragment"
    assert fragment_name in detail["message"]
    assert _narrative_count(client, run_id) == 0


def test_generate_refuses_wrong_shaped_tornado_fragment(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client)
        _create_ensemble(client, run["id"])
        asyncio.run(
            _set_summary_fragment(
                run["id"], ROBUSTNESS_SUMMARY_KEY, {"tornado": {"rows": "not-a-list"}}
            )
        )
        _assert_corrupt_refusal(client, run["id"], "robustness")


def test_generate_refuses_wrong_shaped_shortfall_fragment(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client)
        _create_ensemble(client, run["id"])
        asyncio.run(
            _set_summary_fragment(
                run["id"], ROBUSTNESS_SUMMARY_KEY, {"expected_shortfall": {"alpha": 0.05}}
            )
        )
        _assert_corrupt_refusal(client, run["id"], "robustness")


def test_generate_refuses_wrong_shaped_threshold_search_fragment(
    monkeypatch, tmp_path: Path
) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client)
        _create_ensemble(client, run["id"])
        asyncio.run(
            _set_summary_fragment(
                run["id"], ROBUSTNESS_SUMMARY_KEY, {"threshold_search": {"variable": "cash"}}
            )
        )
        _assert_corrupt_refusal(client, run["id"], "robustness")


def test_generate_refuses_wrong_shaped_bootstrap_fragment(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client)
        _create_ensemble(client, run["id"])
        asyncio.run(
            _set_summary_fragment(
                run["id"], ROBUSTNESS_SUMMARY_KEY, {"bootstrap": {"baseline": "not-a-list"}}
            )
        )
        _assert_corrupt_refusal(client, run["id"], "robustness")


def test_generate_refuses_non_dict_robustness_fragment(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client)
        _create_ensemble(client, run["id"])
        asyncio.run(_set_summary_fragment(run["id"], ROBUSTNESS_SUMMARY_KEY, "garbage"))
        _assert_corrupt_refusal(client, run["id"], "robustness")


def test_generate_refuses_non_dict_tornado_sub_fragment(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client)
        _create_ensemble(client, run["id"])
        asyncio.run(
            _set_summary_fragment(run["id"], ROBUSTNESS_SUMMARY_KEY, {"tornado": "garbage"})
        )
        _assert_corrupt_refusal(client, run["id"], "robustness")


def test_generate_refuses_wrong_shaped_gates_fragment(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client)
        _create_ensemble(client, run["id"])
        asyncio.run(
            _set_summary_fragment(
                run["id"], DECISION_GATES_SUMMARY_KEY, {"registrations": [{"id": "x"}]}
            )
        )
        _assert_corrupt_refusal(client, run["id"], "decision_gates")


def test_generate_refuses_non_list_gates_registrations(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client)
        _create_ensemble(client, run["id"])
        asyncio.run(
            _set_summary_fragment(run["id"], DECISION_GATES_SUMMARY_KEY, {"registrations": "nope"})
        )
        _assert_corrupt_refusal(client, run["id"], "decision_gates")


def test_generate_refuses_non_dict_gates_fragment(monkeypatch, tmp_path: Path) -> None:
    setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        run = _create_run(client)
        _create_ensemble(client, run["id"])
        asyncio.run(_set_summary_fragment(run["id"], DECISION_GATES_SUMMARY_KEY, "garbage"))
        _assert_corrupt_refusal(client, run["id"], "decision_gates")
