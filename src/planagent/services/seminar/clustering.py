"""Deterministic claim clustering support (Sprint 17, design §7.1).

Pure functions over stored final verdicts — no LLM, no I/O:

* :func:`collect_claim_items` extracts every clusterable item from
  the verdicts (key evidence, load-bearing assumptions, kill
  criteria, dissent held), in roster order, each with a stable item
  id (``I1``, ``I2``, ...). The dissent placeholder ``"None"`` (the
  template's "I hold no dissent" marker) is excluded and counted.
* :func:`normalize_claim_text` implements the design's
  normalization (case / whitespace / punctuation) for exact-duplicate
  detection.
* :func:`deterministic_prepass` groups items by normalized text into
  exact-duplicate groups, and additionally groups exact groups whose
  wordings are near-duplicates (Sprint 18): deterministic normalized
  token-set similarity, no LLM. Near-duplicate groups are ADVISORY —
  they are shown to the chair (model or agent) as merge candidates;
  the deterministic fallback never merges distinct wordings.
* :func:`expand_clusters` validates an LLM clustering against the
  pre-pass (every item id in exactly one claim) and expands each
  source with the item's stored facts, building the auditable merge
  map in code.
* :func:`deterministic_clusters` builds clusters from the pre-pass
  alone (the cluster-stage fallback): one canonical claim per exact
  group, stance ``support`` throughout — the group's author asserted
  each item.
* :func:`derive_disagreements` lists every claim whose sources
  disagree, with both sides' evidence. Disagreements are identified,
  never resolved.

The merge map is a mapping ``item_id -> claim index`` covering every
pre-pass item exactly once. It is built in code, never trusted from
model output.
"""

from __future__ import annotations

import re
import string
from typing import Any

from planagent.services.seminar.contracts import ClaimClusters

#: Verdict fields whose list items are clusterable claims, in the
#: order items are collected (fixed, so item ids are stable).
CLUSTERABLE_FIELDS: tuple[str, ...] = (
    "key_evidence",
    "load_bearing_assumptions",
    "kill_criteria",
    "dissent_held",
)

#: The dissent placeholder: a model holding no dissent writes exactly
#: this (design §6 / final-verdict template). It is not a claim.
DISSENT_PLACEHOLDER = "None"

_PUNCTUATION_RE = re.compile(f"[{re.escape(string.punctuation)}]")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_claim_text(text: str) -> str:
    """Normalize claim text for exact-duplicate detection: lowercase,
    strip punctuation, collapse whitespace."""
    lowered = text.strip().lower()
    stripped = _PUNCTUATION_RE.sub("", lowered)
    return _WHITESPACE_RE.sub(" ", stripped).strip()


#: Default Jaccard threshold for near-duplicate grouping (Sprint 18).
#: Two wordings group when their normalized token sets are at least
#: this similar. Configurable per seminar; pinned by tests.
DEFAULT_NEAR_DUPLICATE_THRESHOLD = 0.8


def token_set(normalized_text: str) -> frozenset[str]:
    """The normalized token set of a claim: whitespace-split words."""
    return frozenset(normalized_text.split())


def jaccard_similarity(left: frozenset[str], right: frozenset[str]) -> float:
    """Jaccard similarity of two token sets.

    Two empty sets are identical (1.0) — both wordings normalized to
    nothing (pure punctuation); an empty set against a non-empty one
    is 0.0. Empty wordings share one exact group anyway, so this edge
    only matters for grouping across exact groups.
    """
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def group_near_duplicates(
    exact_groups: list[list[str]],
    items_by_id: dict[str, dict[str, Any]],
    *,
    threshold: float,
) -> list[list[str]]:
    """Group exact groups into near-duplicate groups, deterministically.

    Single-pass greedy grouping in first-appearance order: each exact
    group joins the FIRST earlier near-duplicate group whose
    representative (the first exact group's token set) is at least
    ``threshold`` similar; otherwise it starts a new group. The
    representative never moves, so grouping is stable and order
    independent of later arrivals — identical inputs always produce
    identical groups. Returns item-id lists (exact groups flattened,
    in order); singleton groups are included so every exact group
    appears exactly once.
    """
    representatives: list[frozenset[str]] = []
    groups: list[list[str]] = []
    for exact_group in exact_groups:
        first_item = items_by_id[exact_group[0]]
        tokens = token_set(str(first_item["normalized_text"]))
        placed = False
        for index, representative in enumerate(representatives):
            if jaccard_similarity(tokens, representative) >= threshold:
                groups[index].extend(exact_group)
                placed = True
                break
        if not placed:
            representatives.append(tokens)
            groups.append(list(exact_group))
    return groups


