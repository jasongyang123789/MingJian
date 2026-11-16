"""Template library tests: registry integrity, provenance, and
byte-stable deterministic rendering (Sprint 6, D9)."""

from __future__ import annotations

import pytest

from planagent.services.skills.templates import (
    TEMPLATES,
    get_template,
    list_templates,
    render_template,
    validate_registry,
)

EXPECTED_TEMPLATE_IDS = [
    "mckinsey.intake_classify",
    "mckinsey.diagnose",
    "mckinsey.market_map",
    "mckinsey.option_generate",
    "mckinsey.filter_shortlist",
    "mckinsey.synthesize",
    "mckinsey.verify_assumptions",
    "mckinsey.verify_wargame",
    "mckinsey.verify_execution",
    "mckinsey.tournament_judge",
    "advisory.crit_intake",
    "advisory.lens_position",
    "advisory.lens_revision",
    "advisory.forced_debate",
    "advisory.chair_synthesis",
    "gambit.premortem",
    "mece.propose_tree",
]


def test_registry_contains_exactly_the_expected_templates() -> None:
    assert sorted(TEMPLATES) == sorted(EXPECTED_TEMPLATE_IDS)
    assert [template.id for template in list_templates()] == EXPECTED_TEMPLATE_IDS


def test_every_template_carries_provenance_and_version() -> None:
    for template in list_templates():
        assert template.version == "2"
        assert template.title
        assert template.source_repo
        assert template.source_file
        assert template.license_note
        assert template.max_tokens > 0
        assert template.system_prompt.strip()
        assert template.user_template.strip()


def test_registry_slot_validation_passes() -> None:
    validate_registry()


def test_flingjie_template_records_the_missing_license() -> None:
    template = get_template("mece.propose_tree")
    assert "No license" in template.license_note
    assert "original" in template.license_note


def test_mit_sources_record_mit() -> None:
    for template_id in ("mckinsey.intake_classify", "advisory.crit_intake", "gambit.premortem"):
        assert get_template(template_id).license_note.startswith("MIT")


def test_unknown_template_raises_with_known_ids() -> None:
    with pytest.raises(ValueError, match="Unknown skill template"):
        get_template("no.such.template")


@pytest.mark.parametrize("template_id", EXPECTED_TEMPLATE_IDS)
def test_rendering_is_byte_stable_and_includes_slot_values(template_id: str) -> None:
    template = get_template(template_id)
    inputs = {slot: f"<{slot}>" for slot in template.slots}
    first = render_template(template, inputs)
    second = render_template(template, inputs)
    assert first == second
    system_prompt, user_content = first
    for slot, marker in inputs.items():
        assert marker in system_prompt or marker in user_content, slot
    # No placeholder survives rendering.
    assert "{output_language}" not in user_content


def test_rendering_requires_every_slot_and_names_the_missing() -> None:
    template = get_template("mckinsey.intake_classify")
    with pytest.raises(ValueError, match="topic.*decision_question|decision_question.*topic"):
        render_template(template, {"context": "c", "output_language": "English"})


def test_rendering_ignores_extra_inputs() -> None:
    template = get_template("mckinsey.diagnose")
    inputs = {slot: "x" for slot in template.slots}
    inputs["not_a_slot"] = "ignored"
    system_prompt, user_content = render_template(template, inputs)
    assert system_prompt and user_content


def test_templates_instruct_json_only_and_no_new_numbers() -> None:
    for template in list_templates():
        assert "Return valid JSON only" in template.user_template
        assert "Do not compute new numbers" in template.user_template
