"""Directions as variable overrides (option B, Sprint 14 follow-up).

The fourth direction source, alongside explicit per-request
definitions (Sprint 13), deterministic rule derivation (Sprint
14), and LLM proposals (option C): a direction names fixed-value
overrides for variables bound on the anchor run, and applying it
creates a NEW simulation run — a scenario branch of the anchor —
whose variable bindings carry the overrides. The direction is
stored as a mapping pointing at the child run, with the override
spec pinned in an ``override_record``.

What Sprint 14 actually recorded about option B is one line:
"directions that trigger new simulation runs", plus two open
product decisions — "override shape, who may create runs". Those
decisions were never recorded anywhere else in the repo, so this
module implements the minimal faithful reading, stated here so a
reviewer can disagree with the interpretation rather than hunt
for it:

- Override shape: fixed values only — ``{variable_id: value}``.
  Each overridden variable keeps the anchor run's bound
  definition (unit, evidence, description, scope tags) with its
  distribution replaced by ``fixed`` at the given value. The
  inline set merges over the anchor's bindings with the Sprint 3
  branch semantics (``merge_variable_sets``: override wins per
  id), and the merged set must pass the same validation gate as
  run creation. Full distribution surgery stays available via
  the scenario-branch endpoint, which accepts a whole
  ``VariableSet``; option B's contract is the direction-level
  one: "what if X were V".
- Grounding: override ids must already be bound on the anchor
  run (the option C discipline: stored bindings only). An
  override naming an unbound variable refuses the whole request
  before any run is created. No range check against the original
  distribution: setting a value outside the sampled range is the
  point of a what-if.
- Who may create runs: the explicit human caller of the
  endpoint, and nobody else. No background creation, no
  auto-trigger from generation, derivation, or proposals (the
  Sprint 9 automation boundary). There is no separate permission
  layer: the endpoint follows the same access as the other
  directions endpoints, exactly as scenario branching does.
- Branch semantics: the child run is a scenario branch — it
  forks from the anchor's state snapshot at ``fork_step``
  (default: the branch midpoint convention) and runs the
  remaining ticks with the overridden bindings. Overrides apply
  from the fork point forward; pre-fork history is inherited.
  A fresh-from-tick-0 re-simulation is a different primitive
  and is deliberately not built here.
- No eager ensemble: creating the run is the definition's whole
  job. A Monte Carlo ensemble is a separate explicit step with
  its own endpoint and trial cost; the response names the
  monte-carlo URL for each child run, and narrative generation
  refuses with the existing ``narrative_requires_ensemble``
  until the ensemble exists.

The branch-creation capability arrives through a port
(:class:`BranchRunner`), mirroring the ``SkillLLMPort`` pattern:
the narratives service never imports the simulation service.
The production adapter lives in the route wiring
(:mod:`planagent.api.routes._deps`), which already owns both
services. Tests use scripted runners. Hardening (option B
follow-up): a runner that fails after committing reports the
committed branch via :class:`BranchCreationFailed`, and the port
carries :meth:`BranchRunner.discard_branch` so the service can
remove such a branch — and the branch of a direction that loses
a concurrent same-name race — instead of leaving orphans.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from planagent.services.narratives.models import DirectionError
from planagent.services.variables.models import (
    DistributionType,
    VariableDefinition,
    VariableDistribution,
    VariableSet,
)
from planagent.services.variables.validator import (
    merge_variable_sets,
    validate_scope_bindings,
    validate_variable_set,
)


@dataclass
class BranchRequest:
    """What the branch runner needs to create one override child run."""

    fork_step: int
    variable_set: VariableSet
    assumptions: list[str] = field(default_factory=list)
    # Arm resampling (fix/arm-resample): when true, the child run
    # re-draws its non-pinned variables from their own
    # distributions, deterministically from the run seed (see
    # ScenarioRunCreate.resample_variables). False keeps the
    # fork-snapshot precedence for every caller that does not opt
    # in — the pre-fix behavior.
    resample_variables: bool = False


@dataclass
class BranchResult:
    """What the branch runner reports back for one created branch."""

    branch_id: str
    run_id: str
    fork_step: int


class BranchCreationFailed(Exception):
    """Branch creation failed after the branch may have committed.

    Raised by a runner when the branch row was committed but the
    creation could not be reported normally (e.g. the adapter failed
    while building the result from the committed branch). The
    identities, when known, let the caller discard the committed
    branch instead of leaving it orphaned; ``None`` means the
    runner could not determine them, and there is nothing safe to
    discard. Plain exceptions from a runner still mean what they
    always meant: nothing was committed, and the caller's rollback
    covers the failure.
    """

    def __init__(
        self,
        message: str,
        *,
        branch_id: str | None = None,
        run_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.branch_id = branch_id
        self.run_id = run_id


class BranchRunner(Protocol):
    """Creates one scenario-branch run. Implemented by the wiring layer."""

    def is_available(self) -> bool:
        """Whether branch creation is wired up at all.

        The service checks this after whole-request grounding
        validation and before creating any branch: a missing
        runner refuses the whole request as unavailable (503),
        rather than failing each direction in turn.
        """
        ...

    async def create_branch(
        self, session: AsyncSession, parent_run_id: str, request: BranchRequest
    ) -> BranchResult: ...

    async def discard_branch(self, session: AsyncSession, branch_id: str) -> bool:
        """Delete one committed branch and its child run.

        The inverse of :meth:`create_branch`, for branches that
        committed but must not survive: a post-commit creation
        failure (see :class:`BranchCreationFailed`) or a direction
        that lost a concurrent same-name race. Deletes ONLY the
        named branch, its child run, and the rows branch execution
        created for that child; never touches other runs. Returns
        ``True`` when a branch was deleted, ``False`` when no such
        branch exists (already discarded: idempotent). The
        deletion commits, so it survives the caller's rollback.
        """
        ...


def build_override_set(anchor_bindings: VariableSet, overrides: dict[str, float]) -> VariableSet:
    """Build the inline override set for one direction.

    Each overridden variable keeps the anchor's bound definition
    with its distribution replaced by ``fixed`` at the override
    value. Every override id must already be bound on the anchor;
    an ungrounded id refuses with the valid ids named, before
    anything is built from it.
    """
    bound = {variable.id: variable for variable in anchor_bindings.variables}
    for variable_id in overrides:
        if variable_id not in bound:
            raise DirectionError(
                "direction_override_unknown_variable",
                f"Override names unknown variable {variable_id!r}. Valid "
                f"variables: {', '.join(sorted(bound)) or '(none)'}",
            )
    return VariableSet(
        name=anchor_bindings.name,
        variables=[
            VariableDefinition(
                id=variable_id,
                unit=bound[variable_id].unit,
                distribution=VariableDistribution(type=DistributionType.FIXED, value=value),
                evidence_ref=bound[variable_id].evidence_ref,
                description=bound[variable_id].description,
                scope_tags=list(bound[variable_id].scope_tags),
            )
            for variable_id, value in overrides.items()
        ],
    )


def validate_merged_overrides(
    anchor_bindings: VariableSet,
    override_set: VariableSet,
    root_scope: list[str] | None,
) -> VariableSet:
    """Merge the override set over the anchor bindings and gate it.

    Uses the Sprint 3 branch merge + validation discipline: the
    override wins per variable id, and the merged set must pass
    ``validate_variable_set`` plus the decomposition-root scope
    cross-check (when the anchor carries a tree). Returns the
    merged set; failures raise ``DirectionError`` naming the
    validation issues, before any run is created.
    """
    merged = merge_variable_sets(anchor_bindings, override_set)
    result = validate_variable_set(merged)
    issues = list(result.issues)
    if root_scope is not None:
        issues.extend(validate_scope_bindings(root_scope, merged))
    if issues:
        detail = "; ".join(
            f"{issue.kind}: {issue.message}" + (f" ({issue.variable})" if issue.variable else "")
            for issue in issues
        )
        raise DirectionError(
            "direction_override_invalid",
            f"Override variable set failed validation: {detail}",
        )
    return merged


def assumption_line(name: str, overrides: dict[str, float]) -> str:
    """One deterministic assumption line for the branch record.

    The branch record's assumptions list is the child run's own
    audit trail; the line names the direction and every override
    in sorted-id order so the same spec always renders the same
    line.
    """
    rendered = ", ".join(
        f"{variable_id}={overrides[variable_id]!r}" for variable_id in sorted(overrides)
    )
    return f"Direction {name!r}: override {rendered}."


__all__ = [
    "BranchCreationFailed",
    "BranchRequest",
    "BranchResult",
    "BranchRunner",
    "assumption_line",
    "build_override_set",
    "validate_merged_overrides",
]
