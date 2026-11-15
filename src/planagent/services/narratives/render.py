"""Deterministic markdown rendering of a narrative body (Sprint 13).

Pure function, fixed section order, fixed number formatting (the
Sprint 6 ``format_number`` rule: integers without decimals, floats
to 6 places with trailing zeros stripped). The rendering is part of
the artifact body and therefore covered by the content hash: the
same inputs render byte-identical markdown. Every section carries
its provenance mark in the text, so the rendering never presents
template wording as analysis.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from planagent.services.skills.context import format_number

if TYPE_CHECKING:
    from planagent.services.narratives.models import (
        DirectionNarrative,
        NarrativeBody,
    )


def _mark(provenance: str) -> str:
    return f"[{provenance}]"


def _render_direction(direction: DirectionNarrative) -> list[str]:
    dist = direction.distribution
    lines = [
        f"## 方向 {direction.rank}：{direction.name}",
        "",
        (
            f"- 来源：Run `{direction.source_run_id}`，{direction.arm} 臂，"
            f"ensemble `{dist.ensemble_id}`（{dist.trials} trials，seed {dist.seed}）"
        ),
        "",
        f"### 结果分布 {_mark(dist.provenance)}",
        "",
        (
            f"- 指标 {dist.metric}（loss threshold {format_number(dist.loss_threshold)}）："
            f"P10 {format_number(dist.p10)} / P50 {format_number(dist.p50)} / "
            f"P90 {format_number(dist.p90)}；均值 {format_number(dist.mean)}；"
            f"亏损概率 {format_number(dist.p_loss)}；n={dist.n}"
        ),
    ]
    if dist.expected_shortfall is not None:
        es = dist.expected_shortfall
        lines.append(
            f"- 期望损失（ES，alpha {format_number(es['alpha'])}，{es['tail']}）："
            f"{format_number(es['value'])}（尾部 {es['tail_count']} / {es['n']}）"
        )
    for interval in dist.bootstrap_intervals:
        lines.append(
            f"- Bootstrap {interval['statistic']}：估计 "
            f"{format_number(interval['estimate'])}，区间 "
            f"[{format_number(interval['low'])}, {format_number(interval['high'])}]"
            f"（{interval['draws']} draws，level {format_number(interval['level'])}）"
        )
    lines += ["", f"### 关键驱动 {_mark(direction.drivers.provenance)}", ""]
    if direction.drivers.rows:
        for row in direction.drivers.rows:
            lines.append(
                f"- {row.variable}：{format_number(row.low_value)} → "
                f"{format_number(row.high_value)} 时结果 "
                f"{format_number(row.outcome_low)} → "
                f"{format_number(row.outcome_high)}（swing {format_number(row.swing)}）"
            )
    elif direction.drivers.note:
        lines.append(f"- {direction.drivers.note}")
    lines += ["", "### 调头信号", ""]
    if direction.signals:
        for signal in direction.signals:
            lines.append(f"- {_mark(signal.provenance)} {signal.text}")
    elif direction.signals_note:
        lines.append(f"- {direction.signals_note}")
    premortem = direction.premortem
    lines += ["", f"### 事前验尸 {_mark(premortem.provenance)}", ""]
    if premortem.failure_narrative is not None:
        lines.append(premortem.failure_narrative)
        lines.append("")
        for mode in premortem.failure_modes:
            lines.append(
                f"- 失败模式：{mode.mode}；原因：{mode.cause}；"
                f"早期信号：{mode.early_signal}；预防：{mode.prevention}"
            )
        for flag in premortem.fatal_flags:
            lines.append(f"- 致命标记：{flag}")
        if premortem.deliberation_id is not None:
            lines.append(f"- 引自 deliberation `{premortem.deliberation_id}`")
    elif premortem.note:
        lines.append(premortem.note)
    first_step = direction.first_step
    lines += ["", f"### 48 小时第一步 {_mark(first_step.provenance)}", ""]
    if first_step.next_action is not None:
        lines.append(first_step.next_action)
        if first_step.cheapest_validation_test is not None:
            lines.append(f"- 最便宜的验证：{first_step.cheapest_validation_test}")
        for condition in first_step.conditions:
            lines.append(f"- 条件：{condition}")
        if first_step.deliberation_id is not None:
            lines.append(f"- 引自 deliberation `{first_step.deliberation_id}`")
    elif first_step.note:
        lines.append(first_step.note)
    lines += ["", "### 回溯", ""]
    if direction.mece_trace is not None:
        for branch in direction.mece_trace.branches:
            lines.append(f"- MECE 分支：{branch.name}（{', '.join(branch.scope)}）")
    elif direction.mece_note:
        lines.append(f"- {direction.mece_note}")
    lines.append("")
    return lines


def render_narrative_markdown(body: NarrativeBody) -> str:
    """Render the deterministic reading text for a narrative body."""
    lines = [
        f"# 决策方向简报：{body.topic}",
        "",
        (
            f"锚定 Run：`{body.anchor_run_id}` | 领域：{body.domain_id} | "
            f"协议：{body.protocol} | 方向数：{len(body.directions)}"
        ),
        "",
    ]
    if body.mece is not None:
        lines += [
            f"## MECE 结构 {_mark(body.mece.provenance)}",
            "",
            (
                f"- 主题：{body.mece.topic}；校验："
                f"{'通过' if body.mece.is_mece else '未通过'}；"
                f"{body.mece.branch_count} 个分支，{body.mece.scope_tag_count} 个 scope 标签"
            ),
            "",
        ]
    if body.calibration_context:
        lines += ["## 校准状态 [computed]", ""]
        for entry in body.calibration_context:
            loo = format_number(entry.loo_rmse) if entry.loo_rmse is not None else "n/a"
            lines.append(
                f"- 拟合 `{entry.fit_id}`（{entry.kind}，LOO RMSE {loo}，"
                f"{entry.n_observations} 个观测）"
            )
        lines.append("")
    if body.loop_context is not None:
        lines += [
            f"## 监测循环 {_mark(body.loop_context.provenance)}",
            "",
            (
                f"- 循环：{body.loop_context.loop_name}（`{body.loop_context.loop_id}`），"
                f"活跃注册 `{body.loop_context.registration_id}`，"
                f"{body.loop_context.trigger_count} 个触发器"
            ),
            "",
        ]
    for direction in body.directions:
        lines.extend(_render_direction(direction))
    lines.append(
        "_本简报由确定性引擎生成：[computed] 来自已存储的数值结果，"
        "[deliberated] 引自已存储的商议输出，[template] 为模板措辞，"
        "不代表分析结论。_"
    )
    return "\n".join(lines)


__all__ = ["render_narrative_markdown"]
