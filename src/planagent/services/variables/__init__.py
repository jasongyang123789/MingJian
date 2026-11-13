"""Variable tables (Sprint 2, PRD deltas D2/D3).

Only the dependency-free modules are exported here, so ``domain/api.py`` can
import the models without pulling in the pack registry or the database layer.
Import ``presets`` and ``store`` from their submodules directly.
"""

from .models import (
    MAX_VARIABLES,
    DistributionType,
    MetricPolicySpec,
    TemplateStateField,
    VariableCheckRecord,
    VariableDefinition,
    VariableDistribution,
    VariableRunRead,
    VariableSet,
    VariableTemplate,
    VariableTemplateCreate,
    VariableTemplateRead,
    VariableTemplateUpdate,
    VariableValidationIssue,
    VariableValidationResult,
)
from .validator import (
    VariableTemplateError,
    VariableValidationError,
    merge_variable_sets,
    validate_or_raise,
    validate_scope_bindings,
    validate_template,
    validate_variable_set,
)

__all__ = [
    "MAX_VARIABLES",
    "DistributionType",
    "MetricPolicySpec",
    "TemplateStateField",
    "VariableCheckRecord",
    "VariableDefinition",
    "VariableDistribution",
    "VariableRunRead",
    "VariableSet",
    "VariableTemplate",
    "VariableTemplateCreate",
    "VariableTemplateError",
    "VariableTemplateRead",
    "VariableTemplateUpdate",
    "VariableValidationError",
    "VariableValidationIssue",
    "VariableValidationResult",
    "merge_variable_sets",
    "validate_or_raise",
    "validate_scope_bindings",
    "validate_template",
    "validate_variable_set",
]
