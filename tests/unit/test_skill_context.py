"""Context-builder tests: stored fragments render verbatim and
deterministically; absent fragments are omitted, never invented
(Sprint 6, D9)."""

from __future__ import annotations

from planagent.services.skills.context import (
    format_number,
    render_calibration_block,
    render_ensemble_block,
    render_firewall_block,
    render_mece_block,
    render_robustness_block,
    render_run_context,
    render_variables_block,
)


def test_format_number_strips_trailing_zeros() -> None:
    assert format_number(160.1) == "160.1"
    assert format_number(7.5) == "7.5"
    assert format_number(-124.4) == "-124.4"
    assert format_number(0.384) == "0.384"
    assert format_number(12) == "12"
    assert format_number(12.0) == "12"
    assert format_number(0) == "0"
    assert format_number(0.000001) == "0.000001"
    assert format_number(1 / 3) == "0.333333"


def test_render_mece_block_golden() -> None:
    fragment = {
        "decomposition": {
            "topic": "Should we launch?",
            "root": {
                "name": "Launch",
                "scope": ["demand", "cost"],
                "children": [
                    {"name": "Demand", "scope": ["demand"]},
                    {"name": "Cost", "scope": ["cost"]},
                ],
            },
        },
        "validation": {
            "is_mece": True,
            "checks": [
                {
                    "node": "Launch",
                    "check": "mutual_exclusion",
                    "status": "PASS",
                    "detail": "ok",
                },
                {
                    "node": "Launch",
                    "check": "exhaustiveness",
                    "status": "PASS",
                    "detail": "ok",
                },
            ],
            "issues": [],
        },
    }
    assert render_mece_block(fragment) == (
        "MECE decomposition:\n"
        "Topic: Should we launch?\n"
        "- Launch [scope: demand, cost]\n"
        "  - Demand [scope: demand]\n"
        "  - Cost [scope: cost]\n"
        "Validation verdict: PASS\n"
        "  - Launch mutual_exclusion: PASS\n"
        "  - Launch exhaustiveness: PASS"
    )


def test_render_mece_block_reports_issues() -> None:
    fragment = {
        "decomposition": {"topic": "T", "root": {"name": "R", "scope": ["a"]}},
        "validation": {
            "is_mece": False,
            "checks": [],
            "issues": [
                {"kind": "overlap", "node": "R", "detail": "tag shared", "tags": ["a"]}
            ],
        },
    }
    rendered = render_mece_block(fragment)
    assert "Validation verdict: FAIL" in rendered
    assert "issue overlap at R: tag shared" in rendered


def test_render_mece_block_empty_when_absent() -> None:
    assert render_mece_block(None) == ""
    assert render_mece_block({}) == ""
    assert render_mece_block({"validation": {}}) == ""


def test_render_variables_block_golden() -> None:
    fragment = {
        "template_id": "builtin:corporate",
        "template": {
            "name": "Corporate",
            "state_fields": [{"name": "cash", "default": 100.0}],
        },
        "bindings": {
            "name": "case",
            "variables": [
                {
                    "id": "cash",
                    "unit": "k",
                    "distribution": {"type": "triangular", "min": 60, "mode": 100, "max": 140},
                    "evidence_ref": "estimate: founder judgment",
                    "description": "Starting cash",
                    "scope_tags": ["cost"],
                },
                {
                    "id": "churn",
                    "unit": "rate",
                    "distribution": {"type": "fixed", "value": 0.05},
                    "evidence_ref": "evidence:q3-report",
                    "description": "",
                    "scope_tags": [],
                },
            ],
            "formulas": [
                {"output": "runway", "expression": {"op": "/", "args": [{"ref": "cash"}, {"ref": "burn"}]}}
            ],
            "internal": {"team": "20 people", "runway": "9 months"},
        },
    }
    assert render_variables_block(fragment) == (
        "Variable table:\n"
        "Template: Corporate\n"
        "State defaults: cash=100\n"
        "Variable set: case\n"
        "- cash [k]: triangular (min 60, mode 100, max 140) — evidence: estimate: founder judgment — Starting cash (scope: cost)\n"
        "- churn [rate]: fixed (value 0.05) — evidence: evidence:q3-report\n"
        '- derived runway = {"args": [{"ref": "cash"}, {"ref": "burn"}], "op": "/"}\n'
        "Internal situation:\n"
        "  - runway: 9 months\n"
        "  - team: 20 people"
    )


def test_render_ensemble_block_golden() -> None:
    fragment = {
        "metric": "cash",
        "trials": 50,
        "seed": 42,
        "loss_threshold": 0,
        "strategy_levers": {"cash": 120.0},
        "baseline": {
            "n": 50, "mean": 100.5, "min": 60, "max": 140,
            "p10": 70.25, "p50": 100.0, "p90": 130.75, "stddev": 20.5, "p_loss": 0.12,
        },
        "strategy": {
            "n": 50, "mean": 110.0, "min": 80, "max": 150,
            "p10": 85.0, "p50": 110.0, "p90": 135.0, "stddev": 15.0, "p_loss": 0.04,
        },
        "paired": {
            "n": 50, "mean_delta": 9.5, "p10": -5.0, "p50": 10.0, "p90": 25.0,
            "p_strategy_better": 0.78,
        },
    }
    assert render_ensemble_block(fragment) == (
        "Monte Carlo ensemble:\n"
        "Metric: cash, trials=50, seed=42, loss threshold=0\n"
        "Strategy levers: cash=120\n"
        "Baseline: n=50, mean=100.5, P10=70.25, P50=100, P90=130.75, min=60, max=140, stddev=20.5, loss probability=0.12\n"
        "Strategy: n=50, mean=110, P10=85, P50=110, P90=135, min=80, max=150, stddev=15, loss probability=0.04\n"
        "Paired deltas (strategy - baseline): mean delta=9.5, P10=-5, P50=10, P90=25, P(strategy better)=0.78"
    )


