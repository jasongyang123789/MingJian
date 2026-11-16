"""Seminar synthesis service tests (Sprint 17, design §7/§8/§10.4).

Fake ports only — no live LLM calls. Covers the chair path
(clustering + synthesis + versioned report), the deterministic
fallback path (chair unavailable / chair-stage failure), the
partial mechanism (minimum finals, allow_partial, absent models),
re-synthesis versioning, the chair-participation flag, report-hash
reproducibility, and the GET read methods.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
from sqlalchemy import select

from planagent.db import get_database
from planagent.domain.models import SeminarRecord, SeminarReportRecord
from planagent.services.distributions.canonical import canonical_json
from planagent.services.seminar.models import SynthesizeRequest
from planagent.services.seminar.service import (
    SeminarServiceError,
    compute_report_hash,
)
from tests.skill_fixtures import ScriptedSkillPort, strategy_team_script
from tests.test_seminar_service import (
    FakePortFactory,
    count_rows,
    failing_analysis_script,
    make_request,
    make_run,
    make_service,
    merge_scripts,
    reflection_payload,
    setup_db,
)


def verdict_a(**overrides: object) -> dict:
    payload: dict = {
        "recommendation": "Roll out in phases.",
        "ranked_alternatives": ["Phased rollout", "Full launch"],
        "confidence": "medium",
        "key_evidence": ["Runway is 14 months", "Support tickets grew 40%"],
        "load_bearing_assumptions": ["Demand grows"],
        "kill_criteria": ["Fewer than six conversions"],
        "dissent_held": ["Full launch is viable if hiring doubles"],
        "rounds_summary": "Stable across rounds.",
        "board_snapshot_seq": 4,
    }
    payload.update(overrides)
    return payload


def verdict_b(**overrides: object) -> dict:
    payload: dict = {
        "recommendation": "Launch fully now.",
        "ranked_alternatives": ["Full launch", "Phased rollout"],
        "confidence": "high",
        "key_evidence": ["Runway is 14 months", "Competitor shipped first"],
        "load_bearing_assumptions": ["Demand grows", "Churn stays low"],
        "kill_criteria": ["Fewer than six conversions"],
        "dissent_held": ["Fourteen months of runway is too thin to bet the company"],
        "rounds_summary": "Shifted to full launch.",
        "board_snapshot_seq": 4,
    }
    payload.update(overrides)
    return payload


def cluster_payload() -> dict:
    """Covers I1..I11 exactly; claim 0 carries a genuine disagreement
    (model-b's dissent opposes the runway claim both models cite)."""
    return {
        "claims": [
            {
                "claim": "Runway is 14 months",
                "sources": [
                    {"item_id": "I1", "stance": "support"},
                    {"item_id": "I6", "stance": "support"},
                    {"item_id": "I11", "stance": "oppose"},
                ],
            },
            {
                "claim": "Support demand is rising",
                "sources": [{"item_id": "I2", "stance": "support"}],
            },
            {
                "claim": "Demand grows",
                "sources": [
                    {"item_id": "I3", "stance": "support"},
                    {"item_id": "I8", "stance": "support"},
                ],
            },
            {
                "claim": "Fewer than six conversions kills the launch",
                "sources": [
                    {"item_id": "I4", "stance": "support"},
                    {"item_id": "I10", "stance": "support"},
                ],
            },
            {
                "claim": "Full launch is viable if hiring doubles",
                "sources": [{"item_id": "I5", "stance": "support"}],
            },
            {
                "claim": "Competitor shipped first",
                "sources": [{"item_id": "I7", "stance": "support"}],
            },
            {
                "claim": "Churn stays low",
                "sources": [{"item_id": "I9", "stance": "support"}],
            },
        ]
    }


def synthesis_payload() -> dict:
    return {
        "unified_recommendation": "Phase the rollout over two quarters.",
        "recommendation_basis": "chair_judgment",
        "agreement_level": "low",
        "alternatives_ranked": ["Phased rollout", "Full launch"],
        "aggregation_rule": "Chair judgment weighted the runway evidence over the Borda tie.",
        "key_evidence": [{"text": "Runway is 14 months", "source_models": ["model-a", "model-b"]}],
        "kill_criteria": [
            {"text": "Fewer than six conversions", "source_models": ["model-a", "model-b"]}
        ],
        "minority_report": (
            "[model-a] Full launch is viable if hiring doubles\n"
            "[model-b] Fourteen months of runway is too thin to bet the company"
        ),
        "open_questions": ["Will demand hold through the second quarter?"],
        "chair_notes": "Model B offered the distinctive runway challenge.",
    }


def chair_script(*, copies: int = 1) -> dict[str, list[dict]]:
    return {
        "seminar.cluster": [copy.deepcopy(cluster_payload()) for _ in range(copies)],
        "seminar.synthesize": [copy.deepcopy(synthesis_payload()) for _ in range(copies)],
    }


def model_script(rounds: int, verdict: dict) -> dict[str, list[dict]]:
    script = merge_scripts(*[strategy_team_script(mode="standard") for _ in range(rounds)])
    script["seminar.reflect"] = [
        reflection_payload(confidence="medium", changes=[]) for _ in range(rounds)
    ]
    script["seminar.final_verdict"] = [copy.deepcopy(verdict)]
    return script


async def run_to_collecting(service, run_id: str, request, rounds: int = 2) -> str:
    async with get_database().session() as session:
        created = await service.create_seminar(session, run_id, request)
    seminar_id = created.seminar_id
    for _ in range(rounds):
        async with get_database().session() as session:
            await service.advance_seminar(session, seminar_id)
    async with get_database().session() as session:
        await service.finalize_seminar(session, seminar_id)
    return seminar_id


async def report_rows() -> list[SeminarReportRecord]:
    async with get_database().session() as session:
        result = await session.execute(
            select(SeminarReportRecord).order_by(SeminarReportRecord.version)
        )
        return list(result.scalars().all())


async def seminar_status(seminar_id: str) -> str:
    async with get_database().session() as session:
        record = await session.get(SeminarRecord, seminar_id)
        assert record is not None
        return str(record.status)


# --- chair path --------------------------------------------------------------


async def test_synthesize_chair_path_writes_versioned_report(monkeypatch, tmp_path: Path) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    ports = {
        "model-a": ScriptedSkillPort(model_script(2, verdict_a())),
        "model-b": ScriptedSkillPort(model_script(2, verdict_b())),
        "chair-1": ScriptedSkillPort(chair_script()),
    }
    service = make_service(FakePortFactory(ports))
    seminar_id = await run_to_collecting(
        service, run.id, make_request(roster_ids=["model-a", "model-b"], max_rounds=2)
    )
    assert await seminar_status(seminar_id) == "collecting"
    async with get_database().session() as session:
        read = await service.synthesize_seminar(session, seminar_id, SynthesizeRequest())
    assert read.version == 1
    assert read.partial is False
    assert read.agreement_level == "low"
    assert read.production_path == "chair"
    assert read.cluster_production == "llm"
    assert read.fallback_reason is None
    assert read.report_hash.startswith("sha256:")
    assert read.status == "reported"
    assert await seminar_status(seminar_id) == "reported"

    rows = await report_rows()
    assert len(rows) == 1
    row = rows[0]
    assert row.version == 1
    assert row.partial is False
    assert row.chair_model_id == "chair-1"
    clusters = row.clusters or {}
    assert len(clusters["claims"]) == 7
    assert sorted(clusters["merge_map"]) == sorted(f"I{n}" for n in range(1, 12))
    assert clusters["prepass"]["item_count"] == 11
    assert clusters["prepass"]["exact_duplicate_groups"] == 3
    assert clusters["prepass"]["excluded_dissent_placeholders"] == 0
    assert clusters["stage"]["template_id"] == "seminar.cluster"
    assert clusters["stage"]["template_version"] == "1"
    assert clusters["stage"]["contract_version"] == "1"
    assert len(clusters["disagreements"]) == 1
    assert clusters["disagreements"][0]["claim_index"] == 0
    synthesis = row.synthesis or {}
    assert synthesis["production_path"] == "chair"
    assert (
        synthesis["synthesis"]["unified_recommendation"] == "Phase the rollout over two quarters."
    )
    assert synthesis["stage"]["template_id"] == "seminar.synthesize"
    metrics = row.computed_metrics or {}
    assert metrics["recommendation_agreement"] == {
        "n_models": 2,
        "pairs_total": 1,
        "pairs_agreeing": 0,
        "rate": 0.0,
    }
    assert metrics["confidence_distribution"] == {"low": 0, "medium": 1, "high": 1}
    assert metrics["borda"]["totals"] == {"Full launch": 3, "Phased rollout": 3}
    assert metrics["borda"]["ranked"] == ["Full launch", "Phased rollout"]
    assert metrics["dedup"]["original_items"] == 11
    assert metrics["dedup"]["canonical_claims"] == 7
    assert metrics["dedup"]["semantic_merge_groups"] == 1
    assert metrics["disagreement_count"] == 1
    assert metrics["finals_used"] == 2
    assert metrics["absent_models"] == []


async def test_synthesize_records_chair_prompts_quote_verdicts(monkeypatch, tmp_path: Path) -> None:
    """Chair prompts carry quoted verdicts + the trust-boundary notice,
    and the cluster prompt carries the pre-pass groups."""
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    chair_port = ScriptedSkillPort(chair_script())
    ports = {
        "model-a": ScriptedSkillPort(model_script(2, verdict_a())),
        "model-b": ScriptedSkillPort(model_script(2, verdict_b())),
        "chair-1": chair_port,
    }
    service = make_service(FakePortFactory(ports))
    seminar_id = await run_to_collecting(
        service, run.id, make_request(roster_ids=["model-a", "model-b"], max_rounds=2)
    )
    async with get_database().session() as session:
        await service.synthesize_seminar(session, seminar_id, SynthesizeRequest())
    assert [call["template_id"] for call in chair_port.calls] == [
        "seminar.cluster",
        "seminar.synthesize",
    ]
    cluster_call = chair_port.calls[0]
    assert "may be right or wrong" in cluster_call["system_prompt"]
    assert '[I1 | model-a | key_evidence] "Runway is 14 months"' in cluster_call["user_content"]
    assert "Exact-duplicate group: I1, I6" in cluster_call["user_content"]
    synth_call = chair_port.calls[1]
    assert "Runway is 14 months" in synth_call["user_content"]
    assert "Disagreement on claim 0" in synth_call["user_content"]
    assert "did NOT participate" in synth_call["user_content"]


async def test_get_report_composes_the_full_document(monkeypatch, tmp_path: Path) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    service = make_service(
        FakePortFactory(
            {
                "model-a": ScriptedSkillPort(model_script(2, verdict_a())),
                "model-b": ScriptedSkillPort(model_script(2, verdict_b())),
                "chair-1": ScriptedSkillPort(chair_script()),
            }
        )
    )
    seminar_id = await run_to_collecting(
        service, run.id, make_request(roster_ids=["model-a", "model-b"], max_rounds=2)
    )
    async with get_database().session() as session:
        await service.synthesize_seminar(session, seminar_id, SynthesizeRequest())
        detail = await service.get_report(session, seminar_id, 1)
    assert detail.version == 1
    assert detail.partial is False
    document = detail.document
    assert document["header"]["production_path"] == "chair"
    assert document["unified_recommendation"]["basis"] == "chair_judgment"
    assert document["canonical_claims"]["claims"][0]["claim"] == "Runway is 14 months"
    assert document["disagreements"]["count"] == 1
    assert document["minority_report"]["text"].startswith("[model-a] Full launch is viable")
    assert document["computed_metrics"]["borda"]["ranked"] == ["Full launch", "Phased rollout"]
    assert document["audit_appendix"]["board_publications"] == 4
    assert document["audit_appendix"]["board_seq_range"] == [1, 4]
    # Composing twice from stored rows is byte-identical.
    async with get_database().session() as session:
        again = await service.get_report(session, seminar_id, 1)
    assert canonical_json(again.document) == canonical_json(document)


# --- fallback path -----------------------------------------------------------


async def test_synthesize_chair_unavailable_falls_back_and_records_it(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    # The seminar is built with a live chair port (creation checks
    # chair availability); synthesize then runs against a factory
    # whose chair port is dead.
    live_service = make_service(
        FakePortFactory(
            {
                "model-a": ScriptedSkillPort(model_script(2, verdict_a())),
                "model-b": ScriptedSkillPort(model_script(2, verdict_b())),
                "chair-1": ScriptedSkillPort(chair_script()),
            }
        )
    )
    seminar_id = await run_to_collecting(
        live_service, run.id, make_request(roster_ids=["model-a", "model-b"], max_rounds=2)
    )
    dead_chair_service = make_service(
        FakePortFactory({"chair-1": ScriptedSkillPort({}, available=False)})
    )
    async with get_database().session() as session:
        read = await dead_chair_service.synthesize_seminar(session, seminar_id, SynthesizeRequest())
    assert read.production_path == "deterministic_fallback"
    assert read.cluster_production == "deterministic_prepass"
    assert read.agreement_level is None
    assert read.fallback_reason is not None
    assert "cluster stage failed (unavailable)" in read.fallback_reason
    assert "synthesize stage failed (unavailable)" in read.fallback_reason
    assert read.status == "reported"
    rows = await report_rows()
    assert len(rows) == 1
    assert rows[0].synthesis["synthesis"] is None
    assert rows[0].synthesis["stage"] is None
    assert len(rows[0].clusters["claims"]) == 8  # 8 exact groups, no semantic merges
    assert rows[0].computed_metrics["dedup"]["semantic_merge_groups"] == 0
    assert rows[0].computed_metrics["disagreement_count"] == 0
    async with get_database().session() as session:
        detail = await dead_chair_service.get_report(session, seminar_id, 1)
    assert detail.document["unified_recommendation"]["provenance"] == "template"
    assert "POST /seminars/" in detail.document["unified_recommendation"]["text"]
    assert (
        "[model-a] Full launch is viable if hiring doubles"
        in detail.document["minority_report"]["text"]
    )


async def test_synthesize_cluster_failure_keeps_chair_synthesis(
    monkeypatch, tmp_path: Path
) -> None:
    """Cluster contract failure -> deterministic clusters, but the
    synthesize stage still runs over them (independent stages)."""
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    chair_port = ScriptedSkillPort(
        {
            "seminar.cluster": [{}],  # contract violation
            "seminar.synthesize": [synthesis_payload()],
        }
    )
    service = make_service(
        FakePortFactory(
            {
                "model-a": ScriptedSkillPort(model_script(2, verdict_a())),
                "model-b": ScriptedSkillPort(model_script(2, verdict_b())),
                "chair-1": chair_port,
            }
        )
    )
    seminar_id = await run_to_collecting(
        service, run.id, make_request(roster_ids=["model-a", "model-b"], max_rounds=2)
    )
    async with get_database().session() as session:
        read = await service.synthesize_seminar(session, seminar_id, SynthesizeRequest())
    assert read.production_path == "chair"
    assert read.cluster_production == "deterministic_prepass"
    assert "cluster stage failed (contract)" in (read.fallback_reason or "")
    rows = await report_rows()
    assert len(rows[0].clusters["claims"]) == 8
    assert rows[0].synthesis["synthesis"] is not None


async def test_synthesize_incomplete_merge_map_falls_back_to_prepass(
    monkeypatch, tmp_path: Path
) -> None:
    """A clustering that drops an item id is a contract failure:
    deterministic clusters, and the reason says so."""
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    dropped = cluster_payload()
    dropped["claims"] = dropped["claims"][:-1]  # drops I9
    chair_port = ScriptedSkillPort(
        {
            "seminar.cluster": [dropped],
            "seminar.synthesize": [synthesis_payload()],
        }
    )
    service = make_service(
        FakePortFactory(
            {
                "model-a": ScriptedSkillPort(model_script(2, verdict_a())),
                "model-b": ScriptedSkillPort(model_script(2, verdict_b())),
                "chair-1": chair_port,
            }
        )
    )
    seminar_id = await run_to_collecting(
        service, run.id, make_request(roster_ids=["model-a", "model-b"], max_rounds=2)
    )
    async with get_database().session() as session:
        read = await service.synthesize_seminar(session, seminar_id, SynthesizeRequest())
    assert read.cluster_production == "deterministic_prepass"
    assert "drops item ids" in (read.fallback_reason or "")
    rows = await report_rows()
    assert sorted(rows[0].clusters["merge_map"]) == sorted(f"I{n}" for n in range(1, 12))


# --- partial mechanism -------------------------------------------------------


async def test_synthesize_with_one_final_refuses_with_zero_rows(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    service = make_service(
        FakePortFactory(
            {
                "model-a": ScriptedSkillPort(model_script(2, verdict_a())),
                "model-b": ScriptedSkillPort(failing_analysis_script()),
                "chair-1": ScriptedSkillPort(chair_script()),
            }
        )
    )
    seminar_id = await run_to_collecting(
        service, run.id, make_request(roster_ids=["model-a", "model-b"], max_rounds=2)
    )
    assert await seminar_status(seminar_id) == "collecting"
    async with get_database().session() as session:
        with pytest.raises(SeminarServiceError) as exc_info:
            await service.synthesize_seminar(session, seminar_id, SynthesizeRequest())
    assert exc_info.value.code == "seminar_insufficient_finals"
    assert await count_rows(SeminarReportRecord) == 0
    assert await seminar_status(seminar_id) == "collecting"


async def test_synthesize_with_one_final_and_allow_partial_writes_partial_report(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    service = make_service(
        FakePortFactory(
            {
                "model-a": ScriptedSkillPort(model_script(2, verdict_a())),
                "model-b": ScriptedSkillPort(failing_analysis_script()),
                "chair-1": ScriptedSkillPort(
                    {
                        "seminar.cluster": [
                            {
                                "claims": [
                                    {
                                        "claim": "Runway is 14 months",
                                        "sources": [{"item_id": "I1", "stance": "support"}],
                                    },
                                    {
                                        "claim": "Support demand is rising",
                                        "sources": [{"item_id": "I2", "stance": "support"}],
                                    },
                                    {
                                        "claim": "Demand grows",
                                        "sources": [{"item_id": "I3", "stance": "support"}],
                                    },
                                    {
                                        "claim": "Fewer than six conversions",
                                        "sources": [{"item_id": "I4", "stance": "support"}],
                                    },
                                    {
                                        "claim": "Full launch is viable if hiring doubles",
                                        "sources": [{"item_id": "I5", "stance": "support"}],
                                    },
                                ]
                            }
                        ],
                        "seminar.synthesize": [synthesis_payload()],
                    }
                ),
            }
        )
    )
    seminar_id = await run_to_collecting(
        service, run.id, make_request(roster_ids=["model-a", "model-b"], max_rounds=2)
    )
    async with get_database().session() as session:
        read = await service.synthesize_seminar(
            session, seminar_id, SynthesizeRequest(allow_partial=True)
        )
    assert read.partial is True
    assert read.status == "partial"
    rows = await report_rows()
    assert rows[0].partial is True
    assert rows[0].computed_metrics["finals_used"] == 1
    assert rows[0].computed_metrics["roster_size"] == 2
    assert rows[0].computed_metrics["recommendation_agreement"]["rate"] is None
    absent = rows[0].computed_metrics["absent_models"]
    assert len(absent) == 1
    assert absent[0]["model_id"] == "model-b"
    assert absent[0]["status"] == "failed"
    assert "contract" in absent[0]["reason"]


async def test_synthesize_with_zero_finals_always_refuses(monkeypatch, tmp_path: Path) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    service = make_service(
        FakePortFactory(
            {
                "model-a": ScriptedSkillPort(failing_analysis_script()),
                "model-b": ScriptedSkillPort(failing_analysis_script()),
                "chair-1": ScriptedSkillPort(chair_script()),
            }
        )
    )
    seminar_id = await run_to_collecting(
        service, run.id, make_request(roster_ids=["model-a", "model-b"], max_rounds=2)
    )
    async with get_database().session() as session:
        with pytest.raises(SeminarServiceError) as exc_info:
            await service.synthesize_seminar(
                session, seminar_id, SynthesizeRequest(allow_partial=True)
            )
    assert exc_info.value.code == "seminar_no_finals"
    assert await count_rows(SeminarReportRecord) == 0


async def test_synthesize_partial_when_a_model_is_absent(monkeypatch, tmp_path: Path) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    service = make_service(
        FakePortFactory(
            {
                "model-a": ScriptedSkillPort(model_script(2, verdict_a())),
                "model-b": ScriptedSkillPort(model_script(2, verdict_b())),
                "model-c": ScriptedSkillPort(failing_analysis_script()),
                "chair-1": ScriptedSkillPort(chair_script()),
            }
        )
    )
    seminar_id = await run_to_collecting(
        service,
        run.id,
        make_request(roster_ids=["model-a", "model-b", "model-c"], max_rounds=2),
    )
    async with get_database().session() as session:
        read = await service.synthesize_seminar(session, seminar_id, SynthesizeRequest())
    assert read.partial is True
    assert read.status == "partial"
    rows = await report_rows()
    absent = rows[0].computed_metrics["absent_models"]
    assert [entry["model_id"] for entry in absent] == ["model-c"]
    assert rows[0].computed_metrics["finals_used"] == 2
    assert rows[0].computed_metrics["roster_size"] == 3


async def test_synthesize_from_open_seminar_refuses(monkeypatch, tmp_path: Path) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    service = make_service(FakePortFactory({"chair-1": ScriptedSkillPort(chair_script())}))
    async with get_database().session() as session:
        created = await service.create_seminar(
            session, run.id, make_request(roster_ids=["model-a", "model-b"])
        )
    async with get_database().session() as session:
        with pytest.raises(SeminarServiceError) as exc_info:
            await service.synthesize_seminar(session, created.seminar_id, SynthesizeRequest())
    assert exc_info.value.code == "seminar_not_ready"
    assert await count_rows(SeminarReportRecord) == 0


# --- versioning / hash / chair participation ---------------------------------


async def test_resynthesis_creates_a_new_version_with_the_same_hash(
    monkeypatch, tmp_path: Path
) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    service = make_service(
        FakePortFactory(
            {
                "model-a": ScriptedSkillPort(model_script(2, verdict_a())),
                "model-b": ScriptedSkillPort(model_script(2, verdict_b())),
                "chair-1": ScriptedSkillPort(chair_script(copies=2)),
            }
        )
    )
    seminar_id = await run_to_collecting(
        service, run.id, make_request(roster_ids=["model-a", "model-b"], max_rounds=2)
    )
    async with get_database().session() as session:
        first = await service.synthesize_seminar(session, seminar_id, SynthesizeRequest())
        second = await service.synthesize_seminar(session, seminar_id, SynthesizeRequest())
    assert first.version == 1
    assert second.version == 2
    assert first.report_hash == second.report_hash  # identical deterministic inputs
    rows = await report_rows()
    assert [row.version for row in rows] == [1, 2]
    assert await seminar_status(seminar_id) == "reported"


async def test_report_hash_recomputes_from_stored_inputs(monkeypatch, tmp_path: Path) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    service = make_service(
        FakePortFactory(
            {
                "model-a": ScriptedSkillPort(model_script(2, verdict_a())),
                "model-b": ScriptedSkillPort(model_script(2, verdict_b())),
                "chair-1": ScriptedSkillPort(chair_script()),
            }
        )
    )
    seminar_id = await run_to_collecting(
        service, run.id, make_request(roster_ids=["model-a", "model-b"], max_rounds=2)
    )
    async with get_database().session() as session:
        await service.synthesize_seminar(session, seminar_id, SynthesizeRequest())
        finals = await service.list_finals(session, seminar_id)
    rows = await report_rows()
    row = rows[0]
    verdicts = [
        {"model_id": final.model_id, "verdict": final.verdict}
        for final in sorted(finals, key=lambda f: f.model_id)
    ]
    recomputed = compute_report_hash(
        seminar_id=seminar_id,
        chair_model_id=row.chair_model_id,
        partial=row.partial,
        prepass=(row.clusters or {})["prepass"],
        cluster_production=str((row.clusters or {}).get("production")),
        computed_metrics=row.computed_metrics or {},
        verdicts=verdicts,
        synthesis_production_path=str((row.synthesis or {}).get("production_path")),
    )
    assert recomputed == row.report_hash


async def test_chair_participation_is_flagged_in_the_report(monkeypatch, tmp_path: Path) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    chair_script_merged = merge_scripts(
        model_script(2, verdict_b()),
        chair_script(),
    )
    service = make_service(
        FakePortFactory(
            {
                "model-a": ScriptedSkillPort(model_script(2, verdict_a())),
                "chair-1": ScriptedSkillPort(chair_script_merged),
            }
        )
    )
    seminar_id = await run_to_collecting(
        service,
        run.id,
        make_request(roster_ids=["model-a", "chair-1"], max_rounds=2, chair_id="chair-1"),
    )
    async with get_database().session() as session:
        await service.synthesize_seminar(session, seminar_id, SynthesizeRequest())
        detail = await service.get_report(session, seminar_id, 1)
    assert detail.document["header"]["chair_participates"] is True
    assert "also participated" in detail.document["header"]["chair_participation_flag"]
    rows = await report_rows()
    assert rows[0].synthesis["chair_participates"] is True


# --- GET reads ----------------------------------------------------------------


async def test_get_reads_return_stored_state(monkeypatch, tmp_path: Path) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    service = make_service(
        FakePortFactory(
            {
                "model-a": ScriptedSkillPort(model_script(2, verdict_a())),
                "model-b": ScriptedSkillPort(model_script(2, verdict_b())),
                "chair-1": ScriptedSkillPort(chair_script()),
            }
        )
    )
    seminar_id = await run_to_collecting(
        service, run.id, make_request(roster_ids=["model-a", "model-b"], max_rounds=2)
    )
    async with get_database().session() as session:
        await service.synthesize_seminar(session, seminar_id, SynthesizeRequest())
        detail = await service.get_seminar_detail(session, seminar_id)
        board = await service.list_board(session, seminar_id)
        rounds = await service.list_rounds(session, seminar_id)
        finals = await service.list_finals(session, seminar_id)
        reports = await service.list_reports(session, seminar_id)
        run_seminars = await service.list_seminars_for_run(session, run.id)
    assert detail.status == "reported"
    assert detail.board_publications == 4
    assert detail.board_latest_seq == 4
    assert detail.finals_count == 2
    assert [(m.model_id, m.status, m.rounds, m.has_final) for m in detail.per_model] == [
        ("model-a", "final", 2, True),
        ("model-b", "final", 2, True),
    ]
    assert [row.seq for row in board] == [1, 2, 3, 4]
    assert len(rounds) == 4
    assert all(len(row.stages) == 11 for row in rounds)
    assert [f.model_id for f in finals] == ["model-a", "model-b"]
    assert len(reports) == 1
    assert reports[0].version == 1
    assert reports[0].production_path == "chair"
    assert len(run_seminars) == 1
    assert run_seminars[0].seminar_id == seminar_id
    assert run_seminars[0].report_versions == 1


async def test_get_reads_raise_lookup_error_for_missing_ids(monkeypatch, tmp_path: Path) -> None:
    setup_db(monkeypatch, tmp_path)
    await make_run()
    service = make_service(FakePortFactory({"chair-1": ScriptedSkillPort({})}))
    async with get_database().session() as session:
        with pytest.raises(LookupError):
            await service.get_seminar_detail(session, "nope")
        with pytest.raises(LookupError):
            await service.list_board(session, "nope")
        with pytest.raises(LookupError):
            await service.get_report(session, "nope", 1)
        with pytest.raises(LookupError):
            await service.list_seminars_for_run(session, "nope")


async def test_get_report_missing_version_raises_lookup_error(monkeypatch, tmp_path: Path) -> None:
    setup_db(monkeypatch, tmp_path)
    run = await make_run()
    service = make_service(
        FakePortFactory(
            {
                "model-a": ScriptedSkillPort(model_script(2, verdict_a())),
                "model-b": ScriptedSkillPort(model_script(2, verdict_b())),
                "chair-1": ScriptedSkillPort(chair_script()),
            }
        )
    )
    seminar_id = await run_to_collecting(
        service, run.id, make_request(roster_ids=["model-a", "model-b"], max_rounds=2)
    )
    async with get_database().session() as session:
        await service.synthesize_seminar(session, seminar_id, SynthesizeRequest())
        with pytest.raises(LookupError):
            await service.get_report(session, seminar_id, 99)