def collect_claim_items(
    verdicts: list[dict[str, Any]],
    *,
    round_no_by_model: dict[str, int],
) -> tuple[list[dict[str, Any]], int]:
    """Extract clusterable items from verdicts, in input order.

    ``verdicts`` are ``{"model_id": ..., "verdict": {...}}`` dicts in
    roster order. Returns ``(items, excluded_placeholders)``: each
    item carries a stable id, its source model/round/field, and the
    verbatim text. Empty strings are skipped (not claims).
    """
    items: list[dict[str, Any]] = []
    excluded = 0
    counter = 0
    for entry in verdicts:
        model_id = str(entry["model_id"])
        verdict = entry["verdict"] or {}
        for field_name in CLUSTERABLE_FIELDS:
            values = verdict.get(field_name) or []
            for value in values:
                text = str(value)
                if not text.strip():
                    continue
                if field_name == "dissent_held" and text.strip() == DISSENT_PLACEHOLDER:
                    excluded += 1
                    continue
                counter += 1
                items.append(
                    {
                        "item_id": f"I{counter}",
                        "model_id": model_id,
                        "round_no": int(round_no_by_model.get(model_id, 0)),
                        "field": field_name,
                        "text": text,
                        "normalized_text": normalize_claim_text(text),
                    }
                )
    return items, excluded


def deterministic_prepass(
    items: list[dict[str, Any]],
    *,
    near_duplicate_threshold: float = DEFAULT_NEAR_DUPLICATE_THRESHOLD,
) -> dict[str, Any]:
    """Group items by normalized text into exact-duplicate groups, plus
    near-duplicate groups over the exact groups (Sprint 18).

    Returns ``{"items": [...], "exact_groups": [[item_ids...], ...],
    "exact_duplicate_groups": n, "near_duplicate_groups":
    [[item_ids...], ...], "near_duplicate_group_count": m,
    "near_duplicate_threshold": t, "item_count": len(items)}``. Groups
    are ordered by first appearance; items within a group keep
    collection order. Fully deterministic: identical inputs produce
    byte-identical output under canonical JSON. Near-duplicate groups
    are advisory merge candidates for the chair; they never change
    the exact grouping, and the deterministic fallback clusters on
    exact groups only.
    """
    if not 0.0 < near_duplicate_threshold <= 1.0:
        raise ValueError(
            f"near_duplicate_threshold must be in (0, 1]; got {near_duplicate_threshold}."
        )
    groups: dict[str, list[str]] = {}
    order: list[str] = []
    for item in items:
        key = str(item["normalized_text"])
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(str(item["item_id"]))
    exact_groups = [groups[key] for key in order]
    items_by_id = {str(item["item_id"]): item for item in items}
    near_groups = group_near_duplicates(
        exact_groups, items_by_id, threshold=near_duplicate_threshold
    )
    return {
        "items": [dict(item) for item in items],
        "exact_groups": exact_groups,
        "exact_duplicate_groups": sum(1 for group in exact_groups if len(group) > 1),
        "near_duplicate_groups": near_groups,
        "near_duplicate_group_count": sum(1 for group in near_groups if len(group) > 1),
        "near_duplicate_threshold": near_duplicate_threshold,
        "item_count": len(items),
    }


