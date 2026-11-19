"""Cyclical downturn / reversal shock for growth cases (fix/downside-mechanism).

The growth-coupled diffusion operators (``logistic`` + ``pow`` tick
drivers) only compute "how fast it grows": a growth case's Monte Carlo
ensemble can never decline, so both Desay anchors report ``p_loss 0.0``
and the 2018-19 downturn and the 2020 growth shortfall had no advance
warning. This module adds an OPT-IN (default OFF) downside mechanism
that makes decline expressible without touching any existing behaviour:

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
configuration (or ``enabled: false``), :func:`resolve_downside`
returns None and the executor, the run summary, and every Monte Carlo
statistic are exactly as before. The fragment lives in the run
configuration JSON, so it enters the Sprint 3 input hash, travels
with Monte Carlo trial / scenario-branch / replay configuration
copies, and needs no migration.

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

#: Configuration key holding the downside fragment on a run.
DOWNSIDE_CONFIGURATION_KEY = "downside"

#: Default sampled-variable ids. A case may rename them in the fragment.
DEFAULT_OCCURS_VARIABLE = "downturn_occurs"
DEFAULT_DEPTH_VARIABLE = "downturn_depth"
DEFAULT_START_VARIABLE = "downturn_start"
DEFAULT_DURATION_VARIABLE = "downturn_duration"
DEFAULT_PERSISTENT_VARIABLE = "downturn_persistent"

#: Steepness of the smooth window edges (per tick). The window rises
#: from ~0 to ~1 over about one tick, so a downturn starting mid-tick
#: does not teleport the level.
WINDOW_STEEPNESS = 2.0


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
    the default-off path, which leaves the run exactly as before. Raises
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
