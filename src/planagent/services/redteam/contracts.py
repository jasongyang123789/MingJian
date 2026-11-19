"""Pydantic output contract for the red-team LLM stage (Phase 4, Track 8).

Mirrors the Sprint 6 skill-contract pattern: the LLM output is
validated against a contract, and malformed output is a structured
failure, never a silent pass-through. The contract is the LLM-side
half of the shared finding shape — ``id`` and ``source`` are assigned
by code, never by the model, so a model can never mint a stable id or
claim another layer's provenance.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

REDTEAM_CONTRACT_VERSION = "1"


class RedTeamContractError(RuntimeError):
    """The LLM stage output failed its Pydantic contract."""

    def __init__(
        self,
        template_id: str,
        details: list[dict[str, Any]],
        contract_version: str = REDTEAM_CONTRACT_VERSION,
    ) -> None:
        self.template_id = template_id
        self.contract_version = contract_version
        self.details = details
        summary = "; ".join(
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}" for item in details
        )
        super().__init__(
            f"LLM output for stage {template_id!r} failed contract "
            f"redteam-v{contract_version}: {summary}"
        )


class RedTeamTruncatedError(RedTeamContractError):
    """The LLM output was cut at the token cap (finish_reason='length')."""

    def __init__(
        self,
        template_id: str,
        max_tokens: int,
        contract_version: str = REDTEAM_CONTRACT_VERSION,
    ) -> None:
        self.max_tokens = max_tokens
        self.finish_reason = "length"
        super().__init__(
            template_id,
            [
                {
                    "loc": ("root",),
                    "msg": (
                        f"response truncated at the max_tokens cap of {max_tokens} tokens "
                        "(finish_reason='length'); the JSON output is incomplete"
                    ),
                }
            ],
            contract_version=contract_version,
        )


class RedTeamEmptyResponseError(RedTeamContractError):
    """The upstream returned no content at all."""

    def __init__(
        self,
        template_id: str,
        contract_version: str = REDTEAM_CONTRACT_VERSION,
    ) -> None:
        super().__init__(
            template_id,
            [{"loc": ("root",), "msg": "upstream returned an empty response"}],
            contract_version=contract_version,
        )


class RedTeamLLMFinding(BaseModel):
    """One LLM finding, before code assigns id + source."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    target: str = Field(min_length=1, max_length=200)
    severity: str
    summary: str = Field(min_length=1, max_length=1000)
    evidence: list[str] = Field(min_length=1, max_length=10)
    suggested_fix: str = Field(min_length=1, max_length=2000)
    boundary_class: str
    boundary_basis: str = Field(min_length=1, max_length=1000)


class RedTeamLLMOutput(BaseModel):
    """The whole LLM stage output: a findings list, at most 10."""

    model_config = ConfigDict(extra="forbid")

    findings: list[RedTeamLLMFinding] = Field(default_factory=list, max_length=10)


_VALID_KINDS = {
    "missing_driver",
    "weak_assumption",
    "unjustified_discount",
    "missing_link",
    "overconfident_parameter",
}
_VALID_SEVERITIES = {"high", "medium", "low"}
_VALID_BOUNDARY_CLASSES = {"fixable_defect", "acceptable_limit", "unclassified"}


def parse_red_team_output(template_id: str, payload: dict[str, Any]) -> RedTeamLLMOutput:
    """Validate a stage payload; raises RedTeamContractError on any violation."""
    if not isinstance(payload, dict):
        raise RedTeamContractError(
            template_id,
            [{"loc": ("root",), "msg": "response root must be a JSON object"}],
        )
    try:
        parsed = RedTeamLLMOutput.model_validate(payload)
    except ValidationError as exc:
        raise RedTeamContractError(template_id, exc.errors()) from exc
    for index, finding in enumerate(parsed.findings):
        problems: list[dict[str, Any]] = []
        if finding.kind not in _VALID_KINDS:
            problems.append(
                {
                    "loc": ("findings", index, "kind"),
                    "msg": f"unknown kind {finding.kind!r}",
                }
            )
        if finding.severity not in _VALID_SEVERITIES:
            problems.append(
                {
                    "loc": ("findings", index, "severity"),
                    "msg": f"unknown severity {finding.severity!r}",
                }
            )
        if finding.boundary_class not in _VALID_BOUNDARY_CLASSES:
            problems.append(
                {
                    "loc": ("findings", index, "boundary_class"),
                    "msg": f"unknown boundary_class {finding.boundary_class!r}",
                }
            )
        if problems:
            raise RedTeamContractError(template_id, problems)
    return parsed


__all__ = [
    "REDTEAM_CONTRACT_VERSION",
    "RedTeamContractError",
    "RedTeamEmptyResponseError",
    "RedTeamLLMOutput",
    "RedTeamTruncatedError",
    "parse_red_team_output",
]
