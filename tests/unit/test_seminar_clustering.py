"""Deterministic clustering tests (Sprint 17, design §7.1).

Pure-function pins: normalization, item collection order and ids,
exact-duplicate pre-pass byte-stability, merge-map coverage
validation, deterministic fallback clusters, and disagreement
derivation. No LLM, no I/O.
"""

from __future__ import annotations

import pytest

from planagent.services.distributions.canonical import canonical_json
from planagent.services.seminar.clustering import (
    collect_claim_items,
    derive_disagreements,
    deterministic_clusters,
    deterministic_prepass,
    expand_clusters,
    normalize_claim_text,
    render_clustered_claims,
    render_disagreements,
    render_prepass_groups,
    render_quoted_claims,
)
from planagent.services.seminar.contracts import ClaimClusters


def _verdicts() -> list[dict]:
    return [
        {
            "model_id": "model-a",
            "verdict": {
                "key_evidence": ["Runway is 14 months", "Support tickets grew 40%"],
                "load_bearing_assumptions": ["Demand grows"],
                "kill_criteria": ["Fewer than six conversions"],
                "dissent_held": ["Full launch is viable if hiring doubles"],
            },
        },
        {
            "model_id": "model-b",
            "verdict": {
                "key_evidence": ["runway is 14 MONTHS!", "Competitor shipped first"],
                "load_bearing_assumptions": ["Demand grows", "Churn stays low"],
                "kill_criteria": ["Fewer than six conversions"],
                "dissent_held": ["None"],
            },
        },
    ]


def test_normalize_claim_text_folds_case_punctuation_whitespace() -> None:
    assert normalize_claim_text("Runway is 14 MONTHS!") == "runway is 14 months"
    assert normalize_claim_text("  Demand   grows. ") == "demand grows"
    assert normalize_claim_text("Churn stays low") == "churn stays low"


def test_collect_claim_items_orders_by_roster_then_field_with_stable_ids() -> None:
    items, excluded = collect_claim_items(
        _verdicts(), round_no_by_model={"model-a": 2, "model-b": 2}
    )
    assert excluded == 1  # model-b's "None" dissent placeholder
    assert [item["item_id"] for item in items] == [f"I{n}" for n in range(1, 11)]
    assert items[0]["model_id"] == "model-a"
    assert items[0]["field"] == "key_evidence"
    assert items[0]["text"] == "Runway is 14 months"
    assert items[0]["round_no"] == 2
    assert items[4]["field"] == "dissent_held"
    assert items[5]["model_id"] == "model-b"
    assert items[5]["normalized_text"] == "runway is 14 months"
    assert all(item["text"].strip() for item in items)


def test_collect_claim_items_skips_empty_strings() -> None:
    verdicts = [
        {
            "model_id": "m",
            "verdict": {
                "key_evidence": ["", "  ", "Real claim"],
                "load_bearing_assumptions": [],
                "kill_criteria": [],
                "dissent_held": ["None"],
            },
        }
    ]
    items, excluded = collect_claim_items(verdicts, round_no_by_model={"m": 1})
    assert [item["text"] for item in items] == ["Real claim"]
    assert excluded == 1


def test_deterministic_prepass_groups_exact_duplicates() -> None:
    items, _ = collect_claim_items(_verdicts(), round_no_by_model={"model-a": 2, "model-b": 2})
    prepass = deterministic_prepass(items)
    assert prepass["item_count"] == 10
    assert prepass["exact_duplicate_groups"] == 3
    groups = [set(group) for group in prepass["exact_groups"]]
    assert {"I1", "I6"} in groups  # runway, differing case/punctuation
    assert {"I3", "I8"} in groups  # demand grows
    assert {"I4", "I10"} in groups  # kill criterion
    assert {"I2"} in groups
    assert {"I5"} in groups


def test_deterministic_prepass_is_byte_identical_for_identical_inputs() -> None:
    items, _ = collect_claim_items(_verdicts(), round_no_by_model={"model-a": 2, "model-b": 2})
    first = canonical_json(deterministic_prepass(items))
    items2, _ = collect_claim_items(_verdicts(), round_no_by_model={"model-a": 2, "model-b": 2})
    second = canonical_json(deterministic_prepass(items2))
    assert first == second


def _prepass() -> dict:
    items, _ = collect_claim_items(_verdicts(), round_no_by_model={"model-a": 2, "model-b": 2})
    return deterministic_prepass(items)


