"""Shared case snapshots for red-team tests (Phase 4, Track 8).

``desay_2020`` is the faithful frozen case from
``research/strategy-engine/desay-backtest-2026-11-19/REPORT.md``: the
generic corporate template, NO NEV variable, NO domain-controller
variable, NO transmission formulas. The completeness checks MUST flag
the missing NEV chain and the domain-controller substitution on it.

``complete_case`` is the same case WITH the missing drivers added as
variables AND linked by transmission formulas. The checks must NOT
hallucinate missing drivers on it (acceptance test 2).

Variable evidence strings are copied from the report so the
unjustified-discount check sees the same justifications the backtest
team recorded (e.g. revenue_growth's "恢复年" note). Since audit fix A4
(2026-11-20), base_growth and profit_growth carry the LIVE evidence
strings from the e047f50 re-run harness
(``research/.../backtest-rerun-2026-11-19-e047f50/run_desay_e047f50.py``)
plus one labeled-assumption sentence each, so the fixture reproduces
the two anchor-run false positives the fix removes.
"""

from __future__ import annotations

from planagent.services.redteam.models import (
    CaseSnapshot,
    RedTeamFormula,
    RedTeamVariable,
)

DESAY_2020_SITUATION = (
    "2020 年收入 67.99 亿（+27.39%）、归母净利润 5.18 亿（+77.36%）、毛利率 23.39%、"
    "研发 8.17 亿（12.02%）；智能座舱 59.12 亿（86.95%，+33.52%）、智能驾驶 7.12 亿"
    "（10.48%，+94.78%）、网联服务及其他 1.75 亿（2.57%，+65.10%）；IPU03 域控制器"
    "在小鹏 P7 量产，IPU04（英伟达 Orin）与理想合作、目标 2022 年量产，360 全景环视"
    "出货量中国第 2；新获项目订单年化约 70 亿；中国汽车销量 2531.1 万辆（-1.9%），"
    "NEV 销量 136.7 万辆、渗透率 5.4%，国务院《新能源汽车产业发展规划（2021—2035 年）》："
    "2025 年 NEV 占比 ~20%，L2 装配率 ~12%。"
)

DESAY_2020_TREE = {
    "topic": "德赛西威2020：智能驾驶来了，怎么选",
    "root": {
        "name": "德赛西威2020：智能驾驶来了，怎么选",
        "scope": ["driving", "cockpit", "connected"],
        "children": [
            {"name": "智能驾驶", "scope": ["driving"]},
            {"name": "座舱", "scope": ["cockpit"]},
            {"name": "网联与出海", "scope": ["connected"]},
        ],
    },
}


def _var(
    name: str,
    low: float,
    mode: float,
    high: float,
    evidence: list[str],
    description: str = "",
) -> RedTeamVariable:
    return RedTeamVariable(
        name=name,
        description=description,
        distribution=f"triangular({low}, {mode}, {high})",
        low=low,
        mode=mode,
        high=high,
        evidence=evidence,
    )


def desay_2020_variables() -> list[RedTeamVariable]:
    """The desay-2020 variable table, exactly as the backtest ran it."""
    return [
        _var(
            "market_share",
            0.05,
            0.066,
            0.08,
            [
                (
                    "德赛 2020 年座舱收入 59.12 亿 / 高工智能汽车研究院估计的 2020 年中国智能座舱电子市场 "
                    ">900 亿 = 6.6%（标注假设：市场规模是估计值且为下限，故 6.6% 是偏高估计）"
                )
            ],
        ),
        _var(
            "base_growth",
            0.0,
            0.03,
            0.06,
            [
                (
                    "estimate: labeled assumption — underlying share growth absent "
                    "intelligent-driving adoption; cockpit already 86.95% of revenue and "
                    "growing +33.5% in 2020. Labeled assumption: the cited +33.5% is "
                    "cockpit segment revenue growth including adoption effects, while this "
                    "variable is share growth absent adoption, so its mode sits "
                    "deliberately below the cited segment rate."
                )
            ],
        ),
        _var("disruptor_ceiling", 0.7, 0.85, 0.95, ["标注假设：决策时点推理"]),
        _var("disruptor_rate", 0.8, 1.0, 1.2, ["标注假设：决策时点推理"]),
        _var("disruptor_midpoint", 2.0, 3.0, 4.0, ["标注假设：决策时点推理"]),
        _var("share_coupling", 0.15, 0.25, 0.35, ["标注假设：决策时点推理"]),
        _var(
            "revenue",
            6200,
            6799.06,
            7400,
            ["FY2020 收入 67.99 亿（内部数，2020 年报摘要公告 2021-010，2021-04-13 发布）"],
        ),
        _var(
            "revenue_growth",
            0.05,
            0.15,
            0.30,
            [
                (
                    "2020 年收入 +27.39% 是恢复年（2018 年 -10.0%、2019 年 -1.3% 之后）；2017–2020 年 3 年 "
                    "CAGR 仅 4.2%（60.1 亿→68.0 亿）；众数 15% 已是对订单与 NEV 规划（2025 年占比 20%）的乐观读取"
                )
            ],
        ),
        _var("revenue_coupling", 0.15, 0.25, 0.35, ["标注假设：决策时点推理"]),
        _var(
            "profit",
            450,
            518.15,
            600,
            ["FY2020 归母净利润 5.18 亿（内部数，2020 年报摘要公告 2021-010）"],
        ),
        _var(
            "profit_growth",
            0.0,
            0.12,
            0.25,
            [
                (
                    "estimate: labeled assumption, tracks revenue growth at a lower mode "
                    "(margin pressure; gross margin 23.39% in 2020, down from 25.78% in "
                    "2017). Labeled assumption: the lower mode is a deliberate discount "
                    "for margin pressure, not an unexplained discount."
                )
            ],
        ),
        _var("profit_coupling", 0.10, 0.15, 0.25, ["标注假设：决策时点推理"]),
    ]


