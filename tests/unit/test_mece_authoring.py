"""MECE authoring-aid tests: proposals are validated by the Sprint 1
code validator, never trusted (Sprint 6, D9)."""

from __future__ import annotations

import pytest

from planagent.services.mece.models import DecompositionTree
from planagent.services.skills.contracts import SkillContractError
from planagent.services.skills.mece_authoring import (
    DEFAULT_DIMENSIONS,
    propose_decomposition,
)
from planagent.services.skills.orchestration import SkillLLMUnavailable
from tests.skill_fixtures import ScriptedSkillPort, load_fixture, mece_proposal_script


async def test_valid_proposal_passes_the_validator() -> None:
    port = ScriptedSkillPort(mece_proposal_script(valid=True))
    result = await propose_decomposition(port, topic="Should we launch?")
    port.assert_exhausted()
    assert result.validation.is_mece is True
    assert result.validation.issues == []
    assert result.proposal.topic == "Should we launch the AI customer-service line?"
    assert result.stage.template_id == "mece.propose_tree"
    assert result.stage.template_version == "2"
    assert result.stage.contract_version == "2"


async def test_invalid_proposal_fails_the_validator() -> None:
    port = ScriptedSkillPort(mece_proposal_script(valid=False))
    result = await propose_decomposition(port, topic="Should we launch?")
    assert result.validation.is_mece is False
    assert [issue.kind for issue in result.validation.issues] == ["overlap"]
    assert result.validation.issues[0].tags == ["capability"]


async def test_malformed_tree_is_a_contract_error_not_a_proposal() -> None:
    port = ScriptedSkillPort({"mece.propose_tree": [{"topic": "T"}]})
    with pytest.raises(SkillContractError):
        await propose_decomposition(port, topic="T")


async def test_unavailable_llm_raises_structured_error() -> None:
    port = ScriptedSkillPort({}, available=False)
    with pytest.raises(SkillLLMUnavailable):
        await propose_decomposition(port, topic="T")


async def test_existing_tree_and_dimensions_reach_the_prompt() -> None:
    port = ScriptedSkillPort(mece_proposal_script(valid=True))
    existing = DecompositionTree.model_validate(load_fixture("mece_propose_valid"))
    await propose_decomposition(
        port,
        topic="Revise this",
        context_lines=["cash is tight"],
        suggested_dimensions=["Custom dimension"],
        existing_tree=existing,
    )
    user_content = port.calls[0]["user_content"]
    assert "Custom dimension" in user_content
    assert "cash is tight" in user_content
    assert "Launch decision" in user_content


async def test_default_dimensions_are_used_when_none_given() -> None:
    port = ScriptedSkillPort(mece_proposal_script(valid=True))
    await propose_decomposition(port, topic="T")
    user_content = port.calls[0]["user_content"]
    for dimension in DEFAULT_DIMENSIONS:
        assert dimension in user_content
