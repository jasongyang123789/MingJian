"""Unit tests for ``RuleRegistry.apply_fitted_weights`` (Sprint 5).

The fitted weights replace the current calibration weights outright
(unlike the worker's accuracy blend), are clipped to [0, 2], and the
applied mapping is returned so the caller can record exactly what
took effect.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from planagent.simulation.rules import RuleRegistry


def _registry(tmp_path: Path) -> RuleRegistry:
    return RuleRegistry(tmp_path)


def test_apply_fitted_weights_replaces_and_returns_applied(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    registry.apply_calibration({"corp.cost_pressure": 1.0})
    assert registry.calibration_weights["corp.cost_pressure"] != 1.0
    applied = registry.apply_fitted_weights({"corp.cost_pressure": 0.5, "corp.ship_momentum": 1.25})
    assert applied == {"corp.cost_pressure": 0.5, "corp.ship_momentum": 1.25}
    assert registry.calibration_weights == applied


def test_apply_fitted_weights_clips_to_zero_two(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    applied = registry.apply_fitted_weights({"a": -3.0, "b": 99.0, "c": 1.23456})
    assert applied == {"a": 0.0, "b": 2.0, "c": 1.2346}


def test_apply_fitted_weights_rejects_non_finite(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    with pytest.raises(ValueError, match="must be finite"):
        registry.apply_fitted_weights({"a": float("inf")})
    with pytest.raises(ValueError, match="must be finite"):
        registry.apply_fitted_weights({"a": float("nan")})
    assert registry.calibration_weights == {}


def test_apply_fitted_weights_empty_is_noop(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    assert registry.apply_fitted_weights({}) == {}
    assert registry.calibration_weights == {}
