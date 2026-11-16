"""Seminar round engine (Sprint 16, design §5–§6).

One round = analysis + reflection, in fixed order:

1. **Analysis**: an existing pipeline (strategy-team or advisory-board)
   via :func:`run_stage`-based runners, over the frozen case snapshot
   plus this round's board snapshot (round 1 has no board input).
2. **Reflection**: the ``seminar.reflect`` stage, reading ONLY the
   case snapshot, the model's own history, and this round's board
   snapshot — never other models' full stage outputs.
3. **Digest**: built from the analysis summary + reflection output,
   published by the service layer (sequential, roster order, so board
   ``seq`` assignment is deterministic).

Failure isolation (design §10.1): an analysis failure marks the round
failed and publishes nothing; a reflection failure does NOT discard
the completed analysis (the round is stored, a digest is published
marked reflection-missing, and the model is terminated as failed).
Convergence and per-model status are pure functions over stored
rounds, so they can never drift from the audit trail.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

from planagent.services.seminar.board import (
    AnalysisSummary,
    build_digest,
    extract_analysis_summary,
    normalize_recommendation,
    render_board_snapshot_for_prompt,
    select_board_snapshot,
)
from planagent.services.seminar.contracts import (
    SEMINAR_CONTRACT_VERSION,
    FinalVerdict,
    Reflection,
    parse_seminar_stage_output,
)
from planagent.services.seminar.errors import (
    BudgetExhaustedError,
    ErrorKind,
    is_timeout_exception,
)
from planagent.services.seminar.models import BoardDigest, ModelStatus, RoundError
from planagent.services.seminar.templates import (
    get_seminar_template,
    render_template,
)
from planagent.services.skills.contracts import SkillContractError
from planagent.services.skills.orchestration import (
    AdvisoryBoardResult,
    SkillLLMPort,
    SkillLLMUnavailable,
    StageRecord,
    StrategyTeamResult,
    run_advisory_board,
    run_strategy_team,
)


async def run_seminar_stage(
    port: SkillLLMPort,
    *,
    stage: str,
    template_id: str,
    inputs: dict[str, str],
) -> StageRecord:
    """Render, call, and contract-validate one seminar stage.

    Mirrors :func:`planagent.services.skills.orchestration.run_stage`
    over the seminar template registry and seminar contracts
    (version 1). Raises :class:`SkillLLMUnavailable` when no LLM is
    configured, and :class:`SkillContractError` when the response is
    empty or malformed.
    """
    template = get_seminar_template(template_id)
    system_prompt, user_content = render_template(template, inputs)
    if not port.is_available():
        raise SkillLLMUnavailable(
            f"No LLM target is configured for seminar stage {template_id!r}; "
            "the seminar cannot run without one."
        )
    started = time.monotonic()
    response = await port.generate_json(
        template_id=template_id,
        system_prompt=system_prompt,
        user_content=user_content,
        max_tokens=template.max_tokens,
    )
    duration_ms = (time.monotonic() - started) * 1000.0
    if response.payload is None:
        raise SkillContractError(
            template_id,
            [
                {
                    "loc": ("root",),
                    "msg": ("no usable JSON response (empty, unparseable, or upstream failure)"),
                }
            ],
            contract_version=SEMINAR_CONTRACT_VERSION,
            contract_family="seminar",
        )
    parsed = parse_seminar_stage_output(template_id, response.payload)
    return StageRecord(
        stage=stage,
        template_id=template_id,
        template_version=template.version,
        contract_version=SEMINAR_CONTRACT_VERSION,
        output=parsed.model_dump(mode="json"),
        model=response.model,
        usage=response.usage.to_dict() if response.usage is not None else None,
        duration_ms=duration_ms,
        attempts=response.attempts,
    )


def classify_error(exc: BaseException) -> str:
    """Classify a failure into the formal taxonomy (S18, design §10.2).

    Returns an :class:`ErrorKind` value. ``cancelled`` is classified
    distinctly from ``timeout`` (it must never be retried); SDK
    timeout errors classify as ``timeout``; anything unrecognized is
    ``error`` with the message preserved on the record.
    """
    if isinstance(exc, asyncio.CancelledError):
        return ErrorKind.CANCELLED.value
    if isinstance(exc, BudgetExhaustedError):
        return ErrorKind.BUDGET_EXHAUSTED.value
    if isinstance(exc, SkillLLMUnavailable):
        return ErrorKind.UNAVAILABLE.value
    if isinstance(exc, SkillContractError):
        return ErrorKind.CONTRACT.value
    if is_timeout_exception(exc):
        return ErrorKind.TIMEOUT.value
    return ErrorKind.ERROR.value


@dataclass
class RoundOutcome:
    """The complete result of one model's round, ready to persist."""

    model_id: str
    round_no: int
    board_snapshot_seq: int
    stages: list[StageRecord] = field(default_factory=list)
    reflection: Reflection | None = None
    reflection_stage: StageRecord | None = None
    status: str = "completed"
    error: RoundError | None = None
    digest: BoardDigest | None = None
    analysis_summary: AnalysisSummary | None = None


