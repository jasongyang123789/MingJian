"""Unit tests for the hindsight-firewall cutoff mechanics (Sprint 5).

Covers timestamp normalization, canonical round-tripping, fragment
resolution (including the legacy no-fragment case and malformed
fragments failing loudly), and the inclusive visibility boundary.
Engine-level behavior (claim exclusion, replay) is covered by the API
tests in ``tests/test_calibration_api.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from planagent.services.calibration import (
    CUTOFF_SOURCE_CREATION_TIME,
    CUTOFF_SOURCE_EXPLICIT,
    FIREWALL_CONFIGURATION_KEY,
    FIREWALL_PROTOCOL_VERSION,
    claim_visible_at,
    firewall_configuration_fragment,
    firewall_cutoff_from_configuration,
    format_cutoff,
    normalize_cutoff,
    parse_cutoff,
)


def test_normalize_cutoff_converts_aware_to_naive_utc() -> None:
    shanghai = timezone(timedelta(hours=8))
    aware = datetime(2026, 11, 13, 16, 0, 0, tzinfo=shanghai)
    normalized = normalize_cutoff(aware)
    assert normalized.tzinfo is None
    assert normalized == datetime(2026, 11, 13, 8, 0, 0)


def test_normalize_cutoff_keeps_naive_as_utc() -> None:
    naive = datetime(2026, 11, 13, 8, 0, 0)
    assert normalize_cutoff(naive) == naive


def test_format_parse_round_trip_is_canonical() -> None:
    value = datetime(2026, 11, 13, 8, 30, 15, 123456, tzinfo=UTC)
    text = format_cutoff(value)
    assert text == "2026-11-13T08:30:15.123456Z"
    assert parse_cutoff(text) == datetime(2026, 11, 13, 8, 30, 15, 123456)


def test_parse_cutoff_accepts_offset_and_naive_forms() -> None:
    assert parse_cutoff("2026-11-13T08:30:15+00:00") == datetime(2026, 11, 13, 8, 30, 15)
    assert parse_cutoff("2026-11-13T08:30:15") == datetime(2026, 11, 13, 8, 30, 15)
    assert parse_cutoff("2026-11-13T16:30:15+08:00") == datetime(2026, 11, 13, 8, 30, 15)


def test_parse_cutoff_rejects_garbage() -> None:
    with pytest.raises(ValueError, match="Invalid decision_time cutoff"):
        parse_cutoff("not-a-date")
    with pytest.raises(ValueError, match="Invalid decision_time cutoff"):
        parse_cutoff("")


def test_fragment_builder_records_protocol_and_source() -> None:
    fragment = firewall_configuration_fragment(
        datetime(2026, 11, 13, 8, 0, 0), CUTOFF_SOURCE_EXPLICIT
    )
    stored = fragment[FIREWALL_CONFIGURATION_KEY]
    assert stored["protocol"] == FIREWALL_PROTOCOL_VERSION
    assert stored["decision_time"] == "2026-11-13T08:00:00.000000Z"
    assert stored["cutoff_source"] == CUTOFF_SOURCE_EXPLICIT


def test_fragment_builder_rejects_unknown_source() -> None:
    with pytest.raises(ValueError, match="Unknown cutoff source"):
        firewall_configuration_fragment(datetime(2026, 11, 13), "bogus")


def test_cutoff_from_configuration_missing_fragment_is_legacy() -> None:
    assert firewall_cutoff_from_configuration(None) == (None, None)
    assert firewall_cutoff_from_configuration({}) == (None, None)
    assert firewall_cutoff_from_configuration({"other": 1}) == (None, None)


def test_cutoff_from_configuration_round_trip() -> None:
    configuration = firewall_configuration_fragment(
        datetime(2026, 11, 13, 8, 0, 0), CUTOFF_SOURCE_CREATION_TIME
    )
    cutoff, source = firewall_cutoff_from_configuration(configuration)
    assert cutoff == datetime(2026, 11, 13, 8, 0, 0)
    assert source == CUTOFF_SOURCE_CREATION_TIME


def test_cutoff_from_configuration_malformed_fails_loudly() -> None:
    with pytest.raises(ValueError, match="must be an object"):
        firewall_cutoff_from_configuration({FIREWALL_CONFIGURATION_KEY: "nope"})
    with pytest.raises(ValueError, match="missing decision_time"):
        firewall_cutoff_from_configuration(
            {FIREWALL_CONFIGURATION_KEY: {"cutoff_source": CUTOFF_SOURCE_EXPLICIT}}
        )
    with pytest.raises(ValueError, match="unknown cutoff source"):
        firewall_cutoff_from_configuration(
            {
                FIREWALL_CONFIGURATION_KEY: {
                    "decision_time": "2026-11-13T08:00:00.000000Z",
                    "cutoff_source": "bogus",
                }
            }
        )
    with pytest.raises(ValueError, match="Invalid decision_time cutoff"):
        firewall_cutoff_from_configuration(
            {
                FIREWALL_CONFIGURATION_KEY: {
                    "decision_time": "garbage",
                    "cutoff_source": CUTOFF_SOURCE_EXPLICIT,
                }
            }
        )


def test_claim_visible_at_boundary_is_inclusive() -> None:
    cutoff = datetime(2026, 11, 13, 8, 0, 0)
    assert claim_visible_at(datetime(2026, 11, 13, 7, 59, 59), cutoff) is True
    assert claim_visible_at(datetime(2026, 11, 13, 8, 0, 0), cutoff) is True
    assert claim_visible_at(datetime(2026, 11, 13, 8, 0, 0, 1), cutoff) is False


def test_claim_visible_at_none_cutoff_is_legacy_unfiltered() -> None:
    assert claim_visible_at(datetime(2026, 11, 13, 23, 59, 59), None) is True


def test_claim_visible_at_normalizes_timezones() -> None:
    shanghai = timezone(timedelta(hours=8))
    claim_time = datetime(2026, 11, 13, 16, 0, 0, tzinfo=shanghai)
    assert claim_visible_at(claim_time, datetime(2026, 11, 13, 8, 0, 0)) is True
    assert claim_visible_at(claim_time, datetime(2026, 11, 13, 7, 59, 59)) is False
