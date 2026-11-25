"""Key-opportunity and breakout prompts (Phase 4, Track 9).

Two prompt mechanisms, both report-time checks that CHANGE NO NUMBERS --
they only produce prompt text and suggested actions:

1. **Discounted-growth prompt ("重点机遇提示")** -- when a case's
   decision-time parameter DELIBERATELY DISCOUNTS an observed high growth
   rate, the system surfaces the observed value, the discounted value, the
   gap, and the conditional ("if the high growth persists, the outcome is
   X"). The discount stays allowed; the prompt makes it visible. Opt-in
   per variable via the ``observed_value`` / ``observed_label`` annotation
   on :class:`VariableDefinition` (see ``models.py``); without the
   annotation there is no prompt. This is Ho's 2026-11-19 item (e).

2. **Breakout prompts T1-T4 ("爆发提示")** -- the acceleration /
   explosion factor, built as a prompt mechanism per Ho's ruling and the
   desay-2020 diagnostic (``diagnostic-2020/DIAGNOSTIC-2020.md`` §5.5;
   design in ``new-parameter.md`` §2.5). The diagnostic finds the
   acceleration factor NON-IDENTIFIABLE as a growth parameter (no causal
   referent, almost perfectly collinear with ``revenue_growth``, no
   decision-time evidence to calibrate; as a time-varying pulse it would
   just be another time curve, already excluded by Ho's ruling), so it is
   NOT a formula term and NOT a parameter: it is a set of report-time
   checks at direction review / backtest diagnosis / monitoring review.
   Each prompt carries the diagnostic's four structured fields:
   (i) trigger + numbers; (ii) the stretched assumption; (iii) the named
   uncaptured-upside hypothesis; (iv) suggested action.

Triggers (exact, from DIAGNOSTIC-2020.md §5.5):

- T1: any growth input assumption with sustained growth > 25%/yr (above
  the 2020 defensible ceiling ~20%). Checked on the case's input
  variables at run creation, so it is also surfaced in the run-creation
  response. Operationalization: a variable whose id ends in ``_growth``
  (the codebase's growth-rate naming convention) whose CENTRAL value
  (mode / mean / fixed value -- the sustained assumption, NOT the
  optimistic distribution max) exceeds 0.25. ``disruptor_rate`` is
  deliberately excluded: it is a logistic steepness, not a sustained
  growth rate.
- T2: actual first-year growth exceeds the modeled first-year implied
  growth by > 15pp (monitoring / review time -- needs post-decision
  actuals, so it is a review-time function, not computed at run
  creation). The modeled value is an input, e.g. the B-arm replay
  tick-0 to tick-1 growth (+18.8% for desay-2020).
- T3: a diagnostic fitted value exceeds its variable's distribution max
  by > 2x (backtest diagnosis time). Takes the fitted value and the
  distribution max as inputs; the variable need not be in the current
  run's set (e.g. the NEV-chain ``nev_coupling`` fitted 2.08 vs max
  0.40).
- T4: annualized new-order growth > 50%/yr, OR annualized orders
  > 1.2x current-year revenue AND growing (when order data exists).
  "Growing" is operationalized as year-over-year order growth > 0; when
  order growth is unknown, the ratio clause cannot fire.

Honest boundary (diagnostic §5.5, §7): the mechanism fixes the SPEED
OF DISCOVERY, not prediction accuracy. T1/T4 do not trigger at
2020-12-31 for desay-2020; T2/T4 trigger in 2021 once actuals arrive.
It cannot let a 2020 decision-maker foresee the 2021 explosion.

Boundary verdict (§6, Ho 15:02 item (c)): every T1-T4 prompt carries
``boundary_class`` (``fixable_defect`` | ``acceptable_limit`` |
``unclassified``) + ``boundary_basis`` (one sentence citing the §6
standard). The standard: what decision-time public evidence could
encode into a distribution is something the model should have had --
its absence is a FIXABLE DEFECT; what only later data could reveal is
an ACCEPTABLE LIMIT -- missing it is not a defect. The classification
is an analyst judgment: the checks default to ``unclassified`` with a
stated reason, and an explicit classification must arrive together
with its basis -- never classify for the sake of filling the field.

Pure and deterministic: no LLM, no randomness, no I/O. All thresholds
are strict ``>`` (a value exactly at the threshold does not trigger),
matching the diagnostic's "超过" wording.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import DistributionType, VariableDefinition

#: Fire the discounted-growth prompt when the observed rate exceeds the
#: modeled central value by more than this many percentage points.
DISCOUNT_THRESHOLD_PP = 0.05

#: T1: sustained-growth trigger -- a growth input assumption above this
#: rate is flagged. The diagnostic's 2020 defensible ceiling (~20%) is
#: the default ``defensible_ceiling`` parameter of :func:`check_t1`.
T1_GROWTH_THRESHOLD = 0.25
T1_DEFENSIBLE_CEILING = 0.20

#: T2: actual first-year growth must exceed modeled first-year implied
#: growth by more than this (fraction of 1, i.e. percentage points).
T2_GAP_THRESHOLD_PP = 0.15

#: T3: a diagnostic fitted value must exceed its distribution max by
#: more than this multiple.
T3_STRETCH_MULTIPLE = 2.0

#: T4: annualized new-order growth above this, or orders above this
#: multiple of current-year revenue while growing.
T4_ORDER_GROWTH_THRESHOLD = 0.50
T4_ORDER_REVENUE_RATIO = 1.2

#: Suggested actions (diagnostic §5.5): the four actions a prompt may
#: recommend. Individual triggers pick the applicable subset.
SUGGESTED_ACTIONS = (
    "加一条驱动链",
    "放宽分布并注明依据",
    "加开一个繁荣情景臂",
    "将该案例标注为“预测上限受限”",
)

#: Boundary verdicts (diagnostic §6, Ho 15:02 item (c)).
BoundaryClass = Literal["fixable_defect", "acceptable_limit", "unclassified"]

BOUNDARY_LABELS: dict[str, str] = {
    "fixable_defect": "应修的机制缺失",
    "acceptable_limit": "可接受的预测上限",
    "unclassified": "暂未分类",
}

#: Default boundary bases, used when the caller supplies no verdict:
#: the evidence in the trigger inputs does not decide the §6 question,
#: so the prompt stays unclassified and says why.
T1_DEFAULT_BOUNDARY_BASIS = (
    "仅凭输入假设高于上限，无法判定高增速来自缺失的链还是不可预见的量级"
    "——需复核驱动完整性后定性（§6）。"
)
T2_DEFAULT_BOUNDARY_BASIS = (
    "首年实际超越模型上限，说明存在未捕捉的前置驱动或量级 surprise——需复核缺失通道后定性（§6）。"
)
T3_DEFAULT_BOUNDARY_BASIS = (
    "拟合值超出分布上限，说明假设被拉伸——需判定拉伸来自缺失的链还是不可预见的量级后定性（§6）。"
)
T4_DEFAULT_BOUNDARY_BASIS = (
    "订单激增揭示模型内无订单簿状态变量——需判定机制缺失与量级 surprise各占多少后定性（§6）。"
)


def _resolve_boundary(
    boundary_class: str | None,
    boundary_basis: str | None,
    default_basis: str,
) -> tuple[BoundaryClass, str]:
    """Resolve the §6 boundary verdict for a breakout prompt.

    The classification is an analyst judgment under the diagnostic §6
    standard (encodable from decision-time public evidence -> defect;
    knowable only from later data -> acceptable limit). It must be given
    together with its basis, or not at all: a lone class or a lone basis
    raises ValueError, and the default is "unclassified" with a
    trigger-specific basis stating why the evidence does not decide it.
    Never classify for the sake of filling the field.
    """

    if boundary_class is None and boundary_basis is None:
        return "unclassified", default_basis
    if boundary_class is None or boundary_basis is None:
        raise ValueError("boundary_class and boundary_basis must be given together")
    if boundary_class not in BOUNDARY_LABELS:
        raise ValueError(f"unknown boundary_class {boundary_class!r}")
    if not boundary_basis.strip():
        raise ValueError("boundary_basis must be non-empty")
    return boundary_class, boundary_basis  # type: ignore[return-value]


def _boundary_sentence(boundary_class: str, boundary_basis: str) -> str:
    """The boundary verdict as rendered at the end of the prompt text."""

    return f"边界判定：{BOUNDARY_LABELS[boundary_class]}——{boundary_basis}"


class KeyOpportunityPrompt(BaseModel):
    """A discounted-growth ("重点机遇提示") prompt for one variable.

    The discount itself stays allowed -- this prompt only makes it
    visible. ``gap_pp`` is the absolute gap as a fraction (0.1239 =
    12.39 percentage points). The compounding multiples are the
    conditional: over ``horizon_ticks`` years, the observed rate alone
    compounds to ``observed_multiple`` x the base, the discounted rate to
    ``discounted_multiple`` x. When a level variable pairs with the
    growth variable (``<X>_growth`` -> ``<X>``), the projected levels are
    also given. The multiples are a partial-equilibrium illustration --
    they compound ONLY this growth rate and exclude adoption coupling
    and every other driver (see ``caveat``).
    """

    model_config = ConfigDict(extra="forbid")

    variable_id: str
    variable_description: str = ""
    unit: str = ""
    observed_value: float
    observed_label: str
    discounted_value: float
    discounted_label: str
    gap_pp: float
    gap_relative: float | None
    horizon_ticks: int
    observed_multiple: float | None
    discounted_multiple: float | None
    multiple_ratio: float | None
    base_variable_id: str | None = None
    base_value: float | None = None
    base_unit: str = ""
    projected_observed: float | None = None
    projected_discounted: float | None = None
    text: str
    caveat: str


class BreakoutPrompt(BaseModel):
    """One T1-T4 breakout ("爆发提示") prompt.

    The four structured content fields are exactly the diagnostic's
    §5.5 fields: (i) ``trigger_numbers`` -- trigger + numbers;
    (ii) ``stretched_assumption`` -- the assumption being stretched;
    (iii) ``uncaptured_upside_hypothesis`` -- the named uncaptured-upside
    hypothesis; (iv) ``suggested_action`` -- the suggested action.
    ``details`` carries the trigger-specific numbers for audit (keys
    documented per trigger in the check functions' docstrings).
    ``boundary_class`` / ``boundary_basis`` carry the §6 verdict: whether
    the gap is a fixable defect or an acceptable prediction limit
    (default ``unclassified`` -- see :func:`_resolve_boundary`).
    """

    model_config = ConfigDict(extra="forbid")

    trigger_id: str
    title: str
    trigger_numbers: str
    stretched_assumption: str
    uncaptured_upside_hypothesis: str
    suggested_action: str
    text: str
    boundary_class: BoundaryClass = "unclassified"
    boundary_basis: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


def central_value(variable: VariableDefinition) -> tuple[float, str] | None:
    """The variable's central (sustained-assumption) value + its label.

    Triangular / beta_pert -> mode ("众数"); fixed -> value ("取值");
    normal -> mean ("均值"). Bernoulli has no sustained rate, so it
    returns None. A missing parameter also returns None.
    """

    dist = variable.distribution
    if dist.type is DistributionType.TRIANGULAR:
        return (dist.mode, "众数") if dist.mode is not None else None
    if dist.type is DistributionType.BETA_PERT:
        return (dist.mode, "众数") if dist.mode is not None else None
    if dist.type is DistributionType.FIXED:
        return (dist.value, "取值") if dist.value is not None else None
    if dist.type is DistributionType.NORMAL:
        return (dist.mean, "均值") if dist.mean is not None else None
    return None


def _fmt_num(value: float) -> str:
    """Format a number with up to 3 decimals, trailing zeros trimmed."""

    text = f"{value:.3f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _level_variable_id(growth_variable_id: str) -> str | None:
    """The level variable paired with a ``<X>_growth`` variable: ``<X>``."""

    suffix = "_growth"
    if growth_variable_id.endswith(suffix):
        return growth_variable_id[: -len(suffix)]
    return None


def detect_discount_prompts(
    variables: list[VariableDefinition],
    horizon_ticks: int,
) -> list[KeyOpportunityPrompt]:
    """Discounted-growth prompts for a variable set (decision time).

    Fires for each variable carrying an ``observed_value`` annotation
    whose observed rate exceeds the modeled central value by more than
    :data:`DISCOUNT_THRESHOLD_PP` (5pp). The modeled value is the
    distribution's central value (mode / mean / fixed value). A level
    variable ``<X>`` pairs with ``<X>_growth`` when present, supplying
    the projected levels; without a pair the prompt stays in
    multiple terms. Returns prompts in variable-list order.
    """

    by_id = {variable.id: variable for variable in variables}
    prompts: list[KeyOpportunityPrompt] = []
    for variable in variables:
        if variable.observed_value is None:
            continue
        central = central_value(variable)
        if central is None:
            continue
        discounted, discounted_label = central
        observed = variable.observed_value
        gap = observed - discounted
        if gap <= DISCOUNT_THRESHOLD_PP:
            continue
        gap_relative = gap / discounted if discounted != 0 else None
        observed_multiple: float | None = None
        discounted_multiple: float | None = None
        multiple_ratio: float | None = None
        if 1.0 + observed > 0 and 1.0 + discounted > 0:
            observed_multiple = (1.0 + observed) ** horizon_ticks
            discounted_multiple = (1.0 + discounted) ** horizon_ticks
            multiple_ratio = observed_multiple / discounted_multiple
        base_variable_id = _level_variable_id(variable.id)
        base_value: float | None = None
        base_unit = ""
        projected_observed: float | None = None
        projected_discounted: float | None = None
        if base_variable_id is not None and base_variable_id in by_id:
            level_central = central_value(by_id[base_variable_id])
            if level_central is not None:
                base_value = level_central[0]
                base_unit = by_id[base_variable_id].unit
                if observed_multiple is not None and discounted_multiple is not None:
                    projected_observed = base_value * observed_multiple
                    projected_discounted = base_value * discounted_multiple
        caveat = "示意测算，未含采用耦合等其他驱动；不改变模型结论，只提示被折扣掉的上行空间。"
        text = _render_discount_prompt(
            variable=variable,
            observed=observed,
            discounted=discounted,
            discounted_label=discounted_label,
            gap=gap,
            gap_relative=gap_relative,
            horizon_ticks=horizon_ticks,
            observed_multiple=observed_multiple,
            discounted_multiple=discounted_multiple,
            multiple_ratio=multiple_ratio,
            base_variable_id=base_variable_id,
            base_value=base_value,
            base_unit=base_unit,
            projected_observed=projected_observed,
            projected_discounted=projected_discounted,
            caveat=caveat,
        )
        prompts.append(
            KeyOpportunityPrompt(
                variable_id=variable.id,
                variable_description=variable.description,
                unit=variable.unit,
                observed_value=observed,
                observed_label=variable.observed_label,
                discounted_value=discounted,
                discounted_label=discounted_label,
                gap_pp=gap,
                gap_relative=gap_relative,
                horizon_ticks=horizon_ticks,
                observed_multiple=observed_multiple,
                discounted_multiple=discounted_multiple,
                multiple_ratio=multiple_ratio,
                base_variable_id=base_variable_id if base_value is not None else None,
                base_value=base_value,
                base_unit=base_unit,
                projected_observed=projected_observed,
                projected_discounted=projected_discounted,
                text=text,
                caveat=caveat,
            )
        )
    return prompts


def _render_discount_prompt(
    *,
    variable: VariableDefinition,
    observed: float,
    discounted: float,
    discounted_label: str,
    gap: float,
    gap_relative: float | None,
    horizon_ticks: int,
    observed_multiple: float | None,
    discounted_multiple: float | None,
    multiple_ratio: float | None,
    base_variable_id: str | None,
    base_value: float | None,
    base_unit: str,
    projected_observed: float | None,
    projected_discounted: float | None,
    caveat: str,
) -> str:
    """Render the exact discounted-growth prompt text (deterministic)."""

    if gap_relative is not None:
        gap_clause = f"差距 {gap * 100:.2f} 个百分点（观测值比取值高 {gap_relative:.1%}）。"
    else:
        gap_clause = (
            f"差距 {gap * 100:.2f} 个百分点（取值 {discounted:.2%}，观测值 {observed:.2%}）。"
        )
    parts = [
        (
            f"【重点机遇提示】变量 {variable.id} 的决策时点取值"
            f"（{discounted_label} {discounted:.2%}）大幅低于观测到的历史增速："
            f"{variable.observed_label}。"
        ),
        gap_clause,
        "折扣本身是允许的判断，但请注意其含义：",
    ]
    if (
        observed_multiple is not None
        and discounted_multiple is not None
        and multiple_ratio is not None
    ):
        parts.append(
            f"若 {observed:.2%} 的高增速持续 {horizon_ticks} 年，仅按该增长率复利，"
            f"累计为 {observed_multiple:.2f}×；而按折扣增速 {discounted:.2%} 仅为 "
            f"{discounted_multiple:.2f}×，两者相差 {multiple_ratio:.2f}×。"
        )
    if (
        base_variable_id is not None
        and base_value is not None
        and projected_observed is not None
        and projected_discounted is not None
    ):
        parts.append(
            f"以 {base_variable_id} 起始值 {base_value:.2f}（{base_unit}）计，"
            f"分别为 {projected_observed:.2f} 与 {projected_discounted:.2f}（{base_unit}）。"
        )
    parts.append(caveat)
    return "".join(parts)


def check_t1(
    variables: list[VariableDefinition],
    horizon_ticks: int,
    *,
    defensible_ceiling: float = T1_DEFENSIBLE_CEILING,
    boundary_class: str | None = None,
    boundary_basis: str | None = None,
) -> list[BreakoutPrompt]:
    """T1: a growth input assumption above the sustained-growth trigger.

    Fires once per ``*_growth`` variable whose CENTRAL value exceeds
    :data:`T1_GROWTH_THRESHOLD` (25%/yr). The central value is the
    sustained assumption; the optimistic distribution max does NOT
    trigger. ``disruptor_rate`` and other non-``_growth`` per-year
    variables are not growth assumptions and are ignored. Details keys:
    ``variable_id``, ``central_value``, ``threshold``,
    ``defensible_ceiling``, ``horizon_ticks``, ``boundary_class``.
    The §6 boundary verdict defaults to ``unclassified`` (the trigger
    inputs alone cannot decide it); pass ``boundary_class`` +
    ``boundary_basis`` together to record an analyst verdict.
    """

    prompts: list[BreakoutPrompt] = []
    for variable in variables:
        if not variable.id.endswith("_growth"):
            continue
        central = central_value(variable)
        if central is None:
            continue
        value, central_label = central
        if value <= T1_GROWTH_THRESHOLD:
            continue
        trigger_numbers = (
            f"{variable.id} 的持续增速（{central_label} {value:.2%}）"
            f"超过触发阈值 {T1_GROWTH_THRESHOLD:.0%}/年"
            f"（可辩护上限约 {defensible_ceiling:.0%}/年）"
        )
        stretched = (
            f"持续增速 {value:.2%} 高于可辩护上限约 {defensible_ceiling:.0%}/年，"
            f"需要该增速持续 {horizon_ticks} 年不变。"
        )
        hypothesis = (
            "该高增速可能并非基础增速，而是某条未建模的驱动链"
            "（如需求量传导）在起作用——增速假设可能在替缺失的链背书。"
        )
        action = "，或".join(SUGGESTED_ACTIONS) + "。"
        resolved_class, resolved_basis = _resolve_boundary(
            boundary_class, boundary_basis, T1_DEFAULT_BOUNDARY_BASIS
        )
        text = (
            f"【爆发提示 T1】{trigger_numbers}。"
            f"被拉伸的假设：{stretched}"
            f"未被捕捉的上行空间假说：{hypothesis}"
            f"建议动作：{action}"
            f"{_boundary_sentence(resolved_class, resolved_basis)}"
        )
        prompts.append(
            BreakoutPrompt(
                trigger_id="T1",
                title="爆发提示 T1：增长假设超过可辩护上限",
                trigger_numbers=trigger_numbers,
                stretched_assumption=stretched,
                uncaptured_upside_hypothesis=hypothesis,
                suggested_action=action,
                text=text,
                boundary_class=resolved_class,
                boundary_basis=resolved_basis,
                details={
                    "variable_id": variable.id,
                    "central_value": value,
                    "threshold": T1_GROWTH_THRESHOLD,
                    "defensible_ceiling": defensible_ceiling,
                    "horizon_ticks": horizon_ticks,
                    "boundary_class": resolved_class,
                },
            )
        )
    return prompts


def check_t2(
    *,
    actual_first_year_growth: float,
    modeled_first_year_growth: float,
    case_label: str = "",
    hypothesis: str | None = None,
    boundary_class: str | None = None,
    boundary_basis: str | None = None,
) -> BreakoutPrompt | None:
    """T2: actual first-year growth beat the model's by > 15pp.

    Monitoring / review time -- the caller supplies the post-decision
    actual and the model's first-year implied growth (e.g. the realized
    arm's replay tick-0 to tick-1 growth). Returns None when the gap is at
    or below :data:`T2_GAP_THRESHOLD_PP`. Details keys:
    ``actual_first_year_growth``, ``modeled_first_year_growth``,
    ``gap_pp``, ``threshold_pp``, ``boundary_class``. The §6 boundary
    verdict defaults to ``unclassified``; pass ``boundary_class`` +
    ``boundary_basis`` together to record an analyst verdict.
    """

    gap = actual_first_year_growth - modeled_first_year_growth
    if gap <= T2_GAP_THRESHOLD_PP:
        return None
    label = f"{case_label}：" if case_label else ""
    trigger_numbers = (
        f"{label}实际首年增速 {actual_first_year_growth:.2%} 超过模型首年隐含增速 "
        f"{modeled_first_year_growth:.2%} 共 {gap * 100:.1f} 个百分点"
        f"（触发阈值 {T2_GAP_THRESHOLD_PP * 100:.0f} 个百分点）"
    )
    stretched = (
        f"模型首年隐含增速 {modeled_first_year_growth:.2%} 已被实际超越；"
        "模型 uplift 后置，实际增长前置。"
    )
    if hypothesis is None:
        hypothesis = (
            "实际增速高于模型首年隐含增速，说明存在模型未捕捉的前置增长驱动"
            "（如需求量超预期、订单簿前置）。"
        )
    action = "立即复核驱动完整性：加一条驱动链，或加开一个繁荣情景臂；不要只放宽增长变量的分布。"
    resolved_class, resolved_basis = _resolve_boundary(
        boundary_class, boundary_basis, T2_DEFAULT_BOUNDARY_BASIS
    )
    return BreakoutPrompt(
        trigger_id="T2",
        title="爆发提示 T2：实际首年增速突破模型上限",
        trigger_numbers=trigger_numbers,
        stretched_assumption=stretched,
        uncaptured_upside_hypothesis=hypothesis,
        suggested_action=action,
        text=(
            f"【爆发提示 T2】{trigger_numbers}。"
            f"被拉伸的假设：{stretched}"
            f"未被捕捉的上行空间假说：{hypothesis}"
            f"建议动作：{action}"
            f"{_boundary_sentence(resolved_class, resolved_basis)}"
        ),
        boundary_class=resolved_class,
        boundary_basis=resolved_basis,
        details={
            "actual_first_year_growth": actual_first_year_growth,
            "modeled_first_year_growth": modeled_first_year_growth,
            "gap_pp": gap,
            "threshold_pp": T2_GAP_THRESHOLD_PP,
            "boundary_class": resolved_class,
        },
    )


def check_t3(
    *,
    variable_id: str,
    fitted_value: float,
    distribution_max: float,
    target_label: str = "",
    hypothesis: str | None = None,
    boundary_class: str | None = None,
    boundary_basis: str | None = None,
) -> BreakoutPrompt | None:
    """T3: a diagnostic fitted value exceeds its distribution max by > 2x.

    Backtest-diagnosis time -- the caller supplies the post-hoc fitted
    value (labeled as such; never a decision-time parameter) and the
    variable's distribution max. Returns None when the stretch is at or
    below :data:`T3_STRETCH_MULTIPLE`. Details keys: ``variable_id``,
    ``fitted_value``, ``distribution_max``, ``stretch_ratio``,
    ``threshold_multiple``, ``boundary_class``. The §6 boundary verdict
    defaults to ``unclassified``; pass ``boundary_class`` +
    ``boundary_basis`` together to record an analyst verdict.
    """

    if distribution_max == 0:
        return None
    ratio = fitted_value / distribution_max
    if ratio <= T3_STRETCH_MULTIPLE:
        return None
    label = f"（拟合 {target_label}）" if target_label else ""
    trigger_numbers = (
        f"诊断拟合值 {variable_id} {_fmt_num(fitted_value)} 超出分布 max "
        f"{_fmt_num(distribution_max)} 的 {ratio:.2f} 倍"
        f"（触发阈值 {T3_STRETCH_MULTIPLE:.0f} 倍）{label}"
    )
    stretched = f"{variable_id} 需为合理值的 {ratio:.2f} 倍才能拟合 {target_label or '目标'}。"
    if hypothesis is None:
        hypothesis = (
            "该变量的传导强度或其驱动的需求量路径本身可能高于规划——"
            "通道在模型内但分布过窄，或量级 surprise 超出预测上限。"
        )
    action = (
        "将该案例标注为“预测上限受限”，或放宽分布并注明依据；不要把拟合值当作决策时点参数使用。"
    )
    resolved_class, resolved_basis = _resolve_boundary(
        boundary_class, boundary_basis, T3_DEFAULT_BOUNDARY_BASIS
    )
    return BreakoutPrompt(
        trigger_id="T3",
        title="爆发提示 T3：诊断拟合值超出分布上限",
        trigger_numbers=trigger_numbers,
        stretched_assumption=stretched,
        uncaptured_upside_hypothesis=hypothesis,
        suggested_action=action,
        text=(
            f"【爆发提示 T3】{trigger_numbers}。"
            f"被拉伸的假设：{stretched}"
            f"未被捕捉的上行空间假说：{hypothesis}"
            f"建议动作：{action}"
            f"{_boundary_sentence(resolved_class, resolved_basis)}"
        ),
        boundary_class=resolved_class,
        boundary_basis=resolved_basis,
        details={
            "variable_id": variable_id,
            "fitted_value": fitted_value,
            "distribution_max": distribution_max,
            "stretch_ratio": ratio,
            "threshold_multiple": T3_STRETCH_MULTIPLE,
            "boundary_class": resolved_class,
        },
    )


def check_t4(
    *,
    period_label: str,
    orders_growth: float | None,
    orders_to_revenue: float | None,
    orders_label: str = "",
    boundary_class: str | None = None,
    boundary_basis: str | None = None,
) -> BreakoutPrompt | None:
    """T4: an order-book surge (growth > 50%/yr, or > 1.2x revenue).

    Fires when annualized new-order growth exceeds
    :data:`T4_ORDER_GROWTH_THRESHOLD` (50%/yr), OR annualized orders
    exceed :data:`T4_ORDER_REVENUE_RATIO` (1.2x) of current-year revenue
    while growing (order growth > 0). When order growth is unknown
    (None), the ratio clause cannot fire -- "growing" is unverified.
    Returns None when neither clause fires. Details keys:
    ``orders_growth``, ``orders_to_revenue``, ``clauses`` (which of
    ``"growth"`` / ``"ratio"`` fired), ``boundary_class``. The §6
    boundary verdict defaults to ``unclassified``; pass
    ``boundary_class`` + ``boundary_basis`` together to record an
    analyst verdict.
    """

    clauses: list[str] = []
    if orders_growth is not None and orders_growth > T4_ORDER_GROWTH_THRESHOLD:
        clauses.append("growth")
    if (
        orders_to_revenue is not None
        and orders_to_revenue > T4_ORDER_REVENUE_RATIO
        and orders_growth is not None
        and orders_growth > 0
    ):
        clauses.append("ratio")
    if not clauses:
        return None
    clause_texts: list[str] = []
    if "growth" in clauses and orders_growth is not None:
        clause_texts.append(
            f"年化新获订单同比 {orders_growth:.1%}（触发阈值 {T4_ORDER_GROWTH_THRESHOLD:.0%}）"
        )
    if "ratio" in clauses and orders_to_revenue is not None:
        clause_texts.append(
            f"年化新获订单为当年收入的 {orders_to_revenue:.2f}×"
            f"（触发阈值 {T4_ORDER_REVENUE_RATIO:.1f}×）且在增长"
        )
    orders_clause = f"{orders_label}，" if orders_label else ""
    trigger_numbers = f"{period_label}{orders_clause}" + "；".join(clause_texts)
    stretched = "模型内无订单簿状态变量，订单涌入无法前置收入。"
    hypothesis = (
        "订单簿先行于收入：新获订单涌入会在随后年份转化为收入，收入增速将前置于模型 uplift。"
    )
    action = "复核驱动完整性：引入订单簿存量机制，或加开一个繁荣情景臂。"
    resolved_class, resolved_basis = _resolve_boundary(
        boundary_class, boundary_basis, T4_DEFAULT_BOUNDARY_BASIS
    )
    return BreakoutPrompt(
        trigger_id="T4",
        title="爆发提示 T4：订单簿激增",
        trigger_numbers=trigger_numbers,
        stretched_assumption=stretched,
        uncaptured_upside_hypothesis=hypothesis,
        suggested_action=action,
        text=(
            f"【爆发提示 T4】{trigger_numbers}。"
            f"被拉伸的假设：{stretched}"
            f"未被捕捉的上行空间假说：{hypothesis}"
            f"建议动作：{action}"
            f"{_boundary_sentence(resolved_class, resolved_basis)}"
        ),
        boundary_class=resolved_class,
        boundary_basis=resolved_basis,
        details={
            "orders_growth": orders_growth,
            "orders_to_revenue": orders_to_revenue,
            "clauses": clauses,
            "boundary_class": resolved_class,
        },
    )


def detect_creation_prompts(
    variables: list[VariableDefinition],
    horizon_ticks: int,
) -> tuple[list[KeyOpportunityPrompt], list[BreakoutPrompt]]:
    """The creation-time prompt subset: discount prompts + T1.

    T2-T4 need post-decision actuals or diagnostic fitted values, so
    they are review-time checks (:func:`check_t2`, :func:`check_t3`,
    :func:`check_t4`) and are NOT computed at run creation.
    """

    return detect_discount_prompts(variables, horizon_ticks), check_t1(variables, horizon_ticks)


class FittedStretch(BaseModel):
    """One diagnostic fitted value for a T3 review check."""

    model_config = ConfigDict(extra="forbid")

    variable_id: str
    fitted_value: float
    distribution_max: float
    target_label: str = ""
    hypothesis: str | None = None
    boundary_class: str | None = None
    boundary_basis: str | None = None


def review_breakout_prompts(
    *,
    period_label: str = "",
    actual_first_year_growth: float | None = None,
    modeled_first_year_growth: float | None = None,
    fitted: list[FittedStretch] | None = None,
    orders_growth: float | None = None,
    orders_to_revenue: float | None = None,
    orders_label: str = "",
) -> list[BreakoutPrompt]:
    """The review-time prompt subset: T2 + T3 + T4 (Step 4, 2026-11-24).

    The creation-time subset (:func:`detect_creation_prompts`) covers
    discount prompts + T1 only — T2 needs post-decision actuals, T3
    needs diagnostic fitted values, T4 needs order data, so none of
    them can run at run creation. This composer is their product
    surface: monitoring review (T2/T4, once actuals arrive) and
    backtest diagnosis (T3, once fitted values exist) call it instead
    of reaching for the individual checks. Every input is optional;
    a check with missing inputs stays silent. Returned in trigger
    order: T2, then T3s in input order, then T4.
    """

    prompts: list[BreakoutPrompt] = []
    if actual_first_year_growth is not None and modeled_first_year_growth is not None:
        t2 = check_t2(
            actual_first_year_growth=actual_first_year_growth,
            modeled_first_year_growth=modeled_first_year_growth,
            case_label=period_label,
        )
        if t2 is not None:
            prompts.append(t2)
    for stretch in fitted or []:
        t3 = check_t3(
            variable_id=stretch.variable_id,
            fitted_value=stretch.fitted_value,
            distribution_max=stretch.distribution_max,
            target_label=stretch.target_label,
            hypothesis=stretch.hypothesis,
            boundary_class=stretch.boundary_class,
            boundary_basis=stretch.boundary_basis,
        )
        if t3 is not None:
            prompts.append(t3)
    if orders_growth is not None or orders_to_revenue is not None:
        t4 = check_t4(
            period_label=period_label,
            orders_growth=orders_growth,
            orders_to_revenue=orders_to_revenue,
            orders_label=orders_label,
        )
        if t4 is not None:
            prompts.append(t4)
    return prompts
