"""Pure monitoring-evaluation helpers for the Sprint 11 worker.

The monitoring worker evaluates each loop's active trigger
registration against ALL recorded observations — the cumulative
monitor view, not a review window. A review iteration evaluates a
bounded window ``(previous_cutoff, decision_time]`` because a review
owns one slice of history; the worker reports the loop's *current*
trigger status, so it sees everything recorded so far: threshold
triggers read the latest observation overall, gate statistics see
all values, and deviation triggers see the full history their
consecutive-run semantics need. Observation order is
``observed_at`` then id, the same deterministic order as the Sprint
9 window selection.

Two pure rules live here so they are unit-testable without a
database:

- :func:`evaluation_fingerprint` — the dedup key. A cycle writes
  no new row for a loop when the loop's latest evaluation already
  carries the current fingerprint, so re-evaluating unchanged
  inputs is a no-op instead of a duplicate row.
- :func:`summarize_outcomes` — the loop-level verdict from
  per-trigger outcomes.
"""

from __future__ import annotations

from typing import Any, Literal

from planagent.services.distributions import sha256_hash

from .models import TriggerEvaluationOutcome, TriggerRegistration

EvaluationSummary = Literal["fired", "quiet", "no_data", "error"]


def evaluation_fingerprint(
    observation_ids: list[str],
    registration_id: str | None,
    triggers: Any,
) -> str:
    """Dedup fingerprint for one loop's evaluation inputs.

    The hash covers the sorted observation ids (observations are
    append-only and immutable, so ids identify the set), the
    selected registration's id, and the canonical trigger
    definitions. A new observation, a new registration, or a
    changed trigger set all change the fingerprint; anything else
    leaves it alone. ``triggers`` is the validated registration's
    trigger list as JSON, or the raw stored JSON when the
    registration cannot be validated — the fingerprint must be
    computable even for the corrupt-registration error row.
    """

    return sha256_hash(
        {
            "observation_ids": sorted(observation_ids),
            "registration_id": registration_id,
            "triggers": triggers,
        }
    )


def select_registration(
    registrations: list[TriggerRegistration],
) -> TriggerRegistration | None:
    """Pick the registration a monitoring evaluation uses.

    Same rule as the Sprint 9 iteration evaluation: the latest
    ``active`` registration, else the latest overall. ``None``
    when the loop has no registrations at all.
    """

    if not registrations:
        return None
    active = [item for item in registrations if item.status == "active"]
    return active[-1] if active else registrations[-1]


def summarize_outcomes(
    outcomes: list[TriggerEvaluationOutcome], *, has_triggers: bool
) -> Literal["fired", "quiet", "no_data"]:
    """Loop-level verdict from per-trigger outcomes.

    ``no_data`` when the loop has no triggers, or when every
    trigger evaluated to ``no_data`` (nothing was actually
    evaluated — observations for other fields do not make a
    trigger quiet). ``fired`` when any trigger fired. ``quiet``
    otherwise: at least one trigger was evaluated and none fired.
    Error verdicts are set by the caller, not here: a failed
    evaluation has no outcomes to summarize.
    """

    if not has_triggers:
        return "no_data"
    if not outcomes or all(outcome.status == "no_data" for outcome in outcomes):
        return "no_data"
    if any(outcome.fired for outcome in outcomes):
        return "fired"
    return "quiet"