def _validate_coverage(claims: list[dict[str, Any]], item_ids: frozenset[str]) -> None:
    seen: list[str] = []
    for claim in claims:
        for source in claim.get("sources") or []:
            seen.append(str(source["item_id"]))
    unknown = sorted(set(seen) - set(item_ids))
    if unknown:
        raise ValueError(f"Clustering references unknown item ids: {', '.join(unknown)}.")
    duplicates = sorted({item for item in seen if seen.count(item) > 1})
    if duplicates:
        raise ValueError(
            f"Clustering assigns item ids to multiple claims: {', '.join(duplicates)}."
        )
    missing = sorted(set(item_ids) - set(seen))
    if missing:
        raise ValueError(f"Clustering drops item ids: {', '.join(missing)}.")


def expand_clusters(
    clusters: ClaimClusters,
    *,
    prepass: dict[str, Any],
    production: str = "llm",
) -> dict[str, Any]:
    """Validate + expand a clustering into the stored shape.

    Every pre-pass item id must appear in exactly one claim's sources;
    violations raise ``ValueError`` (the caller treats this as a
    cluster-stage contract failure and falls back to deterministic
    clusters). Sources are expanded with the item's stored facts and
    the merge map (``item_id -> claim index``) is built in code.
    ``production`` names who produced the grouping (``llm`` for the
    model chair, ``agent_chair`` for an agent-chair submission); the
    validation is identical either way.
    """
    items_by_id = {str(item["item_id"]): item for item in prepass["items"]}
    raw_claims = [claim.model_dump(mode="json") for claim in clusters.claims]
    _validate_coverage(raw_claims, frozenset(items_by_id))
    claims: list[dict[str, Any]] = []
    merge_map: dict[str, int] = {}
    for index, raw in enumerate(raw_claims):
        sources: list[dict[str, Any]] = []
        for source in raw["sources"]:
            item = items_by_id[str(source["item_id"])]
            sources.append(
                {
                    "item_id": str(item["item_id"]),
                    "model_id": str(item["model_id"]),
                    "round_no": int(item["round_no"]),
                    "field": str(item["field"]),
                    "stance": str(source["stance"]),
                    "original_text": str(item["text"]),
                }
            )
            merge_map[str(item["item_id"])] = index
        claims.append(
            {
                "claim": str(raw["claim"]),
                "sources": sources,
                "merge_map": [str(source["item_id"]) for source in raw["sources"]],
            }
        )
    return {
        "claims": claims,
        "disagreements": derive_disagreements(claims),
        "merge_map": merge_map,
        "prepass": prepass,
        "production": production,
    }


def deterministic_clusters(prepass: dict[str, Any]) -> dict[str, Any]:
    """Build clusters from the pre-pass alone (cluster fallback).

    One canonical claim per exact group, worded with the first item's
    verbatim text; every source stance is ``support`` (each item's
    author asserted it). No semantic merging happens here — nothing
    can be merged away, and no disagreement can be hidden, because no
    two distinct wordings are ever grouped.
    """
    items_by_id = {str(item["item_id"]): item for item in prepass["items"]}
    claims: list[dict[str, Any]] = []
    merge_map: dict[str, int] = {}
    for index, group in enumerate(prepass["exact_groups"]):
        first = items_by_id[group[0]]
        sources = [
            {
                "item_id": str(item_id),
                "model_id": str(items_by_id[item_id]["model_id"]),
                "round_no": int(items_by_id[item_id]["round_no"]),
                "field": str(items_by_id[item_id]["field"]),
                "stance": "support",
                "original_text": str(items_by_id[item_id]["text"]),
            }
            for item_id in group
        ]
        for item_id in group:
            merge_map[str(item_id)] = index
        claims.append(
            {
                "claim": str(first["text"]),
                "sources": sources,
                "merge_map": [str(item_id) for item_id in group],
            }
        )
    return {
        "claims": claims,
        "disagreements": derive_disagreements(claims),
        "merge_map": merge_map,
        "prepass": prepass,
        "production": "deterministic_prepass",
    }


