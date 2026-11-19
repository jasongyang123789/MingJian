"""Variable-table models (Sprint 2, PRD deltas D2/D3).

Dependency-free Pydantic models, mirroring the Sprint 1 MECE module: this file
imports nothing from the rest of the application, so ``domain/api.py`` can
import ``VariableSet`` without creating a cycle.

Semantics are ported from agilhaykal/strategic-simulation
(``SimplifySimulation``, ``backend/engine.py``): a variable table holds 1-100
variables — the reference pins the cap at 30; it was raised to 100 by Ho's
2026-11-17 decision (the cap was a Sprint 2 design pin, not a semantic
limit) — each with a unit, a distribution (fixed / normal / triangular /
beta_pert / bernoulli), and an ``evidence_ref`` provenance reference (an
explicit ``estimate: ...`` reference counts as provenance). Bounds rules live
in :mod:`validator`; this module only enforces shape, string hygiene, and
finite numeric parameters.
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DistributionType(str, Enum):
    """Supported variable distributions.

    Matches the distribution vocabulary of the SimplifySimulation reference.
    Correlation between variables is supported via
    :class:`VariableCorrelation` on the set (Gaussian copula in the
    sampler); the reference's rejection of correlation is not carried
    over — see ``services/variables/correlation.py``.
    """

    FIXED = "fixed"
    NORMAL = "normal"
    TRIANGULAR = "triangular"
    BETA_PERT = "beta_pert"
    BERNOULLI = "bernoulli"


#: Maximum variables per set/template. Raised from the reference's 30 to
#: 100 by Ho's 2026-11-17 decision (the Sprint 2 pin); the automotive
#: template's promotion of two literal rates to variables depends on it.
MAX_VARIABLES = 100
MAX_INTERNAL_KEY_LENGTH = 64
MAX_INTERNAL_VALUE_LENGTH = 2000
#: Maximum formulas per set/template, ported from the SimplifySimulation
#: reference (``len(formula_graph) > 40`` is rejected there).
MAX_FORMULAS = 40
#: Maximum expression nesting depth, ported from the reference
#: (``depth > 15`` is rejected there).
MAX_FORMULA_DEPTH = 15


class FormulaOperator(str, Enum):
    """The formula-graph operator vocabulary.

    Ported from the SimplifySimulation reference (``OPS``): six binary
    operators, no arbitrary code. ``min``/``max`` are binary here
    (two arguments), matching the reference's two-argument expressions.

    ``pow`` and ``logistic`` extend the reference vocabulary (Fix 2,
    inflection/diffusion dynamics) without changing its shape: still
    binary, still arity 2, still no function calls or arbitrary code.
    ``pow(base, exponent)`` is the power function; ``logistic(z,
    ceiling)`` is ``ceiling / (1 + exp(-z))``, the S-curve primitive
    a disruptor-adoption driver is built from.
    """

    ADD = "add"
    SUBTRACT = "subtract"
    MULTIPLY = "multiply"
    DIVIDE = "divide"
    MIN = "min"
    MAX = "max"
    POW = "pow"
    LOGISTIC = "logistic"


class FormulaDefinition(BaseModel):
    """One derived variable in a formula graph (Sprint 4, PRD delta D7).

    ``output`` is the derived variable's id (unique within the set, and it
    must not collide with a sampled variable id). ``expression`` is raw JSON
    in the reference's expression shape: a finite number literal, a
    ``{"ref": "<id>"}`` reference, or a ``{"op": "<operator>", "args":
    [<expr>, <expr>]}`` node with exactly two arguments. The expression is
    deliberately held as untyped JSON here: its shape is checked by the
    pure validator (:mod:`formulas`), so malformed expressions surface as
    structured validation issues at the gate instead of 422s — the same
    discipline as missing units and provenance on variables.

    ``tick_driver`` (Phase 1, automotive track) marks a formula that is
    evaluated on EVERY tick instead of once per run: the executor skips it
    at run start and re-evaluates it per tick over the sampled values, the
    initial derived values, the current state, and the tick index. A tick
    driver may reference its own output id (the current state value) and
    the reserved ``tick`` reference; see :mod:`formulas` for the exact
    scope rules. ``False`` (the default) keeps the Sprint 4 once-per-run
    semantics exactly.
    """

    model_config = ConfigDict(extra="forbid")

    output: str = Field(min_length=1, max_length=120)
    expression: Any
    description: str = Field(default="", max_length=2000)
    tick_driver: bool = False

    @field_validator("output", "description", mode="before")
    @classmethod
    def _strip_strings(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


def _require_finite_number(value: object) -> float:
    """Coerce a JSON number to a finite float.

    Strings are rejected (the reference requires real numbers, and silently
    coercing ``"12"`` would hide authoring mistakes); booleans, NaN, and
    infinities are rejected too.
    """

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("must be a finite number")
    return result


class VariableDistribution(BaseModel):
    """Distribution plus its parameters.

    Only the parameters relevant to ``type`` are required (enforced by the
    validator); parameters for other distribution types are ignored when
    present, matching the reference implementation. Every numeric parameter
    must be finite.
    """

    model_config = ConfigDict(extra="forbid")

    type: DistributionType
    value: float | None = None
    mean: float | None = None
    std: float | None = None
    min: float | None = None
    mode: float | None = None
    max: float | None = None
    p: float | None = None

    @field_validator("value", "mean", "std", "min", "mode", "max", "p", mode="before")
    @classmethod
    def _validate_finite(cls, value: object) -> float | None:
        if value is None:
            return None
        return _require_finite_number(value)


class VariableCorrelation(BaseModel):
    """One pairwise correlation between two sampled variables.

    ``correlation`` is the target Pearson correlation in [-1, 1] between
    ``variable_a`` and ``variable_b``. The sampler realises it as a
    Gaussian copula, so the achieved Pearson correlation is approximately
    (not exactly) this value: exact for normal marginals, slightly
    attenuated for bounded/skewed marginals and for Bernoulli marginals.
    The pair is unordered — (a, b, rho) and (b, a, rho) are the same
    pair and may not both appear. All pairs together must form a
    positive-semidefinite matrix (enforced by the validator); a
    ``fixed`` variable has zero variance and cannot be correlated.
    """

    model_config = ConfigDict(extra="forbid")

    variable_a: str = Field(min_length=1, max_length=120)
    variable_b: str = Field(min_length=1, max_length=120)
    correlation: float

    @field_validator("variable_a", "variable_b", mode="before")
    @classmethod
    def _strip_strings(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("correlation", mode="before")
    @classmethod
    def _validate_finite(cls, value: object) -> float:
        return _require_finite_number(value)


class VariableDefinition(BaseModel):
    """One variable in a variable table.

    ``id`` is the stable variable key (unique within a set). ``unit`` is
    required so downstream consumers never have to guess the scale.
    ``evidence_ref`` is the provenance reference: a pointer to evidence, or
    an explicit ``estimate: ...`` marker recording that the value is a human
    estimate. ``scope_tags`` optionally bind the variable to MECE scope tags
    from the run's decomposition tree (cross-checked by the validator).

    ``unit`` and ``evidence_ref`` default to empty (rather than failing
    Pydantic shape validation) so missing values surface as structured
    validation issues from the validator, matching the empty-set rule.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=120)
    unit: str = Field(default="", max_length=60)
    distribution: VariableDistribution
    evidence_ref: str = Field(default="", max_length=500)
    description: str = Field(default="", max_length=2000)
    scope_tags: list[str] = Field(default_factory=list)

    @field_validator("id", "unit", "evidence_ref", "description", mode="before")
    @classmethod
    def _strip_strings(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("scope_tags", mode="before")
    @classmethod
    def _normalize_scope_tags(cls, value: object) -> object:
        if isinstance(value, list):
            return [tag.strip() if isinstance(tag, str) else tag for tag in value]
        return value


class VariableSet(BaseModel):
    """A named set of variables plus the internal-situation table.

    ``internal`` mirrors the prototype's ``internal`` table (free-form
    key/value context such as decision-maker style, team, cash runway): keys
    and values follow the same length limits as the run decision-context
    normalizer. The validator enforces the 1-100 variable count, so this model
    deliberately carries no length constraint on ``variables`` — an empty or
    oversized set must surface as a structured validation issue, not a 422.

    ``formulas`` (Sprint 4) is the formula graph: derived variables computed
    from the sampled variables, evaluated in list order (the topological
    order — a formula may only reference variables and earlier formulas).

    ``assumption_data`` (Phase 1, automotive track) is opaque template-bound
    JSON consumed by domain helpers, not by the sampler or the formula
    graph: lookup tables and assumption parameters that travel with the
    bindings so a run's audit trail pins exactly which assumptions it ran
    under (e.g. the automotive price-band × energy fitment priors). Merging
    replaces whole top-level keys (see :func:`merge_variable_sets`); the
    validator treats the content as opaque and never inspects it.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="", max_length=200)
    variables: list[VariableDefinition] = Field(default_factory=list)
    formulas: list[FormulaDefinition] = Field(default_factory=list)
    correlations: list[VariableCorrelation] = Field(default_factory=list)
    internal: dict[str, str] = Field(default_factory=dict)
    assumption_data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name", mode="before")
    @classmethod
    def _strip_name(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("internal", mode="before")
    @classmethod
    def _normalize_internal(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        normalized: dict[str, str] = {}
        for raw_key, raw_value in value.items():
            key = raw_key.strip() if isinstance(raw_key, str) else raw_key
            text = raw_value.strip() if isinstance(raw_value, str) else raw_value
            if not isinstance(key, str) or not key:
                raise ValueError("internal keys must be non-empty strings")
            if len(key) > MAX_INTERNAL_KEY_LENGTH:
                raise ValueError(
                    f"internal key {key!r} exceeds {MAX_INTERNAL_KEY_LENGTH} characters"
                )
            if not isinstance(text, str):
                raise TypeError("internal values must be strings")
            if len(text) > MAX_INTERNAL_VALUE_LENGTH:
                raise ValueError(
                    f"internal value for {key!r} exceeds {MAX_INTERNAL_VALUE_LENGTH} characters"
                )
            normalized[key] = text
        return normalized


class VariableValidationIssue(BaseModel):
    """One structured validation problem."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    variable: str = ""
    message: str


class VariableCheckRecord(BaseModel):
    """One recorded check, mirroring the MECE check records."""

    model_config = ConfigDict(extra="forbid")

    variable: str = ""
    check: str
    status: str
    detail: str = ""


class VariableValidationResult(BaseModel):
    """Outcome of validating a variable set or template."""

    model_config = ConfigDict(extra="forbid")

    is_valid: bool
    variable_count: int = 0
    checks: list[VariableCheckRecord] = Field(default_factory=list)
    issues: list[VariableValidationIssue] = Field(default_factory=list)


class TemplateStateField(BaseModel):
    """One state field default in a variable template.

    Templates generalize the hardcoded domain-pack state defaults: a field
    name, a human description, and the default value a run starts from before
    actor-template and ``initial_state`` overlays apply.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    default: float

    @field_validator("name", "description", mode="before")
    @classmethod
    def _strip_strings(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("default", mode="before")
    @classmethod
    def _validate_finite(cls, value: object) -> float:
        return _require_finite_number(value)


class MetricPolicySpec(BaseModel):
    """Templated form of ``MetricPolicy`` (see ``simulation_branching``).

    ``preferred_direction`` says whether higher values are better
    (``increase``) or lower values are better (``decrease``). Threshold
    ordering is enforced by the template validator: for ``increase``,
    ``alert_threshold > critical_threshold``; for ``decrease`` the reverse.
    """

    model_config = ConfigDict(extra="forbid")

    preferred_direction: str = Field(pattern="^(increase|decrease)$")
    alert_threshold: float
    critical_threshold: float

    @field_validator("alert_threshold", "critical_threshold", mode="before")
    @classmethod
    def _validate_finite(cls, value: object) -> float:
        return _require_finite_number(value)


class VariableTemplate(BaseModel):
    """A variable template: state defaults + metric policies + variables.

    Built-in templates (``builtin:<domain_id>``) are synthesized from the
    domain-pack code at read time and are never stored or edited, so their
    defaults hold identical to the packs by construction.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    domain_id: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=2000)
    state_fields: list[TemplateStateField] = Field(default_factory=list)
    policies: dict[str, MetricPolicySpec] = Field(default_factory=dict)
    variables: list[VariableDefinition] = Field(default_factory=list)
    formulas: list[FormulaDefinition] = Field(default_factory=list)
    correlations: list[VariableCorrelation] = Field(default_factory=list)
    internal: dict[str, str] = Field(default_factory=dict)
    assumption_data: dict[str, Any] = Field(default_factory=dict)
    is_builtin: bool = False

    @field_validator("id", "name", "domain_id", "description", mode="before")
    @classmethod
    def _strip_strings(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("internal", mode="before")
    @classmethod
    def _normalize_internal(cls, value: object) -> object:
        # Reuse the VariableSet normalizer so both tables share the limits.
        return VariableSet._normalize_internal(value)


class VariableTemplateCreate(BaseModel):
    """Payload for creating a stored variable template."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    domain_id: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=2000)
    state_fields: list[TemplateStateField] = Field(default_factory=list)
    policies: dict[str, MetricPolicySpec] = Field(default_factory=dict)
    variables: list[VariableDefinition] = Field(default_factory=list)
    formulas: list[FormulaDefinition] = Field(default_factory=list)
    correlations: list[VariableCorrelation] = Field(default_factory=list)
    internal: dict[str, str] = Field(default_factory=dict)
    assumption_data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name", "domain_id", "description", mode="before")
    @classmethod
    def _strip_strings(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("internal", mode="before")
    @classmethod
    def _normalize_internal(cls, value: object) -> object:
        return VariableSet._normalize_internal(value)


class VariableTemplateUpdate(BaseModel):
    """Payload for updating a stored variable template.

    All fields are optional; omitted fields keep their stored values, and
    provided collections replace the stored ones wholesale. ``domain_id`` is
    immutable and is not accepted here.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    state_fields: list[TemplateStateField] | None = None
    policies: dict[str, MetricPolicySpec] | None = None
    variables: list[VariableDefinition] | None = None
    formulas: list[FormulaDefinition] | None = None
    correlations: list[VariableCorrelation] | None = None
    internal: dict[str, str] | None = None
    assumption_data: dict[str, Any] | None = None

    @field_validator("name", "description", mode="before")
    @classmethod
    def _strip_strings(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("internal", mode="before")
    @classmethod
    def _normalize_internal(cls, value: object) -> object:
        if value is None:
            return None
        return VariableSet._normalize_internal(value)


class VariableTemplateRead(VariableTemplate):
    """A template as returned by the API, with persistence timestamps.

    Built-in templates have no stored timestamps (``None``).
    """

    created_at: str | None = None
    updated_at: str | None = None


class VariableRunRead(BaseModel):
    """The variable bindings attached to a run, for audit retrieval."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    template: VariableTemplate | None = None
    bindings: VariableSet | None = None
    validation: VariableValidationResult | None = None
