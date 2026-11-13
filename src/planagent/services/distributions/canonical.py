"""Canonical JSON + SHA-256 hashing for determinism hardening (Sprint 3).

Pattern ported from the adadsws deterministic market-game engine
(``market/protocols.py``): canonical JSON (sorted keys, compact separators,
UTF-8) hashed with SHA-256, digests prefixed with ``"sha256:"``; sub-seeds
derived by hashing seed material (their ``derive_sub_seed``).

One deliberate deviation: the reference avoids floats entirely (its
protocol objects use fixed-point integers), so RFC 8785 number edge cases
do not apply there. This engine's state is floats, so floats are
supported here and rely on Python's ``repr``-based float formatting, which
is deterministic for a given Python version and platform. Hashes are
therefore stable within this runtime — cross-language stability is NOT
claimed. NaN and infinities are rejected outright.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping

HASH_PROTOCOL_VERSION = "sprint3-v1"

#: Configuration key holding the input-hash fragment on a run.
DETERMINISM_CONFIGURATION_KEY = "determinism"


def _primitive(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Canonical JSON does not support NaN or infinities.")
        return value
    if isinstance(value, Mapping):
        return {str(key): _primitive(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_primitive(item) for item in value]
    raise TypeError(f"Canonical JSON does not support {type(value).__name__}.")


def canonical_json(value: Any) -> str:
    """Canonical JSON encoding: sorted keys, compact separators, UTF-8.

    Byte-stable for equal inputs: key order, whitespace, and float
    formatting are all fixed. Raises on non-JSON values and non-finite
    floats.
    """

    return json.dumps(
        _primitive(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def sha256_hash(value: Any) -> str:
    """SHA-256 of the canonical JSON encoding, ``"sha256:"``-prefixed."""

    digest = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
    return "sha256:" + digest


def state_hash(state: Mapping[str, Any]) -> str:
    """Hash of a simulation state dict.

    A ``state_hash`` key inside the state itself is excluded, so a stored
    hash never contaminates the hash of the state carrying it (same rule
    as the reference).
    """

    payload = {key: item for key, item in state.items() if key != "state_hash"}
    return sha256_hash(payload)


def derive_sub_seed(seed: int, *labels: str) -> int:
    """Derive a non-negative 64-bit sub-seed from a seed and string labels.

    The derivation hashes canonical seed material, so the same (seed,
    labels) always yields the same sub-seed and different labels yield
    (cryptographically) independent streams. Monte Carlo trials derive
    their per-trial seed from ``(base_seed, "monte-carlo", trial_index)``
    — the arm is deliberately NOT a label, so baseline/strategy pairs
    share one RNG stream (see :mod:`sampler`).
    """

    material = canonical_json(
        {"protocol": HASH_PROTOCOL_VERSION, "seed": seed, "labels": list(labels)}
    )
    return int.from_bytes(hashlib.sha256(material.encode("utf-8")).digest()[:8], "big")


def compute_input_hash(
    *,
    domain_id: str,
    actor_template: str,
    tick_count: int,
    seed: int,
    company_id: str | None,
    force_id: str | None,
    tenant_id: str | None,
    preset_id: str | None,
    configuration: Mapping[str, Any] | None,
) -> str:
    """Hash of everything a run's execution is a function of.

    The payload covers the run's identity fields (subject, tenant, preset,
    domain, actor template, tick count, seed) plus the full run
    configuration — initial state, market/theater, MECE decomposition,
    variable template/bindings, scenario and Monte Carlo fragments —
    except any stored ``determinism`` fragment itself, which is excluded
    so the hash is stable under re-computation.
    """

    payload = {
        "protocol": HASH_PROTOCOL_VERSION,
        "domain_id": domain_id,
        "actor_template": actor_template,
        "tick_count": tick_count,
        "seed": seed,
        "company_id": company_id,
        "force_id": force_id,
        "tenant_id": tenant_id,
        "preset_id": preset_id,
        "configuration": {
            key: item
            for key, item in (configuration or {}).items()
            if key != DETERMINISM_CONFIGURATION_KEY
        },
    }
    return sha256_hash(payload)


def determinism_input_fragment(
    *,
    domain_id: str,
    actor_template: str,
    tick_count: int,
    seed: int,
    company_id: str | None,
    force_id: str | None,
    tenant_id: str | None,
    preset_id: str | None,
    configuration: Mapping[str, Any] | None,
) -> dict[str, str]:
    """The ``determinism`` fragment stored in a run's configuration."""

    return {
        "protocol": HASH_PROTOCOL_VERSION,
        "input_hash": compute_input_hash(
            domain_id=domain_id,
            actor_template=actor_template,
            tick_count=tick_count,
            seed=seed,
            company_id=company_id,
            force_id=force_id,
            tenant_id=tenant_id,
            preset_id=preset_id,
            configuration=configuration,
        ),
    }
