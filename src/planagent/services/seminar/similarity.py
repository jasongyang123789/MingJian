"""Deterministic claim similarity (Sprint 18 Jaccard, upgraded Sprint 19).

Pure functions, stdlib only, no network, no model calls. The pre-pass
uses similarity ONLY to propose advisory near-duplicate groups; the
chair (model or agent) adjudicates whether candidates are the same
claim, and the deterministic fallback never merges distinct wordings.

The Sprint 19 scorer combines two signals and takes their MAXIMUM
(a deliberate choice, pinned by tests): either strong signal suffices
to propose a candidate, because the two signals catch different
near-duplicate shapes — token-set overlap catches word substitution
and reordering, character-bigram overlap catches morphological and
typo variants and unspaced (CJK) text. The pre-pass is advisory, so
recall matters more than precision here; the 0.8 default threshold
still applies to the combined score, and grouping never chains
(the representative never moves — Sprint 18 discipline, unchanged).

Signals:

* Token-set Jaccard over :func:`similarity_tokens`: CJK-aware
  tokenization (each CJK character is a token; Latin runs are word
  tokens) plus light conservative English stemming (documented
  suffix rules in :func:`stem_word`). Stemming only ever merges
  inflections of one stem; it never merges distinct stems, and it
  never touches CJK characters or numeric tokens.
* Character-bigram Jaccard over the compacted text (whitespace and
  punctuation removed). Short texts (< 2 content characters) compare
  by equality instead — bigram sets would be empty and an
  empty/empty Jaccard of 1.0 would wrongly group distinct
  single-character claims.

The :class:`ClaimSimilarity` protocol is the seam for alternative
scorers: :class:`JaccardClaimSimilarity` (the default) and
:class:`EmbeddingClaimSimilarity` (cosine over precomputed vectors
from a :class:`VectorProvider`). No embedding provider ships in
Sprint 19 — the interface lets a future provider plug in without
changing clustering code. :class:`StaticVectorProvider` is a
dict-backed provider used by tests (and usable by any future
offline provider).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Protocol

#: Default combined-score threshold for near-duplicate grouping
#: (Sprint 18 pin, kept in Sprint 19 on the combined score).
DEFAULT_NEAR_DUPLICATE_THRESHOLD = 0.8


def jaccard_similarity(left: frozenset[str], right: frozenset[str]) -> float:
    """Jaccard similarity of two sets.

    Two empty sets are identical (1.0); an empty set against a
    non-empty one is 0.0.
    """
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


# --- CJK-aware tokenization -------------------------------------------
#
# Ranges: CJK Unified Ideographs Extension A, Unified Ideographs,
# Compatibility Ideographs, Hiragana/Katakana, Hangul syllables, and
# Extension B (astral plane). CJK punctuation (。、，：；) is NOT in
# these ranges and acts as a separator, like whitespace.

_CJK_RANGES: tuple[tuple[int, int], ...] = (
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xF900, 0xFAFF),
    (0x3040, 0x30FF),
    (0xAC00, 0xD7A3),
    (0x20000, 0x2A6DF),
)


def _is_cjk(char: str) -> bool:
    codepoint = ord(char)
    return any(start <= codepoint <= end for start, end in _CJK_RANGES)


#: Consonants whose doubling is undone after stripping -ing/-ed
#: (running -> run, stopping -> stop). ``s``, ``l``, and ``z`` are
#: excluded: pass/miss/fill/buzz are true stems ending in a double
#: consonant, and undoubling them would under-merge (passing -> pas).
#: Vowels never undouble.
_UNDOUBLE_CONSONANTS = frozenset("bdgmnprt")


def _undouble(stem: str) -> str:
    if (
        len(stem) >= 2
        and stem[-1] == stem[-2]
        and stem[-1] in _UNDOUBLE_CONSONANTS
    ):
        return stem[:-1]
    return stem


def stem_word(word: str) -> str:
    """Light conservative English stemming: documented suffix rules.

    At most one rule applies (first match wins, longest suffix
    first). The rules only strip inflectional suffixes; they never
    rewrite a stem, never re-add a dropped ``e`` (``agreed`` ->
    ``agre``, which under-merges with ``agree`` — the safe
    direction), and never touch words shorter than 3 characters or
    words containing digits. Distinct stems never merge: ``this``
    (ends in ``is``), ``class`` (``ss``), ``status`` (``us``), and
    ``goes``/``does`` (``oes``) keep their final ``s``.
    """
    if len(word) < 3 or any(char.isdigit() for char in word):
        return word
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"  # stories -> story
    if word.endswith("ing") and len(word) > 5:
        return _undouble(word[:-3])  # growing -> grow, running -> run
    if word.endswith("ed") and len(word) > 4:
        return _undouble(word[:-2])  # stayed -> stay, stopped -> stop
    if (
        word.endswith("es")
        and len(word) > 4
        and word[:-2].endswith(("s", "x", "z", "ch", "sh"))
    ):
        return word[:-2]  # passes -> pass, watches -> watch
    if (
        word.endswith("s")
        and len(word) > 3
        and not word.endswith(("ss", "us", "is", "oes"))
    ):
        return word[:-1]  # tickets -> ticket, grows -> grow
    return word


def similarity_tokens(normalized_text: str) -> frozenset[str]:
    """Tokenize normalized claim text for similarity scoring.

    CJK characters become one token each (unspaced text has no word
    boundaries); Latin/digit runs become word tokens, stemmed by
    :func:`stem_word`. Whitespace and punctuation separate tokens.
    """
    tokens: set[str] = set()
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            tokens.add(stem_word("".join(buffer)))
            buffer.clear()

    for char in normalized_text:
        if _is_cjk(char):
            flush()
            tokens.add(char)
        elif char.isalnum():
            buffer.append(char)
        else:
            flush()
    flush()
    return frozenset(tokens)


def _compact(normalized_text: str) -> str:
    """Content characters only: whitespace and punctuation removed."""
    return "".join(char for char in normalized_text if char.isalnum() or _is_cjk(char))


def _bigrams(compacted: str) -> frozenset[str]:
    return frozenset(
        compacted[index : index + 2] for index in range(len(compacted) - 1)
    )


def char_bigram_similarity(left_normalized: str, right_normalized: str) -> float:
    """Character-bigram Jaccard of two normalized claim texts.

    Texts with fewer than 2 content characters compare by equality:
    their bigram sets would be empty, and empty/empty Jaccard (1.0)
    would wrongly group distinct single-character claims.
    """
    left = _compact(left_normalized)
    right = _compact(right_normalized)
    if len(left) < 2 or len(right) < 2:
        return 1.0 if left == right else 0.0
    return jaccard_similarity(_bigrams(left), _bigrams(right))


def combined_similarity(left_normalized: str, right_normalized: str) -> float:
    """The Sprint 19 combined score: MAX(token Jaccard, bigram Jaccard).

    Either strong signal proposes a candidate; the chair adjudicates.
    """
    token_score = jaccard_similarity(
        similarity_tokens(left_normalized), similarity_tokens(right_normalized)
    )
    bigram_score = char_bigram_similarity(left_normalized, right_normalized)
    return max(token_score, bigram_score)


# --- Scorer seam -------------------------------------------------------


class ClaimSimilarity(Protocol):
    """Scores two NORMALIZED claim texts in [0, 1]."""

    name: str

    def similarity(self, left_normalized: str, right_normalized: str) -> float: ...


class JaccardClaimSimilarity:
    """The default scorer: the Sprint 19 combined score."""

    name = "jaccard"

    def similarity(self, left_normalized: str, right_normalized: str) -> float:
        return combined_similarity(left_normalized, right_normalized)


class VectorProvider(Protocol):
    """Supplies a precomputed vector for a normalized claim text.

    Returns ``None`` when the text has no vector (the embedding
    scorer then scores 0.0 — no evidence of similarity — rather
    than failing the synthesis).
    """

    def vector_for(self, normalized_text: str) -> tuple[float, ...] | None: ...


class VectorScorer(Protocol):
    """Scores two precomputed vectors in [0, 1]."""

    def score(self, left: Sequence[float], right: Sequence[float]) -> float: ...


class CosineVectorScorer:
    """Cosine similarity clamped to [0, 1].

    Zero-norm vectors and dimension mismatches score 0.0; negative
    cosine clamps to 0.0 (dissimilar for grouping purposes).
    """

    def score(self, left: Sequence[float], right: Sequence[float]) -> float:
        if len(left) != len(right) or not left:
            return 0.0
        dot = math.fsum(a * b for a, b in zip(left, right, strict=True))
        left_norm = math.sqrt(math.fsum(a * a for a in left))
        right_norm = math.sqrt(math.fsum(b * b for b in right))
        if left_norm == 0.0 or right_norm == 0.0:
            return 0.0
        return max(0.0, min(1.0, dot / (left_norm * right_norm)))


class StaticVectorProvider:
    """A dict-backed vector provider (tests + future offline use).

    Vectors are looked up by exact normalized text; unknown texts
    have no vector. Deterministic, no network, no model.
    """

    def __init__(self, vectors: Mapping[str, Sequence[float]]) -> None:
        self._vectors = {text: tuple(values) for text, values in vectors.items()}

    def vector_for(self, normalized_text: str) -> tuple[float, ...] | None:
        return self._vectors.get(normalized_text)


class EmbeddingClaimSimilarity:
    """Cosine similarity over precomputed vectors from a provider.

    A future embedding provider plugs in by implementing
    :class:`VectorProvider`; clustering code does not change. No
    provider ships in Sprint 19.
    """

    name = "embedding"

    def __init__(
        self,
        provider: VectorProvider,
        scorer: VectorScorer | None = None,
    ) -> None:
        self._provider = provider
        self._scorer = scorer or CosineVectorScorer()

    def similarity(self, left_normalized: str, right_normalized: str) -> float:
        left = self._provider.vector_for(left_normalized)
        right = self._provider.vector_for(right_normalized)
        if left is None or right is None:
            return 0.0
        return self._scorer.score(left, right)


__all__ = [
    "DEFAULT_NEAR_DUPLICATE_THRESHOLD",
    "ClaimSimilarity",
    "CosineVectorScorer",
    "EmbeddingClaimSimilarity",
    "JaccardClaimSimilarity",
    "StaticVectorProvider",
    "VectorProvider",
    "VectorScorer",
    "char_bigram_similarity",
    "combined_similarity",
    "jaccard_similarity",
    "similarity_tokens",
    "stem_word",
]
