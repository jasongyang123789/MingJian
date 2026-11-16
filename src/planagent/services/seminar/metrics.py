"""Deterministic seminar metrics (Sprint 17, design §7.3).

Pure functions over stored verdicts, clusters, and rounds — computed
in code, never in a prompt (the Sprint 6 PanelTally precedent). The
computed metrics are presented ALONGSIDE the chair's judgment in the
report; neither substitutes for the other.

* Recommendation agreement rate: pairs of models whose normalized
  recommendations match, over all model pairs. The denominator is
  always recorded (``n`` models, ``pairs_total`` pairs) so a partial
  report can never imply full-panel consensus.
* Confidence distribution: counts of low/medium/high over verdicts.
* Borda count: each model's ranking awards ``len(ranked) - position``
  points per alternative; totals sum across models. Ties break by
  alternative name (ascending) so the ranking is deterministic.
  Alternatives a model did not rank earn 0 from that model.
* Dedup statistics: original items → canonical claims, exact
  duplicate groups, semantic merge groups (claims spanning more than
  one exact group).
* Disagreement count: canonical claims with mixed stances.
* Round statistics: per-model rounds, derived status, and board
  snapshot versions seen.
"""

from __future__ import annotations

from itertools import combinations
from typing import Any

from planagent.services.seminar.board import normalize_recommendation


def recommendation_agreement(
    verdicts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Pairwise recommendation agreement over normalized recommendations."""
    normalized = [
        normalize_recommendation(str(entry["verdict"].get("recommendation") or ""))
        for entry in verdicts
    ]
    pairs = list(combinations(range(len(normalized)), 2))
    agreeing = sum(1 for left, right in pairs if normalized[left] == normalized[right])
    total = len(pairs)
    return {
        "n_models": len(verdicts),
        "pairs_total": total,
        "pairs_agreeing": agreeing,
        "rate": (agreeing / total) if total else None,
    }


def confidence_distribution(verdicts: list[dict[str, Any]]) -> dict[str, int]:
    """Counts of low/medium/high confidence over verdicts."""
    counts = {"low": 0, "medium": 0, "high": 0}
    for entry in verdicts:
        confidence = str(entry["verdict"].get("confidence") or "")
        if confidence in counts:
            counts[confidence] += 1
    return counts


def borda_count(verdicts: list[dict[str, Any]]) -> dict[str, Any]:
    """Borda aggregation over the verdicts' ranked alternatives.

    Each model awards ``len(ranked) - position`` points to each
    alternative it ranks (first place earns the most). Totals sum
    across models; the ranking orders by total descending, then
    alternative name ascending (deterministic tie-break).
    """
    totals: dict[str, int] = {}
    for entry in verdicts:
        ranked = entry["verdict"].get("ranked_alternatives") or []
        width = len(ranked)
        for position, alternative in enumerate(ranked):
            name = str(alternative)
            totals[name] = totals.get(name, 0) + (width - position)
    ranking = sorted(totals.items(), key=lambda item: (-item[1], item[0]))
    return {
        "method": "borda: each model awards len(ranked)-position points per ranked alternative; ties break by alternative name ascending",
        "n_models": len(verdicts),
        "totals": {name: total for name, total in ranking},
        "ranked": [name for name, _ in ranking],
    }


def dedup_statistics(
    *,
    clusters: dict[str, Any],
) -> dict[str, Any]:
    """Original items → canonical claims, exact vs semantic merges."""
    prepass = clusters.get("prepass") or {}
    exact_groups: list[list[str]] = prepass.get("exact_groups") or []
    group_of: dict[str, int] = {}
    for index, group in enumerate(exact_groups):
        for item_id in group:
            group_of[str(item_id)] = index
    claims = clusters.get("claims") or []
    semantic_merges = 0
    for claim in claims:
        groups = {group_of.get(str(source["item_id"])) for source in claim["sources"]}
        if len(groups) > 1:
            semantic_merges += 1
    return {
        "original_items": int(prepass.get("item_count", 0)),
        "canonical_claims": len(claims),
        "exact_duplicate_groups": int(prepass.get("exact_duplicate_groups", 0)),
        "semantic_merge_groups": semantic_merges,
        "cluster_production": str(clusters.get("production", "unknown")),
    }


def round_statistics(
    *,
    roster_ids: list[str],
    round_rows: list[dict[str, Any]],
    statuses: dict[str, str],
) -> dict[str, Any]:
    """Per-model round counts, derived statuses, board versions seen."""
    per_model: dict[str, Any] = {}
    for model_id in roster_ids:
        rows = [row for row in round_rows if str(row["model_id"]) == model_id]
        per_model[model_id] = {
            "rounds": len(rows),
            "status": statuses.get(model_id, "unknown"),
            "board_snapshot_seqs": sorted({int(row["board_snapshot_seq"]) for row in rows}),
            "round_statuses": [str(row["status"]) for row in sorted(rows, key=lambda r: int(r["round_no"]))],
        }
    return {
        "per_model": per_model,
        "total_rounds": len(round_rows),
    }


def compute_metrics(
    *,
    verdicts: list[dict[str, Any]],
    clusters: dict[str, Any],
    roster_ids: list[str],
    round_rows: list[dict[str, Any]],
    statuses: dict[str, str],
    absent_models: list[dict[str, Any]],
) -> dict[str, Any]:
    """Assemble the full computed-metrics block for a report."""
    return {
        "recommendation_agreement": recommendation_agreement(verdicts),
        "confidence_distribution": confidence_distribution(verdicts),
        "borda": borda_count(verdicts),
        "dedup": dedup_statistics(clusters=clusters),
        "disagreement_count": len(clusters.get("disagreements") or []),
        "rounds": round_statistics(
            roster_ids=roster_ids, round_rows=round_rows, statuses=statuses
        ),
        "finals_used": len(verdicts),
        "roster_size": len(roster_ids),
        "absent_models": absent_models,
    }


__all__ = [
    "borda_count",
    "compute_metrics",
    "confidence_distribution",
    "dedup_statistics",
    "recommendation_agreement",
    "round_statistics",
]
