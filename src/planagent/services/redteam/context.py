"""Pure context rendering for the red-team LLM stage (Phase 4, Track 8).

The rendered snapshot is the ONLY numeric input the LLM stage
receives — same discipline as the Sprint 6 skill context builders.
Rendering is deterministic: fixed section order, no truncation, absent
sections omitted.
"""

from __future__ import annotations

from typing import Any

from planagent.services.redteam.models import CaseSnapshot, RedTeamFinding


def _format_number(value: Any) -> str:
    if value is None:
        return "?"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        text = f"{value:.6f}".rstrip("0").rstrip(".")
        return text or "0"
    return str(value)


def render_snapshot_context(snapshot: CaseSnapshot) -> str:
    """Render the frozen case snapshot as the LLM stage's context block."""
    sections: list[str] = [
        f"Decision question: {snapshot.decision_question}",
        f"Decision time: {snapshot.decision_time or '(not stated)'}",
        f"Domain: {snapshot.domain}",
    ]
    if snapshot.mece_tree is not None:
        tree = snapshot.mece_tree
        lines = ["MECE decomposition:"]
        lines.append(f"- Topic: {tree.topic or snapshot.decision_question}")
        lines.append(f"- Root: {tree.root.name}")
        for child in tree.root.children:
            lines.append(f"  - Branch: {child.name}")
            for grandchild in child.children:
                lines.append(f"    - {grandchild.name}")
        sections.append("\n".join(lines))
    if snapshot.variables:
        lines = ["Variable table:"]
        for variable in snapshot.variables:
            dist = variable.distribution or (
                f"triangular({variable.low}, {variable.mode}, {variable.high})"
                if variable.low is not None
                else "(no distribution stated)"
            )
            text = f"- {variable.name}: {dist}"
            if variable.description:
                text += f" — {variable.description}"
            if variable.evidence:
                text += " — evidence: " + "; ".join(variable.evidence)
            if variable.notes:
                text += f" — notes: {variable.notes}"
            lines.append(text)
        sections.append("\n".join(lines))
    if snapshot.formulas:
        lines = ["Transmission formulas:"]
        for formula in snapshot.formulas:
            text = f"- {formula.target} = {formula.expression}"
            if formula.description:
                text += f" — {formula.description}"
            lines.append(text)
        sections.append("\n".join(lines))
    else:
        sections.append(
            "Transmission formulas: (none — every growth rate is an "
            "exogenous draw; no driver is linked to revenue or share)"
        )
    if snapshot.internal_situation.strip():
        sections.append(f"Internal situation (decision-time facts):\n{snapshot.internal_situation}")
    if snapshot.context_lines:
        sections.append(
            "Caller-supplied context:\n" + "\n".join(f"- {line}" for line in snapshot.context_lines)
        )
    return "\n\n".join(sections)


def render_completeness_block(findings: list[RedTeamFinding]) -> str:
    """Render the deterministic findings so the LLM does not repeat them."""
    if not findings:
        return (
            "Deterministic completeness checks found no gaps: do not invent "
            "missing drivers the checks already ruled out."
        )
    lines = [
        (
            "Deterministic completeness checks ALREADY found these findings — do NOT "
            "repeat them; find what the rules cannot see:"
        )
    ]
    for finding in findings:
        lines.append(
            f"- [{finding.severity}] {finding.kind} on {finding.target}: {finding.summary}"
        )
    return "\n".join(lines)


__all__ = ["render_completeness_block", "render_snapshot_context"]
