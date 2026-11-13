"""Pure, deterministic MECE validation over scope tags.

Semantics ported from the v0.1 prototype
(``~/workspace/strategy-engine/engine.py::check_mece``), strengthened
where the prototype was silent on degenerate input:

- At every node with children, the children's scope tags must be
  pairwise disjoint (mutual exclusivity) and their union must equal the
  parent node's scope (exhaustiveness). Any failure fails the tree.
- Structural problems are failures too: a decomposition with no
  branches, a branch covering no scope tags, duplicate tags inside one
  branch's own scope list, and trees deeper than ``MAX_TREE_DEPTH``.
- Overlap detection is structural (scope-tag identity), never
  keyword-heuristic: two branches overlap iff they share a tag.

The validator is a pure function of the submitted tree: no LLM, no
randomness, no I/O, no clock. Identical input always yields identical
output (issue order follows tree traversal order; tags inside an issue
are sorted), so results are byte-stable and safe to persist as an audit
trail.
"""

from __future__ import annotations

from .models import (
    DecompositionBranch,
    DecompositionTree,
    MeceCheckRecord,
    MeceIssue,
    MeceValidationResult,
)

MAX_TREE_DEPTH = 10


class MeceValidationError(ValueError):
    """Raised when a decomposition fails MECE validation.

    Carries the full structured result so callers (API routes) can
    return the issues to the client. Subclasses ``ValueError`` so any
    generic ``ValueError`` handler still surfaces a readable summary.
    """

    def __init__(self, result: MeceValidationResult) -> None:
        self.result = result
        summary = "; ".join(issue.detail for issue in result.issues[:5])
        super().__init__(f"MECE validation failed: {summary}")


def find_branch_by_path(tree: DecompositionTree, path: str) -> DecompositionBranch | None:
    """Find a branch by its slash-separated path from the root.

    Path segments are branch names, e.g. ``"Launch / Demand"`` for the
    ``Demand`` child of the root branch named ``Launch``; the first
    segment must equal the root branch's name, and a single segment
    names the root itself. Segments are matched exactly (no
    normalization, same as scope tags). Returns None when the path is
    empty or names no branch. Used by Sprint 3 branch-level bindings to
    scope variable tags against one decomposition branch instead of the
    whole root scope.
    """

    segments = [segment.strip() for segment in path.split("/")]
    segments = [segment for segment in segments if segment]
    if not segments or segments[0] != tree.root.name:
        return None
    current = tree.root
    for segment in segments[1:]:
        nxt = next((child for child in current.children if child.name == segment), None)
        if nxt is None:
            return None
        current = nxt
    return current


def validate_decomposition(tree: DecompositionTree) -> MeceValidationResult:
    """Validate a decomposition tree. Pure function of ``tree``."""
    state = _ValidationState()
    _validate_node(tree.root, path="root", depth=1, state=state)
    return MeceValidationResult(
        is_mece=not state.issues,
        checks=state.checks,
        issues=state.issues,
        scope_tag_count=len(set(tree.root.scope)),
        branch_count=state.branch_count,
    )


def validate_or_raise(tree: DecompositionTree) -> MeceValidationResult:
    """Validate and return the result, or raise ``MeceValidationError``."""
    result = validate_decomposition(tree)
    if not result.is_mece:
        raise MeceValidationError(result)
    return result


class _ValidationState:
    def __init__(self) -> None:
        self.checks: list[MeceCheckRecord] = []
        self.issues: list[MeceIssue] = []
        self.branch_count = 0


