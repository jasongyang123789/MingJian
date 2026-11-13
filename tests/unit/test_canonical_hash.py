"""Unit tests for canonical JSON + SHA-256 hashing (Sprint 3).

Covers byte-stability (key order, nesting, unicode, float formatting),
the sha256: prefix, state-hash self-exclusion, sub-seed derivation, input
hashes (stability, seed sensitivity, determinism-fragment exclusion), and
rejection of non-JSON / non-finite values.
"""

from __future__ import annotations

import pytest

from planagent.services.distributions import (
    canonical_json,
    compute_input_hash,
    derive_sub_seed,
    determinism_input_fragment,
    sha256_hash,
    state_hash,
)


def test_canonical_json_is_byte_stable_regardless_of_key_order() -> None:
    first = {"b": 1, "a": {"d": [3, 2], "c": "x"}}
    second = {"a": {"c": "x", "d": [3, 2]}, "b": 1}
    assert canonical_json(first) == canonical_json(second)
    assert canonical_json(first) == '{"a":{"c":"x","d":[3,2]},"b":1}'


def test_canonical_json_keeps_unicode_unescaped_and_floats_stable() -> None:
    assert canonical_json({"name": "现金流"}) == '{"name":"现金流"}'
    assert canonical_json({"v": 0.1}) == canonical_json({"v": 0.1})
    assert canonical_json({"v": 123.0}) == '{"v":123.0}'


def test_canonical_json_rejects_non_json_and_non_finite_values() -> None:
    with pytest.raises(TypeError):
        canonical_json({"s": {1, 2}})
    with pytest.raises(ValueError):
        canonical_json({"v": float("nan")})
    with pytest.raises(ValueError):
        canonical_json({"v": float("inf")})


def test_sha256_hash_prefix_and_stability() -> None:
    digest = sha256_hash({"a": 1})
    assert digest.startswith("sha256:")
    assert len(digest) == len("sha256:") + 64
    assert sha256_hash({"a": 1}) == digest
    assert sha256_hash({"a": 2}) != digest


def test_state_hash_excludes_a_stored_state_hash_key() -> None:
    state = {"cash": 100.0, "pipeline": 1.0}
    hashed = dict(state, state_hash="sha256:whatever")
    assert state_hash(state) == state_hash(hashed)
    assert state_hash({"cash": 99.0, "pipeline": 1.0}) != state_hash(state)


def test_derive_sub_seed_is_deterministic_and_label_sensitive() -> None:
    assert derive_sub_seed(7, "monte-carlo", "0") == derive_sub_seed(7, "monte-carlo", "0")
    assert derive_sub_seed(7, "monte-carlo", "0") != derive_sub_seed(7, "monte-carlo", "1")
    assert derive_sub_seed(7, "monte-carlo", "0") != derive_sub_seed(8, "monte-carlo", "0")
    assert derive_sub_seed(7, "monte-carlo", "0") != derive_sub_seed(7, "replay", "0")
    # Fits a signed 64-bit INTEGER column (SQLite/Postgres) when stored.
    assert 0 <= derive_sub_seed(-3, "x") < 2**63


def _input_kwargs(**overrides):
    kwargs = {
        "domain_id": "corporate",
        "actor_template": "ai_model_provider",
        "tick_count": 4,
        "seed": 7,
        "company_id": "co-1",
        "force_id": None,
        "tenant_id": None,
        "preset_id": None,
        "configuration": {"initial_state": {}, "market": "ai"},
    }
    kwargs.update(overrides)
    return kwargs


def test_input_hash_stable_for_equal_inputs_and_seed_sensitive() -> None:
    assert compute_input_hash(**_input_kwargs()) == compute_input_hash(**_input_kwargs())
    assert compute_input_hash(**_input_kwargs(seed=8)) != compute_input_hash(**_input_kwargs())
    assert compute_input_hash(**_input_kwargs(tick_count=5)) != compute_input_hash(
        **_input_kwargs()
    )
    assert compute_input_hash(
        **_input_kwargs(configuration={"initial_state": {"cash": 1.0}, "market": "ai"})
    ) != compute_input_hash(**_input_kwargs())


def test_input_hash_ignores_a_stored_determinism_fragment() -> None:
    base = compute_input_hash(**_input_kwargs())
    with_fragment = compute_input_hash(
        **_input_kwargs(
            configuration={
                "initial_state": {},
                "market": "ai",
                "determinism": {"protocol": "sprint3-v1", "input_hash": "sha256:old"},
            }
        )
    )
    assert base == with_fragment


def test_determinism_input_fragment_shape() -> None:
    fragment = determinism_input_fragment(**_input_kwargs())
    assert fragment["protocol"] == "sprint3-v1"
    assert fragment["input_hash"] == compute_input_hash(**_input_kwargs())
