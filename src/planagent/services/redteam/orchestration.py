"""Red-team orchestration (Phase 4, Track 8).

One pipeline, two paths, one merged output:

* Deterministic completeness checks ALWAYS run (no LLM, no network).
  They are the layer that must catch the desay-2020 miss.
* The LLM stage runs when the mode asks for it and a port is
  available. It receives the snapshot context AND the completeness
  findings, with an instruction not to repeat them — it finds what the
  rules cannot see.
* Merge dedupes on (kind, normalized target): a deterministic finding
  always wins over an LLM finding on the same (kind, target), because
  the deterministic one is evidence-grounded in code. Findings are
  sorted deterministically: severity desc, then kind, then target.

Modes:
* ``auto`` — completeness + LLM when a port is available; completeness
  only otherwise (``llm_available`` records the truth, no error).
* ``live`` — LLM is required; an unavailable port raises
  :class:`SkillLLMUnavailable` (HTTP 503 at the API boundary).
* ``completeness_only`` — never calls the LLM, even when one is available.

LLM findings are SUGGESTIONS needing human review, NOT facts: the
result carries that disclaimer verbatim, and the prompt forbids the
model from computing new numbers or giving a decision verdict.
"""

from __future__ import annotations

import re
import time
from typing import Any, Literal

from planagent.services.redteam.completeness import (
    llm_finding_id,
    run_completeness_checks,
)
from planagent.services.redteam.context import (
    render_completeness_block,
    render_snapshot_context,
)
from planagent.services.redteam.contracts import (
    REDTEAM_CONTRACT_VERSION,
    RedTeamContractError,
    RedTeamEmptyResponseError,
    RedTeamTruncatedError,
    parse_red_team_output,
)
from planagent.services.redteam.models import (
    CaseSnapshot,
    RedTeamFinding,
    RedTeamResult,
)
from planagent.services.redteam.templates import get_template, render_template
from planagent.services.skills.orchestration import (
    SkillLLMPort,
    SkillLLMUnavailable,
    StageRecord,
)

TEMPLATE_ID = "redteam.challenge"

DISCLAIMER = (
    "Red-team findings are challenges to the case structure, not facts "
    "about the world. Deterministic (completeness_check) findings cite "
    "the case's own evidence; LLM (red_team_llm) findings are suggestions "
    "that need human review before any variable, formula, or assumption "
    "is changed. Nothing here re-runs the simulation or recommends a decision."
)

_SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}


def normalize_target(target: str) -> str:
    """Normalize a finding target for dedupe: case/whitespace-insensitive."""
    return re.sub(r"\s+", " ", target.strip().lower())


def merge_findings(
    deterministic: list[RedTeamFinding],
    llm_findings: list[RedTeamFinding],
) -> list[RedTeamFinding]:
    """Merge with dedupe: deterministic wins on (kind, normalized target)."""
    seen: dict[tuple[str, str], RedTeamFinding] = {}
    for finding in deterministic:
        seen[(finding.kind, normalize_target(finding.target))] = finding
    for finding in llm_findings:
        key = (finding.kind, normalize_target(finding.target))
        if key not in seen:
            seen[key] = finding
    merged = list(seen.values())
    merged.sort(
        key=lambda f: (
            _SEVERITY_RANK.get(f.severity, 3),
            f.kind,
            normalize_target(f.target),
        )
    )
    return merged