def desay_2020_snapshot() -> CaseSnapshot:
    return CaseSnapshot(
        case_id="desay-2020",
        decision_question="加码智能驾驶+座舱域控，还是稳守座舱/适度投入？",
        decision_time="2020-12-31T00:00:00Z",
        domain="corporate",
        mece_tree=DESAY_2020_TREE,  # type: ignore[arg-type]
        variables=desay_2020_variables(),
        formulas=[],
        internal_situation=DESAY_2020_SITUATION,
    )


def complete_case_snapshot() -> CaseSnapshot:
    """desay-2020 WITH the missing drivers added and linked by formulas."""
    variables = desay_2020_variables() + [
        _var(
            "nev_penetration",
            0.05,
            0.08,
            0.20,
            ["CAAM：2020 年 NEV 渗透率 5.4%；国务院 2025 年目标 ~20%"],
            description="NEV share of new-car sales (penetration)",
        ),
        _var(
            "domain_controller_substitution",
            0.0,
            0.15,
            0.40,
            ["IPU03 域控制器小鹏 P7 量产；2020 年中国首批量产智能驾驶域控制器"],
            description=(
                "Share of cockpit/ADAS value shifting from discrete ECUs "
                "to domain controllers (substitution rate)"
            ),
        ),
        _var(
            "adas_penetration",
            0.10,
            0.12,
            0.25,
            ["2020 年 L2 装配率 ~12%"],
            description="L2 ADAS fitment rate",
        ),
        # Step 4 (2026-11-24): the order book is a fourth known driver.
        # The situation names 新获项目订单年化约 70 亿, so the complete
        # case must carry the backlog chain too — otherwise the
        # "complete" fixture would newly flag order_backlog.
        _var(
            "order_backlog",
            0.0,
            6799.06,
            10000.0,
            ["2020 年新获项目订单年化约 70 亿（年报摘要）；开簿按 mode 收入一年 intake"],
            description="Stock of booked-but-undelivered orders (order_backlog)",
        ),
        _var(
            "backlog_conversion",
            0.30,
            0.40,
            0.60,
            ["SOP 滞后：订单兑现按 backlog_conversion 转化"],
            description="Share of the order book converting to revenue per tick",
        ),
    ]
    formulas = [
        RedTeamFormula(
            target="revenue_growth",
            expression=(
                "revenue_growth = 0.05 + 0.6 * nev_penetration + 0.4 * "
                "domain_controller_substitution + 0.3 * order_backlog / revenue"
            ),
            description="NEV adoption, domain-controller substitution, and the order book drive revenue growth.",
        ),
        RedTeamFormula(
            target="market_share",
            expression="market_share = base_share * (1 + 0.5 * adas_penetration)",
            description="ADAS penetration lifts share.",
        ),
    ]
    return CaseSnapshot(
        case_id="desay-2020-complete",
        decision_question="加码智能驾驶+座舱域控，还是稳守座舱/适度投入？",
        decision_time="2020-12-31T00:00:00Z",
        domain="corporate",
        mece_tree=DESAY_2020_TREE,  # type: ignore[arg-type]
        variables=variables,
        formulas=formulas,
        internal_situation=DESAY_2020_SITUATION,
    )


