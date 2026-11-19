"""Pure deterministic validation for variable tables (Sprint 2).

No LLM, no randomness, no I/O. Rules are ported from
agilhaykal/strategic-simulation (``backend/engine.py``):

- 1-100 variables per set (raised from the reference's 30 by Ho's
  2026-11-17 decision; see ``MAX_VARIABLES``);
- every variable has a unit and an ``evidence_ref`` (an explicit
  ``estimate: ...`` reference counts as provenance);
- ``fixed`` requires ``value``; ``normal`` requires ``mean`` and ``std`` with
  ``std > 0``; ``triangular``/``beta_pert`` require ``min``/``mode``/``max``
  with ``min <= mode <= max`` and ``min != max``; ``bernoulli`` requires
  ``p`` with ``0 <= p <= 1``;
- duplicate variable ids are rejected.

On top of the reference, this module adds template-level checks (unique state
field names, policy threshold ordering) and the MECE scope cross-check used
when a run carries both a decomposition tree and variable bindings.
"""

from __future__ import annotations

from .correlation import build_correlation_matrix, is_positive_semidefinite
from .formulas import TICK_REFERENCE, validate_formulas
from .models import (
    MAX_VARIABLES,
    DistributionType,
    VariableCheckRecord,
    VariableCorrelation,
    VariableDefinition,
    VariableSet,
    VariableTemplate,
    VariableValidationIssue,
    VariableValidationResult,
)


class VariableValidationError(ValueError):
    """Raised when a variable set or template fails validation.

    Mirrors ``MeceValidationError``: the structured result travels with the
    exception so routes can return the repo's dict-detail error shape.
    """

    def __init__(self, result: VariableValidationResult, message: str | None = None) -> None:
        self.result = result
        super().__init__(message or "Variable validation failed.")


