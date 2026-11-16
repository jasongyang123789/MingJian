"""Orchestration tests: tally/weighting/unanimity rules in code, stage
execution against a scripted LLM port, and full pipeline runs on
recorded fixtures (Sprint 6, D9). No live LLM call is made anywhere."""

from __future__ import annotations

import pytest

from planagent.services.skills.contracts import SkillContractError
from planagent.services.skills.orchestration import (
    OpenAIServiceSkillPort,
    SkillLLMUnavailable,
    assemble_weighted_direction,
    detect_unanimity,
    normalize_flag,
    run_advisory_board,
    run_stage,
    run_strategy_team,
    tally_panel_flags,
    unanimity_note,
)
from planagent.services.skills.contracts import LensPosition
from tests.skill_fixtures import (
    ScriptedSkillPort,
    advisory_board_script,
    load_fixture,
    strategy_team_script,
)


def _lens_position(lens: str, scores: dict[str, float]) -> LensPosition:
    return LensPosition(
        lens=lens,
        option_scores=scores,
        confidence="high",
        decisive_evidence="e",
        primary_upside="u",
        primary_failure_mode="f",
        opening_recommendation="Phased rollout",
        risk_veto=None,
    )


# ---------------------------------------------------------------------------
# Pure rules
# ---------------------------------------------------------------------------


def test_normalize_flag_collapses_case_and_whitespace() -> None:
    assert normalize_flag("  Demand  Growth ") == "demand growth"
    assert normalize_flag("Demand growth") == normalize_flag("  DEMAND   growth ")


def test_tally_requires_two_distinct_lenses() -> None:
    tally = tally_panel_flags(
        {
            "assumptions": ["Demand growth assumption is untested"],
            "wargame": ["  demand growth assumption is UNTESTED "],
            "execution": ["Delivery capacity cannot cover launch volume"],
            "premortem": ["Delivery capacity cannot cover launch volume"],
        }
    )
    assert tally.must_address == [
        "Delivery capacity cannot cover launch volume",
        "Demand growth assumption is untested",
    ]
    by_flag = {flag.flag: flag for flag in tally.flags}
    assert by_flag["Demand growth assumption is untested"].lenses == ["assumptions", "wargame"]
    assert by_flag["Delivery capacity cannot cover launch volume"].lens_count == 2


def test_tally_single_lens_flag_is_not_must_address() -> None:
    tally = tally_panel_flags({"wargame": ["Rival undercuts price within one quarter"]})
    assert tally.must_address == []
    assert tally.flags[0].must_address is False


def test_tally_same_lens_twice_does_not_count_twice() -> None:
    tally = tally_panel_flags({"wargame": ["Same flag", "same flag", "SAME FLAG"]})
    assert len(tally.flags) == 1
    assert tally.flags[0].lens_count == 1
    assert tally.must_address == []


def test_weighted_direction_arithmetic() -> None:
    direction = assemble_weighted_direction(
        {
            "product_clarity": {"A": 8.0, "B": 4.0},
            "risk_capital": {"A": 6.0, "B": 6.0},
        },
        {"product_clarity": 3, "risk_capital": 1},
    )
    assert direction.scores["A"] == pytest.approx(7.5)
    assert direction.scores["B"] == pytest.approx(4.5)
    assert direction.ranking == ["A", "B"]
    assert direction.top_option == "A"


def test_weighted_direction_defaults_missing_weights_to_two() -> None:
    direction = assemble_weighted_direction(
        {"product_clarity": {"A": 8.0}, "risk_capital": {"A": 6.0}}, {}
    )
    assert direction.scores["A"] == pytest.approx(7.0)
    assert direction.weights == {"product_clarity": 2, "risk_capital": 2}


def test_weighted_direction_ties_break_by_name() -> None:
    direction = assemble_weighted_direction(
        {"product_clarity": {"B": 5.0, "A": 5.0}}, {"product_clarity": 2}
    )
    assert direction.ranking == ["A", "B"]


