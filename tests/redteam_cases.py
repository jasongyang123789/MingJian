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
team recorded (e.g. revenue_growth's "恢复年" note).
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
        _var("base_growth", 0.0, 0.03, 0.06, ["标注假设：决策时点推理"]),
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
        _var("profit_growth", 0.0, 0.12, 0.25, ["标注假设：决策时点推理"]),
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
    ]
    formulas = [
        RedTeamFormula(
            target="revenue_growth",
            expression=(
                "revenue_growth = 0.05 + 0.6 * nev_penetration + 0.4 * "
                "domain_controller_substitution"
            ),
            description="NEV adoption and domain-controller substitution drive revenue growth.",
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


__all__ = [
    "DESAY_2020_SITUATION",
    "DESAY_2020_TREE",
    "complete_case_snapshot",
    "complete_case_snapshot_dict",
    "desay_2020_snapshot",
    "desay_2020_snapshot_dict",
    "desay_2020_variables",
]
