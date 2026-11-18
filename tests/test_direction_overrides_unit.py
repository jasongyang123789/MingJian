"""Unit tests for option B: directions as variable overrides.

Covers the pure override helpers (grounding in
``build_override_set``, the merged-set gate in
``validate_merged_overrides``, deterministic assumption lines)
and the request-model validation discipline (stripping, dedup,
finite-value enforcement, unique names, direction-count cap).
No database, no HTTP: the service and endpoint behavior lives
in tests/test_direction_overrides_api.py.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from planagent.services.narratives.models import (
    DirectionError,
    DirectionOverrideRequest,
    DirectionOverrideSpec,
)
from planagent.services.narratives.overrides import (
    assumption_line,
    build_override_set,
    validate_merged_overrides,
)
from planagent.services.variables.models import (
    DistributionType,
    VariableDefinition,
    VariableDistribution,
    VariableSet,
)


def _anchor_set() -> VariableSet:
    return VariableSet(
        name="case",
        variables=[
            VariableDefinition(
                id="cash",
                unit="k",
                distribution=VariableDistribution(
                    type=DistributionType.TRIANGULAR, min=60, mode=100, max=140
                ),
                evidence_ref="estimate: founder judgment",
                description="Cash on hand",
                scope_tags=["demand"],
            ),
            VariableDefinition(
                id="burn",
                unit="k",
                distribution=VariableDistribution(type=DistributionType.FIXED, value=20),
                evidence_ref="estimate: founder judgment",
                scope_tags=["cost"],
            ),
        ],
        internal={"team": "20 people"},
    )


# ---------------------------------------------------------------------------
# build_override_set
# ---------------------------------------------------------------------------


def test_build_override_set_replaces_distribution_and_keeps_metadata() -> None:
    override = build_override_set(_anchor_set(), {"cash": 80})
    assert len(override.variables) == 1
    variable = override.variables[0]
    assert variable.id == "cash"
    assert variable.unit == "k"
    assert variable.distribution.type is DistributionType.FIXED
    assert variable.distribution.value == 80
    assert variable.evidence_ref == "estimate: founder judgment"
    assert variable.description == "Cash on hand"
    assert variable.scope_tags == ["demand"]


def test_build_override_set_refuses_unknown_variable() -> None:
    with pytest.raises(DirectionError) as caught:
        build_override_set(_anchor_set(), {"nope": 1})
    assert caught.value.code == "direction_override_unknown_variable"
    assert "nope" in str(caught.value)
    assert "burn" in str(caught.value) and "cash" in str(caught.value)


def test_build_override_set_allows_out_of_range_value() -> None:
    # Setting a value outside the sampled range is the point of a
    # what-if: no range check against the original distribution.
    override = build_override_set(_anchor_set(), {"cash": 999})
    assert override.variables[0].distribution.value == 999


# ---------------------------------------------------------------------------
# validate_merged_overrides
# ---------------------------------------------------------------------------


def test_validate_merged_overrides_merges_override_over_anchor() -> None:
    override = build_override_set(_anchor_set(), {"cash": 80})
    merged = validate_merged_overrides(_anchor_set(), override, ["demand", "cost"])
    by_id = {variable.id: variable for variable in merged.variables}
    assert by_id["cash"].distribution.type is DistributionType.FIXED
    assert by_id["cash"].distribution.value == 80
    assert by_id["burn"].distribution.value == 20
    assert merged.internal == {"team": "20 people"}


def test_validate_merged_overrides_refuses_scope_mismatch() -> None:
    # The merged set must pass the same gate as run creation,
    # including the decomposition-root scope cross-check.
    override = build_override_set(_anchor_set(), {"cash": 80})
    with pytest.raises(DirectionError) as caught:
        validate_merged_overrides(_anchor_set(), override, ["demand"])
    assert caught.value.code == "direction_override_invalid"
    assert "burn" in str(caught.value)


def test_validate_merged_overrides_without_tree_skips_scope_check() -> None:
    override = build_override_set(_anchor_set(), {"cash": 80})
    merged = validate_merged_overrides(_anchor_set(), override, None)
    assert len(merged.variables) == 2


# ---------------------------------------------------------------------------
# assumption_line
# ---------------------------------------------------------------------------


def test_assumption_line_is_deterministic_and_sorted() -> None:
    first = assumption_line("Boost", {"burn": 10, "cash": 80})
    second = assumption_line("Boost", {"cash": 80, "burn": 10})
    assert first == second
    assert first == "Direction 'Boost': override burn=10, cash=80."


# ---------------------------------------------------------------------------
# Request-model validation
# ---------------------------------------------------------------------------


def test_override_spec_strips_name_branches_and_dedupes() -> None:
    spec = DirectionOverrideSpec.model_validate(
        {
            "name": "  Boost  ",
            "overrides": {" cash ": 80},
            "mece_branches": [" Demand ", "Demand", "Cost"],
        }
    )
    assert spec.name == "Boost"
    assert spec.overrides == {"cash": 80}
    assert spec.mece_branches == ["Demand", "Cost"]
    assert spec.arm == "baseline"
    assert spec.fork_step is None


def test_override_spec_rejects_string_value() -> None:
    with pytest.raises(ValidationError):
        DirectionOverrideSpec.model_validate({"name": "Boost", "overrides": {"cash": "80"}})


def test_override_spec_rejects_bool_nan_and_inf_values() -> None:
    for bad in (True, float("nan"), float("inf"), float("-inf"), None):
        with pytest.raises(ValidationError):
            DirectionOverrideSpec.model_validate({"name": "Boost", "overrides": {"cash": bad}})


def test_override_spec_accepts_int_value_as_float() -> None:
    spec = DirectionOverrideSpec.model_validate({"name": "Boost", "overrides": {"cash": 80}})
    assert spec.overrides == {"cash": 80.0}


def test_override_spec_rejects_empty_overrides() -> None:
    with pytest.raises(ValidationError):
        DirectionOverrideSpec.model_validate({"name": "Boost", "overrides": {}})


def test_override_spec_rejects_empty_key_and_stripped_collision() -> None:
    with pytest.raises(ValidationError):
        DirectionOverrideSpec.model_validate({"name": "Boost", "overrides": {"  ": 1}})
    with pytest.raises(ValidationError):
        DirectionOverrideSpec.model_validate(
            {"name": "Boost", "overrides": {"cash": 1, " cash ": 2}}
        )


def test_override_spec_rejects_blank_branch() -> None:
    with pytest.raises(ValidationError):
        DirectionOverrideSpec.model_validate(
            {"name": "Boost", "overrides": {"cash": 80}, "mece_branches": [" "]}
        )


def test_override_spec_rejects_fork_step_below_one() -> None:
    with pytest.raises(ValidationError):
        DirectionOverrideSpec.model_validate(
            {"name": "Boost", "overrides": {"cash": 80}, "fork_step": 0}
        )


def test_override_spec_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        DirectionOverrideSpec.model_validate(
            {"name": "Boost", "overrides": {"cash": 80}, "surprise": True}
        )


def test_override_request_rejects_duplicate_names_after_stripping() -> None:
    with pytest.raises(ValidationError):
        DirectionOverrideRequest.model_validate(
            {
                "directions": [
                    {"name": "Boost", "overrides": {"cash": 80}},
                    {"name": "  Boost ", "overrides": {"cash": 90}},
                ]
            }
        )


def test_override_request_rejects_empty_and_too_many_directions() -> None:
    with pytest.raises(ValidationError):
        DirectionOverrideRequest.model_validate({"directions": []})
    with pytest.raises(ValidationError):
        DirectionOverrideRequest.model_validate(
            {
                "directions": [
                    {"name": f"Direction {index}", "overrides": {"cash": 80}} for index in range(5)
                ]
            }
        )


def test_override_request_accepts_four_directions() -> None:
    request = DirectionOverrideRequest.model_validate(
        {
            "directions": [
                {"name": f"Direction {index}", "overrides": {"cash": 80}} for index in range(4)
            ]
        }
    )
    assert len(request.directions) == 4
