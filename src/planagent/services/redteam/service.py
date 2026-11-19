"""Red-team service (Phase 4, Track 8).

Two entry points over the same pipeline:

* :meth:`RedTeamService.analyze_snapshot` — the case-build gate. Takes
  a frozen :class:`CaseSnapshot` in the request body, runs the red
  team, returns the result. No persistence: the caller owns the case
  record and attaches the findings to it. This is the primary path —
  the red team challenges the case BEFORE any run exists.
* :meth:`RedTeamService.analyze_run` — runs the red team over a stored
  run's frozen configuration (MECE tree + variable bindings + formulas
  + internal situation, extracted defensively from the stored
  fragments). Unlike skill deliberation, this does NOT require a
  COMPLETED run: the red team challenges structure, not results, so
  any run with a stored configuration qualifies. The result is
  appended to the run summary's ``red_team`` list (fragment
  discipline, no migration); a failed red-team run writes nothing.

Port selection: an injected ``llm_port`` wins (tests pre-seed a
scripted fixture port); otherwise the live Kakouai port
(:class:`KakouaiCliPort`, vault-backed, never sees the key). An
injected ``openai_service`` is also accepted and wraps the existing
``primary`` target, for deployments where the primary target is
configured — the Kakouai port stays the default live path because the
primary target has no key on this VM.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from planagent.config import Settings
from planagent.domain.models import SimulationRun, generate_id, utc_now
from planagent.services.mece.models import DecompositionTree
from planagent.services.openai_client import OpenAIService
from planagent.services.redteam.kakouai_port import KakouaiCliPort
from planagent.services.redteam.models import (
    CaseSnapshot,
    RedTeamFormula,
    RedTeamListRead,
    RedTeamRecord,
    RedTeamResult,
    RedTeamVariable,
)
from planagent.services.redteam.orchestration import run_red_team
from planagent.services.skills.orchestration import (
    OpenAIServiceSkillPort,
    SkillLLMPort,
    SkillLLMUnavailable,
)

RED_TEAM_SUMMARY_KEY = "red_team"


class RedTeamServiceError(ValueError):
    """A client-visible red-team failure with a stable error code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class _NoLLMPort:
    """Port used when no LLM is wired: always unavailable."""

    def is_available(self) -> bool:
        return False

    async def generate_json(self, **_kwargs: Any) -> Any:
        raise SkillLLMUnavailable("No LLM service is configured for red-teaming.")


