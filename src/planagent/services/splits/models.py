"""Bottom-layer split-structure models (Phase 1, automotive track).

Dependency-free Pydantic models, mirroring the MECE/variables pattern, so
``domain/api.py`` can import ``SplitStructure`` without creating a cycle.

The structure is the MECE bottom layer of the synthesis design (§C1) plus
the two Ho-confirmed extensions: the SUPPLIER-SHARE dimension (Ho
2026-11-16: two suppliers split share per product slot; no supplier gets
100%) and the GENERATION dimension (Ho 2026-11-16: successive generations
under the same nameplate, each with its own product/solution mix and trim
structure; the outgoing generation phases out while the successor ramps).

Shape rules live here (finite numbers, non-empty ids, controlled
vocabularies); SUM rules live in the pure validator (:mod:`validator`),
so a bad split surfaces as a structured gate refusal (400) instead of a
422 — the same discipline as missing units on variables.

Phase 2 additions (all optional, backward compatible — Phase 1 payloads
validate unchanged):

- ``ProductFitment.solution_code``: the workbook solution label
  (e.g. ``"SA8650"``, ``"MFK:EQ4"``, ``"ABT12.9"``). The prompt engine
  classifies solutions by (code, product-line) pairs (Ho Q4 ruling);
  the code itself carries no global class.
- ``ProductFitment.price_basis``: ``"discrete"`` (default), ``"bundle"``
  (Huawei full-solution bundle incl. screen + cameras, Ho Q11), or
  ``"includes_screen"`` (IVI one-box P01 ASP includes the screen, Ho
  Q1/C4). Bundle / includes-screen prices are never compared with
  discrete ASPs.
- ``TrimSplit.morphology``: the computing-form attribute, a
  model x year property (Ho Q1/Q5/Q9): ``"ivi_one_box"``,
  ``"discrete_host"``, ``"scdc"``, ``"central_compute"``,
  ``"fused"`` (screen folded into the cockpit/P01, VW T-Roc/CC 2026).
- ``NameplateSplit.model_year``: the model year the structure row
  describes; morphology facts are keyed by (OEM, nameplate, year).
- ``NameplateSplit.transition_schedule``: the per-nameplate
  generation-transition schedule (Phase 2, replacing Phase 1's single
  global transition index for S-layer aggregation). The schedule
  interpolates the generation mix from the static shares toward the
  successor over ``duration_ticks`` starting at ``start_tick``.
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _require_finite_number(value: object) -> float:
    """Coerce a JSON number to a finite float (strings/bools/NaN rejected)."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("must be a finite number")
    return result


#: Computing-form vocabulary for ``TrimSplit.morphology`` (Ho Q1/Q5/Q9).
#: Morphology is a model x year attribute, never an OEM invariant.
MORPHOLOGIES = frozenset(
    {"ivi_one_box", "discrete_host", "scdc", "central_compute", "fused"}
)

#: Price-basis vocabulary for ``ProductFitment.price_basis``.
PRICE_BASES = frozenset({"discrete", "bundle", "includes_screen"})


