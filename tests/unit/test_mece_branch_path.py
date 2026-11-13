"""Unit tests for MECE branch-path lookup (Sprint 3 branch bindings)."""

from __future__ import annotations

from planagent.services.mece import find_branch_by_path
from planagent.services.mece.models import DecompositionTree

TREE = DecompositionTree(
    topic="Should we launch?",
    root={
        "name": "Launch",
        "scope": ["demand", "cost", "tech"],
        "children": [
            {
                "name": "Demand",
                "scope": ["demand"],
                "children": [
                    {"name": "SMB", "scope": ["demand"]},
                ],
            },
            {"name": "Cost", "scope": ["cost", "tech"]},
        ],
    },
)


def test_root_path_resolves_to_root() -> None:
    assert find_branch_by_path(TREE, "Launch").name == "Launch"


def test_nested_paths_resolve() -> None:
    assert find_branch_by_path(TREE, "Launch / Demand").name == "Demand"
    assert find_branch_by_path(TREE, "Launch/Demand/SMB").name == "SMB"
    assert find_branch_by_path(TREE, "Launch / Cost").scope == ["cost", "tech"]


def test_unknown_paths_return_none() -> None:
    assert find_branch_by_path(TREE, "Nope") is None
    assert find_branch_by_path(TREE, "Launch / Nope") is None
    assert find_branch_by_path(TREE, "Launch / Demand / Nope") is None
    assert find_branch_by_path(TREE, "") is None
    assert find_branch_by_path(TREE, "Demand") is None  # must start at the root
    assert find_branch_by_path(TREE, "launch / Demand") is None  # exact match
