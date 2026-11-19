"""Unit tests for red-team context rendering (pure, deterministic)."""

from __future__ import annotations

from planagent.services.redteam.context import (
    render_completeness_block,
    render_snapshot_context,
)
from planagent.services.redteam.models import RedTeamFinding
from tests.redteam_cases import complete_case_snapshot, desay_2020_snapshot


def test_snapshot_context_renders_all_sections() -> None:
    context = render_snapshot_context(desay_2020_snapshot())
    assert "加码智能驾驶+座舱域控" in context
    assert "MECE decomposition:" in context
    assert "智能驾驶" in context
    assert "Variable table:" in context
    assert "revenue_growth: triangular(0.05, 0.15, 0.3)" in context
    assert "Transmission formulas: (none" in context
    assert "IPU03" in context
    assert "NEV" in context


def test_snapshot_context_renders_formulas_when_present() -> None:
    context = render_snapshot_context(complete_case_snapshot())
    assert "Transmission formulas:" in context
    assert "nev_penetration" in context
    assert "domain_controller_substitution" in context
    assert "(none" not in context


def test_snapshot_context_is_deterministic() -> None:
    snapshot = desay_2020_snapshot()
    assert render_snapshot_context(snapshot) == render_snapshot_context(snapshot)


def test_completeness_block_lists_findings_for_llm() -> None:
    findings = [
        RedTeamFinding(
            id="rt-missing_driver-nev_penetration",
            kind="missing_driver",
            target="nev_penetration",
            severity="high",
            summary="Missing driver.",
            evidence=["e"],
            suggested_fix="fix",
            source="completeness_check",
            boundary_class="fixable_defect",
            boundary_basis="Decision-time evidence could have encoded it.",
        )
    ]
    block = render_completeness_block(findings)
    assert "do NOT repeat them" in block
    assert "nev_penetration" in block


def test_completeness_block_empty_tells_llm_not_to_invent() -> None:
    block = render_completeness_block([])
    assert "do not invent" in block
