"""Pydantic models for MECE decomposition trees and validation results.

A decomposition tree is a root branch whose scope is partitioned by its
child branches, recursively. Each branch carries ``scope`` tags: the
atomic scope labels it covers. The validator (``validator.py``) checks
the tree structurally against those tags — no LLM, no randomness — so
validation is a pure function of the submitted tree.

These models are intentionally free of any dependency on the rest of
the application: ``planagent.domain.api`` imports ``DecompositionTree``
for the simulation-run creation payload, so this module must not import
from ``planagent.domain`` or ``planagent.services`` (that would be a
circular import).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MeceCheckKind = Literal["mutual_exclusion", "exhaustiveness", "structure"]
MeceCheckStatus = Literal["PASS", "FAIL"]
MeceIssueKind = Literal[
    "overlap",
    "gap",
    "extra",
    "duplicate_tag",
    "empty_branch",
    "empty_tree",
    "max_depth_exceeded",
]

_MAX_NAME_LENGTH = 200
_MAX_TAG_LENGTH = 120
_MAX_TOPIC_LENGTH = 500


class DecompositionBranch(BaseModel):
    """One node of a decomposition tree: a named branch covering scope tags.

    ``children`` partitions this branch's scope. A branch with no
    children is a leaf: its scope tags are taken as-is and it is checked
    only as part of its parent's coverage. Duplicate tags inside one
    branch's own ``scope`` list are kept (not deduplicated) so the
    validator can report them.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=_MAX_NAME_LENGTH)
    scope: list[str] = Field(default_factory=list)
    children: list["DecompositionBranch"] = Field(default_factory=list)

    @field_validator("name", mode="before")
    @classmethod
    def _strip_name(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("scope")
    @classmethod
    def _normalize_tags(cls, tags: list[str]) -> list[str]:
        normalized = [tag.strip() for tag in tags]
        if any(not tag for tag in normalized):
            raise ValueError("scope tags must be non-empty strings")
        if any(len(tag) > _MAX_TAG_LENGTH for tag in normalized):
            raise ValueError("scope tags must be at most 120 characters")
        return normalized


class DecompositionTree(BaseModel):
    """A decomposition submitted for validation or attached to a run."""

    model_config = ConfigDict(extra="forbid")

    topic: str = Field(default="", max_length=_MAX_TOPIC_LENGTH)
    root: DecompositionBranch


class MeceCheckRecord(BaseModel):
    """One check outcome at one tree node (mirrors the v0.1 prototype)."""

    model_config = ConfigDict(extra="forbid")

    node: str
    check: MeceCheckKind
    status: MeceCheckStatus
    detail: str


class MeceIssue(BaseModel):
    """One structured validation failure, located at a tree node."""

    model_config = ConfigDict(extra="forbid")

    kind: MeceIssueKind
    node: str
    detail: str
    tags: list[str] = Field(default_factory=list)
    branches: list[str] = Field(default_factory=list)


class MeceValidationResult(BaseModel):
    """Full validation outcome. ``is_mece`` is False iff any issue exists."""

    model_config = ConfigDict(extra="forbid")

    is_mece: bool
    checks: list[MeceCheckRecord] = Field(default_factory=list)
    issues: list[MeceIssue] = Field(default_factory=list)
    scope_tag_count: int = 0
    branch_count: int = 0


class MeceRunRead(BaseModel):
    """Stored decomposition + validation result for one simulation run."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    decomposition: DecompositionTree
    validation: MeceValidationResult
