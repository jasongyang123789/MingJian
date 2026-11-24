"""Unit tests for red-team orchestration: merge, dedupe, modes, errors."""

from __future__ import annotations

import pytest

from planagent.services.redteam.completeness import llm_finding_id
from planagent.services.redteam.models import RedTeamFinding
from planagent.services.redteam.orchestration import (
    merge_findings,
    run_red_team,
)
from planagent.services.skills.orchestration import SkillLLMUnavailable
from tests.redteam_cases import complete_case_snapshot, desay_2020_snapshot
from tests.redteam_fixtures import ScriptedRedTeamPort, redteam_desay_script
from tests.skill_fixtures import ScriptedSkillPort


def _finding(kind, target, severity="high", source="completeness_check"):
    return RedTeamFinding(
        id=f"rt-{kind}-{target}",
        kind=kind,
        target=target,
        severity=severity,
        summary=f"{kind} on {target}",
        evidence=["e"],
        suggested_fix="fix",
        source=source,
        boundary_class="fixable_defect",
        boundary_basis="Decision-time evidence could have encoded it.",
    )


def test_merge_deterministic_wins_on_same_kind_target() -> None:
    deterministic = [_finding("missing_driver", "nev_penetration", "high")]
    llm = [
        _finding("missing_driver", "NEV_penetration", "low", "red_team_llm"),
        _finding("missing_driver", "downside_shock", "medium", "red_team_llm"),
    ]
    merged = merge_findings(deterministic, llm)
    assert [f.target for f in merged] == ["nev_penetration", "downside_shock"]
    assert merged[0].severity == "high"  # deterministic kept, not LLM's low
    assert merged[0].source == "completeness_check"


def test_merge_sorts_by_severity_then_kind_then_target() -> None:
    merged = merge_findings(
        [
            _finding("weak_assumption", "b_var", "low"),
            _finding("missing_driver", "a_var", "high"),
            _finding("missing_link", "c_var", "medium"),
        ],
        [],
    )
    assert [(f.severity, f.target) for f in merged] == [
        ("high", "a_var"),
        ("medium", "c_var"),
        ("low", "b_var"),
    ]


def test_llm_finding_ids_are_stable() -> None:
    first = llm_finding_id("missing_driver", "downside_shock", "No downside.")
    second = llm_finding_id("missing_driver", "downside_shock", "No downside.")
    assert first == second
    assert first.startswith("rt-llm-")


async def test_fixture_run_merges_completeness_and_llm() -> None:
    port = ScriptedRedTeamPort(redteam_desay_script())
    result = await run_red_team(port, snapshot=desay_2020_snapshot(), mode="auto")
    assert result.llm_available is True
    assert result.llm_source == "red_team_fixture"
    by_key = {(f.kind, f.target): f for f in result.findings}
    assert ("missing_driver", "nev_penetration") in by_key
    assert ("missing_link", "domain_controller_substitution") in by_key
    downside = by_key[("missing_driver", "downside_shock")]
    assert downside.source == "red_team_fixture"
    assert downside.severity == "medium"
    assert downside.boundary_class == "fixable_defect"
    assert "down-cycle" in downside.boundary_basis
    assert all(f.boundary_class == "fixable_defect" for f in result.findings)
    assert all(f.boundary_basis for f in result.findings)
    # Step 4 (2026-11-24): deterministic set is four — the order
    # book joins as a third high missing_driver.
    assert result.counts_by_severity == {"high": 3, "medium": 2}
    assert result.counts_by_kind["missing_driver"] == 4
    assert len(result.stages) == 1
    assert result.stages[0]["template_id"] == "redteam.challenge"
    assert "human review" in result.disclaimer
    port.assert_exhausted()


async def test_fixture_run_on_complete_case_only_adds_llm_finding() -> None:
    port = ScriptedRedTeamPort(redteam_desay_script())
    result = await run_red_team(port, snapshot=complete_case_snapshot(), mode="auto")
    assert [(f.kind, f.target) for f in result.findings] == [("missing_driver", "downside_shock")]
    assert result.llm_source == "red_team_fixture"


async def test_auto_mode_without_llm_is_completeness_only() -> None:
    port = ScriptedSkillPort({}, available=False)
    result = await run_red_team(port, snapshot=desay_2020_snapshot(), mode="auto")
    assert result.llm_available is False
    assert result.llm_source == "none"
    assert result.stages == []
    assert len(result.findings) == 4  # the deterministic four (step 4)
    assert port.calls == []


async def test_completeness_only_never_calls_llm() -> None:
    port = ScriptedRedTeamPort(redteam_desay_script())
    result = await run_red_team(port, snapshot=desay_2020_snapshot(), mode="completeness_only")
    assert result.llm_available is True  # port exists, just not used
    assert result.llm_source == "none"
    assert result.stages == []
    assert len(result.findings) == 4  # the deterministic four (step 4)
    assert port.calls == []


async def test_live_mode_without_llm_raises() -> None:
    port = ScriptedSkillPort({}, available=False)
    with pytest.raises(SkillLLMUnavailable):
        await run_red_team(port, snapshot=desay_2020_snapshot(), mode="live")


async def test_malformed_fixture_output_is_contract_error() -> None:
    from planagent.services.redteam.contracts import RedTeamContractError

    bad = {
        "redteam.challenge": [
            {
                "findings": [
                    {
                        "kind": "missing_magic",
                        "target": "x",
                        "severity": "high",
                        "summary": "s",
                        "evidence": ["e"],
                        "suggested_fix": "f",
                        "boundary_class": "fixable_defect",
                        "boundary_basis": "b",
                    }
                ]
            }
        ]
    }
    port = ScriptedRedTeamPort(bad)
    with pytest.raises(RedTeamContractError):
        await run_red_team(port, snapshot=desay_2020_snapshot(), mode="auto")


async def test_context_reaches_the_llm_prompt() -> None:
    port = ScriptedRedTeamPort(redteam_desay_script())
    await run_red_team(port, snapshot=desay_2020_snapshot(), mode="auto")
    user_content = port.calls[0]["user_content"]
    assert "NEV" in user_content
    assert "IPU03" in user_content
    assert "Deterministic completeness checks ALREADY found" in user_content
    assert "nev_penetration" in user_content
