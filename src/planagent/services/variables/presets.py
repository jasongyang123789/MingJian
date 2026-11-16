"""Built-in variable templates and run-configuration resolution (Sprint 2).

The hardcoded domain-pack state defaults and ``_STATE_POLICIES`` thresholds
are generalized into templates. The existing corporate/military packs become
built-in presets: ``builtin_template`` synthesizes them from the pack code at
read time, so identical defaults hold by construction — a preset is never
stored, edited, or allowed to drift from the pack.

The helpers here are pure functions over a run's ``configuration`` JSON, so
both the inline executor and queued workers resolve the same effective state
defaults and policies from the snapshot stored at run creation.
"""

from __future__ import annotations

from typing import Any

from planagent.services.simulation_branching import _STATE_POLICIES, MetricPolicy
from planagent.simulation.domain_packs import registry

from .models import (
    FormulaDefinition,
    MetricPolicySpec,
    TemplateStateField,
    VariableDefinition,
    VariableSet,
    VariableTemplate,
    VariableValidationResult,
)
from .validator import validate_template

BUILTIN_TEMPLATE_ID_PREFIX = "builtin:"

CONFIGURATION_KEY = "variables"


def builtin_template_id(domain_id: str) -> str:
    return f"{BUILTIN_TEMPLATE_ID_PREFIX}{domain_id}"


def is_builtin_template_id(template_id: str) -> bool:
    return template_id.startswith(BUILTIN_TEMPLATE_ID_PREFIX)


def known_domain_ids() -> list[str]:
    """Domain ids with a registered pack, in registration order."""

    return [pack.domain_id for pack in registry.all()]


def builtin_template(domain_id: str) -> VariableTemplate:
    """Synthesize the built-in template for a domain from its pack code.

    Variables, formulas, and assumption data come from the pack's
    template-spec methods (empty by default, so the corporate/military
    presets synthesize exactly as before). The synthesized template is
    validated before it is returned: a built-in that fails validation
    is a code defect, and failing loudly here beats silently serving a
    broken preset to every run that attaches it.
    """

    try:
        pack = registry.get(domain_id)
    except (KeyError, ModuleNotFoundError) as exc:
        # registry.get raises KeyError for a missing pack, but its
        # on-demand import raises ModuleNotFoundError when the domain's
        # package does not exist at all (find_spec on a missing parent).
        raise ValueError(f"Unknown domain_id: {domain_id}") from exc
    template = VariableTemplate(
        id=builtin_template_id(domain_id),
        name=f"Built-in {domain_id} preset",
        domain_id=domain_id,
        description=(
            f"Built-in preset derived from the {domain_id} domain pack. "
            "Read-only; create a stored template to customize it."
        ),
        state_fields=[
            TemplateStateField(
                name=field.name,
                description=field.description,
                default=float(field.default),
            )
            for field in pack.state_fields
        ],
        policies={
            metric: MetricPolicySpec(
                preferred_direction=policy.preferred_direction,
                alert_threshold=policy.alert_threshold,
                critical_threshold=policy.critical_threshold,
            )
            for metric, policy in _STATE_POLICIES.get(domain_id, {}).items()
        },
        variables=[VariableDefinition.model_validate(raw) for raw in pack.template_variables()],
        formulas=[FormulaDefinition.model_validate(raw) for raw in pack.template_formulas()],
        internal={},
        assumption_data=dict(pack.template_assumption_data()),
        is_builtin=True,
    )
    result = validate_template(template)
    if not result.is_valid:
        details = "; ".join(
            f"{issue.kind}({issue.variable}): {issue.message}" for issue in result.issues
        )
        raise RuntimeError(f"Built-in template for domain {domain_id!r} is invalid: {details}")
    return template


def variables_configuration_fragment(
    template: VariableTemplate | None,
    bindings: VariableSet | None,
    validation: VariableValidationResult | None,
) -> dict[str, Any]:
    """Build the ``variables`` fragment stored in a run's configuration.

    The template is snapshotted at creation time, so later edits to a stored
    template never rewrite a run's audit trail.
    """

    return {
        CONFIGURATION_KEY: {
            "template_id": template.id if template is not None else None,
            "template": template.model_dump(mode="json") if template is not None else None,
            "bindings": bindings.model_dump(mode="json") if bindings is not None else None,
            "validation": validation.model_dump(mode="json") if validation is not None else None,
        }
    }


def _stored_template(configuration: dict | None) -> VariableTemplate | None:
    if not isinstance(configuration, dict):
        return None
    fragment = configuration.get(CONFIGURATION_KEY)
    if not isinstance(fragment, dict):
        return None
    template = fragment.get("template")
    if not isinstance(template, dict):
        return None
    return VariableTemplate.model_validate(template)


def resolve_state_defaults(domain_id: str, configuration: dict | None) -> dict[str, float] | None:
    """Effective state defaults for a run, or None for pack defaults.

    Returns None when the run carries no template snapshot, so callers fall
    back to the pack's defaults exactly as before Sprint 2.
    """

    template = _stored_template(configuration)
    if template is None:
        return None
    return {field.name: float(field.default) for field in template.state_fields}


def resolve_policies(domain_id: str, configuration: dict | None) -> dict[str, MetricPolicy]:
    """Effective metric policies: built-ins overlaid with the template's."""

    policies = dict(_STATE_POLICIES.get(domain_id, {}))
    template = _stored_template(configuration)
    if template is not None:
        for metric, spec in template.policies.items():
            policies[metric] = MetricPolicy(
                preferred_direction=spec.preferred_direction,
                alert_threshold=spec.alert_threshold,
                critical_threshold=spec.critical_threshold,
            )
    return policies


def resolve_assumption_data(configuration: dict | None) -> dict[str, Any]:
    """Effective assumption data for a run, or {} when none is attached.

    The run's stored BINDINGS win (they carry the merged template +
    inline override); a template-only run (no bindings stored) falls
    back to the template snapshot. Both are pinned in the run's
    configuration, so the resolution is replay-stable.
    """

    if isinstance(configuration, dict):
        fragment = configuration.get(CONFIGURATION_KEY)
        if isinstance(fragment, dict):
            bindings = fragment.get("bindings")
            if isinstance(bindings, dict):
                data = bindings.get("assumption_data")
                if isinstance(data, dict):
                    return dict(data)
    template = _stored_template(configuration)
    if template is not None:
        return dict(template.assumption_data)
    return {}
