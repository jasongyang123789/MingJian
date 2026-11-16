"""Per-nameplate generation-transition schedules (Phase 2).

Phase 1 drove every nameplate from ONE global
``generation_transition_index``. Phase 2 replaces it for S-layer
aggregation with a schedule per nameplate: each nameplate declares
when its outgoing generation phases out and how many ticks the
successor takes to ramp. The schedule interpolates the generation
mix from the structure's static shares toward the successor, so the
static shares remain the pre-transition mix and the scheduled mix
always sums to 1.

Semantics (documented precisely, pinned by tests):

- progress(t) = clamp((t - start_tick + 1) / duration_ticks, 0, 1)
  for t >= 1; ticks before ``start_tick`` have progress 0.
- outgoing share(t) = static_outgoing x (1 - progress)
- successor share(t) = static_successor + (1 - static_successor) x progress
- the two shares sum to 1 at every tick because the static shares do.

For the canonical static mix (outgoing 1.0, successor 0.0) this
reduces exactly to Phase 1's ``generation_mix_at_index`` with
index = progress. Nameplates without a schedule keep their static
shares at every tick; the global engine index is no longer read by
the S-layer (it remains a pack state field for trajectory display).

Pure functions, no I/O. All helpers re-validate the structure first
through the aggregation path's discipline: callers pass validated
structures, and schedule misuse refuses loudly instead of silently
producing a wrong mix.
"""

from __future__ import annotations

from copy import deepcopy

from .models import GenerationTransitionSchedule, NameplateSplit, SplitStructure


def transition_progress(schedule: GenerationTransitionSchedule, tick: int) -> float:
    """Schedule progress at a 1-based tick: 0 before the start, 1 after."""

    if tick < schedule.start_tick:
        return 0.0
    progress = (tick - schedule.start_tick + 1) / schedule.duration_ticks
    return min(max(progress, 0.0), 1.0)


def effective_shares_for_nameplate(
    nameplate: NameplateSplit, tick: int
) -> dict[str, float]:
    """Effective generation shares for one nameplate object at one tick.

    Unscheduled nameplates return their static shares. Scheduled
    nameplates return the interpolated two-generation mix. Raises
    ``ValueError`` on an invalid scheduled composition (validate the
    structure first — the validator refuses such structures).
    """

    static = {generation.generation_id: generation.share for generation in nameplate.generations}
    schedule = nameplate.transition_schedule
    if schedule is None:
        return dict(static)
    by_id = {generation.generation_id: generation for generation in nameplate.generations}
    outgoing = by_id.get(schedule.outgoing_generation_id)
    successor = by_id.get(schedule.successor_generation_id)
    if outgoing is None or successor is None or len(nameplate.generations) != 2:
        raise ValueError(
            f"Nameplate {nameplate.nameplate_id!r} has a transition schedule over an "
            "invalid generation composition; validate the structure first."
        )
    progress = transition_progress(schedule, tick)
    outgoing_share = outgoing.share * (1.0 - progress)
    successor_share = successor.share + (1.0 - successor.share) * progress
    return {
        schedule.outgoing_generation_id: outgoing_share,
        schedule.successor_generation_id: successor_share,
    }


def generation_shares_at_tick(
    structure: SplitStructure,
    nameplate_id: str,
    tick: int,
) -> dict[str, float]:
    """Effective generation shares for one nameplate at one tick.

    The nameplate must appear in exactly one OEM (ambiguous ids refuse
    loudly, mirroring :func:`generation_mix_at_index`).
    """

    matches = [
        nameplate
        for oem in structure.oems
        for nameplate in oem.nameplates
        if nameplate.nameplate_id == nameplate_id
    ]
    if not matches:
        raise ValueError(f"No nameplate {nameplate_id!r} in the split structure.")
    if len(matches) > 1:
        raise ValueError(f"Nameplate {nameplate_id!r} appears in {len(matches)} OEMs; ambiguous.")
    return effective_shares_for_nameplate(matches[0], tick)


def structure_with_effective_shares(structure: SplitStructure, tick: int) -> SplitStructure:
    """A copy of the structure with scheduled generation shares applied.

    Generation ``share`` values are replaced by the effective shares
    at ``tick``; every other field (including morphology, solution
    codes, and price bases) is preserved. The copy re-validates under
    the sum gates because each scheduled mix sums to 1 by
    construction. Unscheduled nameplates are copied unchanged.
    """

    copied = deepcopy(structure)
    for oem in copied.oems:
        for nameplate in oem.nameplates:
            if nameplate.transition_schedule is None:
                continue
            effective = effective_shares_for_nameplate(nameplate, tick)
            for generation in nameplate.generations:
                generation.share = effective[generation.generation_id]
    return copied