class ProductFitment(BaseModel):
    """One row: one supplier's fitment of one product on one trim.

    ``fitment_kind`` separates the two fitment types the synthesis (§C1)
    says must never be confused: ``rate`` (a share of cars fitted, in
    [0, 1]) vs ``count`` (units per car, >= 0, e.g. cameras per vehicle).
    Multiple rows with the same ``product_id`` AND the same
    ``solution_code`` but different ``supplier_id`` in one trim are the
    legitimate supplier split: their ``supplier_share`` values must sum
    to 1 (the validator's solution-slot gate). Rows with different
    solution codes are different SOLUTIONS of one product line (e.g.
    instrument + central screens in P03): they coexist independently
    and each carries its own supplier split. Uncoded rows (``None``)
    group into one slot per product, preserving the Phase 1 behavior
    for structures without solution codes.
    ``price`` is the per-unit ASP for this product on this trim; None
    means unknown (capacity aggregation refuses unpriced slots loudly).

    Fitment rates are INDEPENDENT penetrations (Ho 2026-11-16 Q7):
    the rate is the share of that model x trim's production volume
    carrying the product, and rates across products/solutions need
    NOT sum to 1. No product-level sum gate exists anywhere.
    """

    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1, max_length=120)
    fitment_kind: Literal["rate", "count"]
    fitment: float
    supplier_id: str = Field(min_length=1, max_length=120)
    supplier_share: float
    price: float | None = None
    solution_code: str | None = Field(default=None, max_length=120)
    price_basis: Literal["discrete", "bundle", "includes_screen"] = "discrete"

    @field_validator("product_id", "supplier_id", mode="before")
    @classmethod
    def _strip_strings(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("solution_code", mode="before")
    @classmethod
    def _strip_solution_code(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @field_validator("fitment", "supplier_share", mode="before")
    @classmethod
    def _validate_finite(cls, value: object) -> float:
        return _require_finite_number(value)

    @field_validator("price", mode="before")
    @classmethod
    def _validate_price(cls, value: object) -> float | None:
        if value is None:
            return None
        return _require_finite_number(value)


class TrimSplit(BaseModel):
    """One trim (high/mid/low, or the actual trim label) of a generation.

    ``morphology`` is the computing-form attribute of this trim's
    model x year (Ho Q1/Q5/Q9). It is advisory data for the
    co-occurrence prompt engine, never a gate: a trim without a
    morphology simply yields no morphology prompts.
    """

    model_config = ConfigDict(extra="forbid")

    trim_id: str = Field(min_length=1, max_length=120)
    share: float
    fitments: list[ProductFitment] = Field(default_factory=list)
    morphology: Literal["ivi_one_box", "discrete_host", "scdc", "central_compute", "fused"] | None = None

    @field_validator("trim_id", mode="before")
    @classmethod
    def _strip_strings(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("share", mode="before")
    @classmethod
    def _validate_finite(cls, value: object) -> float:
        return _require_finite_number(value)


class GenerationSplit(BaseModel):
    """One generation of a nameplate, with its lifecycle phase.

    ``lifecycle_phase`` is the controlled vocabulary for the
    generation-transition dimension: ``ramp`` (successor ramping),
    ``mature`` (volume generation), ``phase_out`` (outgoing generation).
    """

    model_config = ConfigDict(extra="forbid")

    generation_id: str = Field(min_length=1, max_length=120)
    lifecycle_phase: Literal["ramp", "mature", "phase_out"]
    share: float
    trims: list[TrimSplit] = Field(default_factory=list)

    @field_validator("generation_id", mode="before")
    @classmethod
    def _strip_strings(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("share", mode="before")
    @classmethod
    def _validate_finite(cls, value: object) -> float:
        return _require_finite_number(value)


class GenerationTransitionSchedule(BaseModel):
    """Per-nameplate generation-transition schedule (Phase 2).

    The schedule interpolates the nameplate's generation mix from the
    static ``share`` values toward the successor: at tick ``t`` the
    progress is ``clamp((t - start_tick + 1) / duration_ticks, 0, 1)``;
    the outgoing generation's share moves from its static share toward
    0 and the successor's from its static share toward 1, linearly in
    progress. The two shares always sum to 1 (the static shares do).
    Ticks before ``start_tick`` use the static shares unchanged.

    A schedule requires exactly two generations on the nameplate — the
    outgoing (``phase_out``) and the successor (``ramp``) — enforced
    by the validator. Three-generation schedules are not modeled.
    """

    model_config = ConfigDict(extra="forbid")

    outgoing_generation_id: str = Field(min_length=1, max_length=120)
    successor_generation_id: str = Field(min_length=1, max_length=120)
    start_tick: int = Field(ge=1)
    duration_ticks: int = Field(ge=1)

    @field_validator("outgoing_generation_id", "successor_generation_id", mode="before")
    @classmethod
    def _strip_strings(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class NameplateSplit(BaseModel):
    """One nameplate (model line) of an OEM.

    ``energy`` and ``price_band`` are the two strongest explanatory
    variables (synthesis §C1 item 7): every nameplate carries them, and
    fitment priors are looked up by price band x energy. ``price_band``
    is a free string matching the lookup keys (e.g. "<10", "20-30").

    ``model_year`` (Phase 2, optional) is the model year this row
    describes; morphology registry facts are keyed by
    (OEM, nameplate, year). ``transition_schedule`` (Phase 2,
    optional) is the per-nameplate generation schedule; nameplates
    without one keep their static generation shares at every tick.
    """

    model_config = ConfigDict(extra="forbid")

    nameplate_id: str = Field(min_length=1, max_length=120)
    energy: Literal["NEV", "ICE"]
    price_band: str = Field(min_length=1, max_length=60)
    share: float
    generations: list[GenerationSplit] = Field(default_factory=list)
    model_year: int | None = Field(default=None, ge=1990, le=2100)
    transition_schedule: GenerationTransitionSchedule | None = None

    @field_validator("nameplate_id", "price_band", mode="before")
    @classmethod
    def _strip_strings(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("share", mode="before")
    @classmethod
    def _validate_finite(cls, value: object) -> float:
        return _require_finite_number(value)


class OemSplit(BaseModel):
    """One OEM with its nameplate splits.

    ``customer_status`` (Ho 2026-11-16): ``existing`` customers get
    supply-share attribution; ``prospect`` customers (e.g. Dongfeng
    Honda, not yet developed) get market capacity computed but a supply
    share of 0 in the S-layer.
    """

    model_config = ConfigDict(extra="forbid")

    oem_id: str = Field(min_length=1, max_length=120)
    customer_status: Literal["existing", "prospect"] = "existing"
    nameplates: list[NameplateSplit] = Field(default_factory=list)

    @field_validator("oem_id", mode="before")
    @classmethod
    def _strip_strings(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class SplitStructure(BaseModel):
    """The full bottom-layer split tree attached to a run."""

    model_config = ConfigDict(extra="forbid")

    oems: list[OemSplit] = Field(default_factory=list)


class SplitCheckRecord(BaseModel):
    """One recorded check, mirroring the MECE/variables check records."""

    model_config = ConfigDict(extra="forbid")

    check: str
    status: str
    detail: str = ""


class SplitValidationIssue(BaseModel):
    """One structured validation problem, located by tree path."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    path: str = ""
    message: str


class SplitValidationResult(BaseModel):
    """Outcome of validating a split structure."""

    model_config = ConfigDict(extra="forbid")

    is_valid: bool
    checks: list[SplitCheckRecord] = Field(default_factory=list)
    issues: list[SplitValidationIssue] = Field(default_factory=list)


class OemProductionShares(BaseModel):
    """Stored per-OEM production shares: the S-layer's OEM-mix input.

    Phase 2 left the OEM mix caller-supplied at S-layer computation
    time because no stored mix existed. The S-layer real-splits work
    stores it as a run input instead: attached at run creation beside
    the split structure, validated against the structure's OEMs by the
    same refuse-before-write gate, carried into the run's
    ``split_structure`` configuration fragment (so the Sprint 3 input
    hash covers it), and inherited by living-loop re-simulations. The
    sales-layer endpoint uses the stored shares when the request body
    omits them; an explicit body still overrides.

    Shape rules live here (non-empty map, finite per-OEM values in
    [0, 1], a non-empty provenance ``source``); the coverage + sum-to-1
    rules live in :func:`validator.validate_oem_shares`, which needs
    the structure. ``source`` + ``as_of`` + ``notes`` are provenance,
    not decoration: a stored mix is only interpretable with its
    denominator (which OEM set the shares sum over) recorded. See
    :mod:`real_structure` for the workbook-derived instance.
    """

    model_config = ConfigDict(extra="forbid")

    shares: dict[str, float] = Field(min_length=1)
    source: str = Field(min_length=1, max_length=200)
    as_of: str | None = Field(default=None, max_length=40)
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("shares", mode="before")
    @classmethod
    def _validate_share_values(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        for oem_id, share in value.items():
            if (
                isinstance(share, bool)
                or not isinstance(share, (int, float))
                or not math.isfinite(float(share))
                or not 0.0 <= float(share) <= 1.0
            ):
                raise ValueError(
                    f"Production share for OEM {oem_id!r} must be a number in [0, 1]."
                )
        return value
