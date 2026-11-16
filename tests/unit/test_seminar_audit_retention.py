"""Seminar Sprint 19 unit tests: audit-retention victim selection,
budget ledger roll-forward across purges, and diagnosis counters.

Pure functions only — no database, no ports.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from planagent.services.seminar.audit import (
    AuditEventKind,
    compute_diagnosis,
    ledger_totals,
    select_purge_victims,
)

NOW = datetime(2026, 11, 16, 12, 0, 0, tzinfo=UTC)


def _event(seq: int, *, age_days: float = 0.0, kind: str = "stage_call_finished") -> dict:
    return {
        "id": f"ev-{seq}",
        "seq": seq,
        "created_at": NOW - timedelta(days=age_days),
        "kind": kind,
        "detail": (
            {"usage": {"total_tokens": 10}} if kind == "stage_call_finished" else {}
        ),
    }


def _seqs(victims: list[dict]) -> list[int]:
    return [int(v["seq"]) for v in victims]


# --- select_purge_victims: keep_last_n --------------------------------------


def test_keep_last_n_deletes_oldest_only() -> None:
    events = [_event(seq) for seq in range(1, 6)]
    assert _seqs(select_purge_victims(events, keep_last_n=2, older_than_days=None, now=NOW)) == [1, 2, 3]


def test_keep_last_n_exact_limit_is_noop() -> None:
    events = [_event(seq) for seq in range(1, 6)]
    assert select_purge_victims(events, keep_last_n=5, older_than_days=None, now=NOW) == []


def test_keep_last_n_above_count_is_noop() -> None:
    events = [_event(seq) for seq in range(1, 6)]
    assert select_purge_victims(events, keep_last_n=50, older_than_days=None, now=NOW) == []


def test_keep_last_n_zero_deletes_everything() -> None:
    events = [_event(seq) for seq in range(1, 4)]
    assert _seqs(select_purge_victims(events, keep_last_n=0, older_than_days=None, now=NOW)) == [1, 2, 3]


def test_keep_last_n_uses_seq_order_not_input_order() -> None:
    events = [_event(seq) for seq in (3, 1, 5, 2, 4)]
    assert _seqs(select_purge_victims(events, keep_last_n=2, older_than_days=None, now=NOW)) == [1, 2, 3]


# --- select_purge_victims: older_than_days ----------------------------------


def test_older_than_days_deletes_only_old_events() -> None:
    events = [
        _event(1, age_days=10),
        _event(2, age_days=5),
        _event(3, age_days=1),
        _event(4, age_days=0),
    ]
    assert _seqs(select_purge_victims(events, keep_last_n=None, older_than_days=3, now=NOW)) == [1, 2]


def test_event_exactly_at_cutoff_is_kept() -> None:
    events = [_event(1, age_days=3), _event(2, age_days=0)]
    assert select_purge_victims(events, keep_last_n=None, older_than_days=3, now=NOW) == []


def test_older_than_days_zero_deletes_all_past_events() -> None:
    events = [_event(1, age_days=1), _event(2, age_days=0)]
    # Age 0 is exactly "now" — at the cutoff, so kept.
    assert _seqs(select_purge_victims(events, keep_last_n=None, older_than_days=0, now=NOW)) == [1]


# --- select_purge_victims: both criteria / validation -----------------------


def test_both_criteria_survive_only_if_both_bounds_hold() -> None:
    events = [
        _event(1, age_days=10),
        _event(2, age_days=10),
        _event(3, age_days=0),
        _event(4, age_days=0),
        _event(5, age_days=0),
    ]
    # Newest 3 are seqs 3,4,5; younger than 3 days are seqs 3,4,5.
    # Intersection keeps 3,4,5 — victims 1,2.
    assert _seqs(select_purge_victims(events, keep_last_n=3, older_than_days=3, now=NOW)) == [1, 2]


def test_both_criteria_intersection_is_strict() -> None:
    events = [
        _event(1, age_days=10),
        _event(2, age_days=0),
        _event(3, age_days=10),
        _event(4, age_days=0),
        _event(5, age_days=0),
    ]
    # Newest 3 are seqs 3,4,5; younger than 3 days are seqs 2,4,5.
    # Intersection keeps only 4,5 — seq 3 is new enough but too old.
    assert _seqs(select_purge_victims(events, keep_last_n=3, older_than_days=3, now=NOW)) == [1, 2, 3]


def test_no_criteria_deletes_nothing() -> None:
    events = [_event(seq) for seq in range(1, 4)]
    assert select_purge_victims(events, keep_last_n=None, older_than_days=None, now=NOW) == []


def test_negative_keep_last_n_rejected() -> None:
    with pytest.raises(ValueError, match="keep_last_n"):
        select_purge_victims([_event(1)], keep_last_n=-1, older_than_days=None, now=NOW)


def test_negative_older_than_days_rejected() -> None:
    with pytest.raises(ValueError, match="older_than_days"):
        select_purge_victims([_event(1)], keep_last_n=None, older_than_days=-1, now=NOW)


def test_naive_datetimes_treated_as_utc() -> None:
    naive = _event(1, age_days=10)
    naive["created_at"] = naive["created_at"].replace(tzinfo=None)  # type: ignore[union-attr]
    assert _seqs(select_purge_victims([naive], keep_last_n=None, older_than_days=3, now=NOW)) == [1]


# --- ledger roll-forward -----------------------------------------------------


def test_ledger_totals_sums_carried_purge_totals() -> None:
    events = [
        _event(1),
        _event(2),
        {
            "id": "summary",
            "seq": 3,
            "created_at": NOW,
            "kind": AuditEventKind.RETENTION_PURGED,
            "detail": {"purged_stage_calls": 5, "purged_tokens": 100},
        },
    ]
    calls, tokens = ledger_totals(events)
    assert calls == 2 + 5
    assert tokens == 20 + 100


def test_ledger_totals_chains_across_summaries() -> None:
    # A later purge that deletes an earlier summary must carry the
    # earlier summary's totals forward — ledger_totals over the
    # victims includes the summary's carried totals.
    victims = [
        _event(1),
        {
            "id": "summary-1",
            "seq": 2,
            "created_at": NOW,
            "kind": AuditEventKind.RETENTION_PURGED,
            "detail": {"purged_stage_calls": 3, "purged_tokens": 40},
        },
    ]
    calls, tokens = ledger_totals(victims)
    assert calls == 1 + 3
    assert tokens == 10 + 40


def test_ledger_totals_ignores_non_budget_kinds() -> None:
    events = [
        _event(1, kind=AuditEventKind.QUEUE_WAIT),
        _event(2, kind=AuditEventKind.REPORT_WRITTEN),
    ]
    assert ledger_totals(events) == (0, 0)


# --- diagnosis counters ------------------------------------------------------


def test_diagnosis_counts_lease_takeovers_and_purged_events() -> None:
    events = [
        _event(1, kind=AuditEventKind.LEASE_TAKEOVER),
        _event(2, kind=AuditEventKind.LEASE_TAKEOVER),
        {
            "id": "summary",
            "seq": 3,
            "created_at": NOW,
            "kind": AuditEventKind.RETENTION_PURGED,
            "detail": {"deleted_count": 7},
        },
        _event(4),
    ]
    diagnosis = compute_diagnosis(events)
    assert diagnosis.lease_takeovers == 2
    assert diagnosis.events_purged == 7
    assert diagnosis.stage_calls == 1


def test_diagnosis_purged_count_is_zero_without_summaries() -> None:
    assert compute_diagnosis([_event(1)]).events_purged == 0
    assert compute_diagnosis([_event(1)]).lease_takeovers == 0
