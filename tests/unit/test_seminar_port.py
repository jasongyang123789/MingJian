"""Parameterized port tests (Sprint 16).

Endpoint resolution (target + inline forms) and availability — no
network calls. The live call path is fixture-driven only in S16; the
port's generate_json is exercised through the fake-port seminar tests.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from planagent.config import Settings
from planagent.config.openai import OpenAIConfig, OpenAITargetConfig
from planagent.services.seminar.models import EndpointConfig, ModelPortConfig
from planagent.services.seminar.port import (
    ParameterizedSkillPort,
    ResolvedEndpoint,
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


# ---------------------------------------------------------------------------
# Finish-reason threading (fix batch 2): the port reads the SDK finish
# reason off the response and carries it on SkillLLMResponse, so a
# truncated response (payload None + "length") is classifiable. The
# fake client is injected the same way fix batch 1 injected one into
# OpenAIService: no network, no LLM call.
# ---------------------------------------------------------------------------


class _FakePortCompletions:
    def __init__(
        self,
        content: str,
        *,
        finish_reason: str | None,
        usage: SimpleNamespace | None = None,
    ) -> None:
        self.content = content
        self.finish_reason = finish_reason
        self.usage = usage
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        message = SimpleNamespace(content=self.content)
        choice_kwargs: dict[str, Any] = {"message": message}
        if self.finish_reason is not None:
            choice_kwargs["finish_reason"] = self.finish_reason
        return SimpleNamespace(
            choices=[SimpleNamespace(**choice_kwargs)],
            usage=self.usage,
        )


class _FakePortClient:
    def __init__(self, completions: _FakePortCompletions) -> None:
        self.chat = SimpleNamespace(completions=completions)


def _port_with_fake_client(completions: _FakePortCompletions) -> ParameterizedSkillPort:
    resolved = ResolvedEndpoint(
        base_url="https://fake.example/v1",
        api_key="fake-key",
        model="fake-model",
        temperature=0.3,
        timeout_seconds=180.0,
    )
    port = ParameterizedSkillPort(resolved)
    port._client = _FakePortClient(completions)  # type: ignore[assignment]
    return port


async def test_port_reports_length_and_none_payload_on_truncated_json() -> None:
    truncated = '{"critique": [{"weak_point": "x", "reason": "y"}], "responses": ["cut'
    completions = _FakePortCompletions(
        truncated,
        finish_reason="length",
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=8000, total_tokens=8100),
    )
    port = _port_with_fake_client(completions)
    response = await port.generate_json(
        template_id="seminar.reflect",
        system_prompt="s",
        user_content="u",
        max_tokens=8000,
    )
    assert response.payload is None
    assert response.finish_reason == "length"
    assert response.model == "fake-model"
    assert response.usage is not None
    assert response.usage.completion_tokens == 8000
    assert completions.calls[0]["max_tokens"] == 8000


async def test_port_reports_stop_and_parsed_payload_on_complete_json() -> None:
    completions = _FakePortCompletions('{"a": 1}', finish_reason="stop")
    port = _port_with_fake_client(completions)
    response = await port.generate_json(
        template_id="seminar.reflect",
        system_prompt="s",
        user_content="u",
        max_tokens=8000,
    )
    assert response.payload == {"a": 1}
    assert response.finish_reason == "stop"


async def test_port_reports_no_finish_reason_when_sdk_omits_it() -> None:
    completions = _FakePortCompletions('{"a": 1}', finish_reason=None)
    port = _port_with_fake_client(completions)
    response = await port.generate_json(
        template_id="seminar.reflect",
        system_prompt="s",
        user_content="u",
        max_tokens=8000,
    )
    assert response.payload == {"a": 1}
    assert response.finish_reason is None


# ---------------------------------------------------------------------------
# Empty-response signal (retry track): the port inspects the raw
# content and flags an EMPTY response explicitly, so the retry
# wrapper can retry a transient upstream gap while malformed content
# stays a plain contract failure. The 2026-11-17 live shape is
# empty content + no finish reason + no usage.
# ---------------------------------------------------------------------------


async def _call_port(port: ParameterizedSkillPort):
    return await port.generate_json(
        template_id="seminar.reflect",
        system_prompt="s",
        user_content="u",
        max_tokens=8000,
    )


async def test_port_flags_empty_content_as_empty_response() -> None:
    completions = _FakePortCompletions("", finish_reason=None, usage=None)
    port = _port_with_fake_client(completions)
    response = await _call_port(port)
    assert response.payload is None
    assert response.empty_response is True
    assert response.finish_reason is None
    assert response.usage is None
    assert response.model == "fake-model"


async def test_port_flags_whitespace_content_as_empty_response() -> None:
    completions = _FakePortCompletions("  \n\t ", finish_reason=None)
    port = _port_with_fake_client(completions)
    response = await _call_port(port)
    assert response.payload is None
    assert response.empty_response is True


async def test_port_flags_missing_choices_as_empty_response() -> None:
    class _NoChoiceCompletions:
        async def create(self, **kwargs: Any) -> SimpleNamespace:
            return SimpleNamespace(choices=[], usage=None)

    port = _port_with_fake_client(_NoChoiceCompletions())  # type: ignore[arg-type]
    response = await _call_port(port)
    assert response.payload is None
    assert response.empty_response is True
    assert response.finish_reason is None


async def test_port_flags_null_content_as_empty_response() -> None:
    class _NullContentCompletions:
        async def create(self, **kwargs: Any) -> SimpleNamespace:
            choice = SimpleNamespace(message=SimpleNamespace(content=None))
            return SimpleNamespace(choices=[choice], usage=None)

    port = _port_with_fake_client(_NullContentCompletions())  # type: ignore[arg-type]
    response = await _call_port(port)
    assert response.payload is None
    assert response.empty_response is True


async def test_port_does_not_flag_malformed_content_as_empty() -> None:
    # Non-empty content that does not parse: malformed, never
    # retried — the empty flag stays False.
    completions = _FakePortCompletions("not json at all", finish_reason="stop")
    port = _port_with_fake_client(completions)
    response = await _call_port(port)
    assert response.payload is None
    assert response.empty_response is False
    assert response.finish_reason == "stop"


async def test_port_does_not_flag_truncated_content_as_empty() -> None:
    truncated = '{"critique": [{"weak_point": "x", "reason": "y"}], "responses": ["cut'
    completions = _FakePortCompletions(truncated, finish_reason="length")
    port = _port_with_fake_client(completions)
    response = await _call_port(port)
    assert response.payload is None
    assert response.empty_response is False
    assert response.finish_reason == "length"


async def test_port_does_not_flag_sdk_failure_as_empty() -> None:
    # A failed SDK call collapses to payload None with NO signal: a
    # failed call is not an observed empty response.
    class _RaisingCompletions:
        async def create(self, **kwargs: Any) -> SimpleNamespace:
            raise RuntimeError("upstream 500")

    port = _port_with_fake_client(_RaisingCompletions())  # type: ignore[arg-type]
    response = await _call_port(port)
    assert response.payload is None
    assert response.empty_response is False
    assert response.model is None


async def test_port_does_not_flag_valid_json_as_empty() -> None:
    completions = _FakePortCompletions('{"a": 1}', finish_reason="stop")
    port = _port_with_fake_client(completions)
    response = await _call_port(port)
    assert response.payload == {"a": 1}
    assert response.empty_response is False
