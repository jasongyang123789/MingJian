"""Unit tests for red-team models: the shared finding shape (Track 8/10)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from planagent.services.redteam.models import RedTeamFinding


def _finding(**overrides):
    payload = {
        "id": "rt-missing_driver-nev_penetration",
        "kind": "missing_driver",
        "target": "nev_penetration",
        "severity": "high",
        "summary": "Missing driver: NEV penetration.",
        "evidence": ["Situation names NEV at 5.4%."],
        "suggested_fix": "Add a nev_penetration variable.",
        "source": "completeness_check",
        "boundary_class": "fixable_defect",
        "boundary_basis": "NEV 5.4% in 2020 was public decision-time evidence.",
    }
    payload.update(overrides)
    return payload


def test_finding_shape_validates() -> None:
    finding = RedTeamFinding.model_validate(_finding())
    assert finding.kind == "missing_driver"
    assert finding.source == "completeness_check"


def test_finding_rejects_unknown_kind() -> None:
    with pytest.raises(ValidationError):
        RedTeamFinding.model_validate(_finding(kind="missing_magic"))


def test_finding_rejects_unknown_severity() -> None:
    with pytest.raises(ValidationError):
        RedTeamFinding.model_validate(_finding(severity="critical"))


def test_finding_rejects_unknown_source() -> None:
    with pytest.raises(ValidationError):
        RedTeamFinding.model_validate(_finding(source="red_team_human"))


def test_finding_rejects_extra_keys() -> None:
    with pytest.raises(ValidationError):
        RedTeamFinding.model_validate(_finding(extra_field="nope"))


def test_finding_requires_evidence_list_shape() -> None:
    with pytest.raises(ValidationError):
        RedTeamFinding.model_validate(_finding(evidence="a string, not a list"))


def test_finding_rejects_unknown_boundary_class() -> None:
    with pytest.raises(ValidationError):
        RedTeamFinding.model_validate(_finding(boundary_class="maybe_defect"))


def test_finding_requires_boundary_basis() -> None:
    payload = _finding()
    del payload["boundary_basis"]
    with pytest.raises(ValidationError):
        RedTeamFinding.model_validate(payload)


def test_all_three_boundary_classes_validate() -> None:
    for boundary_class in ("fixable_defect", "acceptable_limit", "unclassified"):
        finding = RedTeamFinding.model_validate(_finding(boundary_class=boundary_class))
        assert finding.boundary_class == boundary_class


def test_all_three_sources_validate() -> None:
    for source in ("red_team_llm", "red_team_fixture", "completeness_check"):
        assert RedTeamFinding.model_validate(_finding(source=source)).source == source


def test_all_five_kinds_validate() -> None:
    for kind in (
        "missing_driver",
        "weak_assumption",
        "unjustified_discount",
        "missing_link",
        "overconfident_parameter",
    ):
        assert RedTeamFinding.model_validate(_finding(kind=kind)).kind == kind
