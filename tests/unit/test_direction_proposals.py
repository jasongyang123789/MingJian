"""Unit tests for LLM-proposed decision directions (option C).

Covers the proposal contract (shape, extra-key refusal, uniqueness,
branch/variable normalization), the prompt builder (grounding
surface, determinism), and the scripted-port proposal pass
(success, unavailable, contract failure, truncation, empty
response). No live LLM call is ever made.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from planagent.services.narratives.proposals import (
    PROPOSAL_MAX_TOKENS,
    PROPOSAL_SYSTEM_PROMPT,
    PROPOSAL_TEMPLATE_ID,
    DirectionGate,
    DirectionProposal,
    DirectionProposals,
    ProposalContext,
    ProposalFamilyRun,
    ProposalVariable,
    build_proposal_user_content,
    propose_directions,
)
from planagent.services.skills.contracts import SkillContractError, SkillTruncatedError
from planagent.services.skills.orchestration import SkillLLMUnavailable
from tests.skill_fixtures import ScriptedSkillPort


def _gate(**overrides: object) -> dict:
    payload: dict = {
        "variable_id": "cash",
        "comparison": ">=",
        "threshold": 90.0,
        "basis": "Anchor baseline P50 of cash is 100.0; the gate sits below it.",
    }
    payload.update(overrides)
    return payload


def _proposal(**overrides: object) -> dict:
    payload: dict = {
        "name": "Phased rollout",
        "source_run_id": "run-1",
        "arm": "strategy",
        "mece_branches": ["Demand"],
        "key_variables": ["cash"],
        "rationale": "The strategy arm beats baseline on P50 with a bounded loss.",
        "gates": [_gate()],
    }
    payload.update(overrides)
    return payload


def _context() -> ProposalContext:
    return ProposalContext(
        topic="Should we launch?",
        branches=[("Demand", ["demand"]), ("Cost", ["cost"])],
        family_runs=[
            ProposalFamilyRun(
                run_id="run-1",
                parent_run_id=None,
                ensemble_id="ens-1",
                baseline_p50=100.0,
                baseline_p_loss=0.2,
                strategy_p50=120.0,
                strategy_p_loss=0.1,
            ),
            ProposalFamilyRun(
                run_id="run-2",
                parent_run_id="run-1",
                ensemble_id="ens-2",
                baseline_p50=90.0,
                baseline_p_loss=0.3,
                strategy_p50=95.0,
                strategy_p_loss=0.25,
            ),
        ],
        variables=[ProposalVariable(id="cash", unit="k", description="Cash on hand")],
        guidance="Favor low-cash-exposure directions.",
    )


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


def test_proposal_contract_parses_valid_payload_with_defaults() -> None:
    parsed = DirectionProposals.model_validate({"proposals": [_proposal()]})
    assert len(parsed.proposals) == 1
    assert parsed.proposals[0].name == "Phased rollout"
    assert parsed.proposals[0].arm == "strategy"
    assert parsed.proposals[0].gates[0].variable_id == "cash"
    assert parsed.proposals[0].gates[0].threshold == 90.0
    minimal = DirectionProposal.model_validate(
        {
            "name": "Wait",
            "source_run_id": "run-1",
            "mece_branches": ["Demand"],
            "rationale": "Wait for evidence.",
            "gates": [_gate()],
        }
    )
    assert minimal.arm == "baseline"
    assert minimal.key_variables == []


def test_proposal_contract_refuses_extra_keys() -> None:
    with pytest.raises(ValidationError):
        DirectionProposal.model_validate(_proposal(invented_field="nope"))
    with pytest.raises(ValidationError):
        DirectionProposals.model_validate({"proposals": [_proposal()], "extra": 1})


def test_proposal_contract_refuses_empty_and_oversized_sets() -> None:
    with pytest.raises(ValidationError):
        DirectionProposals.model_validate({"proposals": []})
    with pytest.raises(ValidationError):
        DirectionProposals.model_validate(
            {"proposals": [_proposal(name=f"Direction {index}") for index in range(5)]}
        )


def test_proposal_contract_refuses_duplicate_names() -> None:
    with pytest.raises(ValidationError, match="unique"):
        DirectionProposals.model_validate(
            {"proposals": [_proposal(), _proposal(source_run_id="run-2")]}
        )


def test_proposal_contract_requires_at_least_one_mece_branch() -> None:
    with pytest.raises(ValidationError):
        DirectionProposal.model_validate(_proposal(mece_branches=[]))


def test_proposal_contract_refuses_bad_arm_and_missing_rationale() -> None:
    with pytest.raises(ValidationError):
        DirectionProposal.model_validate(_proposal(arm="sideways"))
    payload = _proposal()
    del payload["rationale"]
    with pytest.raises(ValidationError):
        DirectionProposal.model_validate(payload)


def test_proposal_contract_normalizes_names_and_branches() -> None:
    parsed = DirectionProposal.model_validate(
        _proposal(
            name="  Phased rollout ",
            mece_branches=[" Demand ", "Demand", "Cost"],
            key_variables=[" cash ", "cash"],
        )
    )
    assert parsed.name == "Phased rollout"
    assert parsed.mece_branches == ["Demand", "Cost"]
    assert parsed.key_variables == ["cash"]


def test_proposal_contract_refuses_blank_branch_entries() -> None:
    with pytest.raises(ValidationError):
        DirectionProposal.model_validate(_proposal(mece_branches=["Demand", "  "]))


# ---------------------------------------------------------------------------
# Gates (template v2)
# ---------------------------------------------------------------------------


def test_gate_contract_parses_and_normalizes() -> None:
    gate = DirectionGate.model_validate(
        _gate(variable_id="  cash ", threshold=90, basis="  Anchor P50 100.0. ")
    )
    assert gate.variable_id == "cash"
    assert gate.threshold == 90.0
    assert gate.basis == "Anchor P50 100.0."
    assert gate.comparison == ">="


def test_gate_contract_accepts_all_comparisons() -> None:
    for comparison in (">=", "<=", ">", "<", "=="):
        gate = DirectionGate.model_validate(_gate(comparison=comparison))
        assert gate.comparison == comparison


def test_gate_contract_refuses_non_finite_thresholds() -> None:
    for bad in (float("inf"), float("-inf"), float("nan")):
        with pytest.raises(ValidationError):
            DirectionGate.model_validate(_gate(threshold=bad))


def test_gate_contract_refuses_string_and_bool_thresholds() -> None:
    with pytest.raises(ValidationError):
        DirectionGate.model_validate(_gate(threshold="90"))
    with pytest.raises(ValidationError):
        DirectionGate.model_validate(_gate(threshold=True))


def test_gate_contract_refuses_bad_comparison_blank_basis_and_extra_keys() -> None:
    with pytest.raises(ValidationError):
        DirectionGate.model_validate(_gate(comparison="~="))
    with pytest.raises(ValidationError):
        DirectionGate.model_validate(_gate(basis="   "))
    with pytest.raises(ValidationError):
        DirectionGate.model_validate(_gate(invented_field="nope"))
    with pytest.raises(ValidationError):
        DirectionGate.model_validate(_gate(variable_id="  "))


def test_proposal_contract_requires_at_least_one_gate() -> None:
    with pytest.raises(ValidationError):
        DirectionProposal.model_validate(_proposal(gates=[]))
    payload = _proposal()
    del payload["gates"]
    with pytest.raises(ValidationError):
        DirectionProposal.model_validate(payload)


def test_proposal_contract_refuses_more_than_four_gates() -> None:
    with pytest.raises(ValidationError):
        DirectionProposal.model_validate(_proposal(gates=[_gate() for _ in range(5)]))


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


def test_prompt_builder_lists_the_grounding_surface() -> None:
    content = build_proposal_user_content(_context())
    assert "Should we launch?" in content
    assert "Demand: demand" in content
    assert "Cost: cost" in content
    assert "run run-1" in content
    assert "run run-2" in content
    assert "ensemble ens-1" in content
    assert "120.0" in content
    assert "cash (k)" in content
    assert "Favor low-cash-exposure directions." in content
    assert "run-3" not in content


def test_prompt_builder_is_deterministic_and_omits_empty_guidance() -> None:
    first = build_proposal_user_content(_context())
    second = build_proposal_user_content(_context())
    assert first == second
    context = _context()
    context.guidance = None
    assert "Chair guidance" not in build_proposal_user_content(context)


def test_prompt_builder_reports_no_variables_honestly() -> None:
    context = _context()
    context.variables = []
    assert "(no variables bound to the anchor run)" in build_proposal_user_content(context)


def test_prompt_builder_names_the_ensemble_metric_when_known() -> None:
    context = _context()
    context.family_runs[0].metric = "cash"
    content = build_proposal_user_content(context)
    assert "baseline P50 of cash 100.0" in content
    assert "strategy P50 of cash 120.0" in content
    # A run without a metric keeps the v1 rendering.
    assert "baseline P50 90.0" in content


def test_prompt_builder_mentions_gates_in_the_closing_instruction() -> None:
    content = build_proposal_user_content(_context())
    assert "1 to 4 gates" in content
    assert "derive from the stored summary numbers" in content


def test_system_prompt_states_the_grounding_rules() -> None:
    assert "Never invent a run id" in PROPOSAL_SYSTEM_PROMPT
    assert "Never invent a branch name" in PROPOSAL_SYSTEM_PROMPT
    assert "Never invent a variable id" in PROPOSAL_SYSTEM_PROMPT
    assert "at least one MECE branch" in PROPOSAL_SYSTEM_PROMPT
    assert "Return valid JSON only" in PROPOSAL_SYSTEM_PROMPT
    assert "Do not compute new numbers" in PROPOSAL_SYSTEM_PROMPT
    assert '"gates" is a list of 1 to 4 decision gates' in PROPOSAL_SYSTEM_PROMPT
    assert "Derive every threshold from a number shown in the context" in PROPOSAL_SYSTEM_PROMPT
    assert "Never invent a threshold or a basis number" in PROPOSAL_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Proposal pass (scripted port; no live LLM)
# ---------------------------------------------------------------------------


async def test_propose_returns_output_and_model() -> None:
    port = ScriptedSkillPort({PROPOSAL_TEMPLATE_ID: [{"proposals": [_proposal()]}]})
    output, model = await propose_directions(port, "context")
    assert len(output.proposals) == 1
    assert output.proposals[0].name == "Phased rollout"
    assert model == "fixture"
    assert port.calls[0]["template_id"] == PROPOSAL_TEMPLATE_ID
    assert port.calls[0]["max_tokens"] == str(PROPOSAL_MAX_TOKENS)
    assert "Never invent a run id" in port.calls[0]["system_prompt"]
    port.assert_exhausted()


async def test_propose_unavailable_port_raises_without_calling() -> None:
    port = ScriptedSkillPort({}, available=False)
    with pytest.raises(SkillLLMUnavailable):
        await propose_directions(port, "context")
    assert port.calls == []


async def test_propose_contract_failure_raises() -> None:
    port = ScriptedSkillPort({PROPOSAL_TEMPLATE_ID: [{"wrong_key": "nope"}]})
    with pytest.raises(SkillContractError):
        await propose_directions(port, "context")


async def test_propose_truncated_response_raises_truncation_error_naming_the_cap() -> None:
    port = ScriptedSkillPort(
        {PROPOSAL_TEMPLATE_ID: [None]},  # type: ignore[list-item]
        finish_reason_script={PROPOSAL_TEMPLATE_ID: ["length"]},
    )
    with pytest.raises(SkillTruncatedError, match="truncated") as excinfo:
        await propose_directions(port, "context")
    assert "8000" in str(excinfo.value)
    assert excinfo.value.max_tokens == 8000


async def test_propose_empty_response_raises_contract_error() -> None:
    port = ScriptedSkillPort({PROPOSAL_TEMPLATE_ID: [None]})  # type: ignore[list-item]
    with pytest.raises(SkillContractError, match="no usable JSON response"):
        await propose_directions(port, "context")
