"""Engine-artifact -> deliberation-context builders (Sprint 6, D9).

Pure, deterministic formatters: they render numbers and structures
already stored on a run (MECE decomposition, variable set, ensemble
summary, robustness outputs, calibration fits) into the text blocks a
skill stage argues about. They never compute statistics, never call the
LLM, and never touch the numeric core — the deliberation layer reads
stored artifacts only.

Every builder tolerates a missing fragment (returns ``""``) and skips
malformed lines defensively: a partial audit trail must degrade to a
shorter context block, never crash a deliberation.
"""

from __future__ import annotations

import json
from typing import Any


def format_number(value: Any) -> str:
    """Deterministic number formatting: no trailing zeros, no surprises.

    Integers render without a decimal point; floats render with up to
    six decimal places, trailing zeros stripped. Non-numbers render via
    ``str`` so a malformed stored value degrades visibly, not silently.
    """
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != value:  # NaN
            return "NaN"
        if value in (float("inf"), float("-inf")):
            return "Infinity" if value > 0 else "-Infinity"
        if value == 0:
            return "0"
        if abs(value) >= 1e15 or abs(value) < 1e-6:
            return repr(value)
        return f"{value:.6f}".rstrip("0").rstrip(".")
    return str(value)


def _as_dict(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _render_branch(branch: dict[str, Any], depth: int, lines: list[str]) -> None:
    name = branch.get("name", "?")
    tags = _as_list(branch.get("scope"))
    indent = "  " * depth
    if tags:
        lines.append(f"{indent}- {name} [scope: {', '.join(str(tag) for tag in tags)}]")
    else:
        lines.append(f"{indent}- {name}")
    for child in _as_list(branch.get("children")):
        if isinstance(child, dict):
            _render_branch(child, depth + 1, lines)


def render_mece_block(fragment: dict[str, Any] | None) -> str:
    """Render the stored MECE decomposition + validation verdict."""
    fragment = _as_dict(fragment)
    if not fragment:
        return ""
    decomposition = _as_dict(fragment.get("decomposition"))
    if decomposition is None:
        return ""
    lines = ["MECE decomposition:"]
    topic = decomposition.get("topic")
    if topic:
        lines.append(f"Topic: {topic}")
    root = _as_dict(decomposition.get("root"))
    if root is not None:
        _render_branch(root, 0, lines)
    validation = _as_dict(fragment.get("validation"))
    if validation is not None:
        verdict = "PASS" if validation.get("is_mece") else "FAIL"
        lines.append(f"Validation verdict: {verdict}")
        for check in _as_list(validation.get("checks")):
            if isinstance(check, dict):
                lines.append(
                    f"  - {check.get('node', '?')} "
                    f"{check.get('check', '?')}: {check.get('status', '?')}"
                )
        for issue in _as_list(validation.get("issues")):
            if isinstance(issue, dict):
                lines.append(
                    f"  - issue {issue.get('kind', '?')} at "
                    f"{issue.get('node', '?')}: {issue.get('detail', '')}"
                )
    return "\n".join(lines)


def _distribution_text(distribution: dict[str, Any]) -> str:
    kind = distribution.get("type", "?")
    params = []
    for key in ("value", "mean", "std", "min", "mode", "max", "p"):
        if distribution.get(key) is not None:
            params.append(f"{key} {format_number(distribution[key])}")
    if params:
        return f"{kind} ({', '.join(params)})"
    return str(kind)


def render_variables_block(fragment: dict[str, Any] | None) -> str:
    """Render the stored variable template snapshot + bindings."""
    fragment = _as_dict(fragment)
    if not fragment:
        return ""
    lines = ["Variable table:"]
    template = _as_dict(fragment.get("template"))
    if template is not None:
        lines.append(f"Template: {template.get('name', template.get('id', '?'))}")
        state_fields = _as_list(template.get("state_fields"))
        if state_fields:
            defaults = []
            for field in state_fields:
                if isinstance(field, dict):
                    defaults.append(
                        f"{field.get('name', '?')}={format_number(field.get('default'))}"
                    )
            if defaults:
                lines.append(f"State defaults: {', '.join(defaults)}")
    bindings = _as_dict(fragment.get("bindings"))
    if bindings is None:
        return "\n".join(lines) if len(lines) > 1 else ""
    name = bindings.get("name")
    if name:
        lines.append(f"Variable set: {name}")
    for variable in _as_list(bindings.get("variables")):
        if not isinstance(variable, dict):
            continue
        distribution = _as_dict(variable.get("distribution")) or {}
        text = (
            f"- {variable.get('id', '?')} [{variable.get('unit', '')}]: "
            f"{_distribution_text(distribution)}"
        )
        evidence = variable.get("evidence_ref")
        if evidence:
            text += f" — evidence: {evidence}"
        description = variable.get("description")
        if description:
            text += f" — {description}"
        tags = _as_list(variable.get("scope_tags"))
        if tags:
            text += f" (scope: {', '.join(str(tag) for tag in tags)})"
        lines.append(text)
    for formula in _as_list(bindings.get("formulas")):
        if not isinstance(formula, dict):
            continue
        expression = json.dumps(formula.get("expression"), sort_keys=True)
        lines.append(f"- derived {formula.get('output', '?')} = {expression}")
    internal = _as_dict(bindings.get("internal"))
    if internal:
        lines.append("Internal situation:")
        for key in sorted(internal):
            lines.append(f"  - {key}: {internal[key]}")
    return "\n".join(lines)


def _distribution_lines(label: str, summary: dict[str, Any] | None) -> list[str]:
    if summary is None:
        return []
    return [
        f"{label}: n={summary.get('n', '?')}, mean={format_number(summary.get('mean'))}, "
        f"P10={format_number(summary.get('p10'))}, P50={format_number(summary.get('p50'))}, "
        f"P90={format_number(summary.get('p90'))}, min={format_number(summary.get('min'))}, "
        f"max={format_number(summary.get('max'))}, stddev={format_number(summary.get('stddev'))}, "
        f"loss probability={format_number(summary.get('p_loss'))}"
    ]


def render_ensemble_block(fragment: dict[str, Any] | None) -> str:
    """Render the stored Monte Carlo ensemble summary."""
    fragment = _as_dict(fragment)
    if not fragment:
        return ""
    lines = ["Monte Carlo ensemble:"]
    lines.append(
        f"Metric: {fragment.get('metric', '?')}, trials={fragment.get('trials', '?')}, "
        f"seed={fragment.get('seed', '?')}, loss threshold="
        f"{format_number(fragment.get('loss_threshold'))}"
    )
    levers = _as_dict(fragment.get("strategy_levers"))
    if levers:
        lever_text = ", ".join(
            f"{key}={format_number(value)}" for key, value in sorted(levers.items())
        )
        lines.append(f"Strategy levers: {lever_text}")
    lines.extend(_distribution_lines("Baseline", _as_dict(fragment.get("baseline"))))
    lines.extend(_distribution_lines("Strategy", _as_dict(fragment.get("strategy"))))
    paired = _as_dict(fragment.get("paired"))
    if paired is not None:
        lines.append(
            f"Paired deltas (strategy - baseline): mean delta="
            f"{format_number(paired.get('mean_delta'))}, P10="
            f"{format_number(paired.get('p10'))}, P50={format_number(paired.get('p50'))}, "
            f"P90={format_number(paired.get('p90'))}, P(strategy better)="
            f"{format_number(paired.get('p_strategy_better'))}"
        )
    return "\n".join(lines)


def render_robustness_block(
    fragment: dict[str, Any] | None,
    gates_fragment: dict[str, Any] | None = None,
) -> str:
    """Render stored robustness outputs + decision-gate evaluations."""
    fragment = _as_dict(fragment)
    gates_fragment = _as_dict(gates_fragment)
    if not fragment and not gates_fragment:
        return ""
    lines = ["Robustness evaluation:"]
    if fragment:
        shortfall = _as_dict(fragment.get("expected_shortfall"))
        if shortfall is not None:
            lines.append(
                f"Expected shortfall (alpha={format_number(shortfall.get('alpha'))}, "
                f"tail={shortfall.get('tail', '?')}):"
            )
            for arm in ("baseline", "strategy", "paired"):
                detail = _as_dict(shortfall.get(arm))
                if detail is not None:
                    lines.append(
                        f"  - {arm}: ES={format_number(detail.get('value'))} "
                        f"(threshold {format_number(detail.get('threshold'))}, "
                        f"tail {detail.get('tail_count', '?')}/{detail.get('n', '?')})"
                    )
        tornado = _as_dict(fragment.get("tornado"))
        if tornado is not None:
            rows = _as_list(tornado.get("rows"))
            lines.append(
                f"Tornado sensitivity (metric {tornado.get('metric', '?')}, "
                f"quantiles {format_number(tornado.get('low_quantile'))}-"
                f"{format_number(tornado.get('high_quantile'))}, ranked by swing):"
            )
            for row in rows[:5]:
                if isinstance(row, dict):
                    lines.append(
                        f"  - {row.get('variable', '?')}: swing "
                        f"{format_number(row.get('swing'))} "
                        f"({format_number(row.get('low_value'))} -> "
                        f"{format_number(row.get('high_value'))}: outcome "
                        f"{format_number(row.get('outcome_low'))} -> "
                        f"{format_number(row.get('outcome_high'))}, base "
                        f"{format_number(row.get('outcome_base'))})"
                    )
        threshold = _as_dict(fragment.get("threshold_search"))
        if threshold is not None:
            if threshold.get("reachable"):
                lines.append(
                    f"Threshold search: {threshold.get('variable', '?')} "
                    f"({threshold.get('mode', '?')}, target "
                    f"{format_number(threshold.get('target'))}) reaches the "
                    f"target at {format_number(threshold.get('threshold'))} "
                    f"(achieved {format_number(threshold.get('achieved_statistic'))}, "
                    f"{threshold.get('iterations', '?')} iterations)."
                )
            else:
                lines.append(
                    f"Threshold search: {threshold.get('variable', '?')} "
                    f"({threshold.get('mode', '?')}, target "
                    f"{format_number(threshold.get('target'))}) is NOT reachable "
                    f"within bounds {threshold.get('bounds', '?')}."
                )
        bootstrap = _as_dict(fragment.get("bootstrap"))
        if bootstrap is not None:
            rendered_arms = []
            for arm in ("baseline", "strategy"):
                intervals = _as_list(bootstrap.get(arm))
                for interval in intervals:
                    if isinstance(interval, dict):
                        rendered_arms.append(
                            f"  - {arm} {interval.get('statistic', '?')}: "
                            f"point {format_number(interval.get('estimate'))} "
                            f"[{format_number(interval.get('low'))}, "
                            f"{format_number(interval.get('high'))}] "
                            f"(level {format_number(interval.get('level'))}, "
                            f"draws={interval.get('draws', '?')})"
                        )
            if rendered_arms:
                lines.append("Bootstrap intervals:")
                lines.extend(rendered_arms)
    if gates_fragment:
        evaluations = _as_list(gates_fragment.get("evaluations"))
        if evaluations:
            lines.append("Decision-gate evaluations:")
            for evaluation in evaluations:
                if not isinstance(evaluation, dict):
                    continue
                lines.append(
                    f"  - evaluation {evaluation.get('id', '?')} "
                    f"(pre-registered: {evaluation.get('pre_registered', '?')}, "
                    f"all passed: {evaluation.get('all_passed', '?')}):"
                )
                for outcome in _as_list(evaluation.get("outcomes")):
                    if isinstance(outcome, dict):
                        lines.append(
                            f"    - {outcome.get('name', '?')}: {outcome.get('metric', '?')} "
                            f"{outcome.get('operator', '?')} "
                            f"{format_number(outcome.get('threshold'))} on "
                            f"{outcome.get('arm', '?')} — observed "
                            f"{format_number(outcome.get('observed'))}, "
                            f"passed={outcome.get('passed', '?')}"
                        )
    return "\n".join(lines)


def render_calibration_block(fits: list[dict[str, Any]]) -> str:
    """Render Sprint 5 calibration deltas (fitted vs prior)."""
    if not fits:
        return ""
    lines = ["Calibration (fitted vs prior):"]
    for fit in fits:
        kind = fit.get("kind", "?")
        header = (
            f"Fit {fit.get('id', '?')} ({kind}, metric {fit.get('metric', '?')}, "
            f"n={fit.get('n_observations', '?')}, ridge "
            f"{format_number(fit.get('ridge_strength'))})"
        )
        lines.append(header)
        changes = _as_dict(fit.get("changes")) or {}
        metrics = _as_dict(changes.get("metrics"))
        if metrics:
            for metric in sorted(metrics):
                change = _as_dict(metrics[metric])
                if change is None:
                    continue
                if change.get("rejected_fit"):
                    lines.append(f"  - {metric}: fit REJECTED ({change.get('unchanged_reason', '')})")
                    continue
                lines.append(
                    f"  - {metric}: alert threshold "
                    f"{format_number(change.get('prior_alert_threshold'))} -> "
                    f"{format_number(change.get('fitted_alert_threshold'))}, "
                    f"critical threshold "
                    f"{format_number(change.get('prior_critical_threshold'))} -> "
                    f"{format_number(change.get('fitted_critical_threshold'))} "
                    f"(n={change.get('n_observations', '?')}, "
                    f"tail={change.get('n_tail', '?')})"
                )
        rules = _as_dict(changes.get("rules"))
        if rules:
            for rule_id in sorted(rules):
                change = _as_dict(rules[rule_id])
                if change is None:
                    continue
                lines.append(
                    f"  - rule {rule_id}: weight "
                    f"{format_number(change.get('prior_weight'))} -> "
                    f"{format_number(change.get('fitted_weight'))} "
                    f"(matches={change.get('total_matches', '?')})"
                )
            note = changes.get("association_note")
            if note:
                lines.append(f"  Note: {note}")
    return "\n".join(lines)


def render_firewall_block(fragment: dict[str, Any] | None) -> str:
    """Render the hindsight-firewall cutoff for the run."""
    fragment = _as_dict(fragment)
    if not fragment:
        return ""
    return (
        "Evidence cutoff (hindsight firewall): only evidence dated at or "
        f"before {fragment.get('decision_time', '?')} was visible to the "
        f"simulation (source: {fragment.get('cutoff_source', '?')})."
    )


def render_run_context(
    *,
    configuration: dict[str, Any] | None,
    summary: dict[str, Any] | None,
    calibration_fits: list[dict[str, Any]] | None = None,
) -> str:
    """Assemble the full deliberation context block for one run.

    Sections appear in a fixed order; absent sections are omitted.
    The block is the only numeric input a skill stage receives.
    """
    configuration = configuration or {}
    summary = summary or {}
    sections = [
        render_mece_block(_as_dict(configuration.get("mece"))),
        render_variables_block(_as_dict(configuration.get("variables"))),
        render_ensemble_block(_as_dict(summary.get("monte_carlo"))),
        render_robustness_block(
            _as_dict(summary.get("robustness")),
            _as_dict(summary.get("decision_gates")),
        ),
        render_calibration_block(calibration_fits or []),
        render_firewall_block(_as_dict(configuration.get("hindsight_firewall"))),
    ]
    return "\n\n".join(section for section in sections if section)


__all__ = [
    "format_number",
    "render_calibration_block",
    "render_ensemble_block",
    "render_firewall_block",
    "render_mece_block",
    "render_robustness_block",
    "render_run_context",
    "render_variables_block",
]
