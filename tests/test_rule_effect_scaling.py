"""Unit tests for variable-scaled rule effects (Phase 1 automotive pack).

Covers ``scaled_effect_value`` (fixed constants unchanged, scaling,
missing/non-finite fallback), the YAML ``scale_by`` parse (loud failure
on malformed values), and the shipped automotive rules file (13 rules,
exactly one scaled effect, keyword-only triggers).
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from planagent.simulation.rules import RuleEffect, RuleRegistry, scaled_effect_value

RULES_ROOT = Path(__file__).resolve().parent.parent / "rules"


def test_fixed_effect_ignores_scope() -> None:
    effect = RuleEffect(target="cash", op="add", value=5.0)
    assert scaled_effect_value(effect, {"confidence": 2.0}) == 5.0
    assert scaled_effect_value(effect, None) == 5.0


def test_scaled_effect_multiplies_by_scope_value() -> None:
    effect = RuleEffect(target="production_volume", op="add", value=6.0, scale_by="confidence")
    assert scaled_effect_value(effect, {"confidence": 0.5}) == pytest.approx(3.0)
    assert scaled_effect_value(effect, {"confidence": 1.2}) == pytest.approx(7.2)


def test_scaled_effect_missing_id_falls_back_to_base() -> None:
    effect = RuleEffect(target="production_volume", op="add", value=6.0, scale_by="confidence")
    assert scaled_effect_value(effect, {"other": 2.0}) == 6.0
    assert scaled_effect_value(effect, {}) == 6.0
    assert scaled_effect_value(effect, None) == 6.0


def test_scaled_effect_non_finite_factor_falls_back_to_base() -> None:
    effect = RuleEffect(target="production_volume", op="add", value=6.0, scale_by="confidence")
    assert scaled_effect_value(effect, {"confidence": math.inf}) == 6.0
    assert scaled_effect_value(effect, {"confidence": math.nan}) == 6.0


def test_yaml_scale_by_parses(tmp_path: Path) -> None:
    domain_root = tmp_path / "testdom"
    domain_root.mkdir()
    (domain_root / "default_rules.yaml").write_text(
        "rules:\n"
        '  - id: "test.scaled"\n'
        '    domain: "testdom"\n'
        '    action_id: "hold_and_monitor"\n'
        "    priority: 80\n"
        "    trigger:\n"
        '      keywords: ["surge"]\n'
        "    effects:\n"
        '      - target: "production_volume"\n'
        '        op: "add"\n'
        "        value: 6.0\n"
        '        scale_by: "consumer_confidence_proxy"\n'
        '  - id: "test.fixed"\n'
        '    domain: "testdom"\n'
        '    action_id: "hold_and_monitor"\n'
        "    priority: 70\n"
        "    trigger:\n"
        '      keywords: ["calm"]\n'
        "    effects:\n"
        '      - target: "cash"\n'
        '        op: "add"\n'
        "        value: 1.0\n",
        encoding="utf-8",
    )
    rules = RuleRegistry(tmp_path).get_rules("testdom")
    by_id = {rule.rule_id: rule for rule in rules}
    assert by_id["test.scaled"].effects[0].scale_by == "consumer_confidence_proxy"
    assert by_id["test.fixed"].effects[0].scale_by is None


@pytest.mark.parametrize("bad_value", ['""', '"   "', "42", '["x"]'])
def test_yaml_scale_by_malformed_fails_loudly(tmp_path: Path, bad_value: str) -> None:
    domain_root = tmp_path / "testdom"
    domain_root.mkdir()
    (domain_root / "default_rules.yaml").write_text(
        "rules:\n"
        '  - id: "test.bad"\n'
        '    domain: "testdom"\n'
        '    action_id: "hold_and_monitor"\n'
        "    trigger:\n"
        '      keywords: ["surge"]\n'
        "    effects:\n"
        '      - target: "cash"\n'
        '        op: "add"\n'
        f"        value: 1.0\n"
        f"        scale_by: {bad_value}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="scale_by"):
        RuleRegistry(tmp_path).get_rules("testdom")


def test_automotive_rules_file_shape() -> None:
    rules = RuleRegistry(RULES_ROOT).get_rules("automotive")
    assert len(rules) == 13
    ids = {rule.rule_id for rule in rules}
    assert ids == {
        "auto.chip_shortage",
        "auto.price_war",
        "auto.policy_tax_hike",
        "auto.subsidy_payback",
        "auto.inventory_overhang",
        "auto.demand_surge",
        "auto.dms_mandate",
        "auto.generation_changeover",
        "auto.margin_pressure",
        "auto.export_hedge",
        "auto.material_cost_shock",
        "auto.rate_cut",
        "auto.nev_momentum",
    }
    # Keyword-only triggers: no rule relies on conditions the engine
    # never evaluates against state.
    assert all(not rule.trigger_conditions for rule in rules)
    assert all(rule.trigger_keywords for rule in rules)
    # Exactly one scaled effect in Phase 1: the demand-surge demo.
    scaled = [
        (rule.rule_id, effect)
        for rule in rules
        for effect in rule.effects
        if effect.scale_by is not None
    ]
    assert len(scaled) == 1
    rule_id, effect = scaled[0]
    assert rule_id == "auto.demand_surge"
    assert effect.target == "production_volume"
    assert effect.value == 6.0
    assert effect.scale_by == "consumer_confidence_proxy"
    # Generation changeover advances the transition index.
    changeover = next(rule for rule in rules if rule.rule_id == "auto.generation_changeover")
    assert [effect.target for effect in changeover.effects] == ["generation_transition_index"]
    assert changeover.effects[0].value == 0.05
