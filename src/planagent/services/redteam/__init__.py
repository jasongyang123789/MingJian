"""The red-team layer (Phase 4, Track 8).

Challenges a FROZEN case snapshot — MECE tree, variables, formulas,
internal situation — before any run exists. Deterministic completeness
checks always run; a live LLM stage (Kakouai, vault-backed) runs in
``auto`` mode when available and is required in ``live`` mode.
"""

from __future__ import annotations

from planagent.services.redteam.completeness import (
    DRIVER_CATALOG,
    DriverCheck,
    finding_id,
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
    RedTeamLLMOutput,
    RedTeamTruncatedError,
    parse_red_team_output,
)
from planagent.services.redteam.kakouai_port import KakouaiCliPort
from planagent.services.redteam.models import (
    CaseSnapshot,
    RedTeamFinding,
    RedTeamFormula,
    RedTeamListRead,
    RedTeamRecord,
    RedTeamRequest,
    RedTeamResult,
    RedTeamRunRequest,
    RedTeamVariable,
)
from planagent.services.redteam.orchestration import (
    DISCLAIMER,
    TEMPLATE_ID,
    merge_findings,
    run_red_team,
    run_red_team_stage,
)
from planagent.services.redteam.service import (
    RED_TEAM_SUMMARY_KEY,
    RedTeamService,
    RedTeamServiceError,
    snapshot_from_run_configuration,
)
from planagent.services.redteam.templates import (
    get_template,
    list_templates,
    render_template,
)

__all__ = [
    "DISCLAIMER",
    "DRIVER_CATALOG",
    "REDTEAM_CONTRACT_VERSION",
    "RED_TEAM_SUMMARY_KEY",
    "TEMPLATE_ID",
    "CaseSnapshot",
    "DriverCheck",
    "KakouaiCliPort",
    "RedTeamContractError",
    "RedTeamEmptyResponseError",
    "RedTeamFinding",
    "RedTeamFormula",
    "RedTeamLLMOutput",
    "RedTeamListRead",
    "RedTeamRecord",
    "RedTeamRequest",
    "RedTeamResult",
    "RedTeamRunRequest",
    "RedTeamService",
    "RedTeamServiceError",
    "RedTeamTruncatedError",
    "RedTeamVariable",
    "finding_id",
    "get_template",
    "list_templates",
    "llm_finding_id",
    "merge_findings",
    "parse_red_team_output",
    "render_completeness_block",
    "render_snapshot_context",
    "render_template",
    "run_completeness_checks",
    "run_red_team",
    "run_red_team_stage",
    "snapshot_from_run_configuration",
]
