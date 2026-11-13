"""Hindsight firewall: decision-time evidence cutoff (Sprint 5, PRD delta D8).

Structural rule ported from saisrikolanu's multi-agent decision
simulator: the deliberation briefing is built ONLY from information
available before a knowledge cutoff, and ground truth (outcome-time
information) is never passed to the deciding component — the evaluator
alone reads it, separately. Here the same split is enforced on the
numeric engine: a run records a ``decision_time``, and the claim reads
in ``_execute_run`` are filtered to ``created_at <= decision_time``,
so evidence ingested after the decision was "made" cannot influence
the run. The calibration worker's verification path is the evaluator
side of the split and deliberately keeps reading later evidence —
verification is supposed to use outcomes; simulation must not.

All timestamps are UTC. SQLite stores datetimes without timezone
information, so cutoffs are normalized to naive UTC before they are
stored or compared; an aware input is converted to UTC, a naive input
is assumed to already be UTC. The stored cutoff string is canonical
(``YYYY-MM-DDTHH:MM:SS.ffffffZ``) so equal cutoffs hash equally.

The cutoff lives in the run's ``configuration`` JSON under the
``hindsight_firewall`` key, which puts it inside the Sprint 3 input
hash: a replay replays the same configuration, so it reproduces the
same evidence set even when new claims arrived after the original run.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

#: Configuration key holding the firewall fragment on a run.
FIREWALL_CONFIGURATION_KEY = "hindsight_firewall"

#: Protocol version for the firewall fragment.
FIREWALL_PROTOCOL_VERSION = "sprint5-v1"

#: The caller supplied an explicit decision_time.
CUTOFF_SOURCE_EXPLICIT = "explicit"

#: No decision_time was supplied; the cutoff defaults to run creation time.
CUTOFF_SOURCE_CREATION_TIME = "creation_time"


def normalize_cutoff(value: datetime) -> datetime:
    """Normalize a cutoff to naive UTC.

    Aware inputs are converted to UTC and stripped of tzinfo; naive
    inputs are assumed to already be UTC. The result is what gets
    stored and compared, so storage and comparison never disagree
    about timezones.
    """

    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def format_cutoff(value: datetime) -> str:
    """Canonical cutoff string: naive UTC with microsecond precision."""

    return normalize_cutoff(value).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_cutoff(text: str) -> datetime:
    """Parse a stored cutoff string back to naive UTC.

    Accepts the canonical ``...Z`` form, explicit ``+00:00`` offsets,
    and naive ISO strings (assumed UTC). Raises ``ValueError`` on
    anything unparseable: a corrupt cutoff must fail loudly rather
    than silently disabling the firewall.
    """

    raw = text.strip()
    if raw.endswith(("Z", "z")):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"Invalid decision_time cutoff: {text!r}.") from exc
    return normalize_cutoff(parsed)


def firewall_configuration_fragment(decision_time: datetime, source: str) -> dict[str, Any]:
    """The ``hindsight_firewall`` fragment stored in a run's configuration."""

    if source not in (CUTOFF_SOURCE_EXPLICIT, CUTOFF_SOURCE_CREATION_TIME):
        raise ValueError(f"Unknown cutoff source: {source!r}.")
    return {
        FIREWALL_CONFIGURATION_KEY: {
            "protocol": FIREWALL_PROTOCOL_VERSION,
            "decision_time": format_cutoff(decision_time),
            "cutoff_source": source,
        }
    }


def firewall_cutoff_from_configuration(
    configuration: dict[str, Any] | None,
) -> tuple[datetime | None, str | None]:
    """Resolve the firewall cutoff from a run's configuration.

    Returns ``(cutoff, source)``. ``(None, None)`` means the run
    carries no firewall fragment — pre-Sprint-5 runs and rows built
    outside the run-creation path — and the legacy unfiltered claim
    reads apply. A present-but-malformed fragment raises
    ``ValueError``: silently ignoring a corrupt cutoff would leak
    hindsight, so corruption fails loudly instead.
    """

    if not isinstance(configuration, dict):
        return None, None
    fragment = configuration.get(FIREWALL_CONFIGURATION_KEY)
    if fragment is None:
        return None, None
    if not isinstance(fragment, dict):
        raise ValueError("Hindsight firewall fragment must be an object.")
    decision_time = fragment.get("decision_time")
    if not isinstance(decision_time, str) or not decision_time:
        raise ValueError("Hindsight firewall fragment is missing decision_time.")
    source = fragment.get("cutoff_source")
    if source not in (CUTOFF_SOURCE_EXPLICIT, CUTOFF_SOURCE_CREATION_TIME):
        raise ValueError(f"Hindsight firewall fragment has unknown cutoff source: {source!r}.")
    return parse_cutoff(decision_time), source


def claim_visible_at(claim_created_at: datetime, cutoff: datetime | None) -> bool:
    """Whether a claim ingested at ``claim_created_at`` is visible.

    The boundary is inclusive: a claim ingested exactly at the
    decision time was available when the decision was made. ``None``
    cutoff means no firewall (legacy behavior): everything is visible.
    """

    if cutoff is None:
        return True
    return normalize_cutoff(claim_created_at) <= normalize_cutoff(cutoff)