def _duplicated_tags(scope: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicated: set[str] = set()
    for tag in scope:
        if tag in seen:
            duplicated.add(tag)
        seen.add(tag)
    return sorted(duplicated)


def _validate_node(
    node: DecompositionBranch,
    path: str,
    depth: int,
    state: _ValidationState,
) -> None:
    state.branch_count += 1

    if depth > MAX_TREE_DEPTH:
        state.issues.append(
            MeceIssue(
                kind="max_depth_exceeded",
                node=path,
                detail=f"tree depth exceeds the maximum of {MAX_TREE_DEPTH}",
                branches=[node.name],
            )
        )
        state.checks.append(
            MeceCheckRecord(
                node=path,
                check="structure",
                status="FAIL",
                detail=f"tree depth exceeds the maximum of {MAX_TREE_DEPTH}",
            )
        )
        return

    # Own-scope duplicates are this node's structural problem.
    own_duplicates = _duplicated_tags(node.scope)
    if own_duplicates:
        state.issues.append(
            MeceIssue(
                kind="duplicate_tag",
                node=path,
                detail=(
                    f"branch '{node.name}' lists scope tag(s) more than once: {own_duplicates}"
                ),
                tags=own_duplicates,
                branches=[node.name],
            )
        )

    # A non-root branch covering no scope tags is a structural problem.
    if depth > 1 and not node.scope:
        state.issues.append(
            MeceIssue(
                kind="empty_branch",
                node=path,
                detail=f"branch '{node.name}' covers no scope tags",
                branches=[node.name],
            )
        )

    if not node.children:
        if depth == 1:
            # A decomposition that does not decompose: the prototype is
            # silent here (no records); we fail it explicitly.
            state.issues.append(
                MeceIssue(
                    kind="empty_tree",
                    node=path,
                    detail="decomposition has no branches; the root scope is not decomposed",
                    branches=[node.name],
                )
            )
            state.checks.append(
                MeceCheckRecord(
                    node=path,
                    check="structure",
                    status="FAIL",
                    detail="decomposition has no branches",
                )
            )
        return

    _check_mutual_exclusion(node, path, state)
    _check_exhaustiveness(node, path, state)
    _check_structure(node, path, own_duplicates, state)

    for child in node.children:
        _validate_node(child, f"{path} / {child.name}", depth + 1, state)


def _check_mutual_exclusion(
    node: DecompositionBranch,
    path: str,
    state: _ValidationState,
) -> None:
    """Children's scope tags must be pairwise disjoint."""
    owner: dict[str, str] = {}
    overlap_count = 0
    for child in node.children:
        for tag in child.scope:
            first_owner = owner.get(tag)
            if first_owner is None:
                owner[tag] = child.name
            elif first_owner != child.name:
                # Same-branch repeats are duplicate_tag issues, not overlaps.
                state.issues.append(
                    MeceIssue(
                        kind="overlap",
                        node=path,
                        detail=(
                            f"scope tag '{tag}' appears in both '{first_owner}' and '{child.name}'"
                        ),
                        tags=[tag],
                        branches=[first_owner, child.name],
                    )
                )
                overlap_count += 1
    if overlap_count:
        state.checks.append(
            MeceCheckRecord(
                node=path,
                check="mutual_exclusion",
                status="FAIL",
                detail=f"{overlap_count} overlapping scope tag(s) across sibling branches",
            )
        )
    else:
        state.checks.append(
            MeceCheckRecord(
                node=path,
                check="mutual_exclusion",
                status="PASS",
                detail=(f"{len(node.children)} child branches have pairwise disjoint scope tags"),
            )
        )


def _check_exhaustiveness(
    node: DecompositionBranch,
    path: str,
    state: _ValidationState,
) -> None:
    """Union of children's scope tags must equal the parent scope."""
    parent_scope = set(node.scope)
    union: set[str] = set()
    for child in node.children:
        union.update(child.scope)
    missing = sorted(parent_scope - union)
    extra = sorted(union - parent_scope)
    if missing:
        state.issues.append(
            MeceIssue(
                kind="gap",
                node=path,
                detail=f"parent scope tags not covered by any child branch: {missing}",
                tags=missing,
            )
        )
    if extra:
        contributing = sorted(
            {child.name for child in node.children if set(child.scope) & set(extra)}
        )
        state.issues.append(
            MeceIssue(
                kind="extra",
                node=path,
                detail=f"child scope tags outside the parent scope: {extra}",
                tags=extra,
                branches=contributing,
            )
        )
    if missing or extra:
        state.checks.append(
            MeceCheckRecord(
                node=path,
                check="exhaustiveness",
                status="FAIL",
                detail=f"missing: {missing or 'none'}; outside parent scope: {extra or 'none'}",
            )
        )
    else:
        state.checks.append(
            MeceCheckRecord(
                node=path,
                check="exhaustiveness",
                status="PASS",
                detail=(f"children union equals parent scope, {len(parent_scope)} scope tags"),
            )
        )


def _check_structure(
    node: DecompositionBranch,
    path: str,
    own_duplicates: list[str],
    state: _ValidationState,
) -> None:
    """Node-level structure: own duplicates, malformed direct children.

    Children's own problems are reported as issues at the child's path
    when the child is visited; this record only reflects what is visible
    at this node without descending.
    """
    child_problems = any(
        not child.scope or _duplicated_tags(child.scope) for child in node.children
    )
    if own_duplicates or child_problems:
        state.checks.append(
            MeceCheckRecord(
                node=path,
                check="structure",
                status="FAIL",
                detail=(
                    "branch scope lists contain duplicates or a child branch covers no scope tags"
                ),
            )
        )
    else:
        state.checks.append(
            MeceCheckRecord(
                node=path,
                check="structure",
                status="PASS",
                detail="all branch scope lists are non-empty and duplicate-free",
            )
        )
