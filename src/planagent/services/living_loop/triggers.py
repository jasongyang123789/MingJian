"""Pure trigger evaluation for the living-strategy loop (Sprint 9).

Triggers are evaluated deterministically from stored observations —
no I/O, no LLM, no randomness. The evaluation window is
``(previous_cutoff, decision_time]``: observations recorded at or
before the previous review's cutoff belong to an earlier window and
are never re-evaluated, and observations after the review's
decision time are not yet visible to it (the same inclusive-upper /
exclusive-lower discipline as the Sprint 5 firewall boundary, which
is inclusive on its cutoff; here the lower bound is exclusive
because the previous window already owned its endpoint).

Three trigger kinds, all pre-registered:

- ``threshold``: the latest observed value in the window breaches a
  threshold. The latest value is the current state of the world as
  observed; older values in the window are recorded but do not fire.
- ``gate``: a Sprint 4 gate statistic computed over ALL window
  observations of the field, reusing :func:`gate_observed_value`
  with the observations as the arm's values. The statistic sees the
  whole window, not just the latest point.
- ``deviation``: ``consecutive`` successive observations (in
  observed_at order) each deviate from the reference by more than
  ``tolerance``. A single stray reading never fires it.
"""

from __future__ import annotations

from datetime import datetime

from planagent.services.calibration.firewall import format_cutoff, parse_cutoff
from planagent.services.robustness.methods import apply_gate_operator, gate_observed_value

from .models import (
    DeviationTrigger,
    GateTrigger,
    LoopObservationRead,
    LoopTriggerDefinition,
    ThresholdTrigger,
    TriggerEvaluationOutcome,
    TriggerKind,
)

_OPERATORS = {
    ">": lambda value, threshold: value > threshold,
    ">=": lambda value, threshold: value >= threshold,
    "<": lambda value, threshold: value < threshold,
    "<=": lambda value, threshold: value <= threshold,
}


def select_window(
    observations: list[LoopObservationRead],
    *,
    after: datetime | None,
    up_to: datetime,
) -> list[LoopObservationRead]:
    """Observations in ``(after, up_to]``, in observed_at order.

    ``after=None`` means no lower bound (the baseline run predates
    the firewall). Ties on observed_at break by id, so the window
    order is deterministic.
    """

    selected = [
        item
        for item in observations
        if (after is None or parse_cutoff(item.observed_at) > after)
        and parse_cutoff(item.observed_at) <= up_to
    ]
    selected.sort(key=lambda item: (parse_cutoff(item.observed_at), item.id))
    return selected


def _no_data_outcome(
    trigger: LoopTriggerDefinition,
) -> TriggerEvaluationOutcome:
    return TriggerEvaluationOutcome(
        name=trigger.name,
        kind=TriggerKind(trigger.kind),
        field=trigger.field,
        fired=False,
        status="no_data",
        note=(
            f"No observations for field {trigger.field!r} in the review window; "
            "the trigger could not be evaluated."
        ),
    )


def _evaluate_threshold(
    trigger: ThresholdTrigger,
    window: list[LoopObservationRead],
) -> TriggerEvaluationOutcome:
    field_items = [item for item in window if item.field == trigger.field]
    if not field_items:
        return _no_data_outcome(trigger)
    latest = field_items[-1]
    fired = bool(_OPERATORS[trigger.operator](latest.value, trigger.threshold))
    return TriggerEvaluationOutcome(
        name=trigger.name,
        kind=TriggerKind.THRESHOLD,
        field=trigger.field,
        fired=fired,
        status="fired" if fired else "quiet",
        observed_value=latest.value,
        threshold=trigger.threshold,
        observation_ids=[item.id for item in field_items],
        observed_values=[item.value for item in field_items],
        note=(
            f"Latest observed {trigger.field} = {latest.value} "
            f"(observed {latest.observed_at}); threshold: "
            f"{trigger.operator} {trigger.threshold}."
        ),
    )


