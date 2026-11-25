"""Shared red-team / completeness finding shape (Phase 4, Tracks 8 + 10).

This module owns the ONE finding shape both the deterministic
completeness check (Track 10, this package) and the LLM red-team layer
(Track 8) emit, so the two sources can never produce duplicated or
contradictory outputs: same fields, same enums, same severity scale.
Track 8 should import :class:`RedTeamFinding` from here rather than
re-defining the shape.

The meta-check phrase lives here too: the top-ranked finding of a
completeness run carries it in its summary, so the deterministic check
and the red team agree on what "the biggest risk" looks like.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

#: The meta-check phrasing. Only the TOP-ranked finding of a check
#: carries this prefix; every other finding uses a plain summary.
#: Ho's wording (2026-11-19): "your biggest risk is a variable you
#: didn't include".
META_CHECK_PREFIX = "Your biggest risk is a variable you didn't include"


class FindingKind(str, Enum):
    """What is wrong with the model element the finding targets."""

    MISSING_DRIVER = "missing_driver"
    WEAK_ASSUMPTION = "weak_assumption"
    UNJUSTIFIED_DISCOUNT = "unjustified_discount"
    MISSING_LINK = "missing_link"
    OVERCONFIDENT_PARAMETER = "overconfident_parameter"
    # Huawei opportunity rethink (2026-11-25): revenue is a single
    # undifferentiated total — no region / product / customer split —
    # so growth cannot be located and opportunity has nowhere to sit.
    # The deterministic missing-segment-split check (Track 10 registry
    # + checklist, Track 8 snapshot rule) emits this kind; the LLM
    # red-team contract does NOT accept it (the LLM is instructed to
    # use only the five kinds above).
    MISSING_SEGMENT_SPLIT = "missing_segment_split"


class FindingSeverity(str, Enum):
    """How much the finding matters for the decision at hand."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class FindingSource(str, Enum):
    """Which layer produced the finding. Never mix sources in one id."""

    RED_TEAM_LLM = "red_team_llm"
    RED_TEAM_FIXTURE = "red_team_fixture"
    COMPLETENESS_CHECK = "completeness_check"


class BoundaryClass(str, Enum):
    """§6 boundary verdict (diagnostic-2020 §6; Ho 2026-11-19 15:02).

    Every finding carries one — the classification is part of the shared
    shape, not an annotation added later:
    - ``fixable_defect``: the gap could have been encoded from
      decision-time public evidence into a distribution. Missing it is
      a defect and should be fixed.
    - ``acceptable_limit``: the gap is only knowable from post-decision
      data. Missing it is a prediction limit, not a defect — do not
      tune parameters to fit it (hindsight firewall).
    - ``unclassified``: the evidence does not support a verdict. Use
      this rather than forcing a judgment to fill the field; say why
      in ``boundary_basis``.
    """

    FIXABLE_DEFECT = "fixable_defect"
    ACCEPTABLE_LIMIT = "acceptable_limit"
    UNCLASSIFIED = "unclassified"


#: Shared default basis for an unclassified finding. A finding that
#: cannot be classified must say so in these terms rather than invent
#: a verdict.
UNCLASSIFIED_BASIS = (
    "Cannot determine from the case alone whether this gap was encodable "
    "from decision-time public evidence (§6); left unclassified rather "
    "than forced."
)


class RedTeamFinding(BaseModel):
    """One finding, in the exact shared shape (Tracks 8 + 10).

    ``id`` is stable across runs of the same check on the same case:
    ``completeness:<driver-id>`` for registry findings,
    ``completeness:checklist:<item-id>`` for general-checklist
    findings, with a ``:link`` suffix for missing-link findings and a
    ``completeness:residual:<id>`` prefix for residual-gap findings.
    Deterministic checks must never mint a random id.

    ``boundary_class`` / ``boundary_basis`` are REQUIRED, not optional:
    every finding must carry its §6 verdict (defect vs limit) with a
    one-sentence basis. A layer that cannot judge says so
    (``unclassified`` + the reason) instead of forcing a verdict.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    kind: FindingKind
    target: str = Field(min_length=1)
    severity: FindingSeverity
    summary: str = Field(min_length=1)
    evidence: list[str] = Field(default_factory=list)
    suggested_fix: str = Field(min_length=1)
    source: FindingSource
    boundary_class: BoundaryClass
    boundary_basis: str = Field(min_length=1)


# Backwards-friendly alias: the completeness package talks about
# findings; the red-team track talks about red-team findings. Same model.
CompletenessFinding = RedTeamFinding

__all__ = [
    "META_CHECK_PREFIX",
    "UNCLASSIFIED_BASIS",
    "BoundaryClass",
    "CompletenessFinding",
    "FindingKind",
    "FindingSeverity",
    "FindingSource",
    "RedTeamFinding",
]