def _llm_clusters() -> ClaimClusters:
    return ClaimClusters.model_validate(
        {
            "claims": [
                {
                    "claim": "Runway is 14 months",
                    "sources": [
                        {"item_id": "I1", "stance": "support"},
                        {"item_id": "I6", "stance": "support"},
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
                        {"item_id": "I8", "stance": "oppose"},
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
                    "sources": [{"item_id": "I9", "stance": "uncertain"}],
                },
            ]
        }
    )


def test_expand_clusters_builds_merge_map_and_expands_sources() -> None:
    expanded = expand_clusters(_llm_clusters(), prepass=_prepass())
    assert expanded["production"] == "llm"
    assert len(expanded["claims"]) == 7
    assert expanded["merge_map"] == {
        "I1": 0,
        "I6": 0,
        "I2": 1,
        "I3": 2,
        "I8": 2,
        "I4": 3,
        "I10": 3,
        "I5": 4,
        "I7": 5,
        "I9": 6,
    }
    first = expanded["claims"][0]
    assert first["merge_map"] == ["I1", "I6"]
    assert first["sources"][0] == {
        "item_id": "I1",
        "model_id": "model-a",
        "round_no": 2,
        "field": "key_evidence",
        "stance": "support",
        "original_text": "Runway is 14 months",
    }
    assert first["sources"][1]["original_text"] == "runway is 14 MONTHS!"


def test_expand_clusters_rejects_dropped_items() -> None:
    clusters = ClaimClusters.model_validate(
        {"claims": [{"claim": "Only one", "sources": [{"item_id": "I1", "stance": "support"}]}]}
    )
    with pytest.raises(ValueError, match="drops item ids"):
        expand_clusters(clusters, prepass=_prepass())


def test_expand_clusters_rejects_duplicated_items() -> None:
    payload = _llm_clusters().model_dump(mode="json")
    payload["claims"][0]["sources"].append({"item_id": "I2", "stance": "support"})
    with pytest.raises(ValueError, match="multiple claims"):
        expand_clusters(ClaimClusters.model_validate(payload), prepass=_prepass())


def test_expand_clusters_rejects_unknown_items() -> None:
    payload = _llm_clusters().model_dump(mode="json")
    payload["claims"][0]["sources"].append({"item_id": "I99", "stance": "support"})
    with pytest.raises(ValueError, match="unknown item ids"):
        expand_clusters(ClaimClusters.model_validate(payload), prepass=_prepass())


def test_deterministic_clusters_group_exact_duplicates_only() -> None:
    clusters = deterministic_clusters(_prepass())
    assert clusters["production"] == "deterministic_prepass"
    assert len(clusters["claims"]) == 7
    assert clusters["claims"][0]["claim"] == "Runway is 14 months"
    assert clusters["claims"][0]["merge_map"] == ["I1", "I6"]
    assert all(
        source["stance"] == "support" for claim in clusters["claims"] for source in claim["sources"]
    )
    assert sorted(clusters["merge_map"]) == sorted(f"I{n}" for n in range(1, 11))
    assert clusters["disagreements"] == []


def test_derive_disagreements_lists_mixed_stance_claims_with_evidence() -> None:
    expanded = expand_clusters(_llm_clusters(), prepass=_prepass())
    disagreements = expanded["disagreements"]
    assert len(disagreements) == 1
    disagreement = disagreements[0]
    assert disagreement["claim_index"] == 2
    assert disagreement["claim"] == "Demand grows"
    assert disagreement["stances"] == ["oppose", "support"]
    positions = {p["stance"]: p["sources"] for p in disagreement["positions"]}
    assert positions["support"][0]["model_id"] == "model-a"
    assert positions["oppose"][0]["model_id"] == "model-b"
    assert positions["oppose"][0]["original_text"] == "Demand grows"
    assert positions["oppose"][0]["field"] == "load_bearing_assumptions"


def test_derive_disagreements_empty_when_stances_uniform() -> None:
    claims = [
        {
            "claim": "Same view",
            "sources": [
                {
                    "item_id": "I1",
                    "model_id": "a",
                    "round_no": 1,
                    "field": "key_evidence",
                    "stance": "support",
                    "original_text": "x",
                },
                {
                    "item_id": "I2",
                    "model_id": "b",
                    "round_no": 1,
                    "field": "key_evidence",
                    "stance": "support",
                    "original_text": "x",
                },
            ],
            "merge_map": ["I1", "I2"],
        }
    ]
    assert derive_disagreements(claims) == []


def test_render_helpers_label_sources_and_groups() -> None:
    prepass = _prepass()
    quoted = render_quoted_claims(prepass)
    assert '[I1 | model-a | key_evidence] "Runway is 14 months"' in quoted
    groups = render_prepass_groups(prepass)
    assert "Exact-duplicate group: I1, I6" in groups
    expanded = expand_clusters(_llm_clusters(), prepass=prepass)
    clustered = render_clustered_claims(expanded)
    assert 'Claim 0: "Runway is 14 months"' in clustered
    assert "model-a (support, key_evidence)" in clustered
    rendered = render_disagreements(expanded)
    assert 'Disagreement on claim 2: "Demand grows"' in rendered
    assert "oppose: model-b" in rendered
