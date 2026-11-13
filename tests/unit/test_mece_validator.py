"""Unit tests for the MECE scope-tag validator (Sprint 1, PRD delta D1).

The validator is a pure function: no database, no services, no LLM.
Semantics under test are the port of the v0.1 prototype's check_mece:
sibling scope tags pairwise disjoint, children union equals parent
scope, any failure fails the tree.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from planagent.services.mece import (
    MAX_TREE_DEPTH,
    DecompositionBranch,
    DecompositionTree,
    MeceValidationError,
    validate_decomposition,
    validate_or_raise,
)


def branch(
    name: str,
    scope: list[str],
    children: list[DecompositionBranch] | None = None,
) -> DecompositionBranch:
    return DecompositionBranch(name=name, scope=scope, children=children or [])


def tree(root: DecompositionBranch) -> DecompositionTree:
    return DecompositionTree(topic="test", root=root)


def issue_kinds(result) -> list[str]:
    return [issue.kind for issue in result.issues]


def test_disjoint_siblings_pass() -> None:
    result = validate_decomposition(
        tree(
            branch(
                "root",
                ["a", "b", "c"],
                [branch("A", ["a"]), branch("B", ["b", "c"])],
            )
        )
    )
    assert result.is_mece is True
    assert result.issues == []
    assert [(c.check, c.status) for c in result.checks] == [
        ("mutual_exclusion", "PASS"),
        ("exhaustiveness", "PASS"),
        ("structure", "PASS"),
    ]
    assert result.scope_tag_count == 3
    assert result.branch_count == 3


def test_overlap_fails_with_tag_and_branches() -> None:
    result = validate_decomposition(
        tree(
            branch(
                "root",
                ["a", "b"],
                [branch("A", ["a", "b"]), branch("B", ["b"])],
            )
        )
    )
    assert result.is_mece is False
    assert issue_kinds(result) == ["overlap"]
    issue = result.issues[0]
    assert issue.node == "root"
    assert issue.tags == ["b"]
    assert issue.branches == ["A", "B"]
    # Coverage still holds: the failure is exclusivity only.
    statuses = {c.check: c.status for c in result.checks}
    assert statuses["mutual_exclusion"] == "FAIL"
    assert statuses["exhaustiveness"] == "PASS"


def test_gap_fails_with_missing_tags() -> None:
    result = validate_decomposition(
        tree(
            branch(
                "root",
                ["a", "b", "c"],
                [branch("A", ["a"]), branch("B", ["b"])],
            )
        )
    )
    assert result.is_mece is False
    assert issue_kinds(result) == ["gap"]
    assert result.issues[0].tags == ["c"]
    statuses = {c.check: c.status for c in result.checks}
    assert statuses["mutual_exclusion"] == "PASS"
    assert statuses["exhaustiveness"] == "FAIL"


def test_extra_tag_outside_parent_scope_fails() -> None:
    result = validate_decomposition(
        tree(
            branch(
                "root",
                ["a"],
                [branch("A", ["a"]), branch("B", ["b"])],
            )
        )
    )
    assert result.is_mece is False
    assert issue_kinds(result) == ["extra"]
    issue = result.issues[0]
    assert issue.tags == ["b"]
    assert issue.branches == ["B"]


def test_empty_tree_fails() -> None:
    result = validate_decomposition(tree(branch("root", ["a", "b"])))
    assert result.is_mece is False
    assert issue_kinds(result) == ["empty_tree"]
    assert result.checks[0].check == "structure"
    assert result.checks[0].status == "FAIL"


def test_duplicate_tags_within_one_branch_fail_without_overlap() -> None:
    result = validate_decomposition(
        tree(
            branch(
                "root",
                ["a", "b"],
                [branch("A", ["a", "a"]), branch("B", ["b"])],
            )
        )
    )
    assert result.is_mece is False
    # A same-branch repeat is a duplicate_tag issue, not an overlap.
    assert issue_kinds(result) == ["duplicate_tag"]
    issue = result.issues[0]
    assert issue.node == "root / A"
    assert issue.tags == ["a"]
    assert issue.branches == ["A"]
    statuses = {c.check: c.status for c in result.checks}
    assert statuses["structure"] == "FAIL"
    assert statuses["mutual_exclusion"] == "PASS"


def test_root_scope_duplicates_fail() -> None:
    result = validate_decomposition(
        tree(
            branch(
                "root",
                ["a", "a", "b"],
                [branch("A", ["a"]), branch("B", ["b"])],
            )
        )
    )
    assert result.is_mece is False
    assert issue_kinds(result) == ["duplicate_tag"]
    assert result.issues[0].node == "root"


def test_empty_scope_branch_fails() -> None:
    result = validate_decomposition(
        tree(
            branch(
                "root",
                ["a"],
                [branch("A", ["a"]), branch("B", [])],
            )
        )
    )
    assert result.is_mece is False
    assert "empty_branch" in issue_kinds(result)
    empty = next(i for i in result.issues if i.kind == "empty_branch")
    assert empty.node == "root / B"
    assert empty.branches == ["B"]


def test_nested_branches_pass() -> None:
    result = validate_decomposition(
        tree(
            branch(
                "root",
                ["a", "b", "c", "d"],
                [
                    branch("A", ["a", "b"], [branch("A1", ["a"]), branch("A2", ["b"])]),
                    branch("B", ["c", "d"], [branch("B1", ["c"]), branch("B2", ["d"])]),
                ],
            )
        )
    )
    assert result.is_mece is True
    assert result.issues == []
    assert result.branch_count == 7
    assert result.scope_tag_count == 4
    nodes = {c.node for c in result.checks}
    assert nodes == {"root", "root / A", "root / B"}
    assert all(c.status == "PASS" for c in result.checks)


def test_nested_overlap_reports_deep_node_path() -> None:
    result = validate_decomposition(
        tree(
            branch(
                "root",
                ["a", "b"],
                [
                    branch("A", ["a"], [branch("A1", ["a"]), branch("A2", ["a"])]),
                    branch("B", ["b"]),
                ],
            )
        )
    )
    assert result.is_mece is False
    assert issue_kinds(result) == ["overlap"]
    assert result.issues[0].node == "root / A"
    assert result.issues[0].branches == ["A1", "A2"]


def test_nested_gap_fails_at_child_level() -> None:
    result = validate_decomposition(
        tree(
            branch(
                "root",
                ["a", "b"],
                [
                    branch("A", ["a", "x"], [branch("A1", ["a"])]),
                    branch("B", ["b"]),
                ],
            )
        )
    )
    assert result.is_mece is False
    # The child scope 'x' is outside the root scope AND uncovered below.
    kinds = issue_kinds(result)
    assert "extra" in kinds
    assert "gap" in kinds
    gap = next(i for i in result.issues if i.kind == "gap")
    assert gap.node == "root / A"
    assert gap.tags == ["x"]


def test_single_branch_covering_full_scope_passes() -> None:
    result = validate_decomposition(
        tree(branch("root", ["a", "b"], [branch("Only", ["a", "b"])]))
    )
    assert result.is_mece is True
    assert result.issues == []


def test_single_branch_partial_scope_fails_with_gap() -> None:
    result = validate_decomposition(
        tree(branch("root", ["a", "b"], [branch("Only", ["a"])]))
    )
    assert result.is_mece is False
    assert issue_kinds(result) == ["gap"]


def test_max_depth_exceeded_fails() -> None:
    # Build a chain one level deeper than the cap; every level is
    # otherwise MECE (single child covering the parent scope).
    node = branch(f"L{MAX_TREE_DEPTH + 1}", ["a"])
    for level in range(MAX_TREE_DEPTH, 0, -1):
        node = branch(f"L{level}", ["a"], [node])
    result = validate_decomposition(tree(node))
    assert result.is_mece is False
    assert "max_depth_exceeded" in issue_kinds(result)


def test_validation_is_deterministic_and_pure() -> None:
    decomposition = tree(
        branch(
            "root",
            ["a", "b"],
            [branch("A", ["a", "b"]), branch("B", ["b"])],
        )
    )
    before = decomposition.model_dump(mode="json")
    first = validate_decomposition(decomposition).model_dump(mode="json")
    second = validate_decomposition(decomposition).model_dump(mode="json")
    assert first == second
    assert decomposition.model_dump(mode="json") == before


def test_validate_or_raise() -> None:
    passing = tree(branch("root", ["a"], [branch("A", ["a"])]))
    assert validate_or_raise(passing).is_mece is True

    failing = tree(branch("root", ["a", "b"], [branch("A", ["a"])]))
    with pytest.raises(MeceValidationError) as exc_info:
        validate_or_raise(failing)
    assert exc_info.value.result.is_mece is False
    assert "MECE validation failed" in str(exc_info.value)


def test_model_rejects_empty_names_and_blank_tags() -> None:
    with pytest.raises(ValidationError):
        DecompositionBranch(name="  ", scope=["a"])
    with pytest.raises(ValidationError):
        DecompositionBranch(name="A", scope=["a", "  "])


def test_model_strips_whitespace_but_keeps_duplicates() -> None:
    node = DecompositionBranch(name="  A ", scope=[" a ", "a"])
    assert node.name == "A"
    assert node.scope == ["a", "a"]
