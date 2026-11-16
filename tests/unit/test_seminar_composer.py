"""Deterministic composer tests (Sprint 17, design §7.4/§8).

Pins: the chair path fills narrative sections from the synthesis
contract with deliberated provenance; the fallback path marks them
as not generated with the endpoint that can produce them (Sprint 13
discipline); dissent is preserved verbatim in both paths; the chair
participation flag appears when the chair also participated; and
identical stored inputs compose byte-identical documents.
"""

from __future__ import annotations

from planagent.services.distributions.canonical import canonical_json
from planagent.services.seminar.composer import compose_report

ROSTER = [
    {
        "model_id": "model-a",
        "endpoint": {"target": "primary"},
        "temperature": 0.3,
        "timeout_seconds": 180.0,
        "max_rounds": None,
        "role": "participant",
    },
    {
        "model_id": "model-b",
        "endpoint": {"target": "primary"},
        "temperature": 0.7,
        "timeout_seconds": 180.0,
        "max_rounds": None,
        "role": "participant",
    },
]

CHAIR_CONFIG = {"model_id": "chair-1", "endpoint": {"target": "extraction"}}

CLUSTERS = {
    "claims": [
        {
            "claim": "Runway is 14 months",
            "sources": [
                {
                    "item_id": "I1",
                    "model_id": "model-a",
                    "round_no": 2,
                    "field": "key_evidence",
                    "stance": "support",
                    "original_text": "Runway is 14 months",
                }
            ],
            "merge_map": ["I1"],
        },
        {
            "claim": "Fewer than six conversions kills the launch",
            "sources": [
                {
                    "item_id": "I2",
                    "model_id": "model-a",
                    "round_no": 2,
                    "field": "kill_criteria",
                    "stance": "support",
                    "original_text": "Fewer than six conversions",
                }
            ],
            "merge_map": ["I2"],
        },
    ],
    "disagreements": [
        {
            "claim_index": 0,
            "claim": "Runway is 14 months",
            "stances": ["oppose", "support"],
            "positions": [],
        }
    ],
    "merge_map": {"I1": 0, "I2": 1},
    "prepass": {"item_count": 2, "exact_groups": [["I1"], ["I2"]]},
    "production": "llm",
    "stage": {"template_id": "seminar.cluster", "template_version": "1"},
}

SYNTHESIS = {
    "unified_recommendation": "Phase the rollout over two quarters.",
    "recommendation_basis": "chair_judgment",
    "agreement_level": "low",
    "alternatives_ranked": ["Phased rollout", "Full launch"],
    "aggregation_rule": "Chair judgment weighted the runway evidence.",
    "key_evidence": [{"text": "Runway is 14 months", "source_models": ["model-a"]}],
    "kill_criteria": [{"text": "Fewer than six conversions", "source_models": ["model-a"]}],
    "minority_report": "[model-b] Fourteen months is too thin.",
    "open_questions": ["Will demand hold?"],
    "chair_notes": "Model B offered the distinctive runway challenge.",
}

METRICS = {
    "recommendation_agreement": {"n_models": 2, "pairs_total": 1, "pairs_agreeing": 0, "rate": 0.0},
    "confidence_distribution": {"low": 0, "medium": 1, "high": 1},
    "borda": {"ranked": ["Full launch", "Phased rollout"], "totals": {"Full launch": 3}},
    "dedup": {"original_items": 2, "canonical_claims": 2},
    "disagreement_count": 1,
    "rounds": {"per_model": {}, "total_rounds": 4},
    "finals_used": 2,
    "roster_size": 2,
    "absent_models": [],
}

VERDICTS = [
    {
        "model_id": "model-a",
        "verdict": {
            "rounds_summary": "Stable across rounds.",
            "dissent_held": ["Full launch is viable if hiring doubles"],
        },
        "stage": {
            "template_id": "seminar.final_verdict",
            "template_version": "1",
            "contract_version": "1",
            "model": "fixture",
        },
        "board_snapshot_seq": 4,
    },
    {
        "model_id": "model-b",
        "verdict": {
            "rounds_summary": "Shifted to full launch.",
            "dissent_held": ["Fourteen months is too thin."],
        },
        "stage": {
            "template_id": "seminar.final_verdict",
            "template_version": "1",
            "contract_version": "1",
            "model": "fixture",
        },
        "board_snapshot_seq": 4,
    },
]


def _compose(**overrides) -> dict:
    kwargs = {
        "seminar_id": "sem-1",
        "run_id": "run-1",
        "topic": "Should we launch?",
        "version": 1,
        "partial": False,
        "chair_model_id": "chair-1",
        "chair_participates": False,
        "case_snapshot_hash": "sha256:abc",
        "roster": ROSTER,
        "chair_config": CHAIR_CONFIG,
        "clusters": CLUSTERS,
        "synthesis_envelope": {
            "synthesis": SYNTHESIS,
            "stage": {"template_id": "seminar.synthesize"},
            "production_path": "chair",
            "fallback_reason": None,
            "chair_participates": False,
        },
        "computed_metrics": METRICS,
        "verdicts": VERDICTS,
        "round_rows": [
            {"model_id": "model-a", "stages": [{}, {}]},
            {"model_id": "model-b", "stages": [{}]},
        ],
        "board_rows": [{"seq": 1}, {"seq": 4}],
        "report_hash": "sha256:report",
    }
    kwargs.update(overrides)
    return compose_report(**kwargs)


