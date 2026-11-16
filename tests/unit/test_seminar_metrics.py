"""Deterministic seminar metrics tests (Sprint 17, design §7.3).

Pure-function pins: pairwise agreement rate with its denominator,
confidence distribution, Borda aggregation with the deterministic
tie-break, dedup statistics, and round statistics. No LLM, no I/O.
"""

from __future__ import annotations

from planagent.services.seminar.metrics import (
    borda_count,
    compute_metrics,
    confidence_distribution,
    dedup_statistics,
    recommendation_agreement,
    round_statistics,
)


def _verdict(
    model_id: str,
    *,
    recommendation: str,
    ranked: list[str],
    confidence: str,
) -> dict:
    return {
        "model_id": model_id,
        "verdict": {
            "recommendation": recommendation,
            "ranked_alternatives": ranked,
            "confidence": confidence,
        },
    }


def test_recommendation_agreement_counts_pairs_with_denominator() -> None:
    verdicts = [
        _verdict("a", recommendation="Roll out in phases.", ranked=["X"], confidence="medium"),
        _verdict("b", recommendation="roll  out in PHASES.", ranked=["X"], confidence="high"),
        _verdict("c", recommendation="Launch fully now.", ranked=["X"], confidence="low"),
    ]
    result = recommendation_agreement(verdicts)
    assert result["n_models"] == 3
    assert result["pairs_total"] == 3
    assert result["pairs_agreeing"] == 1  # a/b agree after normalization
    assert result["rate"] == 1 / 3


def test_recommendation_agreement_single_model_has_no_pairs() -> None:
    verdicts = [_verdict("a", recommendation="Go.", ranked=["X"], confidence="medium")]
    result = recommendation_agreement(verdicts)
    assert result["pairs_total"] == 0
    assert result["rate"] is None


def test_confidence_distribution_counts_all_levels() -> None:
    verdicts = [
        _verdict("a", recommendation="x", ranked=["X"], confidence="medium"),
        _verdict("b", recommendation="x", ranked=["X"], confidence="high"),
        _verdict("c", recommendation="x", ranked=["X"], confidence="high"),
        _verdict("d", recommendation="x", ranked=["X"], confidence="low"),
    ]
    assert confidence_distribution(verdicts) == {"low": 1, "medium": 1, "high": 2}


def test_borda_count_sums_position_points_and_breaks_ties_by_name() -> None:
    verdicts = [
        _verdict(
            "a",
            recommendation="x",
            ranked=["Phased rollout", "Full launch"],
            confidence="medium",
        ),
        _verdict(
            "b",
            recommendation="x",
            ranked=["Full launch", "Phased rollout"],
            confidence="high",
        ),
    ]
    result = borda_count(verdicts)
    assert result["totals"] == {"Full launch": 3, "Phased rollout": 3}
    assert result["ranked"] == ["Full launch", "Phased rollout"]  # tie -> name ascending
    assert result["n_models"] == 2


def test_borda_count_unranked_alternatives_earn_zero() -> None:
    verdicts = [
        _verdict("a", recommendation="x", ranked=["Alpha", "Beta"], confidence="medium"),
        _verdict("b", recommendation="x", ranked=["Beta"], confidence="medium"),
    ]
    result = borda_count(verdicts)
    # a: Alpha 2, Beta 1; b: Beta 1 -> Alpha 2, Beta 2, tie -> Alpha first.
    assert result["totals"] == {"Alpha": 2, "Beta": 2}
    assert result["ranked"] == ["Alpha", "Beta"]


def test_dedup_statistics_separates_exact_and_semantic_merges() -> None:
    clusters = {
        "production": "llm",
        "prepass": {
            "item_count": 5,
            "exact_duplicate_groups": 1,
            "exact_groups": [["I1", "I2"], ["I3"], ["I4"], ["I5"]],
        },
        "claims": [
            {"sources": [{"item_id": "I1"}, {"item_id": "I2"}]},  # exact group only
            {"sources": [{"item_id": "I3"}, {"item_id": "I4"}]},  # spans 2 groups: semantic
            {"sources": [{"item_id": "I5"}]},
        ],
    }
    result = dedup_statistics(clusters=clusters)
    assert result["original_items"] == 5
    assert result["canonical_claims"] == 3
    assert result["exact_duplicate_groups"] == 1
    assert result["semantic_merge_groups"] == 1
    assert result["cluster_production"] == "llm"


def test_round_statistics_per_model_counts_statuses_and_versions() -> None:
    rows = [
        {"model_id": "a", "round_no": 1, "status": "completed", "board_snapshot_seq": 0},
        {"model_id": "a", "round_no": 2, "status": "completed", "board_snapshot_seq": 2},
        {"model_id": "b", "round_no": 1, "status": "failed", "board_snapshot_seq": 0},
    ]
    result = round_statistics(
        roster_ids=["a", "b"],
        round_rows=rows,
        statuses={"a": "final", "b": "failed"},
    )
    assert result["total_rounds"] == 3
    assert result["per_model"]["a"] == {
        "rounds": 2,
        "status": "final",
        "board_snapshot_seqs": [0, 2],
        "round_statuses": ["completed", "completed"],
    }
    assert result["per_model"]["b"]["rounds"] == 1
    assert result["per_model"]["b"]["status"] == "failed"


def test_compute_metrics_assembles_all_sections() -> None:
    verdicts = [
        _verdict("a", recommendation="Go.", ranked=["X", "Y"], confidence="medium"),
        _verdict("b", recommendation="Go.", ranked=["X", "Y"], confidence="medium"),
    ]
    clusters = {
        "production": "llm",
        "prepass": {"item_count": 2, "exact_duplicate_groups": 0, "exact_groups": [["I1"], ["I2"]]},
        "claims": [{"sources": [{"item_id": "I1"}]}, {"sources": [{"item_id": "I2"}]}],
        "disagreements": [],
    }
    result = compute_metrics(
        verdicts=verdicts,
        clusters=clusters,
        roster_ids=["a", "b", "c"],
        round_rows=[],
        statuses={"a": "final", "b": "final", "c": "failed"},
        absent_models=[{"model_id": "c", "status": "failed", "reason": "failed"}],
    )
    assert result["recommendation_agreement"]["rate"] == 1.0
    assert result["confidence_distribution"] == {"low": 0, "medium": 2, "high": 0}
    assert result["borda"]["ranked"] == ["X", "Y"]
    assert result["disagreement_count"] == 0
    assert result["finals_used"] == 2
    assert result["roster_size"] == 3
    assert result["absent_models"][0]["model_id"] == "c"
