"""Unit tests for the red-team template registry (Sprint 6 pattern)."""

from __future__ import annotations

import pytest

from planagent.services.redteam.templates import (
    get_template,
    list_templates,
    render_template,
)


def test_registry_has_exactly_one_template() -> None:
    templates = list_templates()
    assert [t.id for t in templates] == ["redteam.challenge"]
    assert templates[0].version == "1"


def test_template_carries_provenance() -> None:
    template = get_template("redteam.challenge")
    assert "desay-2020" in template.source_note
    assert template.max_tokens == 8000


def test_rendering_is_byte_stable() -> None:
    template = get_template("redteam.challenge")
    inputs = {
        "context": "Decision question: X",
        "completeness_block": "No gaps found.",
        "output_language": "Chinese",
    }
    first = render_template(template, inputs)
    second = render_template(template, inputs)
    assert first == second
    assert "Decision question: X" in first[1]
    assert "No gaps found." in first[1]


def test_rendering_names_missing_slots() -> None:
    template = get_template("redteam.challenge")
    with pytest.raises(ValueError, match="completeness_block"):
        render_template(template, {"context": "x", "output_language": "Chinese"})


def test_rendering_rejects_extra_slots() -> None:
    template = get_template("redteam.challenge")
    with pytest.raises(ValueError, match="unexpected slots"):
        render_template(
            template,
            {
                "context": "x",
                "completeness_block": "y",
                "output_language": "Chinese",
                "surprise": "z",
            },
        )


def test_template_forbids_new_numbers() -> None:
    template = get_template("redteam.challenge")
    assert "Do not compute new numbers" in template.user_template
    assert "Return valid JSON only" in template.user_template


def test_unknown_template_raises() -> None:
    with pytest.raises(KeyError):
        get_template("redteam.nope")