def test_detect_unanimity() -> None:
    positions = [
        _lens_position("product_clarity", {"A": 9.0, "B": 4.0}),
        _lens_position("risk_capital", {"A": 8.0, "B": 5.0}),
    ]
    assert detect_unanimity(positions) == "A"
    positions.append(_lens_position("scale_systems", {"A": 4.0, "B": 9.0}))
    assert detect_unanimity(positions) is None
    assert detect_unanimity([]) is None


def test_unanimity_note_names_the_option() -> None:
    note = unanimity_note("Phased rollout")
    assert "Phased rollout" in note
    assert "steelman" in note
    assert unanimity_note(None) == ""


# ---------------------------------------------------------------------------
# Stage execution
# ---------------------------------------------------------------------------


async def test_run_stage_records_provenance_and_model() -> None:
    port = ScriptedSkillPort({"mckinsey.diagnose": [load_fixture("diagnose")]})
    record = await run_stage(
        port,
        stage="diagnose",
        template_id="mckinsey.diagnose",
        inputs={
            "topic": "T",
            "decision_question": "Q",
            "context": "C",
            "intake": "{}",
            "output_language": "English",
        },
    )
    assert record.stage == "diagnose"
    assert record.template_id == "mckinsey.diagnose"
    assert record.template_version == "2"
    assert record.contract_version == "2"
    assert record.model == "fixture"
    assert record.output["findings"]
    port.assert_exhausted()


async def test_run_stage_unavailable_llm_raises_structured_error() -> None:
    port = ScriptedSkillPort({}, available=False)
    with pytest.raises(SkillLLMUnavailable, match="No LLM target"):
        await run_stage(
            port,
            stage="diagnose",
            template_id="mckinsey.diagnose",
            inputs={
                "topic": "T",
                "decision_question": "Q",
                "context": "C",
                "intake": "{}",
                "output_language": "English",
            },
        )
    assert port.calls == []


async def test_run_stage_malformed_output_is_a_contract_error() -> None:
    port = ScriptedSkillPort({"mckinsey.diagnose": [{"findings": "not a list"}]})
    with pytest.raises(SkillContractError):
        await run_stage(
            port,
            stage="diagnose",
            template_id="mckinsey.diagnose",
            inputs={
                "topic": "T",
                "decision_question": "Q",
                "context": "C",
                "intake": "{}",
                "output_language": "English",
            },
        )


async def test_run_stage_empty_response_is_a_contract_error() -> None:
    port = ScriptedSkillPort({"mckinsey.diagnose": [None]})  # type: ignore[list-item]
    with pytest.raises(SkillContractError, match="no usable JSON"):
        await run_stage(
            port,
            stage="diagnose",
            template_id="mckinsey.diagnose",
            inputs={
                "topic": "T",
                "decision_question": "Q",
                "context": "C",
                "intake": "{}",
                "output_language": "English",
            },
        )


async def test_openai_service_port_maps_meta_and_payload() -> None:
    class StubOpenAI:
        def is_configured(self, target: str) -> bool:
            return target == "primary"

        async def generate_json_for_target(self, **kwargs):  # type: ignore[no-untyped-def]
            assert kwargs["target"] == "primary"
            assert kwargs["max_tokens"] == 1500
            return {"model": "stub-model"}, {"findings": ["x"]}

    port = OpenAIServiceSkillPort(StubOpenAI())  # type: ignore[arg-type]
    assert port.is_available() is True
    response = await port.generate_json(
        template_id="mckinsey.diagnose",
        system_prompt="s",
        user_content="u",
        max_tokens=1500,
    )
    assert response.model == "stub-model"
    assert response.payload == {"findings": ["x"]}


# ---------------------------------------------------------------------------
# Strategy-team pipeline
# ---------------------------------------------------------------------------


