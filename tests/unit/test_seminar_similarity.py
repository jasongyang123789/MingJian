"""Similarity upgrade tests (Sprint 19).

Pins the deterministic similarity scorer: CJK-aware tokenization,
conservative English stemming, the MAX(token, bigram) combined
score, and the pluggable embedding interface. The Sprint 18
near-duplicate tests pass UNCHANGED under the new scorer (verified
separately); nothing here re-pins a changed expectation — every
grouping the old scorer produced is preserved.
"""

from __future__ import annotations

import pytest

from planagent.services.seminar.clustering import (
    collect_claim_items,
    deterministic_prepass,
)
from planagent.services.seminar.similarity import (
    CosineVectorScorer,
    EmbeddingClaimSimilarity,
    JaccardClaimSimilarity,
    StaticVectorProvider,
    char_bigram_similarity,
    combined_similarity,
    jaccard_similarity,
    similarity_tokens,
    stem_word,
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


# --- stemming -----------------------------------------------------------


def test_stem_word_strips_inflections() -> None:
    assert stem_word("tickets") == "ticket"
    assert stem_word("grows") == "grow"
    assert stem_word("months") == "month"
    assert stem_word("claims") == "claim"
    assert stem_word("stories") == "story"
    assert stem_word("tries") == "try"
    assert stem_word("growing") == "grow"
    assert stem_word("running") == "run"
    assert stem_word("stayed") == "stay"
    assert stem_word("stopped") == "stop"
    assert stem_word("passes") == "pass"
    assert stem_word("watches") == "watch"
    assert stem_word("needed") == "need"
    assert stem_word("ties") == "tie"


def test_stem_word_never_merges_distinct_stems() -> None:
    # Guarded endings keep their final "s".
    assert stem_word("this") == "this"
    assert stem_word("class") == "class"
    assert stem_word("status") == "status"
    assert stem_word("goes") == "goes"
    assert stem_word("does") == "does"
    # Short words and digits are untouched.
    assert stem_word("is") == "is"
    assert stem_word("ring") == "ring"
    assert stem_word("bed") == "bed"
    assert stem_word("40") == "40"
    assert stem_word("q3") == "q3"
    # True double-consonant stems are not undoubled.
    assert stem_word("passing") == "pass"
    assert stem_word("filling") == "fill"
    # Conservative under-merge: no "e" is re-added.
    assert stem_word("agreed") == "agre"


# --- CJK-aware tokenization ----------------------------------------------


def test_similarity_tokens_split_cjk_characters() -> None:
    assert similarity_tokens("需求增长") == {"需", "求", "增", "长"}
    assert similarity_tokens("需求增长。") == {"需", "求", "增", "长"}


def test_similarity_tokens_mix_cjk_and_latin_runs() -> None:
    assert similarity_tokens("需求 grows 40") == {"需", "求", "grow", "40"}
    assert similarity_tokens("runway 14个月") == {"runway", "14", "个", "月"}


def test_similarity_tokens_stem_latin_words() -> None:
    assert similarity_tokens("tickets grew") == {"ticket", "grew"}
    assert similarity_tokens("support tickets grew 40 percent") == {
        "support",
        "ticket",
        "grew",
        "40",
        "percent",
    }


# --- bigram similarity ----------------------------------------------------


def test_char_bigram_similarity_edges() -> None:
    assert char_bigram_similarity("", "") == 1.0
    assert char_bigram_similarity("a", "a") == 1.0
    # Distinct single characters must NOT group via empty bigram sets.
    assert char_bigram_similarity("a", "b") == 0.0
    assert char_bigram_similarity("", "ab") == 0.0


def test_char_bigram_similarity_counts_shared_bigrams() -> None:
    # "demandgrows" (10 bigrams) is a prefix of "demandgrowssteadily"
    # (18 bigrams): 10 shared of 18 union.
    assert char_bigram_similarity("demand grows", "demand grows steadily") == pytest.approx(10 / 18)
    # "supportticketsgrew40" (19 bigrams) is a prefix of
    # "supportticketsgrew40percent" (26 bigrams): 19 of 26.
    assert char_bigram_similarity(
        "support tickets grew 40 percent", "support tickets grew 40"
    ) == pytest.approx(19 / 26)


# --- combined score: MAX, pinned both ways ---------------------------------


def test_combined_score_is_the_max_of_both_signals() -> None:
    # Tokens-only: token Jaccard 4/5 = 0.8, bigram 19/26 < 0.8.
    assert combined_similarity(
        "support tickets grew 40 percent", "support tickets grew 40"
    ) == pytest.approx(0.8)
    assert (
        jaccard_similarity(
            similarity_tokens("support tickets grew 40 percent"),
            similarity_tokens("support tickets grew 40"),
        )
        == 0.8
    )
    assert (
        char_bigram_similarity("support tickets grew 40 percent", "support tickets grew 40") < 0.8
    )


def test_combined_score_groups_on_bigrams_alone() -> None:
    # Synthetic boundary pin: single distinct tokens (token Jaccard
    # 0.0) whose bigram sets share 8 of 10 (0.8 exactly).
    assert (
        jaccard_similarity(similarity_tokens("abcdefghij"), similarity_tokens("abcdefghix")) == 0.0
    )
    assert char_bigram_similarity("abcdefghij", "abcdefghix") == 0.8
    assert combined_similarity("abcdefghij", "abcdefghix") == 0.8
    items = _items("abcdefghij", "abcdefghix")
    prepass = deterministic_prepass(items)
    assert prepass["near_duplicate_groups"] == [["I1", "I2"]]


def test_combined_score_below_threshold_on_both_signals_stays_split() -> None:
    # Token 2/3, bigram 10/18: MAX 2/3 < 0.8.
    assert combined_similarity("demand grows steadily", "demand grows") == pytest.approx(2 / 3)
    items = _items("Demand grows steadily", "Demand grows")
    prepass = deterministic_prepass(items)
    assert prepass["near_duplicate_groups"] == [["I1"], ["I2"]]


# --- grouping behavior ------------------------------------------------------


def test_stemming_merges_inflections_in_grouping() -> None:
    items = _items("Tickets grow fast", "Ticket grows fast")
    prepass = deterministic_prepass(items)
    assert prepass["exact_groups"] == [["I1"], ["I2"]]
    assert prepass["near_duplicate_groups"] == [["I1", "I2"]]


def test_cjk_grouping_with_and_without_spaces() -> None:
    # Identical characters, different spacing: separate exact groups,
    # one near-duplicate group (token score 1.0).
    items = _items("需求增长", "需求 增长")
    prepass = deterministic_prepass(items)
    assert prepass["exact_groups"] == [["I1"], ["I2"]]
    assert prepass["near_duplicate_groups"] == [["I1", "I2"]]


def test_cjk_grouping_follows_the_threshold() -> None:
    # Token 4/6, bigram 3/5: combined 2/3 — split at 0.8, grouped at 0.6.
    items = _items("需求增长强劲", "需求增长")
    assert deterministic_prepass(items)["near_duplicate_groups"] == [["I1"], ["I2"]]
    assert deterministic_prepass(items, near_duplicate_threshold=0.6)["near_duplicate_groups"] == [
        ["I1", "I2"]
    ]


def test_prepass_records_the_similarity_provider() -> None:
    items = _items("Demand grows")
    assert deterministic_prepass(items)["similarity_provider"] == "jaccard"
    assert JaccardClaimSimilarity().name == "jaccard"


def test_distinct_single_character_claims_never_group() -> None:
    items = _items("a", "b")
    prepass = deterministic_prepass(items)
    assert prepass["near_duplicate_groups"] == [["I1"], ["I2"]]


# --- embedding interface ----------------------------------------------------


def test_cosine_vector_scorer_boundaries() -> None:
    scorer = CosineVectorScorer()
    assert scorer.score([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert scorer.score([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert scorer.score([1.0, 0.0], [-1.0, 0.0]) == 0.0  # clamped
    assert scorer.score([0.0, 0.0], [1.0, 0.0]) == 0.0
    assert scorer.score([1.0, 0.0], [1.0, 0.0, 0.0]) == 0.0  # mismatch
    assert scorer.score([], []) == 0.0


def test_static_vector_provider_lookup() -> None:
    provider = StaticVectorProvider({"demand grows": (1.0, 0.0)})
    assert provider.vector_for("demand grows") == (1.0, 0.0)
    assert provider.vector_for("unknown text") is None


def test_embedding_similarity_uses_vectors_not_text() -> None:
    provider = StaticVectorProvider(
        {
            "runway is 14 months": (1.0, 0.0),
            "churn stays low": (1.0, 0.0),
            "demand grows steadily": (0.0, 1.0),
        }
    )
    scorer = EmbeddingClaimSimilarity(provider)
    assert scorer.name == "embedding"
    # Identical vectors group despite wholly different wording.
    assert scorer.similarity("runway is 14 months", "churn stays low") == 1.0
    # Orthogonal vectors never group.
    assert scorer.similarity("runway is 14 months", "demand grows steadily") == 0.0
    # Missing vectors score 0.0, never an exception.
    assert scorer.similarity("runway is 14 months", "no vector here") == 0.0


def test_prepass_with_embedding_scorer_groups_by_vectors() -> None:
    provider = StaticVectorProvider(
        {
            "runway is 14 months": (1.0, 0.0),
            "churn stays low": (1.0, 0.0),
            "demand grows steadily": (0.0, 1.0),
        }
    )
    items = _items("Runway is 14 months", "Churn stays low", "Demand grows steadily")
    prepass = deterministic_prepass(items, similarity=EmbeddingClaimSimilarity(provider))
    assert prepass["similarity_provider"] == "embedding"
    assert prepass["near_duplicate_groups"] == [["I1", "I2"], ["I3"]]
    # The same items under the default scorer stay split (Sprint 18 pin).
    assert deterministic_prepass(items)["near_duplicate_groups"] == [
        ["I1"],
        ["I2"],
        ["I3"],
    ]