class VariableTemplateError(ValueError):
    """Raised when a template reference cannot be resolved for a run."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _issue(kind: str, message: str, variable: str = "") -> VariableValidationIssue:
    return VariableValidationIssue(kind=kind, variable=variable, message=message)


def _distribution_issues(variable: VariableDefinition) -> list[VariableValidationIssue]:
    distribution = variable.distribution
    issues: list[VariableValidationIssue] = []
    variable_id = variable.id

    def missing(param: str) -> VariableValidationIssue:
        return _issue(
            "missing_parameter",
            f"Distribution {distribution.type.value} requires parameter {param!r}.",
            variable_id,
        )

    if distribution.type is DistributionType.FIXED:
        if distribution.value is None:
            issues.append(missing("value"))
    elif distribution.type is DistributionType.NORMAL:
        if distribution.mean is None:
            issues.append(missing("mean"))
        if distribution.std is None:
            issues.append(missing("std"))
        elif distribution.std <= 0:
            issues.append(
                _issue(
                    "invalid_std",
                    "Normal distribution requires std > 0.",
                    variable_id,
                )
            )
    elif distribution.type in (DistributionType.TRIANGULAR, DistributionType.BETA_PERT):
        if distribution.min is None:
            issues.append(missing("min"))
        if distribution.mode is None:
            issues.append(missing("mode"))
        if distribution.max is None:
            issues.append(missing("max"))
        elif distribution.min is not None and distribution.mode is not None:
            if distribution.min == distribution.max:
                issues.append(
                    _issue(
                        "degenerate_bounds",
                        "Triangular/beta_pert bounds require min != max.",
                        variable_id,
                    )
                )
            elif not (distribution.min <= distribution.mode <= distribution.max):
                issues.append(
                    _issue(
                        "invalid_bounds",
                        "Triangular/beta_pert bounds require min <= mode <= max.",
                        variable_id,
                    )
                )
    elif distribution.type is DistributionType.BERNOULLI:
        if distribution.p is None:
            issues.append(missing("p"))
        elif not 0 <= distribution.p <= 1:
            issues.append(
                _issue(
                    "invalid_probability",
                    "Bernoulli distribution requires 0 <= p <= 1.",
                    variable_id,
                )
            )
    return issues


def validate_correlations(
    variables: list[VariableDefinition],
    correlations: list[VariableCorrelation],
) -> list[VariableValidationIssue]:
    """Validate a correlation spec against its variable set.

    Every pair must name two distinct variables that exist in the set,
    carry -1 <= rho <= 1, appear at most once (unordered), and involve
    no ``fixed`` variable (zero variance — correlation is undefined).
    The pairs together must form a positive-semidefinite matrix: an
    inconsistent spec (e.g. three variables pairwise +0.9, +0.9, -0.9)
    is rejected here, at the gate, rather than failing inside the
    sampler. An empty spec is valid and means independent sampling.
    """

    issues: list[VariableValidationIssue] = []
    by_id = {variable.id: variable for variable in variables}
    seen_pairs: set[frozenset[str]] = set()
    usable_pairs: list[tuple[str, str, float]] = []
    for spec in correlations:
        pair = frozenset((spec.variable_a, spec.variable_b))
        if spec.variable_a == spec.variable_b:
            issues.append(
                _issue(
                    "correlation_self_pair",
                    f"Correlation pair {spec.variable_a!r} names the same variable twice.",
                    spec.variable_a,
                )
            )
            continue
        if pair in seen_pairs:
            issues.append(
                _issue(
                    "correlation_duplicate_pair",
                    f"Correlation pair {spec.variable_a!r} / {spec.variable_b!r} "
                    "appears more than once.",
                    spec.variable_a,
                )
            )
            continue
        seen_pairs.add(pair)
        missing = [var_id for var_id in (spec.variable_a, spec.variable_b) if var_id not in by_id]
        if missing:
            issues.append(
                _issue(
                    "correlation_unknown_variable",
                    f"Correlation pair names unknown variable(s): {', '.join(missing)}.",
                    spec.variable_a,
                )
            )
            continue
        if not -1.0 <= spec.correlation <= 1.0:
            issues.append(
                _issue(
                    "correlation_out_of_range",
                    f"Correlation for {spec.variable_a!r} / {spec.variable_b!r} "
                    f"must be in [-1, 1]; got {spec.correlation!r}.",
                    spec.variable_a,
                )
            )
            continue
        fixed = [
            var_id
            for var_id in (spec.variable_a, spec.variable_b)
            if by_id[var_id].distribution.type is DistributionType.FIXED
        ]
        if fixed:
            issues.append(
                _issue(
                    "correlation_with_fixed",
                    f"Correlation pair involves fixed variable(s): {', '.join(fixed)} "
                    "(a fixed variable has zero variance, so correlation is undefined).",
                    spec.variable_a,
                )
            )
            continue
        usable_pairs.append((spec.variable_a, spec.variable_b, spec.correlation))

    if usable_pairs and not issues:
        involved = sorted({var_id for pair in usable_pairs for var_id in pair[:2]})
        matrix = build_correlation_matrix(involved, usable_pairs)
        if not is_positive_semidefinite(matrix):
            issues.append(
                _issue(
                    "correlation_matrix_not_positive_semidefinite",
                    "The correlation pairs do not form a valid (positive "
                    "semidefinite) correlation matrix; the pairwise values "
                    "are mutually inconsistent.",
                )
            )
    return issues


def validate_variable_set(variable_set: VariableSet) -> VariableValidationResult:
    """Validate a variable set, returning a structured result."""

    issues: list[VariableValidationIssue] = []
    checks: list[VariableCheckRecord] = []
    variables = variable_set.variables

    if not variables:
        issues.append(_issue("empty_set", "A variable set must contain at least 1 variable."))
    elif len(variables) > MAX_VARIABLES:
        issues.append(
            _issue(
                "too_many_variables",
                f"A variable set holds at most {MAX_VARIABLES} variables; got {len(variables)}.",
            )
        )
    checks.append(
        VariableCheckRecord(
            check="structure",
            status="fail"
            if any(issue.kind in {"empty_set", "too_many_variables"} for issue in issues)
            else "pass",
            detail=f"{len(variables)} variable(s)",
        )
    )

    seen_ids: set[str] = set()
    for variable in variables:
        if variable.id in seen_ids:
            issues.append(
                _issue(
                    "duplicate_variable",
                    f"Duplicate variable id {variable.id!r}.",
                    variable.id,
                )
            )
        seen_ids.add(variable.id)

        if variable.id == TICK_REFERENCE:
            issues.append(
                _issue(
                    "reserved_tick_id",
                    "Variable id 'tick' is reserved for the tick-driver tick reference.",
                    variable.id,
                )
            )

        if not variable.unit:
            issues.append(
                _issue("missing_unit", "Every variable must declare a unit.", variable.id)
            )
        if not variable.evidence_ref:
            issues.append(
                _issue(
                    "missing_evidence_ref",
                    "Every variable must carry an evidence_ref or an explicit estimate reference.",
                    variable.id,
                )
            )

        seen_tags: set[str] = set()
        for tag in variable.scope_tags:
            if not tag:
                issues.append(
                    _issue("invalid_scope_tag", "Scope tags must be non-empty.", variable.id)
                )
            elif tag in seen_tags:
                issues.append(
                    _issue(
                        "duplicate_scope_tag",
                        f"Duplicate scope tag {tag!r}.",
                        variable.id,
                    )
                )
            seen_tags.add(tag)

        distribution_issues = _distribution_issues(variable)
        issues.extend(distribution_issues)
        checks.append(
            VariableCheckRecord(
                variable=variable.id,
                check="distribution",
                status="fail" if distribution_issues else "pass",
                detail=f"type={variable.distribution.type.value}",
            )
        )

    provenance_failed = any(issue.kind == "missing_evidence_ref" for issue in issues)
    checks.append(
        VariableCheckRecord(
            check="provenance",
            status="fail" if provenance_failed else "pass",
            detail=f"{len(variables)} variable(s) checked",
        )
    )

    # Formula graph (Sprint 4): derived variables over the sampled set,
    # validated with the same gate discipline. No formulas means no extra
    # issues and no extra check record, so sets without formulas serialize
    # exactly as before.
    formula_issues, formula_checks = validate_formulas(variables, variable_set.formulas)
    issues.extend(formula_issues)
    checks.extend(formula_checks)

    # Correlation spec (Phase 2, Track 3): pairs over the sampled set,
    # validated with the same gate discipline. No correlations means no
    # extra issues and no extra check record, so sets without a spec
    # serialize exactly as before.
    correlation_issues = validate_correlations(variables, variable_set.correlations)
    issues.extend(correlation_issues)
    if variable_set.correlations:
        checks.append(
            VariableCheckRecord(
                check="correlations",
                status="fail" if correlation_issues else "pass",
                detail=f"{len(variable_set.correlations)} pair(s)",
            )
        )

    return VariableValidationResult(
        is_valid=not issues,
        variable_count=len(variables),
        checks=checks,
        issues=issues,
    )


def validate_or_raise(variable_set: VariableSet) -> VariableValidationResult:
    """Validate a set, raising :class:`VariableValidationError` on failure."""

    result = validate_variable_set(variable_set)
    if not result.is_valid:
        raise VariableValidationError(result)
    return result


def validate_template(template: VariableTemplate) -> VariableValidationResult:
    """Validate a template's state fields, policies, and variables.

    Templates may legitimately carry zero variables (a template that only
    overrides state defaults and policies), so the empty-set rule does not
    apply here; each variable present is validated with the same rules as a
    standalone set.
    """

    issues: list[VariableValidationIssue] = []
    checks: list[VariableCheckRecord] = []

    seen_fields: set[str] = set()
    for field in template.state_fields:
        if not field.name:
            issues.append(_issue("empty_state_field_name", "State field names must be non-empty."))
        elif field.name in seen_fields:
            issues.append(
                _issue(
                    "duplicate_state_field",
                    f"Duplicate state field {field.name!r}.",
                )
            )
        seen_fields.add(field.name)
    checks.append(
        VariableCheckRecord(
            check="state_fields",
            status="fail"
            if any(
                issue.kind in {"empty_state_field_name", "duplicate_state_field"}
                for issue in issues
            )
            else "pass",
            detail=f"{len(template.state_fields)} field(s)",
        )
    )

    for metric, policy in template.policies.items():
        ordered = (
            policy.alert_threshold > policy.critical_threshold
            if policy.preferred_direction == "increase"
            else policy.alert_threshold < policy.critical_threshold
        )
        if not ordered:
            issues.append(
                _issue(
                    "invalid_policy_thresholds",
                    (
                        f"Policy for {metric!r} has inconsistent thresholds for "
                        f"direction {policy.preferred_direction!r}."
                    ),
                )
            )
    checks.append(
        VariableCheckRecord(
            check="policies",
            status="fail"
            if any(issue.kind == "invalid_policy_thresholds" for issue in issues)
            else "pass",
            detail=f"{len(template.policies)} polic(ies)",
        )
    )

    if template.variables:
        set_result = validate_variable_set(
            VariableSet(
                name=template.name,
                variables=template.variables,
                internal=template.internal,
                correlations=template.correlations,
            )
        )
        # The set validator cannot flag empty_set here (variables is non-empty);
        # carry its issues and per-variable checks through unchanged. Formulas
        # are deliberately excluded from this constructed set: they are checked
        # once, below, against the template's own variables.
        issues.extend(set_result.issues)
        checks.extend(set_result.checks)
    elif template.correlations:
        # No variables means no set validation ran above, so a spec on a
        # variable-less template would otherwise never be checked: every
        # pair names an unknown variable here.
        correlation_issues = validate_correlations([], template.correlations)
        issues.extend(correlation_issues)
        checks.append(
            VariableCheckRecord(
                check="correlations",
                status="fail" if correlation_issues else "pass",
                detail=f"{len(template.correlations)} pair(s)",
            )
        )

    # Formula graph (Sprint 4): validated against the template's variables
    # even when the template carries no variables (literal-only formulas).
    formula_issues, formula_checks = validate_formulas(template.variables, template.formulas)
    issues.extend(formula_issues)
    checks.extend(formula_checks)

    if len(template.variables) > MAX_VARIABLES:
        issues.append(
            _issue(
                "too_many_variables",
                f"A template holds at most {MAX_VARIABLES} variables; got {len(template.variables)}.",
            )
        )

    return VariableValidationResult(
        is_valid=not issues,
        variable_count=len(template.variables),
        checks=checks,
        issues=issues,
    )


def validate_scope_bindings(
    scope_tags: list[str], variable_set: VariableSet
) -> list[VariableValidationIssue]:
    """Cross-check variable scope tags against a decomposition's root scope.

    Every tag a variable declares must appear in the decomposition root's
    scope list; a tag outside the decomposition means the binding refers to a
    part of the problem the tree does not cover. Returns the issues found
    (empty when the bindings are consistent).
    """

    allowed = set(scope_tags)
    issues: list[VariableValidationIssue] = []
    for variable in variable_set.variables:
        for tag in variable.scope_tags:
            if tag not in allowed:
                issues.append(
                    _issue(
                        "scope_tag_outside_decomposition",
                        f"Scope tag {tag!r} is not in the decomposition scope.",
                        variable.id,
                    )
                )
    return issues


def merge_variable_sets(base: VariableSet, override: VariableSet) -> VariableSet:
    """Merge two variable sets; the override wins on id collisions.

    Deterministic: base order is preserved, overridden variables are replaced
    in place, and new override variables are appended in override order. The
    internal tables merge with override values winning per key. Formulas
    merge with the same discipline: the override wins per output id.
    Assumption data merges per top-level key, override wins; nested values
    are replaced wholesale, never deep-merged.
    """

    merged: list[VariableDefinition] = list(base.variables)
    positions = {variable.id: index for index, variable in enumerate(merged)}
    for variable in override.variables:
        if variable.id in positions:
            merged[positions[variable.id]] = variable
        else:
            positions[variable.id] = len(merged)
            merged.append(variable)
    merged_formulas = list(base.formulas)
    formula_positions = {formula.output: index for index, formula in enumerate(merged_formulas)}
    for formula in override.formulas:
        if formula.output in formula_positions:
            merged_formulas[formula_positions[formula.output]] = formula
        else:
            formula_positions[formula.output] = len(merged_formulas)
            merged_formulas.append(formula)
    # Correlations merge with the same discipline: the override wins per
    # unordered pair, base order is preserved, new pairs append.
    merged_correlations = list(base.correlations)
    correlation_positions = {
        frozenset((spec.variable_a, spec.variable_b)): index
        for index, spec in enumerate(merged_correlations)
    }
    for spec in override.correlations:
        key = frozenset((spec.variable_a, spec.variable_b))
        if key in correlation_positions:
            merged_correlations[correlation_positions[key]] = spec
        else:
            correlation_positions[key] = len(merged_correlations)
            merged_correlations.append(spec)
    return VariableSet(
        name=override.name or base.name,
        variables=merged,
        formulas=merged_formulas,
        correlations=merged_correlations,
        internal={**base.internal, **override.internal},
        assumption_data={**base.assumption_data, **override.assumption_data},
    )