def derive_disagreements(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """List every claim whose sources disagree, with both sides' evidence.

    A claim disagrees when its sources carry more than one distinct
    stance. Positions group sources by stance, each with verbatim
    evidence pointers (model, round, field, original text).
    """
    disagreements: list[dict[str, Any]] = []
    for index, claim in enumerate(claims):
        stances = {str(source["stance"]) for source in claim["sources"]}
        if len(stances) < 2:
            continue
        positions: dict[str, list[dict[str, Any]]] = {}
        for source in claim["sources"]:
            positions.setdefault(str(source["stance"]), []).append(
                {
                    "model_id": str(source["model_id"]),
                    "round_no": int(source["round_no"]),
                    "field": str(source["field"]),
                    "original_text": str(source["original_text"]),
                }
            )
        disagreements.append(
            {
                "claim_index": index,
                "claim": str(claim["claim"]),
                "stances": sorted(stances),
                "positions": [
                    {"stance": stance, "sources": positions[stance]} for stance in sorted(positions)
                ],
            }
        )
    return disagreements


def render_quoted_claims(prepass: dict[str, Any]) -> str:
    """Render pre-pass items as labeled quotations for the cluster prompt."""
    lines = []
    for item in prepass["items"]:
        lines.append(f'[{item["item_id"]} | {item["model_id"]} | {item["field"]}] "{item["text"]}"')
    return "\n".join(lines) if lines else "(No clusterable claims in the verdicts.)"


def render_prepass_groups(prepass: dict[str, Any]) -> str:
    """Render the exact-duplicate and near-duplicate groups for the
    cluster prompt. Near-duplicate groups are advisory merge
    candidates (deterministic token-set similarity, Sprint 18): the
    chair adjudicates whether they are the same claim."""
    lines: list[str] = []
    exact = [group for group in prepass["exact_groups"] if len(group) > 1]
    if exact:
        for group in exact:
            lines.append("Exact-duplicate group: " + ", ".join(group))
    else:
        lines.append("(No exact duplicates found by the deterministic pre-pass.)")
    near = [
        group
        for group in prepass.get("near_duplicate_groups") or []
        if len(group) > 1
        and not any(set(group) == set(exact_group) for exact_group in exact)
    ]
    threshold = prepass.get("near_duplicate_threshold", DEFAULT_NEAR_DUPLICATE_THRESHOLD)
    if near:
        lines.append(
            f"Near-duplicate candidate groups (Jaccard >= {threshold}, advisory only):"
        )
        for group in near:
            lines.append("Near-duplicate candidate group: " + ", ".join(group))
    return "\n".join(lines)


def render_clustered_claims(clusters: dict[str, Any]) -> str:
    """Render expanded clusters for the synthesize prompt."""
    claims = clusters.get("claims") or []
    if not claims:
        return "(No canonical claims.)"
    lines = []
    for index, claim in enumerate(claims):
        sources = "; ".join(
            f"{s['model_id']} ({s['stance']}, {s['field']})" for s in claim["sources"]
        )
        lines.append(f'Claim {index}: "{claim["claim"]}" — sources: {sources}')
    return "\n".join(lines)


def render_disagreements(clusters: dict[str, Any]) -> str:
    """Render derived disagreements for the synthesize prompt."""
    disagreements = clusters.get("disagreements") or []
    if not disagreements:
        return "(No disagreements: no canonical claim carries differing stances.)"
    lines = []
    for disagreement in disagreements:
        lines.append(
            f'Disagreement on claim {disagreement["claim_index"]}: "{disagreement["claim"]}"'
        )
        for position in disagreement["positions"]:
            evidence = "; ".join(
                f'{s["model_id"]}: "{s["original_text"]}"' for s in position["sources"]
            )
            lines.append(f"  {position['stance']}: {evidence}")
    return "\n".join(lines)


__all__ = [
    "CLUSTERABLE_FIELDS",
    "DEFAULT_NEAR_DUPLICATE_THRESHOLD",
    "DISSENT_PLACEHOLDER",
    "collect_claim_items",
    "derive_disagreements",
    "deterministic_clusters",
    "deterministic_prepass",
    "expand_clusters",
    "group_near_duplicates",
    "jaccard_similarity",
    "normalize_claim_text",
    "render_clustered_claims",
    "render_disagreements",
    "render_prepass_groups",
    "render_quoted_claims",
    "token_set",
]