async def test_strategy_team_standard_run_end_to_end() -> None:
    port = ScriptedSkillPort(strategy_team_script(mode="standard"))
    result = await run_strategy_team(
        port,
        topic="Should we launch the AI line?",
        decision_question="Should we launch, and in what form?",
        context="Monte Carlo ensemble:\nMetric: cash, trials=50",
        mode="standard",
    )
    port.assert_exhausted()

    assert result.mode == "standard"
    assert [stage.stage for stage in result.stages] == [
        "intake",
        "diagnose",
        "market_map",
        "option_generate:bull",
        "option_generate:lean",
        "filter_shortlist",
        "synthesize",
        "verify:assumptions",
        "verify:wargame:round1",
        "verify:execution",
        "verify:premortem",
    ]
    assert all(stage.template_version == "2" for stage in result.stages)
    assert all(stage.contract_version == "2" for stage in result.stages)
    assert result.synthesis["recommended_option"] == "Phased rollout"
    assert result.synthesis_recommendation_in_shortlist is True
    assert [entry["name"] for entry in result.shortlist["ranked"]] == [
        "Phased rollout",
        "Full launch",
        "Partner-led",
    ]
    # Two independent lenses agree on each must-address flag.
    assert result.tally.must_address == [
        "Delivery capacity cannot cover launch volume",
        "Demand growth assumption is untested",
    ]
    assert result.tournament is None
    assert result.wargame_loop_rounds == 0
    assert result.wargame_loop_stop_reason == "not_deep"
    # The engine context reached the first stage's prompt.
    assert "Monte Carlo ensemble" in port.calls[0]["user_content"]


async def test_strategy_team_without_premortem_skips_the_lens() -> None:
    port = ScriptedSkillPort(strategy_team_script(mode="standard", include_premortem=False))
    result = await run_strategy_team(
        port,
        topic="T",
        decision_question="Q",
        context="C",
        mode="standard",
        include_premortem=False,
    )
    port.assert_exhausted()
    assert "premortem" not in result.panel
    assert result.tally.must_address == ["Demand growth assumption is untested"]


async def test_strategy_team_deep_run_tournament_and_loop() -> None:
    port = ScriptedSkillPort(strategy_team_script(mode="deep"))
    result = await run_strategy_team(
        port,
        topic="Should we launch the AI line?",
        decision_question="Q",
        context="C",
        mode="deep",
    )
    port.assert_exhausted()

    assert result.tournament is not None
    assert result.tournament.winner == "Phased rollout"
    assert result.tournament.wins == {"Phased rollout": 2, "Full launch": 1, "Partner-led": 0}
    assert len(result.tournament.matches) == 3
    # Loop-until-done: round 2 repeats the round-1 flag, round 3 adds
    # nothing — two quiet rounds stop the loop.
    assert result.wargame_loop_rounds == 2
    assert result.wargame_loop_stop_reason == "two_quiet_rounds"
    assert len(result.wargame_rounds) == 3
    assert "option_generate:contrarian" in [stage.stage for stage in result.stages]


async def test_strategy_team_recommendation_outside_shortlist_is_flagged() -> None:
    script = strategy_team_script(mode="standard")
    script["mckinsey.synthesize"][0]["recommended_option"] = "Not on the shortlist"
    port = ScriptedSkillPort(script)
    result = await run_strategy_team(port, topic="T", decision_question="Q", context="C")
    assert result.synthesis_recommendation_in_shortlist is False


# ---------------------------------------------------------------------------
# Advisory-board pipeline
# ---------------------------------------------------------------------------