def test_render_robustness_block_golden() -> None:
    fragment = {
        "expected_shortfall": {
            "alpha": 0.05,
            "tail": "lower",
            "baseline": {"value": -50.5, "threshold": -20.0, "tail_count": 2, "n": 50},
            "strategy": {"value": -10.0, "threshold": -5.0, "tail_count": 2, "n": 50},
            "paired": {"value": -8.0, "threshold": -2.0, "tail_count": 2, "n": 50},
        },
        "tornado": {
            "metric": "cash",
            "low_quantile": 0.1,
            "high_quantile": 0.9,
            "rows": [
                {
                    "variable": "cash", "low_value": 60, "high_value": 140,
                    "outcome_low": 70, "outcome_high": 130, "outcome_base": 100,
                    "swing": 60,
                }
            ],
        },
        "threshold_search": {
            "variable": "cash", "mode": "p_loss", "target": 0.1,
            "reachable": True, "threshold": 85.5, "achieved_statistic": 0.1,
            "iterations": 6,
        },
        "bootstrap": {
            "baseline": [
                {"statistic": "mean", "estimate": 100.5, "low": 95.0, "high": 106.0,
                 "draws": 1000, "level": 0.9}
            ],
            "strategy": [],
        },
    }
    gates = {
        "evaluations": [
            {
                "id": "eval-1",
                "pre_registered": True,
                "all_passed": False,
                "outcomes": [
                    {
                        "name": "floor", "metric": "p50", "operator": ">=",
                        "threshold": 90, "arm": "baseline", "observed": 100.0,
                        "passed": True,
                    }
                ],
            }
        ]
    }
    rendered = render_robustness_block(fragment, gates)
    assert "Expected shortfall (alpha=0.05, tail=lower):" in rendered
    assert "baseline: ES=-50.5 (threshold -20, tail 2/50)" in rendered
    assert "Tornado sensitivity (metric cash, quantiles 0.1-0.9, ranked by swing):" in rendered
    assert "cash: swing 60 (60 -> 140: outcome 70 -> 130, base 100)" in rendered
    assert "reaches the target at 85.5 (achieved 0.1, 6 iterations)" in rendered
    assert "baseline mean: point 100.5 [95, 106] (level 0.9, draws=1000)" in rendered
    assert "pre-registered: True, all passed: False" in rendered
    assert "floor: p50 >= 90 on baseline — observed 100, passed=True" in rendered


def test_render_robustness_block_unreachable_threshold() -> None:
    fragment = {
        "threshold_search": {
            "variable": "cash", "mode": "arm_flip", "target": 0,
            "reachable": False, "bounds": [60, 140],
        }
    }
    rendered = render_robustness_block(fragment)
    assert "is NOT reachable within bounds [60, 140]" in rendered


def test_render_calibration_block_golden() -> None:
    fits = [
        {
            "id": "fit-1",
            "kind": "policy_thresholds",
            "metric": "cash",
            "ridge_strength": 1.0,
            "n_observations": 4,
            "changes": {
                "metrics": {
                    "cash": {
                        "prior_alert_threshold": 50,
                        "fitted_alert_threshold": 86.0,
                        "prior_critical_threshold": 25,
                        "fitted_critical_threshold": 52.5,
                        "n_observations": 4,
                        "n_tail": 2,
                        "rejected_fit": False,
                    }
                }
            },
        },
        {
            "id": "fit-2",
            "kind": "rule_weights",
            "metric": "cash",
            "ridge_strength": 1.0,
            "n_observations": 10,
            "changes": {
                "rules": {
                    "rule_a": {"prior_weight": 1.0, "fitted_weight": 1.5, "total_matches": 6}
                },
                "association_note": "Association, not causation.",
            },
        },
    ]
    rendered = render_calibration_block(fits)
    assert "Fit fit-1 (policy_thresholds, metric cash, n=4, ridge 1)" in rendered
    assert "cash: alert threshold 50 -> 86, critical threshold 25 -> 52.5 (n=4, tail=2)" in rendered
    assert "rule rule_a: weight 1 -> 1.5 (matches=6)" in rendered
    assert "Note: Association, not causation." in rendered
    assert render_calibration_block([]) == ""


def test_render_firewall_block() -> None:
    fragment = {
        "protocol": "hindsight-firewall/v1",
        "decision_time": "2026-11-13T00:00:00+00:00",
        "cutoff_source": "explicit",
    }
    rendered = render_firewall_block(fragment)
    assert "2026-11-13T00:00:00+00:00" in rendered
    assert "explicit" in rendered
    assert render_firewall_block(None) == ""


def test_render_run_context_orders_sections_and_omits_absent() -> None:
    context = render_run_context(
        configuration={"mece": {"decomposition": {"topic": "T", "root": {"name": "R", "scope": ["a"]}}}},
        summary={},
    )
    assert context.startswith("MECE decomposition:")
    assert "Monte Carlo" not in context
    assert render_run_context(configuration={}, summary={}) == ""
    assert render_run_context(configuration=None, summary=None) == ""


def test_render_run_context_is_deterministic() -> None:
    configuration = {"variables": {"bindings": {"variables": [], "internal": {"b": "2", "a": "1"}}}}
    first = render_run_context(configuration=configuration, summary={})
    second = render_run_context(configuration=configuration, summary={})
    assert first == second
    # Internal entries render in sorted key order.
    assert first.index("a: 1") < first.index("b: 2")
