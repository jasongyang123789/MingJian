"""Prompt-shape tests (Sprint 15, templates v2).

The v1 prompts invited JSON shapes the contracts forbid, and the
intake prompt referenced a framework index it never supplied. These
tests pin the v2 wording: exact shape specifications per key, the
rendered framework index, and the preserved JSON-only / no-new-numbers
rules on every template.
"""

from __future__ import annotations

import pytest

from planagent.services.skills.templates import (
    FRAMEWORK_INDEX,
    TEMPLATES,
    get_template,
    render_template,
)


def _rendered_user_content(template_id: str) -> str:
    template = get_template(template_id)
    inputs = {slot: slot.upper() for slot in template.slots}
    _, user_content = render_template(template, inputs)
    return user_content


def test_framework_index_has_21_unique_entries() -> None:
    assert len(FRAMEWORK_INDEX) == 21
    names = [name for name, _, _ in FRAMEWORK_INDEX]
    assert len(set(names)) == 21
    assert all(group and when for _, group, when in FRAMEWORK_INDEX)


def test_intake_prompt_renders_the_framework_index() -> None:
    user_content = _rendered_user_content("mckinsey.intake_classify")
    assert "copy framework names EXACTLY from this list" in user_content
    assert "do not invent framework names" in user_content
    for name, _, _ in FRAMEWORK_INDEX:
        assert name in user_content


def test_intake_prompt_specifies_list_shapes() -> None:
    user_content = _rendered_user_content("mckinsey.intake_classify")
    assert (
        "frameworks (a list of strings: framework names copied exactly "
        "from the index above" in user_content
    )
    assert "wave_plan (a list of strings, one string per assignment" in user_content
    assert "write each assignment as one plain string, never a nested object" in user_content


def test_market_map_prompt_specifies_competitor_strings() -> None:
    user_content = _rendered_user_content("mckinsey.market_map")
    assert (
        "competitors (a list of strings; each string names one competitor "
        "and its likely move in a single line" in user_content
    )


def test_filter_shortlist_prompt_specifies_scores_and_dropped_shapes() -> None:
    user_content = _rendered_user_content("mckinsey.filter_shortlist")
    assert "scores (an object mapping each criterion name to one 0-10 number)" in user_content
    assert "dropped (a list of objects, each with name" in user_content


def test_synthesize_prompt_specifies_alternatives_strings() -> None:
    user_content = _rendered_user_content("mckinsey.synthesize")
    assert (
        "alternatives_considered (a list of strings; each string names one "
        "shortlist option not recommended" in user_content
    )


def test_assumption_audit_prompt_specifies_integer_importance() -> None:
    user_content = _rendered_user_content("mckinsey.verify_assumptions")
    assert "importance (an integer from 1 to 5)" in user_content


def test_tournament_prompt_specifies_criteria_scores_shape() -> None:
    user_content = _rendered_user_content("mckinsey.tournament_judge")
    assert (
        "criteria_scores (an object mapping each criterion name to one 0-10 number" in user_content
    )


def test_crit_intake_prompt_demands_flat_strings() -> None:
    user_content = _rendered_user_content("advisory.crit_intake")
    assert "options (a list of strings: plain option names only" in user_content
    assert "evidence (a single flat string covering known facts" in user_content
    assert "success (a single flat string stating the measurable outcome" in user_content
    assert user_content.count("never a nested object") == 6


def test_lens_prompts_specify_score_map_shapes() -> None:
    position = _rendered_user_content("advisory.lens_position")
    assert "option_scores (an object mapping each option name to one 0-10 number)" in position
    revision = _rendered_user_content("advisory.lens_revision")
    assert "revised_scores (an object mapping each option name to one 0-10 number)" in revision


def test_chair_prompt_specifies_lens_weights_shape() -> None:
    user_content = _rendered_user_content("advisory.chair_synthesis")
    assert (
        "lens_weights (an object mapping each lens name to a relevance integer "
        "from 1 to 3)" in user_content
    )


@pytest.mark.parametrize("template_id", sorted(TEMPLATES))
def test_every_template_keeps_json_only_and_no_new_numbers(template_id: str) -> None:
    user_content = _rendered_user_content(template_id)
    assert "Return valid JSON only, matching the shape described above." in user_content
    assert "Do not compute new numbers" in user_content
    assert "do not invent, adjust, or recompute them" in user_content


def test_all_templates_are_version_2() -> None:
    assert len(TEMPLATES) == 17
    assert {template.version for template in TEMPLATES.values()} == {"2"}