def _as_dict(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _distribution_text(distribution: Any) -> tuple[str, float | None, float | None, float | None]:
    """Render a stored distribution dict as text + (low, mode, high)."""
    if not isinstance(distribution, dict):
        return ("", None, None, None)
    kind = str(distribution.get("type", "?"))
    low = distribution.get("min")
    mode = distribution.get("mode")
    high = distribution.get("max")
    params = []
    for key in ("value", "mean", "std", "min", "mode", "max", "p"):
        if distribution.get(key) is not None:
            params.append(f"{key} {distribution[key]}")
    text = f"{kind} ({', '.join(params)})" if params else kind
    return (
        text,
        float(low) if isinstance(low, (int, float)) else None,
        float(mode) if isinstance(mode, (int, float)) else None,
        float(high) if isinstance(high, (int, float)) else None,
    )


def snapshot_from_run_configuration(
    run: SimulationRun,
) -> CaseSnapshot:
    """Build a frozen snapshot from a run's stored configuration.

    Defensive: missing fragments degrade to empty fields, never a
    crash — but a configuration with neither a MECE tree nor any
    variable is not a case at all, and raises
    :class:`RedTeamServiceError` (``red_team_snapshot_empty``).
    """
    configuration = run.configuration or {}
    mece_fragment = _as_dict(configuration.get("mece"))
    tree: DecompositionTree | None = None
    topic = ""
    if mece_fragment is not None:
        decomposition = _as_dict(mece_fragment.get("decomposition"))
        if decomposition is not None:
            topic = str(decomposition.get("topic") or "")
            try:
                tree = DecompositionTree.model_validate(decomposition)
            except ValidationError:
                tree = None

    variables: list[RedTeamVariable] = []
    formulas: list[RedTeamFormula] = []
    internal_situation = ""
    variables_fragment = configuration.get("variables")
    bindings: dict[str, Any] | None = None
    if isinstance(variables_fragment, dict):
        bindings = _as_dict(variables_fragment.get("bindings"))
    elif isinstance(variables_fragment, list):
        bindings = {"variables": variables_fragment}
    if bindings is not None:
        for item in _as_list(bindings.get("variables")):
            if not isinstance(item, dict):
                continue
            dist_text, low, mode, high = _distribution_text(item.get("distribution"))
            evidence_ref = item.get("evidence_ref")
            evidence = [str(evidence_ref)] if evidence_ref else []
            variables.append(
                RedTeamVariable(
                    name=str(item.get("id") or item.get("name") or "?"),
                    description=str(item.get("description") or ""),
                    distribution=dist_text,
                    low=low,
                    mode=mode,
                    high=high,
                    evidence=evidence,
                    notes=str(item.get("notes") or ""),
                )
            )
        for item in _as_list(bindings.get("formulas")):
            if not isinstance(item, dict):
                continue
            expression = item.get("expression")
            formulas.append(
                RedTeamFormula(
                    target=str(item.get("output") or item.get("target") or "?"),
                    expression=(
                        json.dumps(expression, sort_keys=True, ensure_ascii=False)
                        if not isinstance(expression, str)
                        else expression
                    ),
                    description=str(item.get("description") or ""),
                )
            )
        internal = _as_dict(bindings.get("internal"))
        if internal:
            internal_situation = "\n".join(
                f"{key}: {value}" for key, value in sorted(internal.items())
            )
    if not internal_situation:
        internal_situation = str(configuration.get("internal_situation") or "")

    if tree is None and not variables:
        raise RedTeamServiceError(
            "red_team_snapshot_empty",
            "This run stores neither a MECE tree nor variables, so there "
            "is no frozen case for the red team to challenge.",
        )
    return CaseSnapshot(
        case_id=run.id,
        decision_question=topic or f"Run {run.id}",
        domain=run.domain_id,
        mece_tree=tree,
        variables=variables,
        formulas=formulas,
        internal_situation=internal_situation,
    )


class RedTeamService:
    """Runs the red team over snapshots and stored runs."""

    def __init__(
        self,
        settings: Settings,
        openai_service: OpenAIService | None = None,
        llm_port: SkillLLMPort | None = None,
    ) -> None:
        self.settings = settings
        if llm_port is not None:
            self._port: SkillLLMPort = llm_port
        elif openai_service is not None:
            self._port = OpenAIServiceSkillPort(openai_service)
        else:
            self._port = KakouaiCliPort()

    async def analyze_snapshot(
        self,
        snapshot: CaseSnapshot,
        *,
        mode: str = "auto",
        output_language: str = "Chinese",
    ) -> RedTeamResult:
        return await run_red_team(
            self._port,
            snapshot=snapshot,
            mode=mode,  # type: ignore[arg-type]
            output_language=output_language,
        )

    async def analyze_run(
        self,
        session: AsyncSession,
        run_id: str,
        *,
        mode: str = "auto",
        output_language: str = "Chinese",
    ) -> RedTeamRecord:
        run = await session.get(SimulationRun, run_id)
        if run is None:
            raise LookupError(f"Simulation run {run_id} was not found.")
        snapshot = snapshot_from_run_configuration(run)
        result = await run_red_team(
            self._port,
            snapshot=snapshot,
            mode=mode,  # type: ignore[arg-type]
            output_language=output_language,
        )
        record = RedTeamRecord(
            id=generate_id(),
            run_id=run.id,
            mode=mode,
            created_at=utc_now().isoformat(),
            result=result.model_dump(mode="json"),
        )
        summary = dict(run.summary or {})
        stored = list(summary.get(RED_TEAM_SUMMARY_KEY) or [])
        stored.append(record.model_dump(mode="json"))
        run.summary = {**summary, RED_TEAM_SUMMARY_KEY: stored}
        await session.commit()
        await session.refresh(run)
        return record

    async def list_red_team_runs(self, session: AsyncSession, run_id: str) -> RedTeamListRead:
        run = await session.get(SimulationRun, run_id)
        if run is None:
            raise LookupError(f"Simulation run {run_id} was not found.")
        stored = (run.summary or {}).get(RED_TEAM_SUMMARY_KEY) or []
        return RedTeamListRead(
            run_id=run.id,
            red_team_runs=[RedTeamRecord.model_validate(item) for item in stored],
        )


__all__ = [
    "RED_TEAM_SUMMARY_KEY",
    "RedTeamService",
    "RedTeamServiceError",
    "snapshot_from_run_configuration",
]
