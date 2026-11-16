"""Case snapshot freeze (Sprint 16, design §3.1).

At seminar creation the case evidence is frozen into one JSON
snapshot with a SHA-256 hash (Sprint 3 canonical JSON): the
``render_run_context`` evidence block, the topic, the options, the
caller context lines, plus the stored MECE fragment and the latest
narrative directions when they exist. All models and all rounds read
this frozen snapshot; products added to the run later never enter the
seminar, so no model ever argues from more evidence than another.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from planagent.domain.models import (
    CalibrationFitRecord,
    DecisionNarrativeRecord,
    SimulationRun,
)
from planagent.services.distributions.canonical import sha256_hash
from planagent.services.skills.context import render_run_context

_MAX_CALIBRATION_FITS_IN_CONTEXT = 5


async def fetch_calibration_fits(
    session: AsyncSession, domain_id: str
) -> list[dict[str, Any]]:
    """Latest calibration fits for the context block (skills parity)."""
    result = await session.execute(
        select(CalibrationFitRecord)
        .where(CalibrationFitRecord.domain_id == domain_id)
        .order_by(CalibrationFitRecord.created_at.desc())
        .limit(_MAX_CALIBRATION_FITS_IN_CONTEXT)
    )
    fits = []
    for record in result.scalars().all():
        fits.append(
            {
                "id": record.id,
                "kind": record.kind,
                "metric": record.metric,
                "ridge_strength": record.ridge_strength,
                "n_observations": record.n_observations,
                "changes": record.changes or {},
            }
        )
    return fits


async def latest_narrative_directions(
    session: AsyncSession, run_id: str
) -> list[dict[str, Any]] | None:
    """Directions of the run's latest narrative artifact, if any."""
    result = await session.execute(
        select(DecisionNarrativeRecord)
        .where(DecisionNarrativeRecord.run_id == run_id)
        .order_by(DecisionNarrativeRecord.version.desc())
        .limit(1)
    )
    record = result.scalars().first()
    if record is None:
        return None
    directions = (record.artifact or {}).get("directions")
    if not isinstance(directions, list) or not directions:
        return None
    return directions


def freeze_case_snapshot(
    *,
    run: SimulationRun,
    topic: str,
    options: list[str],
    context_lines: list[str],
    calibration_fits: list[dict[str, Any]],
    narrative_directions: list[dict[str, Any]] | None,
) -> tuple[dict[str, Any], str]:
    """Build the frozen snapshot dict and its SHA-256 hash.

    The context block is exactly the Sprint 6 deliberation context
    (caller lines appended the same way). Optional keys (MECE tree,
    narrative directions) appear only when the run has them — an
    absent key means "did not exist at freeze time", never a default.
    """
    context = render_run_context(
        configuration=run.configuration or {},
        summary=run.summary or {},
        calibration_fits=calibration_fits,
    )
    if context_lines:
        caller_block = "Caller-supplied context:\n" + "\n".join(
            f"- {line}" for line in context_lines
        )
        context = f"{context}\n\n{caller_block}" if context else caller_block
    snapshot: dict[str, Any] = {
        "run_id": run.id,
        "topic": topic,
        "options": list(options),
        "context": context or "(no engine artifacts stored on this run yet)",
        "context_lines": list(context_lines),
    }
    mece_fragment = (run.configuration or {}).get("mece")
    if isinstance(mece_fragment, dict) and mece_fragment:
        snapshot["mece_tree"] = mece_fragment
    if narrative_directions:
        snapshot["narrative_directions"] = narrative_directions
    return snapshot, sha256_hash(snapshot)


__all__ = [
    "fetch_calibration_fits",
    "freeze_case_snapshot",
    "latest_narrative_directions",
]
