"""Tests for Phase 4 Track 9: key-opportunity + breakout (T1-T4) prompts.

REDIRECTION (parent task, 2026-11-19): the acceleration / explosion
factor is NOT built as a formula term or growth parameter. The desay-2020
diagnostic (``diagnostic-2020/DIAGNOSTIC-2020.md`` §5.1b, §5.5) finds it
NON-IDENTIFIABLE as a growth parameter -- no causal referent, almost
perfectly collinear with ``revenue_growth``, no decision-time evidence
to calibrate; as a time-varying pulse it would just be another time
curve (already excluded by Ho's ruling). It is built as the T1-T4
REPORT-TIME PROMPT MECHANISM instead: report-time checks at direction
review / backtest diagnosis / monitoring review that produce prompt text
and suggested actions and CHANGE NO NUMBERS. desay-2020 stays FAIL;
nothing is re-scored.

Two mechanisms, both pure and deterministic:

1. Discounted-growth prompt ("重点机遇提示", Ho's item (e)): a case
   variable whose modeled central value deliberately discounts an
   observed historical rate, annotated via ``observed_value`` /
   ``observed_label`` on the variable. The prompt surfaces the observed
   value, the discounted value, the gap, and the conditional (compounding
   multiples over the horizon, plus projected levels when a ``<X>`` level
   variable pairs with ``<X>_growth``).
2. Breakout prompts T1-T4 ("爆发提示", Ho's item (d), diagnostic §5.5):
   T1 growth assumption > 25%/yr; T2 actual first-year growth beats the
   modeled first-year implied growth by > 15pp; T3 a diagnostic fitted
   value exceeds its distribution max by > 2x; T4 annualized new-order
   growth > 50%/yr, or orders > 1.2x revenue and growing. Each prompt
   carries the diagnostic's four structured fields: (i) trigger +
   numbers; (ii) stretched assumption; (iii) named uncaptured-upside
   hypothesis; (iv) suggested action.

Honest boundary: the mechanism fixes the SPEED OF DISCOVERY, not
prediction accuracy -- T1/T4 do not trigger at 2020-12-31 for
desay-2020; T2/T4 trigger in 2021 once actuals arrive. It cannot let a
2020 decision-maker foresee the 2021 explosion.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from planagent.config import reset_settings_cache
from planagent.db import reset_database_cache
from planagent.main import create_app
from planagent.services.variables.models import (
    VariableDefinition,
    VariableDistribution,
)
from planagent.services.variables.opportunities import (
    check_t1,
    check_t2,
    check_t3,
    check_t4,
    detect_discount_prompts,
)

# ---------------------------------------------------------------------------
# Helpers: the two Desay growth variables, as annotated in the cases.
# ---------------------------------------------------------------------------


def _var(
    var_id: str,
    distribution: dict,
    unit: str = "per-year",
    observed: float | None = None,
    observed_label: str = "",
    description: str = "",
) -> VariableDefinition:
    return VariableDefinition(
        id=var_id,
        unit=unit,
        distribution=VariableDistribution(**distribution),
        evidence_ref="estimate: test",
        description=description,
        observed_value=observed,
        observed_label=observed_label,
    )


def _triangular(min_v: float, mode: float, max_v: float) -> dict:
    return {"type": "triangular", "min": min_v, "mode": mode, "max": max_v}


def _desay_2020_growth_vars() -> list[VariableDefinition]:
    """desay-2020 revenue + revenue_growth, as annotated for the prompt."""

    return [
        _var("revenue", _triangular(6200, 6799.06, 7400), unit="RMB m"),
        _var(
            "revenue_growth",
            _triangular(0.05, 0.15, 0.30),
            observed=0.2739,
            observed_label="2020年收入同比 +27.39%（恢复年）",
            description="无采用时的年均收入增长率",
        ),
        _var("disruptor_rate", _triangular(0.8, 1.0, 1.2)),
        _var("base_growth", _triangular(0.0, 0.03, 0.06)),
        _var("profit_growth", _triangular(0.0, 0.12, 0.25)),
    ]


def _desay_2015_growth_vars() -> list[VariableDefinition]:
    """desay-2015 revenue + revenue_growth, as annotated for the prompt."""

    return [
        _var("revenue", _triangular(3200, 3668.25, 4100), unit="RMB m"),
        _var(
            "revenue_growth",
            _triangular(0.0, 0.10, 0.25),
            observed=0.435,
            observed_label="2013–2015年收入复合增速约 +43.5%（低基数）",
            description="无采用时的年均收入增长率",
        ),
    ]


# ---------------------------------------------------------------------------
# 1. Discounted-growth prompt: fires on both Desay cases (golden text).
# ---------------------------------------------------------------------------

DESAY_2020_DISCOUNT_TEXT = (
    "【重点机遇提示】变量 revenue_growth 的决策时点取值（众数 15.00%）"
    "大幅低于观测到的历史增速：2020年收入同比 +27.39%（恢复年）。"
    "差距 12.39 个百分点（观测值比取值高 82.6%）。"
    "折扣本身是允许的判断，但请注意其含义："
    "若 27.39% 的高增速持续 5 年，仅按该增长率复利，累计为 3.35×；"
    "而按折扣增速 15.00% 仅为 2.01×，两者相差 1.67×。"
    "以 revenue 起始值 6799.06（RMB m）计，分别为 22810.01 与 13675.34（RMB m）。"
    "示意测算，未含采用耦合等其他驱动；不改变模型结论，只提示被折扣掉的上行空间。"
)

DESAY_2015_DISCOUNT_TEXT = (
    "【重点机遇提示】变量 revenue_growth 的决策时点取值（众数 10.00%）"
    "大幅低于观测到的历史增速：2013–2015年收入复合增速约 +43.5%（低基数）。"
    "差距 33.50 个百分点（观测值比取值高 335.0%）。"
    "折扣本身是允许的判断，但请注意其含义："
    "若 43.50% 的高增速持续 5 年，仅按该增长率复利，累计为 6.08×；"
    "而按折扣增速 10.00% 仅为 1.61×，两者相差 3.78×。"
    "以 revenue 起始值 3668.25（RMB m）计，分别为 22321.25 与 5907.75（RMB m）。"
    "示意测算，未含采用耦合等其他驱动；不改变模型结论，只提示被折扣掉的上行空间。"
)


def test_discount_prompt_fires_desay_2020() -> None:
    prompts = detect_discount_prompts(_desay_2020_growth_vars(), 5)
    assert len(prompts) == 1
    prompt = prompts[0]
    assert prompt.text == DESAY_2020_DISCOUNT_TEXT
    assert prompt.variable_id == "revenue_growth"
    assert prompt.observed_value == pytest.approx(0.2739)
    assert prompt.discounted_value == pytest.approx(0.15)
    assert prompt.discounted_label == "众数"
    assert prompt.gap_pp == pytest.approx(0.1239)
    assert prompt.gap_relative == pytest.approx(0.826, abs=1e-3)
    assert prompt.horizon_ticks == 5
    assert prompt.observed_multiple == pytest.approx(3.3549, abs=1e-4)
    assert prompt.discounted_multiple == pytest.approx(2.0114, abs=1e-4)
    assert prompt.multiple_ratio == pytest.approx(1.6680, abs=1e-4)
    assert prompt.base_variable_id == "revenue"
    assert prompt.base_value == pytest.approx(6799.06)
    assert prompt.projected_observed == pytest.approx(22810.01, abs=0.01)
    assert prompt.projected_discounted == pytest.approx(13675.34, abs=0.01)


def test_discount_prompt_fires_desay_2015() -> None:
    prompts = detect_discount_prompts(_desay_2015_growth_vars(), 5)
    assert len(prompts) == 1
    prompt = prompts[0]
    assert prompt.text == DESAY_2015_DISCOUNT_TEXT
    assert prompt.variable_id == "revenue_growth"
    assert prompt.observed_value == pytest.approx(0.435)
    assert prompt.discounted_value == pytest.approx(0.10)
    assert prompt.gap_pp == pytest.approx(0.335)
    assert prompt.gap_relative == pytest.approx(3.35)
    assert prompt.observed_multiple == pytest.approx(6.0850, abs=1e-4)
    assert prompt.discounted_multiple == pytest.approx(1.6105, abs=1e-4)
    assert prompt.multiple_ratio == pytest.approx(3.7783, abs=1e-4)
    assert prompt.base_variable_id == "revenue"
    assert prompt.projected_observed == pytest.approx(22321.25, abs=0.01)
    assert prompt.projected_discounted == pytest.approx(5907.75, abs=0.01)


def test_discount_prompt_silent_without_annotation() -> None:
    variables = [_var("revenue_growth", _triangular(0.05, 0.15, 0.30))]
    assert detect_discount_prompts(variables, 5) == []


def test_discount_prompt_silent_when_gap_below_threshold() -> None:
    # Observed 18% vs mode 15%: gap 3pp < 5pp threshold -- no prompt.
    variables = [
        _var(
            "revenue_growth",
            _triangular(0.05, 0.15, 0.30),
            observed=0.18,
            observed_label="2020年收入同比 +18%",
        )
    ]
    assert detect_discount_prompts(variables, 5) == []


def test_discount_prompt_silent_when_observed_below_mode() -> None:
    # The prompt is one-directional: it fires on a DISCOUNT (observed
    # above modeled), not on optimism (modeled above observed).
    variables = [
        _var(
            "revenue_growth",
            _triangular(0.05, 0.15, 0.30),
            observed=0.05,
            observed_label="2020年收入同比 +5%",
        )
    ]
    assert detect_discount_prompts(variables, 5) == []


def test_discount_prompt_without_level_pair_stays_in_multiples() -> None:
    # base_growth has no "base" level variable: no projected levels,
    # but the multiples conditional is still there.
    variables = [
        _var(
            "base_growth",
            _triangular(0.0, 0.03, 0.06),
            observed=0.20,
            observed_label="历史份额增速 +20%",
        )
    ]
    prompts = detect_discount_prompts(variables, 5)
    assert len(prompts) == 1
    assert prompts[0].base_variable_id is None
    assert prompts[0].projected_observed is None
    assert prompts[0].observed_multiple == pytest.approx(1.20**5)
    assert "以 " not in prompts[0].text.split("两者相差")[1].split("示意测算")[0]
    assert "累计为 2.49×" in prompts[0].text


def test_discount_prompt_zero_central_value_renders() -> None:
    # Mode 0.0 with observed 10%: fires, gap_relative is None, and the
    # text falls back to the (取值 / 观测值) clause instead of a ratio.
    variables = [
        _var(
            "revenue_growth",
            _triangular(0.0, 0.0, 0.10),
            observed=0.10,
            observed_label="历史增速 +10%",
        )
    ]
    prompts = detect_discount_prompts(variables, 5)
    assert len(prompts) == 1
    assert prompts[0].gap_relative is None
    assert "（取值 0.00%，观测值 10.00%）" in prompts[0].text


# ---------------------------------------------------------------------------
# 2. T1: sustained-growth assumption above 25%/yr.
# ---------------------------------------------------------------------------

T1_GOLDEN_TEXT = (
    "【爆发提示 T1】revenue_growth 的持续增速（众数 30.00%）"
    "超过触发阈值 25%/年（可辩护上限约 20%/年）。"
    "被拉伸的假设：持续增速 30.00% 高于可辩护上限约 20%/年，"
    "需要该增速持续 5 年不变。"
    "未被捕捉的上行空间假说：该高增速可能并非基础增速，"
    "而是某条未建模的驱动链（如需求量传导）在起作用——"
    "增速假设可能在替缺失的链背书。"
    "建议动作：加一条驱动链，或放宽分布并注明依据，"
    "或加开一个繁荣情景臂，或将该案例标注为“预测上限受限”。"
    "边界判定：暂未分类——仅凭输入假设高于上限，无法判定高增速来自缺失的链"
    "还是不可预见的量级——需复核驱动完整性后定性（§6）。"
)


def test_t1_silent_for_both_desay_cases() -> None:
    # desay-2020: B implied ~18%/yr; anchor growth modes 0.15 / 0.12 /
    # 0.03 -- all below 25%. desay-2015: modes 0.10 and below.
    assert check_t1(_desay_2020_growth_vars(), 5) == []
    assert check_t1(_desay_2015_growth_vars(), 5) == []
    # The B arm's pinned growth levers are likewise silent.
    b_arm = [
        _var("base_growth", {"type": "fixed", "value": 0.03}),
        _var("revenue_growth", {"type": "fixed", "value": 0.15}),
        _var("profit_growth", {"type": "fixed", "value": 0.12}),
    ]
    assert check_t1(b_arm, 5) == []


def test_t1_ignores_disruptor_rate_and_uses_central_not_max() -> None:
    # disruptor_rate mode 1.0 is a logistic steepness, not a sustained
    # growth rate -- it must never trigger T1.
    variables = [_var("disruptor_rate", _triangular(0.8, 1.0, 1.2))]
    assert check_t1(variables, 5) == []
    # A growth variable whose MAX is 0.30 but whose MODE is 0.15 does
    # not trigger either: T1 tests the sustained (central) assumption,
    # not the optimistic tail.
    variables = [_var("revenue_growth", _triangular(0.10, 0.15, 0.30))]
    assert check_t1(variables, 5) == []


def test_t1_fires_with_exact_text_and_four_fields() -> None:
    variables = [_var("revenue_growth", _triangular(0.20, 0.30, 0.40))]
    prompts = check_t1(variables, 5)
    assert len(prompts) == 1
    prompt = prompts[0]
    assert prompt.text == T1_GOLDEN_TEXT
    assert prompt.trigger_id == "T1"
    assert prompt.trigger_numbers.startswith("revenue_growth 的持续增速")
    assert "持续增速 30.00%" in prompt.stretched_assumption
    assert "需求量传导" in prompt.uncaptured_upside_hypothesis
    assert "加一条驱动链" in prompt.suggested_action
    assert "预测上限受限" in prompt.suggested_action
    assert prompt.details["central_value"] == pytest.approx(0.30)
    assert prompt.details["threshold"] == pytest.approx(0.25)


def test_t1_boundary_exact_threshold_is_silent() -> None:
    # Strict ">": exactly 25% does not trigger; just above does.
    silent = [_var("revenue_growth", _triangular(0.20, 0.25, 0.30))]
    assert check_t1(silent, 5) == []
    fires = [_var("revenue_growth", _triangular(0.20, 0.2501, 0.30))]
    assert len(check_t1(fires, 5)) == 1


# ---------------------------------------------------------------------------
# 3. T2: actual first-year growth beats modeled by > 15pp.
# ---------------------------------------------------------------------------

T2_GOLDEN_TEXT = (
    "【爆发提示 T2】desay-2020 B 臂：实际首年增速 40.70% 超过模型首年隐含增速 "
    "18.80% 共 21.9 个百分点（触发阈值 15 个百分点）。"
    "被拉伸的假设：模型首年隐含增速 18.80% 已被实际超越；"
    "模型 uplift 后置，实际增长前置。"
    "未被捕捉的上行空间假说：NEV 销量路径高于规划"
    "（2021 年实际 352.1 万辆 vs 预测 180 万辆）且订单簿前置"
    "（年化新获订单 >120 亿）——模型内无 NEV 传导链、无订单簿状态变量。"
    "建议动作：立即复核驱动完整性：加一条驱动链，或加开一个繁荣情景臂；"
    "不要只放宽增长变量的分布。"
    "边界判定：应修的机制缺失——首年实际超越模型上限，"
    "揭示 NEV 传导链与订单簿机制缺失——两者均可由 2020 年公开证据论证或编码"
    "（§6：能编码进分布的属应有之物）。"
)


def test_t2_fires_desay_2021() -> None:
    prompt = check_t2(
        actual_first_year_growth=0.407,
        modeled_first_year_growth=0.188,
        case_label="desay-2020 B 臂",
        hypothesis="NEV 销量路径高于规划（2021 年实际 352.1 万辆 vs 预测 180 万辆）"
        "且订单簿前置（年化新获订单 >120 亿）——模型内无 NEV 传导链、无订单簿状态变量。",
        boundary_class="fixable_defect",
        boundary_basis="首年实际超越模型上限，揭示 NEV 传导链与订单簿机制缺失"
        "——两者均可由 2020 年公开证据论证或编码（§6：能编码进分布的属应有之物）。",
    )
    assert prompt is not None
    assert prompt.text == T2_GOLDEN_TEXT
    assert prompt.trigger_id == "T2"
    assert prompt.boundary_class == "fixable_defect"
    assert prompt.details["gap_pp"] == pytest.approx(0.219)
    assert "加一条驱动链" in prompt.suggested_action


def test_t2_silent_at_or_below_threshold() -> None:
    # Gap exactly 15pp: strict ">" -- silent. Gap 10pp: silent.
    assert check_t2(actual_first_year_growth=0.30, modeled_first_year_growth=0.15) is None
    assert check_t2(actual_first_year_growth=0.25, modeled_first_year_growth=0.15) is None
    assert check_t2(actual_first_year_growth=0.31, modeled_first_year_growth=0.15) is not None


# ---------------------------------------------------------------------------
# 4. T3: diagnostic fitted value exceeds distribution max by > 2x.
# ---------------------------------------------------------------------------

T3_NEV_GOLDEN_TEXT = (
    "【爆发提示 T3】诊断拟合值 nev_coupling 2.08 超出分布 max 0.4 的 5.20 倍"
    "（触发阈值 2 倍）（拟合 year-5 收入 32557.18）。"
    "被拉伸的假设：nev_coupling 需为合理值的 5.20 倍才能拟合 year-5 收入 32557.18。"
    "未被捕捉的上行空间假说：该变量的传导强度或其驱动的需求量路径本身可能高于规划——"
    "通道在模型内但分布过窄，或量级 surprise 超出预测上限。"
    "建议动作：将该案例标注为“预测上限受限”，或放宽分布并注明依据；"
    "不要把拟合值当作决策时点参数使用。"
    "边界判定：应修的机制缺失——NEV 传导链可由 2020 年公开证据编码"
    "（国务院 2025 年 20% 目标、中汽协销量预测），链缺失是应修的缺陷（§6）。"
)

T3_RG_GOLDEN_TEXT = (
    "【爆发提示 T3】诊断拟合值 revenue_growth 0.734 超出分布 max 0.3 的 2.45 倍"
    "（触发阈值 2 倍）（拟合 year-3 收入 21908）。"
    "被拉伸的假设：revenue_growth 需为合理值的 2.45 倍才能拟合 year-3 收入 21908。"
    "未被捕捉的上行空间假说：该变量的传导强度或其驱动的需求量路径本身可能高于规划——"
    "通道在模型内但分布过窄，或量级 surprise 超出预测上限。"
    "建议动作：将该案例标注为“预测上限受限”，或放宽分布并注明依据；"
    "不要把拟合值当作决策时点参数使用。"
    "边界判定：可接受的预测上限——即使补上 NEV 链（可辩护值），"
    "year-5 也只到 18212，距实际 32557 仍差 14345——"
    "持续增速 73.4% 在 2020 年无任何预测支持，属量级 surprise，超出预测上限（§6）。"
)


def test_t3_fires_nev_chain_fit() -> None:
    prompt = check_t3(
        variable_id="nev_coupling",
        fitted_value=2.08,
        distribution_max=0.40,
        target_label="year-5 收入 32557.18",
        boundary_class="fixable_defect",
        boundary_basis="NEV 传导链可由 2020 年公开证据编码"
        "（国务院 2025 年 20% 目标、中汽协销量预测），链缺失是应修的缺陷（§6）。",
    )
    assert prompt is not None
    assert prompt.text == T3_NEV_GOLDEN_TEXT
    assert prompt.boundary_class == "fixable_defect"
    assert prompt.details["stretch_ratio"] == pytest.approx(5.2)


def test_t3_fires_revenue_growth_fit() -> None:
    prompt = check_t3(
        variable_id="revenue_growth",
        fitted_value=0.734,
        distribution_max=0.30,
        target_label="year-3 收入 21908",
        boundary_class="acceptable_limit",
        boundary_basis="即使补上 NEV 链（可辩护值），year-5 也只到 18212"
        "，距实际 32557 仍差 14345——持续增速 73.4% 在 2020 年无任何预测支持"
        "，属量级 surprise，超出预测上限（§6）。",
    )
    assert prompt is not None
    assert prompt.text == T3_RG_GOLDEN_TEXT
    assert prompt.boundary_class == "acceptable_limit"
    assert prompt.details["stretch_ratio"] == pytest.approx(0.734 / 0.30)


def test_t3_silent_at_or_below_two_times() -> None:
    # 0.79 vs max 0.40 = 1.975x: silent. Exactly 2.0x: silent (strict >).
    assert (
        check_t3(
            variable_id="nev_coupling",
            fitted_value=0.79,
            distribution_max=0.40,
            target_label="year-5 收入 32557.18",
        )
        is None
    )
    assert (
        check_t3(
            variable_id="nev_coupling",
            fitted_value=0.80,
            distribution_max=0.40,
            target_label="year-5 收入 32557.18",
        )
        is None
    )
    assert (
        check_t3(
            variable_id="nev_coupling",
            fitted_value=0.81,
            distribution_max=0.40,
            target_label="year-5 收入 32557.18",
        )
        is not None
    )


# ---------------------------------------------------------------------------
# 5. T4: order-book surge.
# ---------------------------------------------------------------------------

T4_2021_GOLDEN_TEXT = (
    "【爆发提示 T4】2021 年年化新获订单 >120 亿，"
    "年化新获订单同比 71.4%（触发阈值 50%）；"
    "年化新获订单为当年收入的 1.25×（触发阈值 1.2×）且在增长。"
    "被拉伸的假设：模型内无订单簿状态变量，订单涌入无法前置收入。"
    "未被捕捉的上行空间假说：订单簿先行于收入：新获订单涌入会在随后年份转化为收入，"
    "收入增速将前置于模型 uplift。"
    "建议动作：复核驱动完整性：引入订单簿存量机制，或加开一个繁荣情景臂。"
    "边界判定：应修的机制缺失——订单簿先行于收入的机制在 2020 年即可论证，"
    "模型内无此状态变量是缺失（§6 边缘情形：机制可论证，量级不可标定）。"
)


def test_t4_silent_desay_2020() -> None:
    # 2020: orders 70亿 ≈ 1.03x revenue 67.99亿, growth unknown -- silent.
    assert (
        check_t4(
            period_label="2020 年",
            orders_growth=None,
            orders_to_revenue=70 / 67.99,
            orders_label="年化新获订单 70 亿",
        )
        is None
    )


def test_t4_fires_desay_2021_both_clauses() -> None:
    # 2021: orders >120亿, +71.4% YoY (> 50%), 1.25x revenue (> 1.2x).
    prompt = check_t4(
        period_label="2021 年",
        orders_growth=120 / 70 - 1,
        orders_to_revenue=120 / 95.69,
        orders_label="年化新获订单 >120 亿",
        boundary_class="fixable_defect",
        boundary_basis="订单簿先行于收入的机制在 2020 年即可论证"
        "，模型内无此状态变量是缺失（§6 边缘情形：机制可论证，量级不可标定）。",
    )
    assert prompt is not None
    assert prompt.text == T4_2021_GOLDEN_TEXT
    assert prompt.trigger_id == "T4"
    assert prompt.boundary_class == "fixable_defect"
    assert prompt.details["clauses"] == ["growth", "ratio"]


def test_t4_single_clauses_fire_independently() -> None:
    growth_only = check_t4(period_label="2021 年", orders_growth=0.60, orders_to_revenue=0.90)
    assert growth_only is not None
    assert growth_only.details["clauses"] == ["growth"]
    ratio_only = check_t4(period_label="2021 年", orders_growth=0.10, orders_to_revenue=1.30)
    assert ratio_only is not None
    assert ratio_only.details["clauses"] == ["ratio"]


def test_t4_ratio_clause_needs_growth() -> None:
    # Ratio above 1.2x but growth unknown (or zero): the "且在增长"
    # half is unverified, so the ratio clause cannot fire.
    assert check_t4(period_label="2021 年", orders_growth=None, orders_to_revenue=1.50) is None
    assert check_t4(period_label="2021 年", orders_growth=0.0, orders_to_revenue=1.50) is None


def test_t4_boundaries_are_strict() -> None:
    # Exactly 50% growth: silent. Exactly 1.2x ratio: silent.
    assert check_t4(period_label="2021 年", orders_growth=0.50, orders_to_revenue=1.10) is None
    assert check_t4(period_label="2021 年", orders_growth=0.10, orders_to_revenue=1.20) is None


# ---------------------------------------------------------------------------
# 6. API level: creation response carries the prompts; numbers unchanged.
# ---------------------------------------------------------------------------


def _setup_app(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(
        "PLANAGENT_DATABASE_URL", f"sqlite+aiosqlite:///{(tmp_path / 'breakout.db').as_posix()}"
    )
    monkeypatch.setenv("PLANAGENT_EVENT_BUS_BACKEND", "memory")
    monkeypatch.setenv("PLANAGENT_INLINE_INGEST_DEFAULT", "true")
    monkeypatch.setenv("PLANAGENT_INLINE_SIMULATION_DEFAULT", "true")
    for key in (
        "PLANAGENT_OPENAI_API_KEY",
        "PLANAGENT_OPENAI_BASE_URL",
        "PLANAGENT_OPENAI_PRIMARY_API_KEY",
        "PLANAGENT_OPENAI_PRIMARY_BASE_URL",
        "PLANAGENT_OPENAI_EXTRACTION_API_KEY",
        "PLANAGENT_OPENAI_EXTRACTION_BASE_URL",
        "PLANAGENT_OPENAI_REPORT_API_KEY",
        "PLANAGENT_OPENAI_REPORT_BASE_URL",
    ):
        monkeypatch.setenv(key, "")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    reset_settings_cache()
    reset_database_cache()


def _ref(name: str) -> dict[str, str]:
    return {"ref": name}


def _op(operator: str, left: object, right: object) -> dict[str, object]:
    return {"op": operator, "args": [left, right]}


def _growth_diffusion_drivers() -> list[dict]:
    """The desay growth-coupled diffusion drivers (run_desay.py verbatim).

    adoption = logistic(rate*(tick-midpoint), ceiling);
    share    = min(0.85, max(0, share*(1+base_growth + share_coupling*adoption)))
    revenue  = max(0, revenue*(1+revenue_growth + revenue_coupling*adoption))
    profit   = max(0, profit*(1+profit_growth + profit_coupling*adoption))
    """

    adoption = {
        "output": "disruptor_adoption",
        "expression": {
            "op": "logistic",
            "args": [
                _op(
                    "multiply",
                    _ref("disruptor_rate"),
                    _op("subtract", _ref("tick"), _ref("disruptor_midpoint")),
                ),
                _ref("disruptor_ceiling"),
            ],
        },
        "tick_driver": True,
    }

    def growth(field: str, growth: str, coupling: str, cap: bool) -> dict:
        inner = {
            "op": "multiply",
            "args": [
                _ref(field),
                {
                    "op": "add",
                    "args": [
                        1,
                        {
                            "op": "add",
                            "args": [
                                _ref(growth),
                                _op("multiply", _ref(coupling), _ref("disruptor_adoption")),
                            ],
                        },
                    ],
                },
            ],
        }
        floored = {"op": "max", "args": [0, inner]}
        expr = {"op": "min", "args": [floored, 0.85]} if cap else floored
        return {"output": field, "expression": expr, "tick_driver": True}

    return [
        adoption,
        growth("market_share", "base_growth", "share_coupling", cap=True),
        growth("revenue", "revenue_growth", "revenue_coupling", cap=False),
        growth("profit", "profit_growth", "profit_coupling", cap=False),
    ]


def _desay_2020_variable_set() -> dict:
    """The desay-2020 anchor variable set (exact distributions).

    Only ``revenue_growth`` carries the observed-value annotation; the
    other eleven variables are exactly as in REPORT.md (shortened
    evidence refs -- provenance text does not affect numerics).
    """

    def entry(var_id: str, dist: dict, **extra: object) -> dict:
        item: dict = {
            "id": var_id,
            "unit": "per-year",
            "distribution": dist,
            "evidence_ref": "estimate: test",
        }
        item.update(extra)
        return item

    return {
        "name": "desay-2020-case",
        "variables": [
            entry("market_share", _triangular(0.05, 0.066, 0.08), unit="share"),
            entry("base_growth", _triangular(0.0, 0.03, 0.06)),
            entry("disruptor_ceiling", _triangular(0.7, 0.85, 0.95), unit="share"),
            entry("disruptor_rate", _triangular(0.8, 1.0, 1.2)),
            entry("disruptor_midpoint", _triangular(2.0, 3.0, 4.0), unit="years"),
            entry("share_coupling", _triangular(0.15, 0.25, 0.35), unit="per-unit-adoption"),
            entry("revenue", _triangular(6200, 6799.06, 7400), unit="RMB m"),
            entry(
                "revenue_growth",
                _triangular(0.05, 0.15, 0.30),
                observed_value=0.2739,
                observed_label="2020年收入同比 +27.39%（恢复年）",
            ),
            entry("revenue_coupling", _triangular(0.15, 0.25, 0.35), unit="per-unit-adoption"),
            entry("profit", _triangular(450, 518.15, 600), unit="RMB m"),
            entry("profit_growth", _triangular(0.0, 0.12, 0.25)),
            entry("profit_coupling", _triangular(0.10, 0.15, 0.25), unit="per-unit-adoption"),
        ],
        "formulas": _growth_diffusion_drivers(),
    }


def test_api_desay_2020_anchor_carries_discount_prompt_and_numbers_unchanged(
    monkeypatch, tmp_path: Path
) -> None:
    """The anchor creation response surfaces the discount prompt, and the
    annotation changes no number: the anchor revenue ensemble P50 is
    still 22335.94 (REPORT.md), and T1 stays silent."""

    _setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        created = client.post(
            "/simulation/runs",
            json={
                "company_id": "backtest-desay-2020",
                "company_name": "Desay SV (2020 retrospective)",
                "market": "auto-electronics-china",
                "domain_id": "corporate",
                "actor_template": "ai_model_provider",
                "tick_count": 5,
                "seed": 7,
                "decision_time": "2020-12-31T00:00:00Z",
                "variable_set": _desay_2020_variable_set(),
            },
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["status"] == "COMPLETED"
        prompts = body["key_opportunities"]
        assert len(prompts) == 1
        assert prompts[0]["variable_id"] == "revenue_growth"
        assert prompts[0]["text"] == DESAY_2020_DISCOUNT_TEXT
        assert prompts[0]["gap_pp"] == pytest.approx(0.1239)
        assert prompts[0]["observed_multiple"] == pytest.approx(3.3549, abs=1e-4)
        # T1 silent at decision time (B implied ~18%/yr, modes <= 0.15).
        assert body["breakout_prompts"] == []
        # Numbers unchanged by the annotation: anchor revenue ensemble.
        # Track C (default ON): the anchor now carries the default
        # downside shock, so the ensemble P50 sits at 21202.79 instead
        # of the pre-Track-C 22335.94; the annotation itself still moves
        # nothing (the value is the default-ON anchor, pinned here).
        mc = client.post(
            f"/runs/{body['id']}/monte-carlo",
            json={
                "trials": 20,
                "seed": 42,
                "metric": "revenue",
                "loss_threshold": 6799.06,
            },
        )
        assert mc.status_code == 201, mc.text
        baseline = mc.json()["baseline"]
        assert baseline["p50"] == pytest.approx(21202.7867, abs=0.01)
        assert baseline["p_loss"] == 0.0


def test_api_t1_fires_for_high_growth_assumption(monkeypatch, tmp_path: Path) -> None:
    _setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        created = client.post(
            "/simulation/runs",
            json={
                "company_id": "t1-test-co",
                "company_name": "T1 Test Co",
                "market": "ai",
                "tick_count": 5,
                "seed": 7,
                "actor_template": "default",
                "variable_set": {
                    "name": "t1 case",
                    "variables": [
                        {
                            "id": "cash",
                            "unit": "k",
                            "distribution": {
                                "type": "triangular",
                                "min": 60,
                                "mode": 100,
                                "max": 140,
                            },
                            "evidence_ref": "estimate: test",
                        },
                        {
                            "id": "revenue_growth",
                            "unit": "per-year",
                            "distribution": {
                                "type": "triangular",
                                "min": 0.20,
                                "mode": 0.30,
                                "max": 0.40,
                            },
                            "evidence_ref": "estimate: test",
                        },
                    ],
                },
            },
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["key_opportunities"] == []
        prompts = body["breakout_prompts"]
        assert len(prompts) == 1
        assert prompts[0]["trigger_id"] == "T1"
        assert prompts[0]["text"] == T1_GOLDEN_TEXT


def test_api_acme_baseline_unchanged(monkeypatch, tmp_path: Path) -> None:
    """The Acme baseline guard: the exact docker-verify probe
    (tick_count 2, seed 7; monte-carlo trials 5, seed 42, metric cash,
    loss_threshold 90.0) must still give P50 99.8143, p_loss 0.4.
    Prompt wiring touches no simulation path."""

    _setup_app(monkeypatch, tmp_path)
    with TestClient(create_app()) as client:
        created = client.post(
            "/simulation/runs",
            json={
                "company_id": "docker-verify-co",
                "company_name": "Docker Verify Co",
                "market": "ai",
                "tick_count": 2,
                "seed": 7,
                "actor_template": "default",
                "variable_set": {
                    "name": "case",
                    "variables": [
                        {
                            "id": "cash",
                            "unit": "k",
                            "distribution": {
                                "type": "triangular",
                                "min": 60,
                                "mode": 100,
                                "max": 140,
                            },
                            "evidence_ref": "estimate: founder judgment",
                        },
                        {
                            "id": "pipeline",
                            "unit": "x",
                            "distribution": {"type": "normal", "mean": 1.0, "std": 0.1},
                            "evidence_ref": "estimate: founder judgment",
                        },
                        {
                            "id": "cac",
                            "unit": "yuan",
                            "distribution": {
                                "type": "triangular",
                                "min": 8000,
                                "mode": 12000,
                                "max": 20000,
                            },
                            "evidence_ref": "evidence:q3-report",
                        },
                    ],
                    "internal": {"team": "20 people"},
                },
            },
        )
        assert created.status_code == 201, created.text
        run_id = created.json()["id"]
        assert created.json()["key_opportunities"] == []
        assert created.json()["breakout_prompts"] == []
        mc = client.post(
            f"/runs/{run_id}/monte-carlo",
            json={"trials": 5, "seed": 42, "metric": "cash", "loss_threshold": 90.0},
        )
        assert mc.status_code == 201, mc.text
        baseline = mc.json()["baseline"]
        assert baseline["p50"] == 99.8143
        assert baseline["p_loss"] == 0.4


# ---------------------------------------------------------------------------
# 7. Boundary verdict (§6, Ho 15:02 item (c)).
# ---------------------------------------------------------------------------


def test_boundary_defaults_to_unclassified_for_all_triggers() -> None:
    """With no analyst verdict, every trigger stays unclassified and says
    why the evidence in the trigger inputs does not decide the §6
    question. The verdict is never invented to fill the field."""

    t1 = check_t1([_var("revenue_growth", _triangular(0.20, 0.30, 0.40))], 5)[0]
    assert t1.boundary_class == "unclassified"
    assert t1.boundary_basis.startswith("仅凭输入假设高于上限")
    assert t1.text.endswith(t1.boundary_basis)
    assert "边界判定：暂未分类" in t1.text

    t2 = check_t2(actual_first_year_growth=0.407, modeled_first_year_growth=0.188)
    assert t2 is not None
    assert t2.boundary_class == "unclassified"
    assert t2.boundary_basis.startswith("首年实际超越模型上限")

    t3 = check_t3(variable_id="nev_coupling", fitted_value=2.08, distribution_max=0.40)
    assert t3 is not None
    assert t3.boundary_class == "unclassified"
    assert t3.boundary_basis.startswith("拟合值超出分布上限")

    t4 = check_t4(period_label="2021 年", orders_growth=0.714, orders_to_revenue=1.25)
    assert t4 is not None
    assert t4.boundary_class == "unclassified"
    assert t4.boundary_basis.startswith("订单激增揭示模型内无订单簿状态变量")


def test_boundary_lone_class_or_basis_raises() -> None:
    """Class and basis must arrive together; a lone one is a caller
    error, not a silent default."""

    with pytest.raises(ValueError, match="must be given together"):
        check_t2(
            actual_first_year_growth=0.407,
            modeled_first_year_growth=0.188,
            boundary_class="fixable_defect",
        )
    with pytest.raises(ValueError, match="must be given together"):
        check_t2(
            actual_first_year_growth=0.407,
            modeled_first_year_growth=0.188,
            boundary_basis="some basis",
        )
    with pytest.raises(ValueError, match="must be given together"):
        check_t3(
            variable_id="nev_coupling",
            fitted_value=2.08,
            distribution_max=0.40,
            boundary_basis="some basis",
        )


def test_boundary_unknown_class_or_empty_basis_raises() -> None:
    with pytest.raises(ValueError, match="unknown boundary_class"):
        check_t3(
            variable_id="nev_coupling",
            fitted_value=2.08,
            distribution_max=0.40,
            boundary_class="not_a_class",
            boundary_basis="some basis",
        )
    with pytest.raises(ValueError, match="must be non-empty"):
        check_t4(
            period_label="2021 年",
            orders_growth=0.714,
            orders_to_revenue=1.25,
            boundary_class="fixable_defect",
            boundary_basis="   ",
        )


def test_boundary_desay_2020_demonstration() -> None:
    """Acceptance demonstration (Ho 15:02 item (c)): the two §6 verdicts
    for desay-2020, in prompt outputs.

    - NEV chain missing = fixable_defect: the chain is encodable from
      2020 public evidence (State Council 2025 20% target, CAAM sales
      forecast), so its absence is a defect.
    - The 18212 -> 32557 gap = acceptable_limit: even with the NEV chain
      at defensible values, year-5 only reaches 18212; the remaining
      14345 is a magnitude surprise no 2020 forecast supported.
    """

    chain_missing = check_t3(
        variable_id="nev_coupling",
        fitted_value=2.08,
        distribution_max=0.40,
        target_label="year-5 收入 32557.18",
        boundary_class="fixable_defect",
        boundary_basis="NEV 传导链可由 2020 年公开证据编码"
        "（国务院 2025 年 20% 目标、中汽协销量预测），链缺失是应修的缺陷（§6）。",
    )
    assert chain_missing is not None
    assert chain_missing.boundary_class == "fixable_defect"
    assert "NEV 传导链" in chain_missing.boundary_basis
    assert "应修的缺陷" in chain_missing.boundary_basis
    assert "边界判定：应修的机制缺失" in chain_missing.text

    magnitude_gap = check_t3(
        variable_id="revenue_growth",
        fitted_value=0.734,
        distribution_max=0.30,
        target_label="year-3 收入 21908",
        boundary_class="acceptable_limit",
        boundary_basis="即使补上 NEV 链（可辩护值），year-5 也只到 18212"
        "，距实际 32557 仍差 14345——持续增速 73.4% 在 2020 年无任何预测支持"
        "，属量级 surprise，超出预测上限（§6）。",
    )
    assert magnitude_gap is not None
    assert magnitude_gap.boundary_class == "acceptable_limit"
    assert "18212" in magnitude_gap.boundary_basis
    assert "32557" in magnitude_gap.boundary_basis
    assert "边界判定：可接受的预测上限" in magnitude_gap.text


# ---------------------------------------------------------------------------
# Review composer (Step 4, 2026-11-24): T2 + T3 + T4 in one call.
# ---------------------------------------------------------------------------


def test_review_composer_empty_inputs_stay_silent() -> None:
    from planagent.services.variables.opportunities import review_breakout_prompts

    assert review_breakout_prompts() == []
    assert review_breakout_prompts(actual_first_year_growth=0.30) == []
    assert review_breakout_prompts(modeled_first_year_growth=0.15) == []


def test_review_composer_t2_fires_on_2021_actuals() -> None:
    from planagent.services.variables.opportunities import review_breakout_prompts

    # TRACK9 live check: actual +40.74% vs live B replay +18.75%.
    prompts = review_breakout_prompts(
        period_label="2021",
        actual_first_year_growth=0.4074,
        modeled_first_year_growth=0.1875,
    )
    assert [p.trigger_id for p in prompts] == ["T2"]


def test_review_composer_t2_silent_within_threshold() -> None:
    from planagent.services.variables.opportunities import review_breakout_prompts

    assert (
        review_breakout_prompts(actual_first_year_growth=0.30, modeled_first_year_growth=0.15) == []
    )


def test_review_composer_t3_and_t4_in_trigger_order() -> None:
    from planagent.services.variables.opportunities import (
        FittedStretch,
        review_breakout_prompts,
    )

    prompts = review_breakout_prompts(
        period_label="2021",
        actual_first_year_growth=0.4074,
        modeled_first_year_growth=0.1875,
        fitted=[
            FittedStretch(
                variable_id="nev_coupling",
                fitted_value=2.08,
                distribution_max=0.40,
                target_label="year-5 收入 32557.18",
            ),
            FittedStretch(
                variable_id="revenue_growth",
                fitted_value=0.30,
                distribution_max=0.30,
                target_label="year-3 收入 21908",
            ),
        ],
        orders_growth=0.71,
        orders_to_revenue=1.76,
        orders_label="2021 年新获订单",
    )
    # T2, then the firing T3 (nev_coupling 5.20x; revenue_growth 1.00x
    # stays silent), then T4.
    assert [p.trigger_id for p in prompts] == ["T2", "T3", "T4"]
    t3 = prompts[1]
    assert t3.details["variable_id"] == "nev_coupling"
    assert t3.details["stretch_ratio"] == pytest.approx(5.2)
    t4 = prompts[2]
    assert t4.details["clauses"] == ["growth", "ratio"]
