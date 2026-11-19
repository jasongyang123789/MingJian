"""Live-LLM port for the red team, backed by Kakouai via the Secure Vault.

The port implements the narrow :class:`SkillLLMPort` protocol by
invoking the approved Kakouai helper script
(``~/workspace/custom-connectors/custom.kakouai/bin/kakouai.py``) as a
subprocess. The helper is the registered ``custom.kakouai`` connection:
it places a surrogate where the provider reads the key and the auth
service swaps in the real credential only on an approved request to
the registered host (``api.kakouai.com``). This module NEVER sees, logs,
or stores the key — the key value is entered by Ho, lives in the
Secure Vault, and is never visible to the assistant.

``is_available()`` is deliberately cheap (helper file exists) and does
no network: availability of the upstream is proven at call time, and a
failed call surfaces as :class:`SkillLLMUnavailable` (HTTP 503 in
``live`` mode), never as fabricated content.

Default model ``gpt-6.1-sol`` was verified present in the account's
model list (2026-11-19, status 200). Temperature 0.3 matches the
skill-stage adapter.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from planagent.services.skills.orchestration import (
    SkillLLMResponse,
    SkillLLMUnavailable,
    TokenUsage,
)

HELPER_PATH = (
    Path.home() / "workspace" / "custom-connectors" / "custom.kakouai" / "bin" / "kakouai.py"
)
DEFAULT_MODEL = "gpt-6.1-sol"
DEFAULT_TIMEOUT_SECONDS = 120


class KakouaiCliPort:
    """SkillLLMPort backed by the Kakouai helper script (vault-backed)."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        helper_path: str | Path | None = None,
    ) -> None:
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._helper = Path(helper_path) if helper_path is not None else HELPER_PATH

    def is_available(self) -> bool:
        return self._helper.is_file()

    async def generate_json(
        self,
        *,
        template_id: str,
        system_prompt: str,
        user_content: str,
        max_tokens: int,
    ) -> SkillLLMResponse:
        if not self.is_available():
            raise SkillLLMUnavailable(
                "Kakouai helper script is not present; the live red-team "
                "path cannot run without it."
            )
        env = dict(os.environ)
        # Bracketed IPv6 entries in no_proxy crash some HTTP clients;
        # the helper sanitizes them too — keep the env clean here as well.
        for var in ("no_proxy", "NO_PROXY"):
            if "[" in env.get(var, ""):
                env[var] = "localhost,127.0.0.1"
        command = [
            "python3",
            str(self._helper),
            "chat",
            "--model",
            self._model,
            "--system",
            system_prompt,
            "--user",
            user_content,
            "--max-tokens",
            str(max_tokens),
            "--temperature",
            "0.3",
            "--json",
            "--timeout",
            str(self._timeout_seconds),
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self._timeout_seconds + 30
            )
        except (TimeoutError, OSError) as exc:
            raise SkillLLMUnavailable(f"Kakouai helper call failed to run: {exc}") from exc
        if proc.returncode != 0:
            detail = stderr.decode("utf-8", "replace")[:300] if stderr else ""
            raise SkillLLMUnavailable(
                f"Kakouai helper call failed (exit {proc.returncode}): {detail or 'no stderr'}"
            )
        try:
            envelope = json.loads(stdout.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise SkillLLMUnavailable("Kakouai helper returned unparseable output.") from exc
        status = envelope.get("status")
        body = envelope.get("body") or {}
        if status != 200:
            raise SkillLLMUnavailable(f"Kakouai API returned status {status}: {str(body)[:300]}")
        choices = body.get("choices") or []
        if not choices:
            return SkillLLMResponse(model=self._model, payload=None, empty_response=True)
        message = choices[0].get("message") or {}
        content = message.get("content")
        finish_reason = choices[0].get("finish_reason")
        usage_raw = body.get("usage") or {}
        usage = None
        if usage_raw:
            try:
                usage = TokenUsage(
                    prompt_tokens=int(usage_raw.get("prompt_tokens") or 0),
                    completion_tokens=int(usage_raw.get("completion_tokens") or 0),
                    total_tokens=int(
                        usage_raw.get("total_tokens")
                        or (usage_raw.get("prompt_tokens") or 0)
                        + (usage_raw.get("completion_tokens") or 0)
                    ),
                )
            except (TypeError, ValueError):
                usage = None
        if content is None or (isinstance(content, str) and not content.strip()):
            return SkillLLMResponse(
                model=self._model,
                payload=None,
                usage=usage,
                finish_reason=str(finish_reason) if finish_reason else None,
                empty_response=True,
            )
        if isinstance(content, dict):
            parsed = content
        else:
            try:
                parsed = json.loads(content)
            except ValueError:
                parsed = None
        return SkillLLMResponse(
            model=self._model,
            payload=parsed if isinstance(parsed, dict) else None,
            usage=usage,
            finish_reason=str(finish_reason) if finish_reason else None,
        )


__all__ = ["DEFAULT_MODEL", "HELPER_PATH", "KakouaiCliPort"]