@dataclass
class RoundSummary:
    """The convergence-relevant facts of one stored round."""

    round_no: int
    recommendation: str
    confidence: str | None
    changes_empty: bool
    usable: bool


def round_summary_from_stored(
    *, round_no: int, status: str, digest: dict[str, Any] | None
) -> RoundSummary:
    """Build a convergence summary from a stored round + its digest."""
    if digest is None or status == "failed":
        return RoundSummary(
            round_no=round_no,
            recommendation="",
            confidence=None,
            changes_empty=False,
            usable=False,
        )
    return RoundSummary(
        round_no=round_no,
        recommendation=normalize_recommendation(str(digest.get("recommendation") or "")),
        confidence=digest.get("confidence"),
        changes_empty=not (digest.get("changes") or [])
        and not bool(digest.get("reflection_missing")),
        usable=True,
    )


def evaluate_convergence(summaries: list[RoundSummary], *, quiet_rounds: int) -> bool:
    """Quiet-rounds rule (design §5.3): ``quiet_rounds`` consecutive
    rounds each stable vs its predecessor — recommendation unchanged,
    confidence unchanged, changes empty. Round 1 can never be quiet
    (no predecessor); a reflection-missing round is never quiet."""
    ordered = sorted(summaries, key=lambda item: item.round_no)
    if len(ordered) < quiet_rounds + 1:
        return False
    quiet_streak = 0
    for previous, current in pairwise(ordered):
        if not previous.usable or not current.usable:
            quiet_streak = 0
            continue
        quiet = (
            current.recommendation == previous.recommendation
            and current.confidence is not None
            and current.confidence == previous.confidence
            and current.changes_empty
        )
        quiet_streak = quiet_streak + 1 if quiet else 0
        if quiet_streak >= quiet_rounds:
            return True
    return False


def derive_model_status(
    *,
    round_rows: list[dict[str, Any]],
    digests_by_round: dict[int, dict[str, Any]],
    has_final: bool,
    max_rounds: int,
    quiet_rounds: int,
) -> ModelStatus:
    """Derive one model's status from its stored rounds + final."""
    if has_final:
        return "final"
    ordered = sorted(round_rows, key=lambda row: int(row["round_no"]))
    if ordered:
        last = ordered[-1]
        if last["status"] in ("failed", "completed_reflection_missing"):
            return "failed"
    summaries = [
        round_summary_from_stored(
            round_no=int(row["round_no"]),
            status=str(row["status"]),
            digest=digests_by_round.get(int(row["round_no"])),
        )
        for row in ordered
    ]
    if evaluate_convergence(summaries, quiet_rounds=quiet_rounds):
        return "converged"
    if len(ordered) >= max_rounds:
        return "capped"
    return "active"


def render_own_history(
    *,
    prior_rounds: list[dict[str, Any]],
    digests_by_round: dict[int, dict[str, Any]],
    current_summary: AnalysisSummary | None,
) -> str:
    """Render a model's own history for reflection/verdict prompts.

    Prior rounds contribute their digest + reflection; the current
    round (reflection only) contributes its analysis summary. Nothing
    from other models appears here — that arrives via the board
    snapshot only.
    """
    lines: list[str] = []
    for row in sorted(prior_rounds, key=lambda item: int(item["round_no"])):
        round_no = int(row["round_no"])
        digest = digests_by_round.get(round_no) or {}
        lines.append(
            f"Round {round_no}: recommendation "
            f"'{digest.get('recommendation')}', confidence "
            f"{digest.get('confidence') or 'unknown'}."
        )
        reflection = row.get("reflection") or {}
        changes = reflection.get("changes") or []
        if changes:
            lines.append(f"  Changes you reported: {'; '.join(str(c) for c in changes)}")
        critique = reflection.get("critique") or []
        for point in critique:
            if isinstance(point, dict):
                lines.append(
                    f"  Weakness you flagged: {point.get('weak_point')} ({point.get('reason')})"
                )
    if current_summary is not None:
        lines.append("This round's analysis summary:")
        lines.append(f"  Recommendation: {current_summary.recommendation}")
        if current_summary.key_arguments:
            lines.append(
                "  Key arguments: " + "; ".join(str(a) for a in current_summary.key_arguments)
            )
        if current_summary.kill_criteria:
            lines.append(
                "  Kill criteria: " + "; ".join(str(k) for k in current_summary.kill_criteria)
            )
    if not lines:
        return "(No prior rounds — this is your first round.)"
    return "\n".join(lines)