def _evaluate_gate(
    trigger: GateTrigger,
    window: list[LoopObservationRead],
) -> TriggerEvaluationOutcome:
    field_items = [item for item in window if item.field == trigger.field]
    if not field_items:
        return _no_data_outcome(trigger)
    values = [item.value for item in field_items]
    loss_threshold = trigger.loss_threshold if trigger.loss_threshold is not None else 0.0
    observed = gate_observed_value(trigger.gate, values, [], loss_threshold)
    fired = apply_gate_operator(trigger.gate.operator, observed, trigger.gate.threshold)
    return TriggerEvaluationOutcome(
        name=trigger.name,
        kind=TriggerKind.GATE,
        field=trigger.field,
        fired=bool(fired),
        status="fired" if fired else "quiet",
        observed_value=observed,
        threshold=trigger.gate.threshold,
        observation_ids=[item.id for item in field_items],
        observed_values=values,
        note=(
            f"Gate statistic {trigger.gate.metric.value} over {len(values)} "
            f"observation(s) of {trigger.field} = {observed}; threshold: "
            f"{trigger.gate.operator.value} {trigger.gate.threshold}."
        ),
    )


def _evaluate_deviation(
    trigger: DeviationTrigger,
    window: list[LoopObservationRead],
    reference_value: float,
) -> TriggerEvaluationOutcome:
    field_items = [item for item in window if item.field == trigger.field]
    if not field_items:
        return _no_data_outcome(trigger)
    values = [item.value for item in field_items]
    deviations = [abs(value - reference_value) for value in values]
    breaches = [deviation > trigger.tolerance for deviation in deviations]
    longest_run = 0
    current_run = 0
    for breached in breaches:
        current_run = current_run + 1 if breached else 0
        longest_run = max(longest_run, current_run)
    fired = longest_run >= trigger.consecutive
    return TriggerEvaluationOutcome(
        name=trigger.name,
        kind=TriggerKind.DEVIATION,
        field=trigger.field,
        fired=fired,
        status="fired" if fired else "quiet",
        observed_value=max(deviations),
        tolerance=trigger.tolerance,
        reference_value=reference_value,
        consecutive_breaches=longest_run,
        observation_ids=[item.id for item in field_items],
        observed_values=values,
        note=(
            f"Max |observed - reference| = {max(deviations)} against tolerance "
            f"{trigger.tolerance} (reference {reference_value}); longest "
            f"consecutive breach run = {longest_run}, required = "
            f"{trigger.consecutive}."
        ),
    )


def evaluate_triggers(
    triggers: list[LoopTriggerDefinition],
    window: list[LoopObservationRead],
    *,
    baseline_final_state: dict[str, float],
) -> list[TriggerEvaluationOutcome]:
    """Evaluate every trigger against one review window, in order.

    ``baseline_final_state`` supplies deviation references when a
    trigger carries no explicit ``reference_value``. A deviation
    trigger whose field is absent from the baseline final state
    raises ``ValueError`` naming the field: the evaluation is
    all-or-nothing, and a missing reference must fail loudly rather
    than record a verdict against a default nobody chose.
    """

    outcomes: list[TriggerEvaluationOutcome] = []
    for trigger in triggers:
        if trigger.kind == "threshold":
            outcomes.append(_evaluate_threshold(trigger, window))
        elif trigger.kind == "gate":
            outcomes.append(_evaluate_gate(trigger, window))
        elif trigger.kind == "deviation":
            reference = trigger.reference_value
            if reference is None:
                if trigger.field not in baseline_final_state:
                    raise ValueError(
                        f"Deviation trigger {trigger.name!r} has no reference value "
                        f"for field {trigger.field!r}: the baseline run's final "
                        "state carries no such field. Supply reference_value."
                    )
                reference = baseline_final_state[trigger.field]
            outcomes.append(_evaluate_deviation(trigger, window, reference))
        else:  # pragma: no cover - discriminated union is exhaustive
            raise ValueError(f"Unknown trigger kind: {trigger.kind!r}.")
    return outcomes


def window_bounds(
    previous_cutoff: datetime | None, decision_time: datetime
) -> tuple[str | None, str]:
    """Canonical window bound strings for the iteration record."""

    return (
        format_cutoff(previous_cutoff) if previous_cutoff is not None else None,
        format_cutoff(decision_time),
    )
