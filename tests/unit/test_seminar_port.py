"""Parameterized port tests (Sprint 16).

Endpoint resolution (target + inline forms) and availability — no
network calls. The live call path is fixture-driven only in S16; the
port's generate_json is exercised through the fake-port seminar tests.
"""

from __future__ import annotations

from planagent.config import Settings
from planagent.config.openai import OpenAIConfig, OpenAITargetConfig
from planagent.services.seminar.models import EndpointConfig, ModelPortConfig
from planagent.services.seminar.port import (
    ParameterizedSkillPort,
    default_port_factory,
    resolve_endpoint,
)


def _settings() -> Settings:
    return Settings(
        openai=OpenAIConfig(
            shared_api_key="shared-key",
            shared_base_url="https://shared.example/v1",
            primary=OpenAITargetConfig(model="primary-model"),
        )
    )


def _settings_no_key() -> Settings:
    return Settings(openai=OpenAIConfig(primary=OpenAITargetConfig(model="m")))


def test_resolve_target_entry_uses_settings_resolution() -> None:
    resolved = resolve_endpoint(
        _settings(),
        EndpointConfig(target="primary"),
        temperature=0.3,
        timeout_seconds=180.0,
    )
    assert resolved.api_key == "shared-key"
    assert resolved.base_url == "https://shared.example/v1"
    assert resolved.model == "primary-model"
    assert resolved.temperature == 0.3
    assert resolved.timeout_seconds == 180.0


def test_resolve_target_entry_unconfigured_when_no_key() -> None:
    settings = _settings_no_key()
    resolved = resolve_endpoint(
        settings,
        EndpointConfig(target="primary"),
        temperature=0.3,
        timeout_seconds=180.0,
    )
    assert resolved.api_key is None


def test_resolve_inline_entry_reads_named_environment_variables() -> None:
    resolved = resolve_endpoint(
        _settings(),
        EndpointConfig(
            base_url_env="SEMINAR_TEST_URL",
            api_key_env="SEMINAR_TEST_KEY",
            model="inline-model",
        ),
        temperature=0.7,
        timeout_seconds=300.0,
        env={
            "SEMINAR_TEST_URL": "https://inline.example/v1",
            "SEMINAR_TEST_KEY": "inline-key",
        },
    )
    assert resolved.base_url == "https://inline.example/v1"
    assert resolved.api_key == "inline-key"
    assert resolved.model == "inline-model"
    assert resolved.temperature == 0.7
    assert resolved.timeout_seconds == 300.0


def test_resolve_inline_entry_without_base_url_env_uses_client_default() -> None:
    resolved = resolve_endpoint(
        _settings(),
        EndpointConfig(api_key_env="SEMINAR_TEST_KEY", model="m"),
        temperature=0.3,
        timeout_seconds=60.0,
        env={"SEMINAR_TEST_KEY": "k"},
    )
    assert resolved.base_url is None
    assert resolved.api_key == "k"


def test_port_availability_requires_key_and_model() -> None:
    settings = _settings()
    available = ParameterizedSkillPort(
        resolve_endpoint(
            settings,
            EndpointConfig(target="primary"),
            temperature=0.3,
            timeout_seconds=180.0,
        )
    )
    assert available.is_available() is True
    missing_key = ParameterizedSkillPort(
        resolve_endpoint(
            settings,
            EndpointConfig(api_key_env="SEMINAR_ABSENT_KEY", model="m"),
            temperature=0.3,
            timeout_seconds=180.0,
            env={},
        )
    )
    assert missing_key.is_available() is False


def test_default_port_factory_preserves_single_model_defaults() -> None:
    """Defaults = primary target + temperature 0.3 (Sprint 6 behavior)."""
    factory = default_port_factory(_settings())
    port = factory(ModelPortConfig(model_id="solo"))
    assert port.resolved.temperature == 0.3
    assert port.resolved.model == "primary-model"
    assert port.resolved.api_key == "shared-key"


def test_endpoint_config_rejects_mixed_and_empty_forms() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        EndpointConfig(target="primary", api_key_env="K")
    with pytest.raises(ValidationError):
        EndpointConfig()
    with pytest.raises(ValidationError):
        EndpointConfig(target="not_a_target")
    with pytest.raises(ValidationError):
        EndpointConfig(api_key_env="K")  # inline without model
