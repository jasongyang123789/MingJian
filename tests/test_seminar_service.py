"""Seminar service tests (Sprint 16, design §16 acceptance criteria).

Fake ports only — no live LLM calls. State is verified via the
service layer and direct table reads (GET endpoints are S17).

Acceptance coverage: 3 fake models x 3 rounds with correct board
sequences and snapshot versions; quiet convergence triggering before
the cap; an adversarial flip-flopping model running to the cap;
single-model failure isolation; failure writing zero rows except
already-passed stages.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select

from planagent.config import get_settings, reset_settings_cache
from planagent.db import get_database, reset_database_cache
from planagent.domain.enums import SimulationRunStatus
from planagent.domain.models import (
    SeminarBoardRecord,
    SeminarFinalRecord,
    SeminarRecord,
    SeminarReportRecord,
    SeminarRoundRecord,
    SimulationRun,
    generate_id,
    utc_now,
)
from planagent.services.distributions.canonical import sha256_hash
from planagent.services.seminar.models import (
    ModelPortConfig,
    RosterEntry,
    SeminarCreateRequest,
)
from planagent.services.seminar.service import (
    SeminarChairUnavailable,
    SeminarService,
    SeminarServiceError,
)
from tests.skill_fixtures import (
    ScriptedSkillPort,
    advisory_board_script,
    load_fixture,
    strategy_team_script,
)

TOPIC = "Should we launch the AI customer-service line?"


# --- harness --------------------------------------------------------------


def setup_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(
        "PLANAGENT_DATABASE_URL",
        f"sqlite+aiosqlite:///{(tmp_path / 'seminar.db').resolve().as_posix()}",
    )
    monkeypatch.setenv("PLANAGENT_EVENT_BUS_BACKEND", "memory")
    monkeypatch.setenv("PLANAGENT_OPENAI_API_KEY", "")
    monkeypatch.setenv("PLANAGENT_OPENAI_PRIMARY_API_KEY", "")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    reset_settings_cache()
    reset_database_cache()


async def make_run(
    *,
    status: str = SimulationRunStatus.COMPLETED.value,
    configuration: dict | None = None,
    summary: dict | None = None,
) -> SimulationRun:
    await get_database().ensure_initialized()
    run = SimulationRun(
        id=generate_id(),
        domain_id="corporate",
        actor_template="default",
        tick_count=2,
        seed=7,
        status=status,
        configuration=configuration or {},
        summary=summary or {},
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    async with get_database().session() as session:
        session.add(run)
        await session.commit()
        await session.refresh(run)
    return run


def reflection_payload(
    *,
    confidence: str = "medium",
    changes: list[str] | None = None,
    responses: list[dict] | None = None,
) -> dict:
    return {
        "critique": [{"weak_point": "Demand assumption untested", "reason": "No data"}],
        "responses": responses or [],
        "changes": changes or [],
        "confidence": confidence,
        "confidence_basis": "Evidence is mixed.",
        "open_questions": [],
    }


def verdict_payload(*, board_snapshot_seq: int = 0) -> dict:
    return {
        "recommendation": "Roll out in phases.",
        "ranked_alternatives": ["Phased rollout", "Full launch"],
        "confidence": "medium",
        "key_evidence": ["Runway is 14 months"],
        "load_bearing_assumptions": ["Demand grows"],
        "kill_criteria": ["Fewer than six conversions"],
        "dissent_held": ["None"],
        "rounds_summary": "Stable across rounds.",
        "board_snapshot_seq": board_snapshot_seq,
    }


def merge_scripts(*scripts: dict[str, list[dict]]) -> dict[str, list[dict]]:
    merged: dict[str, list[dict]] = {}
    for script in scripts:
        for key, queue in script.items():
            merged.setdefault(key, []).extend(copy.deepcopy(queue))
    return merged


def stable_model_script(rounds: int) -> dict[str, list[dict]]:
    """Same synthesis every round + stable reflections → converges."""
    script = merge_scripts(*[strategy_team_script(mode="standard") for _ in range(rounds)])
    script["seminar.reflect"] = [
        reflection_payload(confidence="medium", changes=[]) for _ in range(rounds)
    ]
    script["seminar.final_verdict"] = [verdict_payload(board_snapshot_seq=99)]
    return script


def flip_flop_model_script(rounds: int) -> dict[str, list[dict]]:
    """Alternating recommendations + non-empty changes → never converges."""
    alternate = load_fixture("synthesize")
    alternate = copy.deepcopy(alternate)
    alternate["recommended_option"] = "Full launch"
    parts = []
    for index in range(rounds):
        part = strategy_team_script(mode="standard")
        if index % 2 == 1:
            part["mckinsey.synthesize"] = [copy.deepcopy(alternate)]
        parts.append(part)
    script = merge_scripts(*parts)
    script["seminar.reflect"] = [
        reflection_payload(
            confidence="medium" if index % 2 == 0 else "high",
            changes=[f"changed mind in round {index + 1}"],
        )
        for index in range(rounds)
    ]
    script["seminar.final_verdict"] = [verdict_payload(board_snapshot_seq=99)]
    return script


def failing_analysis_script() -> dict[str, list[dict]]:
    script = strategy_team_script(mode="standard")
    script["mckinsey.intake_classify"] = [{}]
    return script


def failing_reflection_script(rounds: int) -> dict[str, list[dict]]:
    script = merge_scripts(*[strategy_team_script(mode="standard") for _ in range(rounds)])
    script["seminar.reflect"] = [{} for _ in range(rounds)]
    script["seminar.final_verdict"] = [verdict_payload(board_snapshot_seq=99)]
    return script


class FakePortFactory:
    """Port factory keyed by model_id; the chair gets its own port."""

    def __init__(self, ports: dict[str, ScriptedSkillPort]) -> None:
        self.ports = ports

    def __call__(self, config: ModelPortConfig) -> ScriptedSkillPort:
        port = self.ports.get(config.model_id)
        if port is None:
            raise AssertionError(f"No fake port for model {config.model_id!r}.")
        return port


def make_request(
    *,
    roster_ids: list[str],
    max_rounds: int = 3,
    pipeline: str = "strategy_team",
    mode: str = "standard",
    chair_id: str = "chair-1",
) -> SeminarCreateRequest:
    return SeminarCreateRequest(
        topic=TOPIC,
        decision_question=TOPIC,
        options=["Phased rollout", "Full launch"],
        roster=[RosterEntry(model_id=model_id) for model_id in roster_ids],
        pipeline=pipeline,  # type: ignore[arg-type]
        mode=mode,
        max_rounds=max_rounds,
        chair_model=ModelPortConfig(model_id=chair_id),
    )


def make_service(factory: FakePortFactory) -> SeminarService:
    return SeminarService(get_settings(), port_factory=factory)


async def count_rows(model: Any) -> int:
    async with get_database().session() as session:
        result = await session.execute(select(func.count()).select_from(model))
        return int(result.scalar_one())


async def board_rows() -> list[SeminarBoardRecord]:
    async with get_database().session() as session:
        result = await session.execute(select(SeminarBoardRecord).order_by(SeminarBoardRecord.seq))
        return list(result.scalars().all())


async def round_rows() -> list[SeminarRoundRecord]:
    async with get_database().session() as session:
        result = await session.execute(
            select(SeminarRoundRecord).order_by(
                SeminarRoundRecord.model_id, SeminarRoundRecord.round_no
            )
        )
        return list(result.scalars().all())


async def final_rows() -> list[SeminarFinalRecord]:
    async with get_database().session() as session:
        result = await session.execute(select(SeminarFinalRecord))
        return list(result.scalars().all())


# --- creation ---------------------------------------------------------------


async def test_create_freezes_snapshot_with_hash(monkeypatch, tmp_path: Path) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run(
        configuration={"mece": {"tree": {"topic": TOPIC}}},
        summary={"monte_carlo": {"metric": "cash"}},
    )
    service = make_service(FakePortFactory({"chair-1": ScriptedSkillPort({})}))
    async with get_database().session() as session:
        created = await service.create_seminar(session, run.id, make_request(roster_ids=["a", "b"]))
    assert created.status == "open"
    assert created.run_id == run.id
    assert created.case_snapshot_hash.startswith("sha256:")
    async with get_database().session() as session:
        record = await session.get(SeminarRecord, created.seminar_id)
        assert record is not None
        snapshot = record.case_snapshot
    assert snapshot["run_id"] == run.id
    assert snapshot["topic"] == TOPIC
    assert snapshot["options"] == ["Phased rollout", "Full launch"]
    assert isinstance(snapshot["context"], str)
    assert snapshot["mece_tree"] == {"tree": {"topic": TOPIC}}
    assert sha256_hash(snapshot) == created.case_snapshot_hash
    assert "narrative_directions" not in snapshot


async def test_create_rejects_non_completed_run(monkeypatch, tmp_path: Path) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run(status=SimulationRunStatus.PENDING.value)
    service = make_service(FakePortFactory({"chair-1": ScriptedSkillPort({})}))
    async with get_database().session() as session:
        with pytest.raises(SeminarServiceError) as exc_info:
            await service.create_seminar(session, run.id, make_request(roster_ids=["a", "b"]))
    assert exc_info.value.code == "seminar_requires_completed_run"
    assert await count_rows(SeminarRecord) == 0


async def test_create_rejects_small_and_duplicate_rosters(monkeypatch, tmp_path: Path) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    service = make_service(FakePortFactory({"chair-1": ScriptedSkillPort({})}))
    async with get_database().session() as session:
        with pytest.raises(SeminarServiceError) as exc_info:
            await service.create_seminar(session, run.id, make_request(roster_ids=["solo"]))
    assert exc_info.value.code == "seminar_roster_too_small"
    async with get_database().session() as session:
        with pytest.raises(SeminarServiceError) as exc_info:
            await service.create_seminar(session, run.id, make_request(roster_ids=["a", "a"]))
    assert exc_info.value.code == "seminar_duplicate_model_id"
    assert await count_rows(SeminarRecord) == 0


async def test_create_chair_unavailable_writes_nothing(monkeypatch, tmp_path: Path) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    service = make_service(FakePortFactory({"chair-1": ScriptedSkillPort({}, available=False)}))
    async with get_database().session() as session:
        with pytest.raises(SeminarChairUnavailable):
            await service.create_seminar(session, run.id, make_request(roster_ids=["a", "b"]))
    assert await count_rows(SeminarRecord) == 0


async def test_create_records_chair_participation_flag(monkeypatch, tmp_path: Path) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    service = make_service(FakePortFactory({"chair-1": ScriptedSkillPort({})}))
    async with get_database().session() as session:
        created = await service.create_seminar(
            session,
            run.id,
            make_request(roster_ids=["a", "chair-1"], chair_id="chair-1"),
        )
    assert created.config.chair_participates is True


# --- waves: board sequences + snapshot versions ------------------------------


async def test_three_models_three_waves_board_seq_and_snapshots(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    ports = {
        "model-a": ScriptedSkillPort(stable_model_script(3)),
        "model-b": ScriptedSkillPort(stable_model_script(3)),
        "model-c": ScriptedSkillPort(stable_model_script(3)),
        "chair-1": ScriptedSkillPort({}),
    }
    service = make_service(FakePortFactory(ports))
    async with get_database().session() as session:
        created = await service.create_seminar(
            session,
            run.id,
            make_request(roster_ids=["model-a", "model-b", "model-c"]),
        )
        wave1 = await service.advance_seminar(session, created.seminar_id)
        assert wave1.wave_no == 1
        assert wave1.status == "running"
        assert [m.board_snapshot_seq for m in wave1.per_model] == [0, 0, 0]
        wave2 = await service.advance_seminar(session, created.seminar_id)
        assert wave2.wave_no == 2
        assert [m.board_snapshot_seq for m in wave2.per_model] == [3, 3, 3]
        wave3 = await service.advance_seminar(session, created.seminar_id)
        assert wave3.wave_no == 3
        assert wave3.status == "collecting"
        assert [m.board_snapshot_seq for m in wave3.per_model] == [6, 6, 6]

    board = await board_rows()
    assert [row.seq for row in board] == [1, 2, 3, 4, 5, 6, 7, 8, 9]
    # Deterministic order: wave order x roster order, despite concurrency.
    assert [(row.seq, row.model_id, row.round_no) for row in board] == [
        (1, "model-a", 1),
        (2, "model-b", 1),
        (3, "model-c", 1),
        (4, "model-a", 2),
        (5, "model-b", 2),
        (6, "model-c", 2),
        (7, "model-a", 3),
        (8, "model-b", 3),
        (9, "model-c", 3),
    ]
    for row in board:
        assert row.digest["recommendation"] == "Phased rollout"
        assert row.digest["confidence"] == "medium"
        assert row.digest["reflection_missing"] is False

    rounds = await round_rows()
    assert len(rounds) == 9
    assert [r.board_snapshot_seq for r in rounds if r.model_id == "model-a"] == [0, 3, 6]
    # Analysis stages carry skills v2; reflection stages carry seminar v1.
    first = next(r for r in rounds if r.model_id == "model-a" and r.round_no == 1)
    assert len(first.stages) == 11
    assert all(s["template_version"] == "2" and s["contract_version"] == "2" for s in first.stages)
    assert first.reflection_stage is not None
    assert first.reflection_stage["template_id"] == "seminar.reflect"
    assert first.reflection_stage["template_version"] == "1"
    assert first.reflection_stage["contract_version"] == "1"
    # S16 writes no reports.
    assert await count_rows(SeminarReportRecord) == 0


async def test_quiet_convergence_stops_stable_model_before_cap(monkeypatch, tmp_path: Path) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    ports = {
        "stable": ScriptedSkillPort(stable_model_script(5)),
        "flipper": ScriptedSkillPort(flip_flop_model_script(5)),
        "chair-1": ScriptedSkillPort({}),
    }
    service = make_service(FakePortFactory(ports))
    async with get_database().session() as session:
        created = await service.create_seminar(
            session,
            run.id,
            make_request(roster_ids=["stable", "flipper"], max_rounds=5),
        )
        for _ in range(3):
            await service.advance_seminar(session, created.seminar_id)
        wave4 = await service.advance_seminar(session, created.seminar_id)
        # The stable model converged after round 3 and is skipped.
        assert [m.model_id for m in wave4.per_model] == ["flipper"]
        wave5 = await service.advance_seminar(session, created.seminar_id)
        assert [m.model_id for m in wave5.per_model] == ["flipper"]
        assert wave5.status == "collecting"

    rounds = await round_rows()
    assert len([r for r in rounds if r.model_id == "stable"]) == 3
    assert len([r for r in rounds if r.model_id == "flipper"]) == 5
    # The flip-flopper's digests alternate recommendations: never quiet.
    flip_digests = [
        row.digest["recommendation"] for row in await board_rows() if row.model_id == "flipper"
    ]
    assert flip_digests == [
        "Phased rollout",
        "Full launch",
        "Phased rollout",
        "Full launch",
        "Phased rollout",
    ]


# --- failure isolation --------------------------------------------------------


async def test_analysis_failure_isolates_model_and_publishes_nothing(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    ports = {
        "model-a": ScriptedSkillPort(stable_model_script(2)),
        "model-b": ScriptedSkillPort(failing_analysis_script()),
        "model-c": ScriptedSkillPort(stable_model_script(2)),
        "chair-1": ScriptedSkillPort({}),
    }
    service = make_service(FakePortFactory(ports))
    async with get_database().session() as session:
        created = await service.create_seminar(
            session,
            run.id,
            make_request(roster_ids=["model-a", "model-b", "model-c"], max_rounds=2),
        )
        wave1 = await service.advance_seminar(session, created.seminar_id)
        failed = next(m for m in wave1.per_model if m.model_id == "model-b")
        assert failed.status == "failed"
        assert [m.status for m in wave1.per_model] == [
            "completed",
            "failed",
            "completed",
        ]
        wave2 = await service.advance_seminar(session, created.seminar_id)
        assert [m.model_id for m in wave2.per_model] == ["model-a", "model-c"]

    rounds = await round_rows()
    bad = [r for r in rounds if r.model_id == "model-b"]
    assert len(bad) == 1
    assert bad[0].status == "failed"
    assert bad[0].stages == []
    assert bad[0].reflection is None
    assert bad[0].error is not None
    assert bad[0].error["kind"] == "contract"
    assert bad[0].error["stage"] == "analysis"
    board = await board_rows()
    assert all(row.model_id != "model-b" for row in board)
    assert [row.seq for row in board] == [1, 2, 3, 4]


async def test_reflection_failure_preserves_analysis_and_marks_digest(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    ports = {
        "model-a": ScriptedSkillPort(stable_model_script(2)),
        "model-b": ScriptedSkillPort(failing_reflection_script(2)),
        "chair-1": ScriptedSkillPort({}),
    }
    service = make_service(FakePortFactory(ports))
    async with get_database().session() as session:
        created = await service.create_seminar(
            session,
            run.id,
            make_request(roster_ids=["model-a", "model-b"], max_rounds=2),
        )
        wave1 = await service.advance_seminar(session, created.seminar_id)
        assert [m.status for m in wave1.per_model] == [
            "completed",
            "completed_reflection_missing",
        ]
        wave2 = await service.advance_seminar(session, created.seminar_id)
        # The reflection-failed model is terminated as failed; only A runs.
        assert [m.model_id for m in wave2.per_model] == ["model-a"]

    rounds = await round_rows()
    bad = [r for r in rounds if r.model_id == "model-b"]
    assert len(bad) == 1
    # Passed stages persist: all 11 analysis stages stored.
    assert len(bad[0].stages) == 11
    assert bad[0].reflection is None
    assert bad[0].reflection_stage is None
    assert bad[0].error is not None
    assert bad[0].error["kind"] == "contract"
    assert bad[0].error["stage"] == "reflection"
    board = await board_rows()
    bad_digest = [row for row in board if row.model_id == "model-b"]
    assert len(bad_digest) == 1
    assert bad_digest[0].digest["reflection_missing"] is True
    assert bad_digest[0].digest["confidence"] is None
    assert bad_digest[0].digest["recommendation"] == "Phased rollout"


# --- finalize -----------------------------------------------------------------


async def test_finalize_writes_verdicts_with_system_snapshot_seq(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    ports = {
        "model-a": ScriptedSkillPort(stable_model_script(2)),
        "model-b": ScriptedSkillPort(stable_model_script(2)),
        "chair-1": ScriptedSkillPort({}),
    }
    service = make_service(FakePortFactory(ports))
    async with get_database().session() as session:
        created = await service.create_seminar(
            session,
            run.id,
            make_request(roster_ids=["model-a", "model-b"], max_rounds=2),
        )
        await service.advance_seminar(session, created.seminar_id)
        await service.advance_seminar(session, created.seminar_id)
        finalized = await service.finalize_seminar(session, created.seminar_id)
        assert [f.status for f in finalized.finals] == ["final", "final"]
        again = await service.finalize_seminar(session, created.seminar_id)
        assert [f.status for f in again.finals] == ["already_final", "already_final"]

    finals = await final_rows()
    assert len(finals) == 2
    for row in finals:
        # The system-known board version (4 publications) is the audit
        # fact; the verdict JSON keeps the model's echo (99) verbatim.
        assert row.board_snapshot_seq == 4
        assert row.verdict["board_snapshot_seq"] == 99
        assert row.verdict["recommendation"] == "Roll out in phases."
        assert row.stage["template_id"] == "seminar.final_verdict"
        assert row.stage["template_version"] == "1"
        assert row.stage["contract_version"] == "1"


async def test_finalize_skips_models_without_usable_rounds(monkeypatch, tmp_path: Path) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    ports = {
        "model-a": ScriptedSkillPort(stable_model_script(1)),
        "model-b": ScriptedSkillPort(failing_analysis_script()),
        "chair-1": ScriptedSkillPort({}),
    }
    service = make_service(FakePortFactory(ports))
    async with get_database().session() as session:
        created = await service.create_seminar(
            session,
            run.id,
            make_request(roster_ids=["model-a", "model-b"], max_rounds=1),
        )
        await service.advance_seminar(session, created.seminar_id)
        finalized = await service.finalize_seminar(session, created.seminar_id)
    assert [(f.model_id, f.status) for f in finalized.finals] == [
        ("model-a", "final"),
        ("model-b", "skipped_no_usable_round"),
    ]
    assert len(await final_rows()) == 1


async def test_finalize_verdict_failure_writes_zero_rows_then_retries(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    script_a = stable_model_script(1)
    script_a["seminar.final_verdict"] = [{}, verdict_payload(board_snapshot_seq=2)]
    ports = {
        "model-a": ScriptedSkillPort(script_a),
        "model-b": ScriptedSkillPort(stable_model_script(1)),
        "chair-1": ScriptedSkillPort({}),
    }
    service = make_service(FakePortFactory(ports))
    async with get_database().session() as session:
        created = await service.create_seminar(
            session,
            run.id,
            make_request(roster_ids=["model-a", "model-b"], max_rounds=1),
        )
        await service.advance_seminar(session, created.seminar_id)
        first = await service.finalize_seminar(session, created.seminar_id)
        failed = next(f for f in first.finals if f.model_id == "model-a")
        assert failed.status == "failed"
        assert failed.error is not None
        assert failed.error["kind"] == "contract"
        assert failed.error["stage"] == "final_verdict"
        assert len(await final_rows()) == 1
        second = await service.finalize_seminar(session, created.seminar_id)
        assert [f.status for f in second.finals] == ["final", "already_final"]
    assert len(await final_rows()) == 2


# --- snapshot freeze + prompt boundaries --------------------------------------


async def test_snapshot_frozen_against_later_run_products(monkeypatch, tmp_path: Path) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run(summary={"monte_carlo": {"metric": "cash"}})
    port_a = ScriptedSkillPort(stable_model_script(1))
    ports = {
        "model-a": port_a,
        "model-b": ScriptedSkillPort(stable_model_script(1)),
        "chair-1": ScriptedSkillPort({}),
    }
    service = make_service(FakePortFactory(ports))
    async with get_database().session() as session:
        created = await service.create_seminar(
            session, run.id, make_request(roster_ids=["model-a", "model-b"])
        )
    # A product lands on the run AFTER the freeze: it must never enter.
    async with get_database().session() as session:
        stored = await session.get(SimulationRun, run.id)
        assert stored is not None
        stored.summary = {
            **(stored.summary or {}),
            "late_product_marker": "LATE-PRODUCT-XYZ",
        }
        await session.commit()
    async with get_database().session() as session:
        await service.advance_seminar(session, created.seminar_id)
    assert port_a.calls, "expected recorded stage calls"
    for call in port_a.calls:
        assert "LATE-PRODUCT-XYZ" not in call["user_content"]


async def test_round1_analysis_has_no_board_input_later_rounds_do(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    port_a = ScriptedSkillPort(stable_model_script(2))
    ports = {
        "model-a": port_a,
        "model-b": ScriptedSkillPort(stable_model_script(2)),
        "chair-1": ScriptedSkillPort({}),
    }
    service = make_service(FakePortFactory(ports))
    async with get_database().session() as session:
        created = await service.create_seminar(
            session,
            run.id,
            make_request(roster_ids=["model-a", "model-b"], max_rounds=2),
        )
        await service.advance_seminar(session, created.seminar_id)
        await service.advance_seminar(session, created.seminar_id)
    intake_calls = [
        call for call in port_a.calls if call["template_id"] == "mckinsey.intake_classify"
    ]
    assert len(intake_calls) == 2
    assert "BOARD SNAPSHOT" not in intake_calls[0]["user_content"]
    assert "BOARD SNAPSHOT" in intake_calls[1]["user_content"]
    assert "[source: model-b, round 1]" in intake_calls[1]["user_content"]
    assert "may be right or wrong" in intake_calls[1]["user_content"]


async def test_reflection_reads_only_snapshot_own_history_and_board(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    port_a = ScriptedSkillPort(stable_model_script(2))
    ports = {
        "model-a": port_a,
        "model-b": ScriptedSkillPort(stable_model_script(2)),
        "chair-1": ScriptedSkillPort({}),
    }
    service = make_service(FakePortFactory(ports))
    async with get_database().session() as session:
        created = await service.create_seminar(
            session,
            run.id,
            make_request(roster_ids=["model-a", "model-b"], max_rounds=2),
        )
        await service.advance_seminar(session, created.seminar_id)
        await service.advance_seminar(session, created.seminar_id)
    reflection_calls = [call for call in port_a.calls if call["template_id"] == "seminar.reflect"]
    assert len(reflection_calls) == 2
    second = reflection_calls[1]["user_content"]
    # Own history + board quotations present...
    assert "This round's analysis summary" in second
    assert "[source: model-b, round 1]" in second
    assert "BOARD QUOTATIONS" in second
    # ...but no other model's full stage output: the diagnosis finding
    # text (which flows through the analysis pipeline) never appears.
    assert "Support tickets grew 40% in two quarters" not in second
    # The reflection system prompt carries the trust-boundary wording.
    assert "may be right or wrong" in reflection_calls[1]["system_prompt"]


async def test_advisory_board_pipeline_round(monkeypatch, tmp_path: Path) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()

    def advisory_script() -> dict[str, list[dict]]:
        script = advisory_board_script(mode="standard")
        script["seminar.reflect"] = [reflection_payload()]
        script["seminar.final_verdict"] = [verdict_payload()]
        return script

    ports = {
        "model-a": ScriptedSkillPort(advisory_script()),
        "model-b": ScriptedSkillPort(advisory_script()),
        "chair-1": ScriptedSkillPort({}),
    }
    service = make_service(FakePortFactory(ports))
    async with get_database().session() as session:
        created = await service.create_seminar(
            session,
            run.id,
            make_request(
                roster_ids=["model-a", "model-b"],
                max_rounds=1,
                pipeline="advisory_board",
            ),
        )
        wave = await service.advance_seminar(session, created.seminar_id)
        assert [m.status for m in wave.per_model] == ["completed", "completed"]
    board = await board_rows()
    assert len(board) == 2
    for row in board:
        assert row.digest["recommendation"].startswith("validate_first: ")
        assert row.digest["key_arguments"], "positions feed key arguments"
        assert any("conversions" in kill for kill in row.digest["kill_criteria"]), (
            "chair kill criterion feeds the digest"
        )
    rounds = await round_rows()
    assert len(rounds[0].stages) == 13


async def test_advance_noop_when_all_models_terminated(monkeypatch, tmp_path: Path) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    ports = {
        "model-a": ScriptedSkillPort(stable_model_script(1)),
        "model-b": ScriptedSkillPort(stable_model_script(1)),
        "chair-1": ScriptedSkillPort({}),
    }
    service = make_service(FakePortFactory(ports))
    async with get_database().session() as session:
        created = await service.create_seminar(
            session,
            run.id,
            make_request(roster_ids=["model-a", "model-b"], max_rounds=1),
        )
        await service.advance_seminar(session, created.seminar_id)
        noop = await service.advance_seminar(session, created.seminar_id)
        assert noop.per_model == []
        assert noop.status == "collecting"
        assert noop.wave_no == 1
    assert await count_rows(SeminarRoundRecord) == 2
    assert await count_rows(SeminarBoardRecord) == 2