async def run_red_team_stage(
    port: SkillLLMPort,
    *,
    snapshot: CaseSnapshot,
    completeness_findings: list[RedTeamFinding],
    output_language: str,
) -> tuple[StageRecord, list[RedTeamFinding]]:
    """Run the single LLM red-team stage and validate its output.

    Findings from a scripted fixture port (``port.is_fixture``) are
    labeled ``red_team_fixture``, never ``red_team_llm``: recorded
    outputs are not live LLM output, and the provenance must say so.
    """
    template = get_template(TEMPLATE_ID)
    system_prompt, user_content = render_template(
        template,
        {
            "context": render_snapshot_context(snapshot),
            "completeness_block": render_completeness_block(completeness_findings),
            "output_language": output_language,
        },
    )
    if not port.is_available():
        raise SkillLLMUnavailable(
            "No LLM target is configured for the red-team stage; "
            "live red-teaming cannot run without one."
        )
    started = time.monotonic()
    response = await port.generate_json(
        template_id=TEMPLATE_ID,
        system_prompt=system_prompt,
        user_content=user_content,
        max_tokens=template.max_tokens,
    )
    duration_ms = (time.monotonic() - started) * 1000.0
    if response.payload is None:
        if response.finish_reason == "length":
            raise RedTeamTruncatedError(TEMPLATE_ID, max_tokens=template.max_tokens)
        if response.empty_response:
            raise RedTeamEmptyResponseError(TEMPLATE_ID)
        raise RedTeamContractError(
            TEMPLATE_ID,
            [
                {
                    "loc": ("root",),
                    "msg": ("no usable JSON response (empty, unparseable, or upstream failure)"),
                }
            ],
        )
    parsed = parse_red_team_output(TEMPLATE_ID, response.payload)
    finding_source: Literal["red_team_llm", "red_team_fixture"] = (
        "red_team_fixture" if getattr(port, "is_fixture", False) else "red_team_llm"
    )
    findings = [
        RedTeamFinding(
            id=llm_finding_id(item.kind, item.target, item.summary),
            kind=item.kind,  # type: ignore[arg-type]
            target=item.target,
            severity=item.severity,  # type: ignore[arg-type]
            summary=item.summary,
            evidence=list(item.evidence),
            suggested_fix=item.suggested_fix,
            source=finding_source,
            boundary_class=item.boundary_class,  # type: ignore[arg-type]
            boundary_basis=item.boundary_basis,
        )
        for item in parsed.findings
    ]
    stage = StageRecord(
        stage="redteam.challenge",
        template_id=TEMPLATE_ID,
        template_version=template.version,
        contract_version=REDTEAM_CONTRACT_VERSION,
        output=parsed.model_dump(mode="json"),
        model=response.model,
        usage=response.usage.to_dict() if response.usage is not None else None,
        duration_ms=duration_ms,
        attempts=response.attempts,
    )
    return stage, findings


async def run_red_team(
    port: SkillLLMPort | None,
    *,
    snapshot: CaseSnapshot,
    mode: Literal["auto", "live", "completeness_only"] = "auto",
    output_language: str = "Chinese",
) -> RedTeamResult:
    """Run the red team over one frozen snapshot (both paths merged)."""
    deterministic = run_completeness_checks(snapshot)
    llm_available = bool(port is not None and port.is_available())
    llm_findings: list[RedTeamFinding] = []
    stages: list[dict[str, Any]] = []
    llm_source: Literal["red_team_llm", "red_team_fixture", "none"] = "none"

    run_llm = mode in ("auto", "live") and port is not None
    if mode == "live" and not llm_available:
        raise SkillLLMUnavailable(
            "Live red-teaming requires a configured LLM target; none is available in this session."
        )
    if run_llm and llm_available:
        stage, llm_findings = await run_red_team_stage(
            port,
            snapshot=snapshot,
            completeness_findings=deterministic,
            output_language=output_language,
        )
        stages.append(stage.model_dump(mode="json"))
        llm_source = "red_team_fixture" if getattr(port, "is_fixture", False) else "red_team_llm"

    merged = merge_findings(deterministic, llm_findings)
    counts_by_severity: dict[str, int] = {}
    counts_by_kind: dict[str, int] = {}
    for finding in merged:
        counts_by_severity[finding.severity] = counts_by_severity.get(finding.severity, 0) + 1
        counts_by_kind[finding.kind] = counts_by_kind.get(finding.kind, 0) + 1

    return RedTeamResult(
        case_id=snapshot.case_id,
        mode=mode,
        llm_available=llm_available,
        llm_source=llm_source,
        findings=merged,
        counts_by_severity=counts_by_severity,
        counts_by_kind=counts_by_kind,
        stages=stages,
        template_version=get_template(TEMPLATE_ID).version,
        contract_version=REDTEAM_CONTRACT_VERSION,
        disclaimer=DISCLAIMER,
    )


__all__ = [
    "DISCLAIMER",
    "TEMPLATE_ID",
    "merge_findings",
    "normalize_target",
    "run_red_team",
    "run_red_team_stage",
]
