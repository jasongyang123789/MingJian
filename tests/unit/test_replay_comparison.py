"""Unit tests for replay hash comparison (Sprint 3)."""

from __future__ import annotations

from planagent.services.simulation.distributions import compare_snapshot_hashes


def test_matching_trajectories_match() -> None:
    hashes = {"0": "sha256:a", "1": "sha256:b", "2": "sha256:c"}
    assert compare_snapshot_hashes(hashes, dict(hashes)) == (True, None)


def test_first_diverging_tick_is_reported() -> None:
    original = {"0": "sha256:a", "1": "sha256:b", "2": "sha256:c"}
    replay = {"0": "sha256:a", "1": "sha256:X", "2": "sha256:c"}
    assert compare_snapshot_hashes(original, replay) == (False, 1)


def test_divergence_at_tick_zero_is_reported() -> None:
    original = {"0": "sha256:a", "1": "sha256:b"}
    replay = {"0": "sha256:X", "1": "sha256:b"}
    assert compare_snapshot_hashes(original, replay) == (False, 0)


def test_missing_and_extra_ticks_count_as_divergence() -> None:
    original = {"0": "sha256:a", "1": "sha256:b", "2": "sha256:c"}
    short = {"0": "sha256:a", "1": "sha256:b"}
    assert compare_snapshot_hashes(original, short) == (False, 2)
    assert compare_snapshot_hashes(short, original) == (False, 2)


def test_numeric_tick_order_not_lexicographic() -> None:
    original = {str(tick): f"sha256:{tick}" for tick in range(12)}
    replay = dict(original, **{"10": "sha256:X"})
    assert compare_snapshot_hashes(original, replay) == (False, 10)
