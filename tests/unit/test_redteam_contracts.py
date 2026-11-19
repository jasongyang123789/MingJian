"""Unit tests for the red-team LLM output contract."""

from __future__ import annotations

import pytest

from planagent.services.redteam.contracts import (
    RedTeamContractError,
    parse_red_team_output,
)
from tests.redteam_fixtures import load_redteam_fixture


def test_recorded_fixture_parses() -> None:
    parsed = parse_red_team_output("redteam.challenge", load_redteam_fixture("redteam_desay_llm"))
    assert len(parsed.findings) == 1
    finding = parsed.findings[0]
    assert finding.kind == "missing_driver"
    assert finding.target == "downside_shock"
    assert finding.severity == "medium"
    assert len(finding.evidence) == 2


def test_empty_findings_list_is_valid() -> None:
    parsed = parse_red_team_output("redteam.challenge", {"findings": []})
    assert parsed.findings == []


def test_unknown_kind_is_contract_error() -> None:
    payload = {
        "findings": [
            {
                "kind": "missing_magic",
                "target": "x",
                "severity": "high",
                "summary": "s",
                "evidence": ["e"],
                "suggested_fix": "f",
                "boundary_class": "fixable_defect",
                "boundary_basis": "Decision-time evidence could have encoded it.",
            }
        ]
    }
    with pytest.raises(RedTeamContractError, match="unknown kind"):
        parse_red_team_output("redteam.challenge", payload)


def test_unknown_severity_is_contract_error() -> None:
    payload = {
        "findings": [
            {
                "kind": "missing_driver",
                "target": "x",
                "severity": "critical",
                "summary": "s",
                "evidence": ["e"],
                "suggested_fix": "f",
                "boundary_class": "fixable_defect",
                "boundary_basis": "Decision-time evidence could have encoded it.",
            }
        ]
    }
    with pytest.raises(RedTeamContractError, match="unknown severity"):
        parse_red_team_output("redteam.challenge", payload)


def test_empty_evidence_is_contract_error() -> None:
    payload = {
        "findings": [
            {
                "kind": "missing_driver",
                "target": "x",
                "severity": "high",
                "summary": "s",
                "evidence": [],
                "suggested_fix": "f",
                "boundary_class": "fixable_defect",
                "boundary_basis": "Decision-time evidence could have encoded it.",
            }
        ]
    }
    with pytest.raises(RedTeamContractError):
        parse_red_team_output("redteam.challenge", payload)


def test_extra_key_is_contract_error() -> None:
    payload = {
        "findings": [
            {
                "kind": "missing_driver",
                "target": "x",
                "severity": "high",
                "summary": "s",
                "evidence": ["e"],
                "suggested_fix": "f",
                "boundary_class": "fixable_defect",
                "boundary_basis": "Decision-time evidence could have encoded it.",
                "id": "model-minted-id",
            }
        ]
    }
    with pytest.raises(RedTeamContractError):
        parse_red_team_output("redteam.challenge", payload)


def test_more_than_ten_findings_is_contract_error() -> None:
    item = {
        "kind": "missing_driver",
        "target": "x",
        "severity": "low",
        "summary": "s",
        "evidence": ["e"],
        "suggested_fix": "f",
        "boundary_class": "fixable_defect",
        "boundary_basis": "Decision-time evidence could have encoded it.",
    }
    with pytest.raises(RedTeamContractError):
        parse_red_team_output("redteam.challenge", {"findings": [item] * 11})


def test_non_object_root_is_contract_error() -> None:
    with pytest.raises(RedTeamContractError):
        parse_red_team_output("redteam.challenge", ["not", "an", "object"])  # type: ignore[arg-type]


def test_unknown_boundary_class_is_contract_error() -> None:
    payload = {
        "findings": [
            {
                "kind": "missing_driver",
                "target": "x",
                "severity": "high",
                "summary": "s",
                "evidence": ["e"],
                "suggested_fix": "f",
                "boundary_class": "maybe_defect",
                "boundary_basis": "b",
            }
        ]
    }
    with pytest.raises(RedTeamContractError, match="unknown boundary_class"):
        parse_red_team_output("redteam.challenge", payload)


def test_missing_boundary_fields_is_contract_error() -> None:
    payload = {
        "findings": [
            {
                "kind": "missing_driver",
                "target": "x",
                "severity": "high",
                "summary": "s",
                "evidence": ["e"],
                "suggested_fix": "f",
            }
        ]
    }
    with pytest.raises(RedTeamContractError):
        parse_red_team_output("redteam.challenge", payload)
