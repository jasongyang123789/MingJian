"""Polish re-check: verify LLM-polished narrative text before storing.

Closes the Sprint 13 gap (SPRINT13.md §6/§8): the polish prompt
forbids changing numbers and provenance marks, but nothing in the
polish path re-validated the polished text against the artifact.
This module is that verification pass. It is pure (no I/O, no
clock, no randomness) and runs in
:meth:`NarrativeService.polish` after the polish pass returns and
BEFORE any row is written: a failed re-check refuses storage, the
same house gate rule as every other narrative refusal.

The check compares the polished text against the deterministic
markdown that was sent to the polish pass (the exact input), not
against the structured body: the markdown already renders every
figure in the body (distributions, drivers, signals, counts), so
text-vs-text is the complete comparison.

Rules (all asserted by tests in
``tests/unit/test_narratives_recheck.py``):

Numbers
    1. Code spans (backtick-delimited) are removed before
       extraction: trace ids (run, ensemble, deliberation, fit,
       loop ids) live in code spans in the deterministic rendering
       and must never contribute numbers. UUIDs are also removed
       wherever they appear, so a polish that drops the backticks
       around an id still does not invent numbers from it.
    2. A number is an optional sign, digits with optional
       thousands-group commas, an optional decimal fraction, and
       an optional exponent. Boundary rules keep identifiers out:
       the character before the token (or its sign) must not be a
       letter, digit, ``_``, ``.``, or ``-``, and the character
       after must not be a letter, digit, ``_``, or ``.`` followed
       by a digit. So ``P50``, ``v0``, ``sprint13-v1``,
       ``delib-strategy-1``, and fragments of ``1.2.3`` never
       yield numbers, while ``P50 10``, ``n=20``, and ``-3`` do.
       A digit run immediately after a hyphen counts as part of
       an identifier (``strategy-1``), not as a number; hyphen
       ranges (``10-20``) therefore yield only their first
       endpoint. Both sides are extracted with the same rule, so
       a polish that preserves the form passes.
    3. Percent: a number immediately followed by ``%`` (optional
       spaces/tabs between) is divided by 100. ``20%`` is the
       same value as ``0.2``; ``20%`` differs from ``20``.
    4. Values compare as :class:`decimal.Decimal` with no rounding
       and no epsilon: ``1,000`` equals ``1000``, ``10.0`` equals
       ``10``, ``0.10`` equals ``0.1``, ``1e3`` equals ``1000``,
       but ``0.333333`` differs from ``0.333334`` and ``10``
       differs from ``11``.
    5. Multiset equality: the polished text must contain exactly
       the same numbers with the same multiplicities as the
       source. A dropped number, an invented number, or an
       altered number (which surfaces as one missing plus one
       extra) all fail. Key figures (P10/P50/P90, loss
       probability) are a subset of the checked numbers, so they
       are preserved exactly by the same rule.
    6. Non-finite sentinels (``NaN``, ``Infinity``) are words, not
       numbers, and are not checked.

Provenance
    7. Marks are the exact tokens ``[computed]``,
       ``[deliberated]``, ``[template]`` (case-sensitive). Counts
       per kind must be equal between source and polished text:
       a dropped, added, or kind-changed mark fails. The footer's
       three marks count like any other occurrence.
    8. Attachment is NOT verified: the check does not confirm a
       mark still sits next to the text it marked, only that the
       multiset of marks is unchanged. Section reordering that
       keeps every mark therefore passes.
    9. Other bracketed tokens are ignored: only the three known
       kinds are marks.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal

PROVENANCE_MARKS: tuple[str, ...] = ("computed", "deliberated", "template")

_CODE_SPAN_RE = re.compile(r"`[^`\n]+`")
_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9_.\-])"
    r"[-+]?"
    r"(?:\d{1,3}(?:,\d{3})+|\d+)"
    r"(?:\.\d+)?"
    r"(?:[eE][-+]?\d+)?"
    r"(?![A-Za-z0-9_])"
    r"(?!\.\d)"
)
_PERCENT_RE = re.compile(r"^[ \t]*%")
_MARK_RE = re.compile(r"\[(computed|deliberated|template)\]")


def _strip_non_numbers(text: str) -> str:
    """Remove code spans and UUIDs so ids never contribute numbers."""
    without_spans = _CODE_SPAN_RE.sub(" ", text)
    return _UUID_RE.sub(" ", without_spans)


def _format_value(value: Decimal) -> str:
    """Canonical display form: plain notation, no trailing zeros."""
    if value == 0:
        value = Decimal(0)  # collapse -0
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def extract_numbers(text: str) -> tuple[Decimal, ...]:
    """Extract the numbers of ``text`` in order of appearance.

    Applies the code-span/UUID stripping, boundary, and percent
    rules from the module docstring. Values are exact
    :class:`Decimal`\\ s; formatting differences (commas, trailing
    zeros, exponents, percent notation) do not survive.
    """
    cleaned = _strip_non_numbers(text)
    values: list[Decimal] = []
    for match in _NUMBER_RE.finditer(cleaned):
        raw = match.group(0).replace(",", "")
        value = Decimal(raw)
        if _PERCENT_RE.match(cleaned[match.end() :]):
            value = value / Decimal(100)
        values.append(value)
    return tuple(values)


def extract_provenance_counts(text: str) -> dict[str, int]:
    """Count the three provenance marks in ``text``, by kind."""
    counts = Counter(_MARK_RE.findall(text))
    return {kind: counts.get(kind, 0) for kind in PROVENANCE_MARKS}


def _multiset_diff(
    source: tuple[Decimal, ...], polished: tuple[Decimal, ...]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return (missing, extra) canonical number strings, sorted by value."""
    missing = Counter(source) - Counter(polished)
    extra = Counter(polished) - Counter(source)
    missing_values = sorted(missing.elements())
    extra_values = sorted(extra.elements())
    return (
        tuple(_format_value(value) for value in missing_values),
        tuple(_format_value(value) for value in extra_values),
    )


