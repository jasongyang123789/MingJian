"""Unit tests for built-in variable presets and run-configuration resolution.

The core guarantee: a built-in preset reproduces the domain pack's state
defaults and the built-in ``_STATE_POLICIES`` exactly, so runs carrying a
preset behave identically to runs without one. Resolution helpers must return
None / built-ins when a run carries no template fragment.
"""

from __future__ import annotations

import pytest

from planagent.services.simulation.domain_packs import SimulationDomainPacksMixin
from planagent.services.simulation_branching import (
    _STATE_POLICIES,
    MetricPolicy,
    metric_compare_score,
    score_branch_delta,
)
from planagent.services.variables.models import (
    MetricPolicySpec,
    VariableSet,
    VariableTemplate,
    VariableValidationResult,
)
from planagent.services.variables.presets import (
    builtin_template,
    builtin_template_id,
    is_builtin_template_id,
    known_domain_ids,
    resolve_policies,
    resolve_state_defaults,
    variables_configuration_fragment,
)
from planagent.simulation.domain_packs import registry


@pytest.mark.parametrize("domain_id", ["corporate", "military"])
def test_builtin_preset_matches_pack_defaults_and_policies(domain_id: str) -> None:
    pack = registry.get(domain_id)
    template = builtin_template(domain_id)
    assert template.id == builtin_template_id(domain_id) == f"builtin:{domain_id}"
    assert template.domain_id == domain_id
    assert template.is_builtin is True
    assert template.variables == []
    assert template.internal == {}

    expected_defaults = {field.name: float(field.default) for field in pack.state_fields}
    preset_defaults = {field.name: field.default for field in template.state_fields}
    assert preset_defaults == expected_defaults
    assert [field.name for field in template.state_fields] == [
        field.name for field in pack.state_fields
    ]

    expected_policies = _STATE_POLICIES[domain_id]
    assert set(template.policies) == set(expected_policies)
    for metric, policy in expected_policies.items():
        spec = template.policies[metric]
        assert spec.preferred_direction == policy.preferred_direction
        assert spec.alert_threshold == policy.alert_threshold
        assert spec.critical_threshold == policy.critical_threshold


def test_builtin_preset_field_and_policy_counts() -> None:
    assert len(builtin_template("corporate").state_fields) == 17
    assert len(builtin_template("corporate").policies) == 16
    assert len(builtin_template("military").state_fields) == 19
    assert len(builtin_template("military").policies) == 19


def test_builtin_template_unknown_domain() -> None:
    with pytest.raises(ValueError, match="Unknown domain_id"):
        builtin_template("no_such_domain")


def test_known_domain_ids_and_builtin_id_helpers() -> None:
    domains = known_domain_ids()
    assert "corporate" in domains
    assert "military" in domains
    assert is_builtin_template_id("builtin:corporate") is True
    assert is_builtin_template_id("some-stored-id") is False


def test_resolve_state_defaults_without_fragment_returns_none() -> None:
    assert resolve_state_defaults("corporate", None) is None
    assert resolve_state_defaults("corporate", {}) is None
    assert resolve_state_defaults("corporate", {"initial_state": {}}) is None


def test_resolve_state_defaults_with_preset_snapshot() -> None:
    template = builtin_template("corporate")
    fragment = variables_configuration_fragment(template, None, None)
    defaults = resolve_state_defaults("corporate", fragment)
    pack = registry.get("corporate")
    assert defaults == {field.name: float(field.default) for field in pack.state_fields}

    # The mixin resolves identical initial states from pack defaults and
    # from the preset snapshot (actor-template overlay applies on top).
    mixin = SimulationDomainPacksMixin()
    from_pack = mixin._resolve_initial_state(pack, "ai_model_provider")
    from_preset = mixin._resolve_initial_state(pack, "ai_model_provider", state_defaults=defaults)
    assert from_preset == from_pack


def test_resolve_state_defaults_with_custom_template() -> None:
    template = builtin_template("corporate")
    customized = template.model_copy(deep=True)
    customized.state_fields[0] = customized.state_fields[0].model_copy(update={"default": 42.0})
    fragment = variables_configuration_fragment(customized, None, None)
    defaults = resolve_state_defaults("corporate", fragment)
    assert defaults is not None
    assert defaults[customized.state_fields[0].name] == 42.0
    pack = registry.get("corporate")
    for field in pack.state_fields[1:]:
        assert defaults[field.name] == float(field.default)


def test_resolve_policies_without_fragment_returns_builtins() -> None:
    policies = resolve_policies("corporate", None)
    assert policies == _STATE_POLICIES["corporate"]
    # A copy: mutating the result must not corrupt the module-level table.
    policies["cash"] = MetricPolicy("increase", 0.1, 0.05)
    assert _STATE_POLICIES["corporate"]["cash"].alert_threshold != 0.1


def test_resolve_policies_overlays_template_policies() -> None:
    template = builtin_template("corporate")
    customized = template.model_copy(deep=True)
    customized.policies["cash"] = MetricPolicySpec(
        preferred_direction="increase", alert_threshold=0.9, critical_threshold=0.8
    )
    customized.policies["brand_new_metric"] = MetricPolicySpec(
        preferred_direction="decrease", alert_threshold=0.2, critical_threshold=0.5
    )
    fragment = variables_configuration_fragment(customized, None, None)
    policies = resolve_policies("corporate", fragment)
    assert policies["cash"] == MetricPolicy("increase", 0.9, 0.8)
    assert policies["brand_new_metric"] == MetricPolicy("decrease", 0.2, 0.5)
    for metric, policy in _STATE_POLICIES["corporate"].items():
        if metric != "cash":
            assert policies[metric] == policy


def test_configuration_fragment_round_trips() -> None:
    template = builtin_template("corporate")
    bindings = VariableSet(name="case", variables=[], internal={"team": "20 people"})
    validation = VariableValidationResult(is_valid=True, variable_count=0)
    fragment = variables_configuration_fragment(template, bindings, validation)
    stored = fragment["variables"]
    assert stored["template_id"] == "builtin:corporate"
    assert VariableTemplate.model_validate(stored["template"]) == template
    assert VariableSet.model_validate(stored["bindings"]) == bindings
    assert VariableValidationResult.model_validate(stored["validation"]) == validation


def test_branching_functions_accept_custom_policies() -> None:
    # nrr is a tracked branch metric; built-in policy is increase/1.0/0.92
    # (span 0.08), so a +0.05 move scores 0.625 by default.
    baseline = {"nrr": 0.9}
    branch = {"nrr": 0.95}
    default_score = score_branch_delta("corporate", baseline, branch)
    assert default_score == pytest.approx(0.05 / 0.08)
    assert default_score == score_branch_delta(
        "corporate", baseline, branch, dict(_STATE_POLICIES["corporate"])
    )

    # A custom policy with a much wider span shrinks the normalized score.
    custom = dict(_STATE_POLICIES["corporate"])
    custom["nrr"] = MetricPolicy("increase", 0.95, 0.05)
    custom_score = score_branch_delta("corporate", baseline, branch, custom)
    assert custom_score == pytest.approx(0.05 / 0.9)

    assert metric_compare_score("corporate", "nrr", 0.9, 0.95) == pytest.approx(
        metric_compare_score("corporate", "nrr", 0.9, 0.95, dict(_STATE_POLICIES["corporate"]))
    )
    assert metric_compare_score("corporate", "nrr", 0.9, 0.95, custom) == pytest.approx(0.05 / 0.9)
