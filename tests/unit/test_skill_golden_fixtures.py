"""Golden-fixture tests (Sprint 15): the exact model outputs captured
on the live 2026-11-16 kakouai run must validate through the fixed
contracts and normalize to the pinned canonical values.

The ``live_*_kakouai.json`` fixtures are byte-exact copies of the
captured ``content`` strings (llm_calls.jsonl seq 8/9 in the run
directory; verified byte-identical at copy time, no key material).
The ``*.normalized.json`` fixtures are the expected canonical outputs,
verified by inspection against the Sprint 15 rendering rules when
created. The raw outputs failed the v1 contracts; they must pass v2.
"""

from __future__ import annotations

import json
from typing import Any

from planagent.services.skills.contracts import parse_stage_output
from tests.skill_fixtures import load_fixture


def _leaf_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        leaves: list[str] = []
        for item in value.values():
            leaves.extend(_leaf_strings(item))
        return leaves
    if isinstance(value, list):
        leaves = []
        for item in value:
            leaves.extend(_leaf_strings(item))
        return leaves
    return []


def test_live_intake_output_validates_and_normalizes() -> None:
    raw = load_fixture("live_intake_classify_kakouai")
    parsed = parse_stage_output("mckinsey.intake_classify", raw)
    dumped = parsed.model_dump(mode="json")
    assert dumped == load_fixture("live_intake_classify_kakouai.normalized")
    assert dumped["frameworks"] == []
    assert dumped["stakes"] == "standard"
    assert len(dumped["wave_plan"]) == 3
    assert dumped["wave_plan"][0].startswith("wave_A: lead: Engagement lead")
    assert dumped["wave_plan"][1].startswith("wave_B: option_mandates:")
    assert dumped["wave_plan"][2].startswith("verifier_panel: Independent strategy reviewer")
    assert len(dumped["constraints"]) == 8
    assert len(dumped["open_questions"]) == 9


def test_live_crit_output_validates_and_normalizes() -> None:
    raw = load_fixture("live_crit_intake_kakouai")
    parsed = parse_stage_output("advisory.crit_intake", raw)
    dumped = parsed.model_dump(mode="json")
    assert dumped == load_fixture("live_crit_intake_kakouai.normalized")
    assert dumped["options"] == [
        "Phased rollout",
        "Full launch",
        "Partner-led",
        "Defer or do not launch",
    ]
    assert "known_facts:" in dumped["evidence"]
    assert "important_unknowns:" in dumped["evidence"]
    assert "q3-marketing-report" in dumped["evidence"]
    assert "measurable_outcome:" in dumped["success"]
    assert "can_be_tested_cheaply:" in dumped["reversibility"]
    assert "lasting_downside:" in dumped["reversibility"]
    assert len(dumped["questions"]) == 3


def test_evidenced_stage1_errors_no_longer_occur_for_golden_inputs() -> None:
    """The v1 failures were: intake ``frameworks: List should have at
    least 1 item`` + ``wave_plan: Input should be a valid list``, and
    crit ``Input should be a valid string`` on 10 fields. Both golden
    payloads now parse without raising SkillContractError."""
    parse_stage_output("mckinsey.intake_classify", load_fixture("live_intake_classify_kakouai"))
    parse_stage_output("advisory.crit_intake", load_fixture("live_crit_intake_kakouai"))


def test_intake_normalization_drops_no_information() -> None:
    raw = load_fixture("live_intake_classify_kakouai")
    dumped = parse_stage_output("mckinsey.intake_classify", raw).model_dump(mode="json")
    rendered = json.dumps(dumped, ensure_ascii=False)
    for leaf in _leaf_strings(raw):
        assert leaf in rendered


def test_crit_normalization_drops_only_option_descriptions() -> None:
    raw = load_fixture("live_crit_intake_kakouai")
    dumped = parse_stage_output("advisory.crit_intake", raw).model_dump(mode="json")
    rendered = json.dumps(dumped, ensure_ascii=False)
    descriptions = [option["description"] for option in raw["options"]]
    assert len(descriptions) == 4
    for description in descriptions:
        assert description not in rendered
    for leaf in _leaf_strings(raw):
        if leaf in descriptions:
            continue
        assert leaf in rendered
