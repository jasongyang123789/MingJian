"""Cyclical downturn / reversal shock for growth cases (fix/downside-mechanism).

The growth-coupled diffusion operators (``logistic`` + ``pow`` tick
drivers) only compute "how fast it grows": a growth case's Monte Carlo
ensemble can never decline, so both Desay anchors report ``p_loss 0.0``
and the 2018-19 downturn and the 2020 growth shortfall had no advance
warning. This module adds a downside mechanism that makes decline
expressible without touching any existing behaviour when it is off:

- DEFAULT ON since Track C (2026-11-20): Ho ordered the default flipped
  from OFF to ON on 2026-11-20 08:42, reversing his 2026-11-19 14:31
  default-OFF decision ("下行风险机制，默认关闭保向后兼容"). A run that
  omits ``downside`` gets the default config (enabled, fields revenue +
  profit, the canonical labeled-assumption variables below, auto-bound
  by the engine where they apply); pass ``downside: null`` or
  ``{"enabled": false}`` to opt out. The default applies only where the
  mechanism can attach: the run must carry a variable set (a run with
  no bindings has no sampling to bind the shock to) and its domain pack
  must carry at least one of the default fields (the military pack
  carries neither revenue nor profit, so military runs are unaffected).
  Pre-existing runs are untouched — the default only affects runs
  created after the change, and replays / Monte Carlo trials / scenario
  branches copy the stored configuration, so they reproduce exactly
  what the base run ran with.
- Per case, the author binds ordinary sampled variables for the shock
  (all LABELED ASSUMPTIONS, no independent estimate claimed):
  ``downturn_occurs`` (Bernoulli — does a downturn hit inside the
  horizon at all), ``downturn_depth`` (triangular — peak per-tick
  fractional level hit), ``downturn_start`` (triangular — first tick of
  the downturn window), ``downturn_duration`` (triangular — window
  length in ticks), and optionally ``downturn_persistent`` (Bernoulli —
  the downturn never recovers: the growth thesis reverses instead of
  cycling back). The variables are sampled once per run from the run
  seed by the existing sampler, so every draw is seed-deterministic:
  Monte Carlo trials draw independently, replays reproduce exactly.
- The engine applies the shock AFTER the tick drivers, as a level
  multiplier on the configured state fields (default revenue + profit):
  ``field *= 1 - depth * occurs * window(tick)``. Because the drivers
  recompute from the current state each tick, the level hit persists as
  a scar — growth resumes from the lower base, it does not snap back.
  The window is a smooth bump (difference of two logistics, so no
  discontinuity at the window edges); in persistent mode it is a step
  that stays down.
- ``p_loss`` (final value below the loss threshold) is structurally
  near-zero for a 5-year growth case even with a severe shock — five
  ticks of ~25% growth need a >55% cumulative hit to end below the
  starting value — so the mechanism's headline statistics are the
  DECLINE probability (fraction of trials whose trajectory falls in at
  least one tick; computed from trial snapshots in the Monte Carlo
  service) and the fatter ES lower tail. A persistent reversal is the
  only regime that can push a final value below its starting value,
  which is why it exists as a separate, low-probability draw rather
  than being folded into the cyclical depth.

Backward compatibility: with no ``downside`` fragment in the run
configuration (explicit opt-out via ``downside: null``, or
``enabled: false``), :func:`resolve_downside`
returns None and the executor, the run summary, and every Monte Carlo
statistic are exactly as before. The fragment lives in the run
configuration JSON, so it enters the Sprint 3 input hash, travels
with Monte Carlo trial / scenario-branch / replay configuration
copies, and needs no migration. The change is deliberately NOT
backward-compatible for NEW runs: a run created after Track C without
an explicit opt-out carries the default shock, so its scores are not
comparable with pre-change scores for the same case — see
DOWNSIDE-MECHANISM.md for the measured comparability impact.

Calibration gap (stated plainly): the shock parameters have NO
independent estimate. They are labelled assumptions anchored, where
possible, on the observed 2018-19 episode (revenue -10.0% then -1.3%
against a ~+15% trend, i.e. a ~25pp swing), but a different equally
reasonable depth / probability moves every score the mechanism
produces. Scores with the mechanism on are assumption-conditional,
never parameter-free conclusions.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from planagent.services.variables.models import (
    DistributionType,
    VariableDefinition,
    VariableDistribution,
)

#: Configuration key holding the downside fragment on a run.
DOWNSIDE_CONFIGURATION_KEY = "downside"

#: Default sampled-variable ids. A case may rename them in the fragment.
DEFAULT_OCCURS_VARIABLE = "downturn_occurs"
DEFAULT_DEPTH_VARIABLE = "downturn_depth"
DEFAULT_START_VARIABLE = "downturn_start"
DEFAULT_DURATION_VARIABLE = "downturn_duration"
DEFAULT_PERSISTENT_VARIABLE = "downturn_persistent"

#: State fields the default shock applies to (narrowed at creation to
#: the fields the run's domain pack actually carries; the military pack
#: carries none of them, so the default never attaches there).
DOWNSIDE_DEFAULT_FIELDS: tuple[str, ...] = ("revenue", "profit")

#: Label carried by the default fragment. The same literal is used by
#: the ``SimulationRunCreate`` default factory in
#: :mod:`planagent.domain.api` (which cannot import this module — see
#: below); a test pins the two equal so they cannot drift apart.
DOWNSIDE_DEFAULT_LABEL = (
    "LABELED ASSUMPTION — default downside shock (Track C, 2026-11-20): "
    "cyclical downturn + optional reversal; parameters have no independent estimate"
)

#: Canonical default parameter set (Track C, 2026-11-20). Ho ordered the
#: default flipped from OFF to ON on 2026-11-20 08:42, reversing his
#: 2026-11-19 14:31 default-OFF decision. The set is UNIFIED across
#: cases: the per-case ON observations differed (2020 used start
#: (1, 2, 4) / persistent 0.10; 2015 and Huawei used start (2, 3, 4) /
#: persistent 0.15) and the unified default takes the majority values.
#: A case that needs its own start / persistence still binds its own
#: variables and passes an explicit fragment — those win over the
#: default. All values are LABELED ASSUMPTIONS with no independent
#: estimate (anchored, where possible, on the observed 2018-19 episode:
#: revenue -10.0% then -1.3% against a ~+15% trend, i.e. a ~25pp swing).
DOWNSIDE_DEFAULT_OCCURS_P = 0.5
DOWNSIDE_DEFAULT_DEPTH = (0.05, 0.20, 0.35)
DOWNSIDE_DEFAULT_START = (2.0, 3.0, 4.0)
DOWNSIDE_DEFAULT_DURATION = (1.0, 2.0, 3.0)
DOWNSIDE_DEFAULT_PERSISTENT_P = 0.15

#: Steepness of the smooth window edges (per tick). The window rises
#: from ~0 to ~1 over about one tick, so a downturn starting mid-tick
#: does not teleport the level.
WINDOW_STEEPNESS = 2.0


def default_downside_variables() -> list[VariableDefinition]:
    """Canonical default downside variables (Track C).

    The five sampled variables of the unified default parameter set,
    in role order (occurs, depth, start, duration, persistent). The
    engine appends the missing ones at the END of a run's variable set
    when the run carries the default (not explicitly supplied) downside
    config, so pre-existing draws are untouched — the sampler draws in
    set order, one draw per variable. ``scope_tags`` are empty on
    purpose: the canonical variables bind to no MECE scope, so they can
    never trip the decomposition scope cross-check. A caller that bound
    its own variable under one of these ids keeps its own definition;
    only missing ids are filled from here.
    """

    def _var(
        var_id: str, unit: str, distribution: VariableDistribution, note: str
    ) -> VariableDefinition:
        return VariableDefinition(
            id=var_id,
            unit=unit,
            distribution=distribution,
            evidence_ref=f"estimate: LABELED ASSUMPTION — {note}",
        )

    return [
        _var(
            DEFAULT_OCCURS_VARIABLE,
            "probability",
            VariableDistribution(
                type=DistributionType.BERNOULLI, p=DOWNSIDE_DEFAULT_OCCURS_P
            ),
            "cyclical downturn hits in ~half of 5-year windows",
        ),
        _var(
            DEFAULT_DEPTH_VARIABLE,
            "fraction",
            VariableDistribution(
                type=DistributionType.TRIANGULAR,
                min=DOWNSIDE_DEFAULT_DEPTH[0],
                mode=DOWNSIDE_DEFAULT_DEPTH[1],
                max=DOWNSIDE_DEFAULT_DEPTH[2],
            ),
            "peak per-tick fractional level hit of a cyclical downturn",
        ),
        _var(
            DEFAULT_START_VARIABLE,
            "years",
            VariableDistribution(
                type=DistributionType.TRIANGULAR,
                min=DOWNSIDE_DEFAULT_START[0],
                mode=DOWNSIDE_DEFAULT_START[1],
                max=DOWNSIDE_DEFAULT_START[2],
            ),
            "first tick of the downturn window",
        ),
        _var(
            DEFAULT_DURATION_VARIABLE,
            "years",
            VariableDistribution(
                type=DistributionType.TRIANGULAR,
                min=DOWNSIDE_DEFAULT_DURATION[0],
                mode=DOWNSIDE_DEFAULT_DURATION[1],
                max=DOWNSIDE_DEFAULT_DURATION[2],
            ),
            "length of the downturn window in ticks",
        ),
        _var(
            DEFAULT_PERSISTENT_VARIABLE,
            "probability",
            VariableDistribution(
                type=DistributionType.BERNOULLI, p=DOWNSIDE_DEFAULT_PERSISTENT_P
            ),
            "small chance the downturn is a reversal (no recovery)",
        ),
    ]


def default_downside_fill(
    fragment: Mapping[str, Any] | None, existing_ids: set[str]
) -> list[VariableDefinition]:
    """Canonical variables a DEFAULT downside fragment still needs.

    Returns [] when the fragment is absent, disabled, or not the
    default — its label differs from ``DOWNSIDE_DEFAULT_LABEL``.
    Explicitly supplied fragments are never auto-completed: their
    loud-failure contract (unbound or misspelled variables fail the
    run) is preserved. For a default fragment, returns the canonical
    variable for every role whose variable is not already bound; the
    caller appends the result at the END of the variable set so
    pre-existing draws are untouched, and enforces the variable-count
    cap itself.
    """

    if not isinstance(fragment, Mapping) or not fragment.get("enabled"):
        return []
    if fragment.get("label") != DOWNSIDE_DEFAULT_LABEL:
        return []
    canonical = {variable.id: variable for variable in default_downside_variables()}
    role_names = (
        (
            fragment.get("occurs_variable") or DEFAULT_OCCURS_VARIABLE,
            DEFAULT_OCCURS_VARIABLE,
        ),
        (
            fragment.get("depth_variable") or DEFAULT_DEPTH_VARIABLE,
            DEFAULT_DEPTH_VARIABLE,
        ),
        (
            fragment.get("start_variable") or DEFAULT_START_VARIABLE,
            DEFAULT_START_VARIABLE,
        ),
        (
            fragment.get("duration_variable") or DEFAULT_DURATION_VARIABLE,
            DEFAULT_DURATION_VARIABLE,
        ),
        (
            fragment.get("persistent_variable") or DEFAULT_PERSISTENT_VARIABLE,
            DEFAULT_PERSISTENT_VARIABLE,
        ),
    )
    missing: list[VariableDefinition] = []
    for name, default_name in role_names:
        if not name or name in existing_ids:
            continue
        variable = canonical.get(default_name)
        if variable is None:
            continue
        missing.append(
            variable
            if name == default_name
            else variable.model_copy(update={"id": name})
        )
    return missing


class DownsideError(ValueError):
    """Misconfigured downside fragment: refused loudly, before any tick."""


def _sigmoid(z: float) -> float:
    """Numerically stable logistic; ``exp`` is only ever taken of a
    non-positive argument, so no ``|z|`` can overflow."""

    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    exp_z = math.exp(z)
    return exp_z / (1.0 + exp_z)


@dataclass(frozen=True)
class DownsideState:
    """A resolved downside shock for one run.

    ``occurs`` and ``persistent`` are weights in [0, 1]: Bernoulli
    draws give 0/1, while a strategy lever may scale them (a hedged arm
    levers ``downturn_depth`` or ``downturn_occurs`` toward 0). The
    persistent weight blends the cyclical bump with a step that stays
    down: 0 is a pure cycle, 1 is a pure reversal.
    """

    fields: tuple[str, ...]
    occurs: float
    depth: float
    start: float
    duration: float
    persistent: float
    label: str | None = None

    def window(self, tick: int) -> float:
        """Shock window at a 1-based tick, in [0, 1].

        Cyclical: ``sigmoid(k*(t-start)) - sigmoid(k*(t-(start+dur)))``,
        ~0 before the window, ~1 inside it, ~0 after — normalised by
        its own peak (``2*sigmoid(k*dur/2) - 1`` at the window centre),
        so ``depth`` is the peak of the continuous window; the realised
        per-tick peak is at most depth and depends on alignment (a
        window centred on an integer tick reaches depth exactly, one
        centred between ticks peaks slightly below it). Persistent: the
        second term is dropped, so the window rises to ~1 and stays (a
        step, not a bump, hence no normalisation — the long-run hit is
        depth).
        """

        rise = _sigmoid(WINDOW_STEEPNESS * (tick - self.start))
        if self.persistent >= 1.0:
            return rise
        bump = rise - _sigmoid(WINDOW_STEEPNESS * (tick - (self.start + self.duration)))
        peak = 2.0 * _sigmoid(WINDOW_STEEPNESS * self.duration / 2.0) - 1.0
        bump = bump / peak if peak > 0.0 else 0.0
        bump = min(1.0, max(0.0, bump))
        if self.persistent <= 0.0:
            return bump
        return (1.0 - self.persistent) * bump + self.persistent * rise

    def factor(self, tick: int) -> float:
        """Level multiplier at a 1-based tick, in (0, 1]."""

        if self.occurs <= 0.0 or self.depth <= 0.0:
            return 1.0
        return 1.0 - self.depth * self.occurs * self.window(tick)

    def factors(self, tick_count: int) -> dict[str, float]:
        """Per-tick multipliers, keyed by tick as strings (JSON-shaped)."""

        return {str(tick): round(self.factor(tick), 4) for tick in range(1, tick_count + 1)}

    def summary(self, tick_count: int) -> dict[str, Any]:
        """Audit fragment stored on the run summary."""

        return {
            "enabled": True,
            "fields": list(self.fields),
            "occurs": self.occurs,
            "depth": self.depth,
            "start": self.start,
            "duration": self.duration,
            "persistent": self.persistent,
            "label": self.label,
            "factors": self.factors(tick_count),
        }


def _require_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DownsideError(f"Downside variable {name!r} must sample a number, got {value!r}.")
    result = float(value)
    if not math.isfinite(result):
        raise DownsideError(f"Downside variable {name!r} sampled a non-finite value.")
    return result


def resolve_downside(
    configuration: Mapping[str, Any] | None,
    sampled_values: Mapping[str, float],
    state_fields: set[str],
) -> DownsideState | None:
    """Resolve a run's downside shock from its configuration + samples.

    Returns None when the fragment is absent or ``enabled`` is false —
    the explicit opt-out path, which leaves the run exactly as before. Raises
    :class:`DownsideError` when the fragment is enabled but
    misconfigured (unknown field, unbound variable, out-of-range
    parameter): a misconfigured shock fails the run loudly before any
    tick executes, never silently degrades to no shock.
    """

    if not isinstance(configuration, Mapping):
        return None
    fragment = configuration.get(DOWNSIDE_CONFIGURATION_KEY)
    if not isinstance(fragment, Mapping) or not fragment.get("enabled"):
        return None

    raw_fields = fragment.get("fields")
    if (
        not isinstance(raw_fields, list)
        or not raw_fields
        or not all(isinstance(item, str) and item for item in raw_fields)
    ):
        raise DownsideError(
            "Downside fragment needs a non-empty 'fields' list of state-field names."
        )
    fields = tuple(dict.fromkeys(raw_fields))
    unknown_fields = sorted(set(fields) - set(state_fields))
    if unknown_fields:
        raise DownsideError(
            f"Downside fields name no state field: {', '.join(unknown_fields)}."
        )

    def _variable(key: str, default: str) -> float:
        name = fragment.get(key, default)
        if not isinstance(name, str) or not name:
            raise DownsideError(f"Downside fragment key {key!r} must name a variable.")
        if name not in sampled_values:
            raise DownsideError(
                f"Downside variable {name!r} ({key}) is not bound on this run; "
                "bind it as a sampled variable or disable the downside fragment."
            )
        return _require_number(sampled_values[name], name)

    occurs = _variable("occurs_variable", DEFAULT_OCCURS_VARIABLE)
    depth = _variable("depth_variable", DEFAULT_DEPTH_VARIABLE)
    start = _variable("start_variable", DEFAULT_START_VARIABLE)
    duration = _variable("duration_variable", DEFAULT_DURATION_VARIABLE)
    persistent = 0.0
    persistent_name = fragment.get("persistent_variable", DEFAULT_PERSISTENT_VARIABLE)
    if isinstance(persistent_name, str) and persistent_name and persistent_name in sampled_values:
        persistent = _require_number(sampled_values[persistent_name], persistent_name)
    elif isinstance(persistent_name, str) and persistent_name:
        # A named persistent variable that is not bound is a case-author
        # error, same as any other unbound downside variable — except
        # when the fragment never names one (the default name with no
        # such variable simply means "no reversal regime").
        if "persistent_variable" in fragment:
            raise DownsideError(
                f"Downside variable {persistent_name!r} (persistent_variable) is not "
                "bound on this run; bind it as a sampled variable or drop the key."
            )

    if not 0.0 <= occurs <= 1.0:
        raise DownsideError(f"Downside occurs weight {occurs} must lie in [0, 1].")
    if not 0.0 <= depth < 1.0:
        raise DownsideError(f"Downside depth {depth} must lie in [0, 1).")
    if not 0.0 < duration:
        raise DownsideError(f"Downside duration {duration} must be positive.")
    if not 0.0 <= persistent <= 1.0:
        raise DownsideError(f"Downside persistent weight {persistent} must lie in [0, 1].")

    label = fragment.get("label")
    if label is not None and not isinstance(label, str):
        raise DownsideError("Downside fragment 'label' must be a string.")
    return DownsideState(
        fields=fields,
        occurs=occurs,
        depth=depth,
        start=start,
        duration=duration,
        persistent=persistent,
        label=label,
    )
