"""Output-contract tests: every recorded fixture parses, and malformed
outputs fail structurally (Sprint 6, D9)."""

from __future__ import annotations

import pytest

from planagent.services.skills.contracts import (
    CONTRACT_FOR_TEMPLATE,
    SKILL_CONTRACT_VERSION,
    SkillContractError,
    parse_stage_output,
)
from planagent.services.skills.templates import TEMPLATES
from tests.skill_fixtures import load_fixture

# Fixture file -> template id. Every template's contract is exercised by
# at least one recorded output.
FIXTURE_CONTRACTS = [
    ("intake_classify", "mckinsey.intake_classify"),
    ("diagnose", "mckinsey.diagnose"),
    ("market_map", "mckinsey.market_map"),
    ("option_generate_bull", "mckinsey.option_generate"),
    ("option_generate_lean", "mckinsey.option_generate"),
    ("option_generate_contrarian", "mckinsey.option_generate"),
    ("filter_shortlist", "mckinsey.filter_shortlist"),
    ("synthesize", "mckinsey.synthesize"),
    ("verify_assumptions", "mckinsey.verify_assumptions"),
    ("verify_wargame_round1", "mckinsey.verify_wargame"),
    ("verify_wargame_round2", "mckinsey.verify_wargame"),
    ("verify_wargame_round3", "mckinsey.verify_wargame"),
    ("verify_execution", "mckinsey.verify_execution"),
    ("tournament_1", "mckinsey.tournament_judge"),
    ("tournament_2", "mckinsey.tournament_judge"),
    ("tournament_3", "mckinsey.tournament_judge"),
    ("crit_intake", "advisory.crit_intake"),
    ("lens_position_product_clarity", "advisory.lens_position"),
    ("lens_position_risk_capital", "advisory.lens_position"),
    ("lens_position_scale_systems", "advisory.lens_position"),
    ("lens_position_offer_strength", "advisory.lens_position"),
    ("lens_position_future_self", "advisory.lens_position"),
    ("lens_revision_product_clarity", "advisory.lens_revision"),
    ("lens_revision_risk_capital", "advisory.lens_revision"),
    ("lens_revision_scale_systems", "advisory.lens_revision"),
    ("lens_revision_offer_strength", "advisory.lens_revision"),
    ("lens_revision_future_self", "advisory.lens_revision"),
    ("forced_debate", "advisory.forced_debate"),
    ("chair_synthesis", "advisory.chair_synthesis"),
    ("premortem", "gambit.premortem"),
    ("mece_propose_valid", "mece.propose_tree"),
    ("mece_propose_invalid", "mece.propose_tree"),
]


def test_every_template_has_a_contract() -> None:
    assert set(CONTRACT_FOR_TEMPLATE) == set(TEMPLATES)
    assert SKILL_CONTRACT_VERSION == "1"


@pytest.mark.parametrize("fixture_name,template_id", FIXTURE_CONTRACTS)
def test_recorded_fixture_parses(fixture_name: str, template_id: str) -> None:
    parsed = parse_stage_output(template_id, load_fixture(fixture_name))
    assert parsed.model_dump(mode="json")


def test_non_dict_output_is_a_contract_error() -> None:
    with pytest.raises(SkillContractError, match="expected a JSON object"):
        parse_stage_output("mckinsey.diagnose", ["not", "an", "object"])


def test_missing_required_field_is_a_contract_error() -> None:
    with pytest.raises(SkillContractError) as excinfo:
        parse_stage_output("mckinsey.diagnose", {"assumptions": []})
    assert excinfo.value.template_id == "mckinsey.diagnose"
    assert excinfo.value.contract_version == SKILL_CONTRACT_VERSION


def test_wrong_field_type_is_a_contract_error() -> None:
    payload = load_fixture("diagnose")
    payload["findings"] = "a single string, not a list"
    with pytest.raises(SkillContractError):
        parse_stage_output("mckinsey.diagnose", payload)


def test_out_of_range_score_is_a_contract_error() -> None:
    payload = load_fixture("lens_position_product_clarity")
    payload["option_scores"]["Phased rollout"] = 11.0
    with pytest.raises(SkillContractError):
        parse_stage_output("advisory.lens_position", payload)


def test_unknown_keys_are_forbidden() -> None:
    payload = load_fixture("diagnose")
    payload["surprise_field"] = "not in the contract"
    with pytest.raises(SkillContractError):
        parse_stage_output("mckinsey.diagnose", payload)


def test_empty_option_set_is_a_contract_error() -> None:
    with pytest.raises(SkillContractError):
        parse_stage_output("mckinsey.option_generate", {"options": []})


def test_invalid_verdict_is_a_contract_error() -> None:
    payload = load_fixture("chair_synthesis")
    payload["verdict"] = "maybe"
    with pytest.raises(SkillContractError):
        parse_stage_output("advisory.chair_synthesis", payload)


def test_too_many_crit_questions_is_a_contract_error() -> None:
    payload = load_fixture("crit_intake")
    payload["questions"] = ["q1", "q2", "q3", "q4"]
    with pytest.raises(SkillContractError):
        parse_stage_output("advisory.crit_intake", payload)


def test_unknown_template_has_no_contract() -> None:
    with pytest.raises(ValueError, match="No output contract"):
        parse_stage_output("no.such.template", {})


def test_contract_error_message_names_the_field() -> None:
    with pytest.raises(SkillContractError, match="findings"):
        parse_stage_output("mckinsey.diagnose", {})