def test_chair_path_fills_narrative_sections_as_deliberated() -> None:
    document = _compose()
    assert document["header"]["production_path"] == "chair"
    assert document["header"]["cluster_production"] == "llm"
    assert document["unified_recommendation"]["text"] == "Phase the rollout over two quarters."
    assert document["unified_recommendation"]["basis"] == "chair_judgment"
    assert document["unified_recommendation"]["provenance"] == "deliberated"
    assert document["agreement"]["chair_level"] == "low"
    assert document["agreement"]["computed"]["rate"] == 0.0
    assert document["alternatives"]["chair_ranked"] == ["Phased rollout", "Full launch"]
    assert document["alternatives"]["borda"]["ranked"] == ["Full launch", "Phased rollout"]
    assert document["minority_report"]["text"] == "[model-b] Fourteen months is too thin."
    assert document["minority_report"]["verbatim"] is True
    assert document["chair_synthesis"]["agreement_level"] == "low"
    assert document["open_questions"]["items"] == ["Will demand hold?"]
    assert document["chair_notes"]["provenance"] == "deliberated"


def test_chair_path_carries_claims_disagreements_and_evidence_union() -> None:
    document = _compose()
    assert len(document["canonical_claims"]["claims"]) == 2
    assert document["canonical_claims"]["merge_map"] == {"I1": 0, "I2": 1}
    assert document["canonical_claims"]["provenance"] == "deliberated"
    assert document["disagreements"]["count"] == 1
    assert document["disagreements"]["provenance"] == "computed"
    assert document["key_evidence"]["items"] == [
        {"text": "Runway is 14 months", "source_models": ["model-a"]}
    ]
    assert document["kill_criteria"]["items"] == [
        {"text": "Fewer than six conversions kills the launch", "source_models": ["model-a"]}
    ]
    assert document["rounds_evolution"][0]["rounds_summary"] == "Stable across rounds."
    assert document["rounds_evolution"][1]["board_snapshot_seq"] == 4


def test_fallback_path_marks_narrative_sections_template_with_endpoint() -> None:
    document = _compose(
        synthesis_envelope={
            "synthesis": None,
            "stage": None,
            "production_path": "deterministic_fallback",
            "fallback_reason": "synthesize stage failed (contract): bad json",
            "chair_participates": False,
        }
    )
    assert document["header"]["production_path"] == "deterministic_fallback"
    assert "synthesize stage failed" in document["header"]["fallback_reason"]
    assert document["unified_recommendation"]["provenance"] == "template"
    assert "POST /seminars/sem-1/synthesize" in document["unified_recommendation"]["text"]
    assert document["agreement"]["chair_level"] is None
    assert document["agreement"]["computed"]["rate"] == 0.0
    assert document["alternatives"]["chair_ranked"] is None
    assert document["chair_synthesis"] is None
    assert document["open_questions"]["items"] == []
    assert document["open_questions"]["provenance"] == "template"


def test_fallback_path_preserves_dissent_verbatim() -> None:
    document = _compose(
        synthesis_envelope={
            "synthesis": None,
            "stage": None,
            "production_path": "deterministic_fallback",
            "fallback_reason": "chair unavailable",
            "chair_participates": False,
        }
    )
    minority = document["minority_report"]
    assert minority["verbatim"] is True
    assert "[model-a] Full launch is viable if hiring doubles" in minority["text"]
    assert "[model-b] Fourteen months is too thin." in minority["text"]


def test_chair_participation_flag_appears_in_header() -> None:
    document = _compose(chair_participates=True)
    assert document["header"]["chair_participates"] is True
    assert "also participated" in document["header"]["chair_participation_flag"]
    assert "weighted equally" in document["header"]["chair_participation_flag"]
    plain = _compose()
    assert "chair_participation_flag" not in plain["header"]


def test_audit_appendix_records_stages_configs_and_no_token_usage() -> None:
    document = _compose()
    audit = document["audit_appendix"]
    assert audit["case_snapshot_hash"] == "sha256:abc"
    assert audit["cluster_stage"]["template_id"] == "seminar.cluster"
    assert audit["synthesis_stage"]["template_id"] == "seminar.synthesize"
    assert audit["verdict_stages"][0]["contract_version"] == "1"
    assert audit["round_stage_counts"] == {"model-a": 2, "model-b": 1}
    assert audit["board_seq_range"] == [1, 4]
    assert audit["board_publications"] == 2
    assert audit["model_configs"][1]["temperature"] == 0.7
    assert audit["chair_config"]["model_id"] == "chair-1"
    assert "S18" in audit["token_usage"]


def test_compose_is_byte_identical_for_identical_inputs() -> None:
    assert canonical_json(_compose()) == canonical_json(_compose())
    fallback = {
        "synthesis": None,
        "stage": None,
        "production_path": "deterministic_fallback",
        "fallback_reason": "x",
        "chair_participates": False,
    }
    assert canonical_json(_compose(synthesis_envelope=fallback)) == canonical_json(
        _compose(synthesis_envelope=fallback)
    )


def test_partial_header_carries_absent_models() -> None:
    metrics = dict(METRICS)
    metrics["absent_models"] = [{"model_id": "model-c", "status": "failed", "reason": "boom"}]
    metrics["roster_size"] = 3
    document = _compose(partial=True, computed_metrics=metrics)
    assert document["header"]["partial"] is True
    assert document["header"]["absent_models"][0]["model_id"] == "model-c"