def desay_2020_snapshot_dict() -> dict:
    return desay_2020_snapshot().model_dump(mode="json")


def complete_case_snapshot_dict() -> dict:
    return complete_case_snapshot().model_dump(mode="json")


HUAWEI_2000_SITUATION = (
    "2000-12-31, 任正非《华为的冬天》；220亿人民币，利润29亿，中国电子百强第一；"
    "海外合同销售额仅1亿多美元，1999年海外收入<4%；互联网泡沫破裂，全球IT投资下滑；"
    "2000年引入IBM ISC；10月校招10000人"
)

HUAWEI_2000_TREE = {
    "topic": "华为2000：冬天来了，收缩过冬还是坚持投入？",
    "root": {
        "name": "华为2000：冬天来了，怎么过冬",
        "scope": ["growth", "survival"],
        "children": [
            {"name": "增长", "scope": ["growth"]},
            {"name": "生存", "scope": ["survival"]},
        ],
    },
}


def huawei_2000_snapshot() -> CaseSnapshot:
    """The Huawei-2000 case, copied from the trials50 harness
    (``scripts/backtest/trials50/run_classic.py`` CASES["huawei"]) with
    the situation joined exactly as the Step 4 live probe built it
    (``probe_redteam_live.py``: decision_point + sales_2000 +
    overseas_2000 + context). Formulas are [] as in the probe
    construction — the red-team structure checks do not depend on
    them here (the situation names no catalog driver).

    Revenue is a single undifferentiated total: six variables, no
    region / product / customer split anywhere — the
    missing_segment_split check MUST fire on this snapshot, and only
    on it (desay-2020's situation + tree name three product segments).
    """
    return CaseSnapshot(
        case_id="huawei-2000",
        decision_question="华为2000：冬天来了，收缩过冬还是坚持投入？",
        decision_time="2000-12-31T00:00:00Z",
        domain="corporate",
        mece_tree=HUAWEI_2000_TREE,  # type: ignore[arg-type]
        variables=[
            _var(
                "market_share",
                0.02,
                0.03,
                0.05,
                [
                    "estimate: labeled assumption — 2000 global share not publicly "
                    "disclosed; 2000 contract sales $2.65B"
                ],
                description="2000年全球电信设备市场份额（起始值）",
            ),
            _var(
                "share_growth",
                -0.05,
                0.08,
                0.25,
                [
                    "estimate: 1995-2000 sales grew ~70%/yr (RMB 1.5B→22B); "
                    "Dec 2000 bubble burst + winter warning; wide distribution, mode 8%"
                ],
                description="年均份额增长率（锚定run的不确定性范围）",
            ),
            _var(
                "revenue",
                180,
                220,
                260,
                [
                    "evidence: 2000 sales RMB 22B (220亿), profit RMB 2.9B; "
                    "decision-time internal figure"
                ],
                description="年销售收入，单位亿人民币（起始值）",
            ),
            _var(
                "revenue_growth",
                0.0,
                0.15,
                0.35,
                [
                    "estimate: 1995-2000 sales ~70%/yr, bubble burst moderates; "
                    "own targets 2001 400亿 (+82%) / 2002 600亿 (+50%) show high "
                    "ambition, mode 15% conservative"
                ],
                description="年均收入增长率（锚定run的不确定性范围）",
            ),
            _var(
                "profit",
                24,
                29,
                35,
                ["evidence: 2000 profit RMB 2.9B (29亿)"],
                description="年利润，单位亿人民币（起始值）",
            ),
            _var(
                "profit_growth",
                0.0,
                0.12,
                0.30,
                [
                    "estimate: labeled assumption, tracks revenue growth at a lower "
                    "mode (margin pressure in a downturn)"
                ],
                description="年均利润增长率（锚定run的不确定性范围）",
            ),
        ],
        formulas=[],
        internal_situation=HUAWEI_2000_SITUATION,
    )


def huawei_2000_snapshot_dict() -> dict:
    return huawei_2000_snapshot().model_dump(mode="json")


__all__ = [
    "DESAY_2020_SITUATION",
    "DESAY_2020_TREE",
    "HUAWEI_2000_SITUATION",
    "HUAWEI_2000_TREE",
    "complete_case_snapshot",
    "complete_case_snapshot_dict",
    "desay_2020_snapshot",
    "desay_2020_snapshot_dict",
    "desay_2020_variables",
    "huawei_2000_snapshot",
    "huawei_2000_snapshot_dict",
]
