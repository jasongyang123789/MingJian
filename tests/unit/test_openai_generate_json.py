"""Unit tests for ``OpenAIService.generate_json_for_target`` (fix batch 1).

No test pinned the REAL method before this batch — callers were tested
through fakes — which is how the str-vs-dict bug shipped: the method
returned ``(meta, None)`` for every successful response, so every live
skill stage failed. These tests run the real method against a fake SDK
client: no network, no LLM call. The fake records the request and
returns scripted content.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from planagent.config import Settings
from planagent.services.openai_client import OpenAIService


class _FakeCompletions:
    def __init__(
        self,
        content: str | None,
        *,
        error: Exception | None = None,
        finish_reason: str | None = None,
        report_finish_reason: bool = False,
    ) -> None:
        self.content = content
        self.error = error
        self.finish_reason = finish_reason
        self.report_finish_reason = report_finish_reason
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        message = SimpleNamespace(content=self.content)
        choice_kwargs: dict[str, Any] = {"message": message}
        if self.report_finish_reason:
            choice_kwargs["finish_reason"] = self.finish_reason
        return SimpleNamespace(choices=[SimpleNamespace(**choice_kwargs)])


class _FakeClient:
    def __init__(
        self,
        content: str | None,
        *,
        error: Exception | None = None,
        finish_reason: str | None = None,
        report_finish_reason: bool = False,
    ) -> None:
        self.completions = _FakeCompletions(
            content,
            error=error,
            finish_reason=finish_reason,
            report_finish_reason=report_finish_reason,
        )
        self.chat = SimpleNamespace(completions=self.completions)


def _service_with_fake_client(
    content: str | None,
    *,
    model: str = "fake-model",
    error: Exception | None = None,
    finish_reason: str | None = None,
    report_finish_reason: bool = False,
) -> tuple[OpenAIService, _FakeClient]:
    settings = Settings(_env_file=None)
    settings.openai.primary.model = model
    service = OpenAIService(settings)
    fake = _FakeClient(
        content,
        error=error,
        finish_reason=finish_reason,
        report_finish_reason=report_finish_reason,
    )
    service.clients["primary"] = fake  # type: ignore[dict-item]
    return service, fake


async def test_valid_json_object_returns_dict_and_meta() -> None:
    service, fake = _service_with_fake_client('{"wave_plan": ["a"], "n": 1}')
    meta, parsed = await service.generate_json_for_target(
        target="primary", system_prompt="sys", user_content="user", max_tokens=500
    )
    # Fix batch 2: meta carries finish_reason (None here — the fake
    # response reports none, and absence is reported, not fabricated).
    assert meta == {
        "model": "fake-model",
        "api_mode": "chat.completions.json",
        "finish_reason": None,
    }
    assert parsed == {"wave_plan": ["a"], "n": 1}
    assert len(fake.completions.calls) == 1
    call = fake.completions.calls[0]
    assert call["model"] == "fake-model"
    assert call["temperature"] == 0.3
    assert call["response_format"] == {"type": "json_object"}
    assert call["max_tokens"] == 500
    assert call["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "user"},
    ]


async def test_fenced_json_returns_dict() -> None:
    service, _fake = _service_with_fake_client('```json\n{"a": 1}\n```')
    meta, parsed = await service.generate_json_for_target(
        target="primary", system_prompt="sys", user_content="user"
    )
    assert meta is not None
    assert parsed == {"a": 1}


async def test_prose_wrapped_json_returns_dict() -> None:
    service, _fake = _service_with_fake_client('Here is the result: {"a": 1} hope it helps.')
    _meta, parsed = await service.generate_json_for_target(
        target="primary", system_prompt="sys", user_content="user"
    )
    assert parsed == {"a": 1}


async def test_json_array_returns_none_payload() -> None:
    service, _fake = _service_with_fake_client("[1, 2]")
    meta, parsed = await service.generate_json_for_target(
        target="primary", system_prompt="sys", user_content="user"
    )
    assert meta is not None
    assert parsed is None


async def test_json_string_returns_none_payload() -> None:
    service, _fake = _service_with_fake_client('"hello"')
    meta, parsed = await service.generate_json_for_target(
        target="primary", system_prompt="sys", user_content="user"
    )
    assert meta is not None
    assert parsed is None


async def test_invalid_json_returns_none_payload() -> None:
    service, _fake = _service_with_fake_client("not json at all")
    meta, parsed = await service.generate_json_for_target(
        target="primary", system_prompt="sys", user_content="user"
    )
    assert meta is not None
    assert parsed is None


async def test_none_content_returns_empty_dict() -> None:
    service, _fake = _service_with_fake_client(None)
    meta, parsed = await service.generate_json_for_target(
        target="primary", system_prompt="sys", user_content="user"
    )
    assert meta is not None
    assert parsed == {}


async def test_empty_content_returns_empty_dict() -> None:
    service, _fake = _service_with_fake_client("")
    meta, parsed = await service.generate_json_for_target(
        target="primary", system_prompt="sys", user_content="user"
    )
    assert meta is not None
    assert parsed == {}


async def test_unconfigured_target_returns_none_none() -> None:
    service = OpenAIService(Settings(_env_file=None))
    meta, parsed = await service.generate_json_for_target(
        target="primary", system_prompt="sys", user_content="user"
    )
    assert meta is None
    assert parsed is None


async def test_missing_model_returns_none_none_without_calling_client() -> None:
    service, fake = _service_with_fake_client('{"a": 1}', model="")
    meta, parsed = await service.generate_json_for_target(
        target="primary", system_prompt="sys", user_content="user"
    )
    assert meta is None
    assert parsed is None
    assert fake.completions.calls == []


async def test_client_error_returns_none_none() -> None:
    service, _fake = _service_with_fake_client('{"a": 1}', error=RuntimeError("boom"))
    meta, parsed = await service.generate_json_for_target(
        target="primary", system_prompt="sys", user_content="user"
    )
    assert meta is None
    assert parsed is None


async def test_truncated_response_reports_length_in_meta_and_none_payload() -> None:
    # Fix batch 2 regression shape: content cut mid-string at the cap
    # (the live 2026-11-16 diagnose output ended mid-string at
    # "Undefined product scope"). The payload is unusable AND the meta
    # says why — the combination the old code could not observe.
    truncated = '{"findings": ["a", "b"], "barriers": ["Undefined product scope'
    service, _fake = _service_with_fake_client(
        truncated, finish_reason="length", report_finish_reason=True
    )
    meta, parsed = await service.generate_json_for_target(
        target="primary", system_prompt="sys", user_content="user", max_tokens=1500
    )
    assert parsed is None
    assert meta is not None
    assert meta["finish_reason"] == "length"


async def test_stop_finish_reason_reported_in_meta() -> None:
    service, _fake = _service_with_fake_client(
        '{"a": 1}', finish_reason="stop", report_finish_reason=True
    )
    meta, parsed = await service.generate_json_for_target(
        target="primary", system_prompt="sys", user_content="user"
    )
    assert parsed == {"a": 1}
    assert meta is not None
    assert meta["finish_reason"] == "stop"


async def test_default_max_tokens_is_the_shared_loose_cap() -> None:
    # Fix batch 2: callers that omit max_tokens get the shared 8000
    # cap, not the old 1000 default (a cliff for any JSON contract).
    from planagent.services.skills.templates import JSON_CONTRACT_MAX_TOKENS

    service, fake = _service_with_fake_client('{"a": 1}')
    await service.generate_json_for_target(
        target="primary", system_prompt="sys", user_content="user"
    )
    assert len(fake.completions.calls) == 1
    assert fake.completions.calls[0]["max_tokens"] == 8000
    assert fake.completions.calls[0]["max_tokens"] == JSON_CONTRACT_MAX_TOKENS