async def run_round(
    port: SkillLLMPort,
    *,
    model_id: str,
    round_no: int,
    board_snapshot_seq: int,
    board_rows: list[dict[str, Any]],
    prior_rounds: list[dict[str, Any]],
    digests_by_round: dict[int, dict[str, Any]],
    snapshot: dict[str, Any],
    pipeline: str,
    mode: str,
    decision_question: str,
    options: list[str],
    output_language: str,
    include_premortem: bool,
    failure_date: str,
    snapshot_policy: str,
) -> RoundOutcome:
    """Run one model's round: analysis, then reflection.

    Never raises for stage failures: they are captured in the outcome
    (the service persists the round record and isolates the model).
    Unexpected exceptions are likewise captured, so one model's crash
    cannot kill its wave-mates.
    """
    outcome = RoundOutcome(
        model_id=model_id, round_no=round_no, board_snapshot_seq=board_snapshot_seq
    )
    context = str(snapshot.get("context") or "")
    snapshot_rows = select_board_snapshot(board_rows, policy=snapshot_policy, exclude_model_id=None)
    # Round 1 has no board input (design §5.1); later rounds read the
    # wave-start snapshot. The round_no guard is defense-in-depth:
    # board_rows is empty in wave 1 by construction.
    if snapshot_rows and round_no > 1:
        context = f"{context}\n\n" + render_board_snapshot_for_prompt(
            snapshot_rows, snapshot_seq=board_snapshot_seq
        )
    topic = str(snapshot.get("topic") or "")
    result: StrategyTeamResult | AdvisoryBoardResult
    try:
        if pipeline == "strategy_team":
            result = await run_strategy_team(
                port,
                topic=topic,
                decision_question=decision_question or topic,
                context=context,
                mode=mode,  # type: ignore[arg-type]
                output_language=output_language,
                include_premortem=include_premortem,
                failure_date=failure_date,
            )
        else:
            result = await run_advisory_board(
                port,
                decision=topic,
                options=list(options),
                context=context,
                mode=mode,  # type: ignore[arg-type]
                output_language=output_language,
            )
    except Exception as exc:  # noqa: BLE001 — isolation boundary
        outcome.status = "failed"
        outcome.error = RoundError(
            kind=classify_error(exc), stage="analysis", message=str(exc)[:500]
        )
        return outcome
    result_dict = result.model_dump(mode="json")
    outcome.stages = list(result.stages)
    summary = extract_analysis_summary(pipeline, result_dict)
    outcome.analysis_summary = summary

    other_rows = select_board_snapshot(
        board_rows, policy=snapshot_policy, exclude_model_id=model_id
    )
    board_block = render_board_snapshot_for_prompt(other_rows, snapshot_seq=board_snapshot_seq)
    try:
        reflection_record = await run_seminar_stage(
            port,
            stage=f"reflection:round{round_no}",
            template_id="seminar.reflect",
            inputs={
                "topic": topic,
                "case_context": str(snapshot.get("context") or ""),
                "own_history": render_own_history(
                    prior_rounds=prior_rounds,
                    digests_by_round=digests_by_round,
                    current_summary=summary,
                ),
                "board_snapshot": board_block,
                "output_language": output_language,
            },
        )
    except Exception as exc:  # noqa: BLE001 — isolation boundary
        # Stage-level isolation: the analysis stands, a digest is still
        # published (marked reflection-missing), and the model is
        # terminated as failed by derive_model_status.
        outcome.status = "completed_reflection_missing"
        outcome.error = RoundError(
            kind=classify_error(exc), stage="reflection", message=str(exc)[:500]
        )
        outcome.digest = build_digest(
            model_id=model_id,
            round_no=round_no,
            summary=summary,
            reflection=None,
            board_snapshot_seq=board_snapshot_seq,
        )
        return outcome
    reflection = Reflection.model_validate(reflection_record.output)
    outcome.reflection = reflection
    outcome.reflection_stage = reflection_record
    outcome.status = "completed"
    outcome.digest = build_digest(
        model_id=model_id,
        round_no=round_no,
        summary=summary,
        reflection=reflection,
        board_snapshot_seq=board_snapshot_seq,
    )
    return outcome


async def run_verdict(
    port: SkillLLMPort,
    *,
    model_id: str,
    board_snapshot_seq: int,
    board_rows: list[dict[str, Any]],
    prior_rounds: list[dict[str, Any]],
    digests_by_round: dict[int, dict[str, Any]],
    snapshot: dict[str, Any],
    output_language: str,
    snapshot_policy: str,
) -> tuple[FinalVerdict, StageRecord]:
    """Run one model's final-verdict stage. Raises on stage failure
    (the service records the failure in the finalize response and
    writes no row for the model)."""
    topic = str(snapshot.get("topic") or "")
    other_rows = select_board_snapshot(
        board_rows, policy=snapshot_policy, exclude_model_id=model_id
    )
    board_block = render_board_snapshot_for_prompt(other_rows, snapshot_seq=board_snapshot_seq)
    record = await run_seminar_stage(
        port,
        stage="final_verdict",
        template_id="seminar.final_verdict",
        inputs={
            "topic": topic,
            "case_context": str(snapshot.get("context") or ""),
            "own_history": render_own_history(
                prior_rounds=prior_rounds,
                digests_by_round=digests_by_round,
                current_summary=None,
            ),
            "board_snapshot": board_block,
            "board_snapshot_seq": str(board_snapshot_seq),
            "output_language": output_language,
        },
    )
    return FinalVerdict.model_validate(record.output), record


__all__ = [
    "RoundOutcome",
    "RoundSummary",
    "classify_error",
    "derive_model_status",
    "evaluate_convergence",
    "render_own_history",
    "round_summary_from_stored",
    "run_round",
    "run_seminar_stage",
    "run_verdict",
]
