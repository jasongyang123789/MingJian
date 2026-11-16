"""Contract coercion tests (Sprint 15, contracts v2).

Live runs on 2026-11-16 showed models returning valid JSON in
structured shapes the v1 contracts forbade. V2 normalizes those
shapes to the canonical ones deterministically, before validation.
These tests pin each coercion rule and each deliberate boundary:
nothing is fabricated, and shapes outside the rules still fail.
"""

from __future__ import annotations

import pytest

from planagent.services.skills.contracts import SkillContractError, parse_stage_output
from tests.skill_fixtures import load_fixture


def _crit_payload(**overrides: object) -> dict:
    payload: dict = {
        "decision": "D",
        "options": ["A"],
        "context": "C",
        "evidence": "E",
        "economics": "Ec",
        "success": "S",
        "current_preference": "P",
        "reversibility": "R",
    }
    payload.update(overrides)
    return payload


def test_object_for_string_field_renders_flat() -> None:
    parsed = parse_stage_output(
        "advisory.crit_intake",
        _crit_payload(evidence={"known": "a", "unknown": "b"}),
    )
    assert parsed.model_dump(mode="json")["evidence"] == "known: a; unknown: b"


def test_list_for_string_field_joins_items() -> None:
    parsed = parse_stage_output("advisory.crit_intake", _crit_payload(evidence=["a", "b"]))
    assert parsed.model_dump(mode="json")["evidence"] == "a; b"


def test_nested_object_renders_recursively_in_insertion_order() -> None:
    parsed = parse_stage_output(
        "advisory.crit_intake",
        _crit_payload(evidence={"a": {"b": "c"}, "d": ["e", "f"]}),
    )
    assert parsed.model_dump(mode="json")["evidence"] == "a: b: c; d: e; f"


def test_scalar_values_render_as_json_literals() -> None:
    parsed = parse_stage_output(
        "advisory.crit_intake",
        _crit_payload(evidence={"flag": True, "n": 3, "nil": None}),
    )
    assert parsed.model_dump(mode="json")["evidence"] == "flag: true; n: 3; nil: null"


def test_dict_for_str_list_field_renders_one_string_per_key() -> None:
    parsed = parse_stage_output("mckinsey.diagnose", {"findings": {"a": "x", "b": "y"}})
    assert parsed.model_dump(mode="json")["findings"] == ["a: x", "b: y"]


def test_list_of_objects_for_str_list_renders_each_item() -> None:
    parsed = parse_stage_output(
        "mckinsey.diagnose", {"findings": [{"k": "v"}, "plain", ["x", "y"]]}
    )
    assert parsed.model_dump(mode="json")["findings"] == ["k: v", "plain", "x; y"]


def test_options_name_items_reduce_to_names() -> None:
    parsed = parse_stage_output(
        "advisory.crit_intake",
        _crit_payload(options=[{"name": "A", "description": "dropped"}, "B"]),
    )
    assert parsed.model_dump(mode="json")["options"] == ["A", "B"]


def test_options_dict_without_name_renders_flat() -> None:
    parsed = parse_stage_output("advisory.crit_intake", _crit_payload(options=[{"label": "X"}]))
    assert parsed.model_dump(mode="json")["options"] == ["label: X"]


def test_nested_model_fields_coerce_too() -> None:
    parsed = parse_stage_output(
        "mckinsey.option_generate",
        {
            "options": [
                {
                    "name": "A",
                    "description": {"a": "b"},
                    "upside": "u",
                    "trade_off": "t",
                    "what_must_be_true": ["w"],
                }
            ]
        },
    )
    option = parsed.model_dump(mode="json")["options"][0]
    assert option["description"] == "a: b"


@pytest.mark.parametrize(
    "fixture_name,template_id",
    [
        ("intake_classify", "mckinsey.intake_classify"),
        ("diagnose", "mckinsey.diagnose"),
        ("market_map", "mckinsey.market_map"),
        ("filter_shortlist", "mckinsey.filter_shortlist"),
        ("synthesize", "mckinsey.synthesize"),
        ("verify_assumptions", "mckinsey.verify_assumptions"),
        ("crit_intake", "advisory.crit_intake"),
        ("lens_position_product_clarity", "advisory.lens_position"),
        ("forced_debate", "advisory.forced_debate"),
        ("chair_synthesis", "advisory.chair_synthesis"),
        ("premortem", "gambit.premortem"),
    ],
)
def test_conforming_input_validates_byte_identical(fixture_name: str, template_id: str) -> None:
    raw = load_fixture(fixture_name)
    assert parse_stage_output(template_id, raw).model_dump(mode="json") == raw


def test_empty_dict_for_required_string_still_fails() -> None:
    with pytest.raises(SkillContractError):
        parse_stage_output("advisory.crit_intake", _crit_payload(evidence={}))


def test_bare_string_for_str_list_still_fails() -> None:
    payload = load_fixture("intake_classify")
    payload["wave_plan"] = "Wave A: diagnose"
    with pytest.raises(SkillContractError):
        parse_stage_output("mckinsey.intake_classify", payload)


def test_dict_scores_are_not_coerced() -> None:
    payload = load_fixture("lens_position_product_clarity")
    payload["option_scores"] = [{"option": "Phased rollout", "score": 7}]
    with pytest.raises(SkillContractError):
        parse_stage_output("advisory.lens_position", payload)


def test_literal_fields_are_not_coerced() -> None:
    payload = load_fixture("intake_classify")
    payload["stakes"] = {"value": "standard"}
    with pytest.raises(SkillContractError):
        parse_stage_output("mckinsey.intake_classify", payload)


def test_empty_frameworks_list_validates() -> None:
    payload = load_fixture("intake_classify")
    payload["frameworks"] = []
    parsed = parse_stage_output("mckinsey.intake_classify", payload)
    assert parsed.model_dump(mode="json")["frameworks"] == []


def test_empty_wave_plan_still_fails() -> None:
    payload = load_fixture("intake_classify")
    payload["wave_plan"] = []
    with pytest.raises(SkillContractError):
        parse_stage_output("mckinsey.intake_classify", payload)
