"""Near-duplicate pre-pass tests (Sprint 18).

Pins the deterministic token-set similarity grouping: near-duplicates
group, genuinely distinct claims do not, grouping is deterministic
and order-stable, the threshold is configurable, and the exact
grouping + deterministic fallback are untouched.
"""

from __future__ import annotations

import pytest

from planagent.services.distributions.canonical import canonical_json
from planagent.services.seminar.clustering import (
    collect_claim_items,
    deterministic_clusters,
    deterministic_prepass,
    group_near_duplicates,
    jaccard_similarity,
    normalize_claim_text,
    render_prepass_groups,
    token_set,
)


def _items(*texts: str) -> list[dict]:
    verdicts = [
        {
            "model_id": "model-a",
            "verdict": {
                "key_evidence": list(texts),
                "load_bearing_assumptions": [],
                "kill_criteria": [],
                "dissent_held": ["None"],
            },
        }
    ]
    items, _ = collect_claim_items(verdicts, round_no_by_model={"model-a": 1})
    return items


def test_jaccard_similarity_boundaries() -> None:
    assert jaccard_similarity(frozenset(), frozenset()) == 1.0
    assert jaccard_similarity(frozenset({"a"}), frozenset()) == 0.0
    assert jaccard_similarity(frozenset({"a", "b"}), frozenset({"a", "b"})) == 1.0
    assert jaccard_similarity(frozenset({"a", "b"}), frozenset({"c", "d"})) == 0.0
    # 4 shared of 5 union = exactly 0.8.
    assert (
        jaccard_similarity(
            frozenset({"support", "tickets", "grew", "40", "percent"}),
            frozenset({"support", "tickets", "grew", "40"}),
        )
        == 0.8
    )


def test_token_set_splits_normalized_text() -> None:
    assert token_set(normalize_claim_text("Runway  is, 14 months!")) == {
        "runway",
        "is",
        "14",
        "months",
    }
    assert token_set("") == frozenset()


def test_near_duplicates_group_at_the_default_threshold() -> None:
    items = _items("Support tickets grew 40 percent", "Support tickets grew 40%")
    prepass = deterministic_prepass(items)
    assert prepass["exact_groups"] == [["I1"], ["I2"]]
    assert prepass["near_duplicate_groups"] == [["I1", "I2"]]
    assert prepass["near_duplicate_group_count"] == 1
    assert prepass["near_duplicate_threshold"] == 0.8


def test_genuinely_distinct_claims_never_group() -> None:
    items = _items("Runway is 14 months", "Churn stays low", "Demand grows steadily")
    prepass = deterministic_prepass(items)
    assert prepass["near_duplicate_groups"] == [["I1"], ["I2"], ["I3"]]
    assert prepass["near_duplicate_group_count"] == 0


def test_below_threshold_pair_does_not_group() -> None:
    # {demand, grows, steadily} vs {demand, grows}: 2/3 < 0.8.
    items = _items("Demand grows steadily", "Demand grows")
    prepass = deterministic_prepass(items)
    assert prepass["near_duplicate_groups"] == [["I1"], ["I2"]]


def test_threshold_is_configurable() -> None:
    items = _items("Demand grows steadily", "Demand grows")
    assert deterministic_prepass(items, near_duplicate_threshold=0.5)[
        "near_duplicate_groups"
    ] == [["I1", "I2"]]
    assert deterministic_prepass(items, near_duplicate_threshold=1.0)[
        "near_duplicate_groups"
    ] == [["I1"], ["I2"]]


def test_invalid_threshold_refuses() -> None:
    items = _items("Demand grows")
    with pytest.raises(ValueError, match="near_duplicate_threshold"):
        deterministic_prepass(items, near_duplicate_threshold=0.0)
    with pytest.raises(ValueError, match="near_duplicate_threshold"):
        deterministic_prepass(items, near_duplicate_threshold=1.5)


def test_grouping_is_deterministic_and_byte_identical() -> None:
    items = _items(
        "Support tickets grew 40 percent",
        "Support tickets grew 40%",
        "Runway is 14 months",
        "Runway is 14 months!",
        "Churn stays low",
    )
    first = deterministic_prepass(items)
    second = deterministic_prepass(items)
    assert canonical_json(first) == canonical_json(second)
    assert first["exact_groups"] == [["I1"], ["I2"], ["I3", "I4"], ["I5"]]
    assert first["near_duplicate_groups"] == [["I1", "I2"], ["I3", "I4"], ["I5"]]


def test_grouping_uses_first_match_and_stable_representatives() -> None:
    # B is near A; C is near B but NOT near A (representative). C must
    # start its own group: no chaining through later arrivals.
    # A = {a b c d e}, B = {a b c d f} (4/6 = 0.667 — use threshold
    # 0.6), C = {a b c f g}: vs A 3/7 = 0.43, vs B 4/6 = 0.667.
    items = _items("a b c d e", "a b c d f", "a b c f g")
    prepass = deterministic_prepass(items, near_duplicate_threshold=0.6)
    assert prepass["near_duplicate_groups"] == [["I1", "I2"], ["I3"]]


def test_exact_groups_cover_every_item_exactly_once() -> None:
    items = _items("One claim", "One claim", "Another claim here", "One claim!")
    prepass = deterministic_prepass(items)
    flat_exact = [item for group in prepass["exact_groups"] for item in group]
    flat_near = [item for group in prepass["near_duplicate_groups"] for item in group]
    assert sorted(flat_exact) == ["I1", "I2", "I3", "I4"]
    assert sorted(flat_near) == ["I1", "I2", "I3", "I4"]


def test_punctuation_only_wordings_do_not_crash_grouping() -> None:
    items = _items("!!!", "???", "Demand grows")
    prepass = deterministic_prepass(items)
    # Both punctuation-only wordings normalize to "" → one exact group.
    assert prepass["exact_groups"] == [["I1", "I2"], ["I3"]]
    assert prepass["near_duplicate_groups"] == [["I1", "I2"], ["I3"]]


def test_deterministic_clusters_still_group_exact_only() -> None:
    items = _items("Support tickets grew 40 percent", "Support tickets grew 40%")
    prepass = deterministic_prepass(items)
    clusters = deterministic_clusters(prepass)
    assert len(clusters["claims"]) == 2
    assert clusters["production"] == "deterministic_prepass"


def test_group_near_duplicates_empty_input() -> None:
    assert group_near_duplicates([], {}, threshold=0.8) == []


def test_render_prepass_groups_shows_candidates_as_advisory() -> None:
    items = _items("Support tickets grew 40 percent", "Support tickets grew 40%")
    rendered = render_prepass_groups(deterministic_prepass(items))
    assert "No exact duplicates" in rendered
    assert "Near-duplicate candidate group: I1, I2" in rendered
    assert "advisory only" in rendered


def test_render_prepass_groups_skips_candidates_matching_exact_groups() -> None:
    items = _items("Runway is 14 months", "Runway is 14 months!")
    rendered = render_prepass_groups(deterministic_prepass(items))
    assert "Exact-duplicate group: I1, I2" in rendered
    assert "Near-duplicate candidate group" not in rendered