async def test_advisory_board_standard_run_end_to_end() -> None:
    port = ScriptedSkillPort(advisory_board_script(mode="standard"))
    result = await run_advisory_board(
        port,
        decision="Should we launch the AI line?",
        options=["Phased rollout", "Full launch", "Partner-led"],
        context="Monte Carlo ensemble:\nMetric: cash, trials=50",
        mode="standard",
    )
    port.assert_exhausted()

    assert [stage.stage for stage in result.stages] == [
        "crit_intake",
        "lens_position:product_clarity",
        "lens_position:risk_capital",
        "lens_position:scale_systems",
        "lens_position:offer_strength",
        "lens_position:future_self",
        "forced_debate",
        "lens_revision:product_clarity",
        "lens_revision:risk_capital",
        "lens_revision:scale_systems",
        "lens_revision:offer_strength",
        "lens_revision:future_self",
        "chair_synthesis",
    ]
    assert result.contract["verdict"] == "validate_first"
    assert result.contract["go_threshold"]
    assert result.contract["kill_criterion"]
    # Round 1 equal-weight direction: Phased 7.2, Partner 6.4, Full 5.6.
    assert result.weighted_direction_round1.top_option == "Phased rollout"
    assert result.weighted_direction_round1.scores["Phased rollout"] == pytest.approx(7.2)
    assert result.weighted_direction_round1.ranking == [
        "Phased rollout",
        "Partner-led",
        "Full launch",
    ]
    # Final direction uses Round 3 scores + chair weights.
    assert result.weighted_direction_final.top_option == "Phased rollout"
    assert result.weighted_direction_final.scores["Phased rollout"] == pytest.approx(82 / 11)
    # The risk veto is recorded and, with a validate_first verdict, is
    # being acted on rather than overridden.
    assert len(result.vetoes) == 1
    assert result.vetoes[0].lens == "risk_capital"
    assert "runway" in result.vetoes[0].failure_path
    assert result.has_unmitigated_veto is False
    assert result.unanimous_option is None
    assert result.debate is not None
    assert len(result.revisions) == 5


async def test_advisory_board_choose_verdict_with_veto_is_unmitigated() -> None:
    port = ScriptedSkillPort(advisory_board_script(mode="standard", chair_verdict="choose"))
    result = await run_advisory_board(
        port, decision="D", options=["Phased rollout"], context="C", mode="standard"
    )
    assert result.has_unmitigated_veto is True


async def test_advisory_board_quick_mode_skips_debate_and_revisions() -> None:
    port = ScriptedSkillPort(advisory_board_script(mode="quick"))
    result = await run_advisory_board(
        port, decision="D", options=["Phased rollout"], context="C", mode="quick"
    )
    port.assert_exhausted()
    assert len(result.stages) == 7
    assert result.debate is None
    assert result.revisions == []
    assert result.contract["verdict"] == "validate_first"
    # Quick mode has no Round 3: the final direction reweights the
    # Round 1 scores with the chair's relevance weights.
    assert result.weighted_direction_final.top_option == "Phased rollout"
    assert result.weighted_direction_final.scores["Phased rollout"] == pytest.approx(80 / 11)
    assert result.weighted_direction_final.weights == {
        "product_clarity": 3,
        "risk_capital": 3,
        "scale_systems": 2,
        "offer_strength": 2,
        "future_self": 1,
    }


async def test_advisory_board_unanimity_triggers_steelman_note() -> None:
    port = ScriptedSkillPort(advisory_board_script(mode="standard", unanimous=True))
    result = await run_advisory_board(
        port, decision="D", options=["Phased rollout"], context="C", mode="standard"
    )
    assert result.unanimous_option == "Phased rollout"
    debate_calls = [call for call in port.calls if call["template_id"] == "advisory.forced_debate"]
    assert len(debate_calls) == 1
    assert "ANTI-GROUPTHINK RULE" in debate_calls[0]["user_content"]
    assert "Phased rollout" in debate_calls[0]["user_content"]


async def test_advisory_board_contract_failure_propagates() -> None:
    script = advisory_board_script(mode="quick")
    script["advisory.crit_intake"] = [{"decision": "D"}]  # missing required fields
    port = ScriptedSkillPort(script)
    with pytest.raises(SkillContractError):
        await run_advisory_board(port, decision="D", options=[], context="C", mode="quick")