@dataclass(frozen=True)
class PolishRecheck:
    """The outcome of one :func:`check_polish` call."""

    passed: bool
    missing_numbers: tuple[str, ...] = ()
    extra_numbers: tuple[str, ...] = ()
    missing_marks: dict[str, int] = field(default_factory=dict)
    extra_marks: dict[str, int] = field(default_factory=dict)

    def describe(self) -> str:
        """Stable, detailed failure message naming every difference."""
        if self.passed:
            return "polish re-check passed: numbers and provenance marks preserved"
        parts: list[str] = []
        if self.missing_numbers:
            parts.append("numbers missing from polished text: " + ", ".join(self.missing_numbers))
        if self.extra_numbers:
            parts.append("numbers invented in polished text: " + ", ".join(self.extra_numbers))
        if self.missing_marks:
            parts.append(
                "provenance marks missing: "
                + ", ".join(
                    f"[{kind}] x{count}" for kind, count in sorted(self.missing_marks.items())
                )
            )
        if self.extra_marks:
            parts.append(
                "provenance marks added: "
                + ", ".join(
                    f"[{kind}] x{count}" for kind, count in sorted(self.extra_marks.items())
                )
            )
        return "; ".join(parts)


def check_polish(source_markdown: str, polished_markdown: str) -> PolishRecheck:
    """Verify polished text against the deterministic source markdown.

    Passes exactly when the multiset of numbers and the per-kind
    counts of provenance marks are unchanged (see the module
    docstring for the matching rules). Never raises on text input.
    """
    missing_numbers, extra_numbers = _multiset_diff(
        extract_numbers(source_markdown), extract_numbers(polished_markdown)
    )
    source_marks = extract_provenance_counts(source_markdown)
    polished_marks = extract_provenance_counts(polished_markdown)
    missing_marks = {
        kind: source_marks[kind] - polished_marks[kind]
        for kind in PROVENANCE_MARKS
        if source_marks[kind] > polished_marks[kind]
    }
    extra_marks = {
        kind: polished_marks[kind] - source_marks[kind]
        for kind in PROVENANCE_MARKS
        if polished_marks[kind] > source_marks[kind]
    }
    passed = not (missing_numbers or extra_numbers or missing_marks or extra_marks)
    return PolishRecheck(
        passed=passed,
        missing_numbers=missing_numbers,
        extra_numbers=extra_numbers,
        missing_marks=missing_marks,
        extra_marks=extra_marks,
    )


__all__ = [
    "PROVENANCE_MARKS",
    "PolishRecheck",
    "check_polish",
    "extract_numbers",
    "extract_provenance_counts",
]
