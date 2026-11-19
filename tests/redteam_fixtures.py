"""Shared fixtures for red-team tests: a scripted port serving recorded
LLM outputs. No live LLM call is ever made: the port serves recorded
fixture JSON in call order, keyed by template id.

The fixture port is labeled ``is_fixture = True`` so the orchestration
marks its findings ``red_team_fixture`` — recorded outputs are not
live LLM output, and the provenance must say so.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.skill_fixtures import ScriptedSkillPort

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "redteam_outputs"


def load_redteam_fixture(name: str) -> dict:
    with open(FIXTURE_DIR / f"{name}.json", encoding="utf-8") as handle:
        return json.load(handle)


class ScriptedRedTeamPort(ScriptedSkillPort):
    """Scripted LLM port for red-team tests; findings are labeled fixture."""

    is_fixture = True


def redteam_desay_script() -> dict[str, list[dict]]:
    return {"redteam.challenge": [load_redteam_fixture("redteam_desay_llm")]}


__all__ = [
    "ScriptedRedTeamPort",
    "load_redteam_fixture",
    "redteam_desay_script",
]
