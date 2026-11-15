"""Pure unit tests for the Sprint 11 monitoring helpers.

No database, no app: the fingerprint, registration-selection, and
summary rules are pure functions over stored shapes.
"""

from __future__ import annotations

from planagent.services.living_loop.models import (
    ThresholdTrigger,
    TriggerEvaluationOutcome,
    TriggerKind,
    TriggerRegistration,
)
from planagent.services.living_loop.monitoring import (
    evaluation_fingerprint,
    select_registration,
    summarize_outcomes,
)


def _outcome(name: str, status: str, fired: bool) -> TriggerEvaluationOutcome:
    return TriggerEvaluationOutcome(
        name=name,
        kind=TriggerKind.THRESHOLD,
        field="cash",
        fired=fired,
        status=status,  # type: ignore[arg-type]
        note="test outcome",
    )


def _registration(registration_id: str, status: str) -> TriggerRegistration:
    return TriggerRegistration(
        id=registration_id,
        loop_id="loop-1",
        triggers=[ThresholdTrigger(name="floor", field="cash", operator="<", threshold=70.0)],
        registered_at="2026-01-01T00:00:00Z",
        observation_count_at_registration=0,
        status=status,  # type: ignore[arg-type]
    )


def _triggers_payload(threshold: float) -> list[dict]:
    return [
        {
            "kind": "threshold",
            "name": "floor",
            "field": "cash",
            "operator": "<",
            "threshold": threshold,
        }
    ]


# --------------------------------------------------------------- fingerprint


def test_fingerprint_is_stable_for_the_same_inputs() -> None:
    left = evaluation_fingerprint(["obs-1", "obs-2"], "reg-1", _triggers_payload(70.0))
    right = evaluation_fingerprint(["obs-1", "obs-2"], "reg-1", _triggers_payload(70.0))
    assert left == right
    assert left.startswith("sha256:")


def test_fingerprint_ignores_observation_order() -> None:
    ordered = evaluation_fingerprint(["obs-1", "obs-2"], "reg-1", _triggers_payload(70.0))
    reversed_ids = evaluation_fingerprint(["obs-2", "obs-1"], "reg-1", _triggers_payload(70.0))
    assert ordered == reversed_ids


def test_fingerprint_changes_with_the_observation_set() -> None:
    base = evaluation_fingerprint(["obs-1", "obs-2"], "reg-1", _triggers_payload(70.0))
    added = evaluation_fingerprint(["obs-1", "obs-2", "obs-3"], "reg-1", _triggers_payload(70.0))
    removed = evaluation_fingerprint(["obs-1"], "reg-1", _triggers_payload(70.0))
    assert added != base
    assert removed != base


def test_fingerprint_changes_with_the_registration() -> None:
    base = evaluation_fingerprint(["obs-1"], "reg-1", _triggers_payload(70.0))
    other_id = evaluation_fingerprint(["obs-1"], "reg-2", _triggers_payload(70.0))
    other_triggers = evaluation_fingerprint(["obs-1"], "reg-1", _triggers_payload(60.0))
    no_registration = evaluation_fingerprint(["obs-1"], None, None)
    assert other_id != base
    assert other_triggers != base
    assert no_registration != base


def test_fingerprint_covers_raw_json_for_corrupt_registrations() -> None:
    raw = [{"kind": "threshold", "name": "broken"}]
    first = evaluation_fingerprint(["obs-1"], None, raw)
    second = evaluation_fingerprint(["obs-1"], None, raw)
    assert first == second
    assert first != evaluation_fingerprint(["obs-1"], None, [{"kind": "threshold"}])


# --------------------------------------------------------- registration pick


def test_select_registration_returns_none_without_registrations() -> None:
    assert select_registration([]) is None


def test_select_registration_prefers_the_latest_active() -> None:
    registrations = [
        _registration("reg-1", "active"),
        _registration("reg-2", "superseded"),
        _registration("reg-3", "active"),
    ]
    assert select_registration(registrations).id == "reg-3"


def test_select_registration_falls_back_to_the_latest_overall() -> None:
    registrations = [
        _registration("reg-1", "superseded"),
        _registration("reg-2", "superseded"),
    ]
    assert select_registration(registrations).id == "reg-2"


# ------------------------------------------------------------------- summary


def test_summary_is_no_data_without_triggers() -> None:
    assert summarize_outcomes([], has_triggers=False) == "no_data"


def test_summary_is_no_data_when_nothing_was_evaluated() -> None:
    assert summarize_outcomes([], has_triggers=True) == "no_data"
    outcomes = [_outcome("a", "no_data", False), _outcome("b", "no_data", False)]
    assert summarize_outcomes(outcomes, has_triggers=True) == "no_data"


def test_summary_is_quiet_when_evaluated_and_none_fired() -> None:
    outcomes = [_outcome("a", "quiet", False), _outcome("b", "no_data", False)]
    assert summarize_outcomes(outcomes, has_triggers=True) == "quiet"


def test_summary_is_fired_when_any_trigger_fired() -> None:
    outcomes = [
        _outcome("a", "quiet", False),
        _outcome("b", "fired", True),
        _outcome("c", "no_data", False),
    ]
    assert summarize_outcomes(outcomes, has_triggers=True) == "fired"
