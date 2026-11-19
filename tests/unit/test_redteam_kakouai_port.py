"""Unit tests for the Kakouai live-LLM port (vault-backed helper script).

The port shells out to the approved helper; these tests use a fake
helper script in tmp_path so no network and no credential are involved.
The real helper is validated live (once, manually) outside the suite —
see TRACK8-RED-TEAM.md.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from planagent.services.redteam.kakouai_port import KakouaiCliPort
from planagent.services.skills.orchestration import SkillLLMUnavailable

FAKE_OK = {
    "status": 200,
    "body": {
        "choices": [
            {
                "message": {
                    "content": json.dumps({"findings": [{"kind": "missing_driver", "target": "x"}]})
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    },
}


def _write_helper(tmp_path: Path, envelope: dict, *, exit_code: int = 0) -> Path:
    helper = tmp_path / "kakouai.py"
    helper.write_text(
        f"import json, sys\nprint(json.dumps({envelope!r}))\nsys.exit({exit_code})\n",
        encoding="utf-8",
    )
    helper.chmod(helper.stat().st_mode | stat.S_IEXEC)
    return helper


async def test_missing_helper_is_unavailable(tmp_path: Path) -> None:
    port = KakouaiCliPort(helper_path=tmp_path / "nope.py")
    assert port.is_available() is False
    with pytest.raises(SkillLLMUnavailable, match="not present"):
        await port.generate_json(
            template_id="redteam.challenge",
            system_prompt="s",
            user_content="u",
            max_tokens=100,
        )


async def test_success_parses_content_usage_and_finish_reason(tmp_path: Path) -> None:
    port = KakouaiCliPort(helper_path=_write_helper(tmp_path, FAKE_OK))
    assert port.is_available() is True
    response = await port.generate_json(
        template_id="redteam.challenge",
        system_prompt="s",
        user_content="u",
        max_tokens=100,
    )
    assert response.model == "gpt-6.1-sol"
    assert response.payload == {"findings": [{"kind": "missing_driver", "target": "x"}]}
    assert response.finish_reason == "stop"
    assert response.usage is not None
    assert response.usage.total_tokens == 15
    assert response.empty_response is False


async def test_non_200_is_unavailable(tmp_path: Path) -> None:
    port = KakouaiCliPort(
        helper_path=_write_helper(
            tmp_path, {"status": 402, "body": {"error": "insufficient_balance"}}
        )
    )
    with pytest.raises(SkillLLMUnavailable, match="402"):
        await port.generate_json(
            template_id="redteam.challenge",
            system_prompt="s",
            user_content="u",
            max_tokens=100,
        )


async def test_empty_choices_is_empty_response(tmp_path: Path) -> None:
    port = KakouaiCliPort(
        helper_path=_write_helper(tmp_path, {"status": 200, "body": {"choices": []}})
    )
    response = await port.generate_json(
        template_id="redteam.challenge",
        system_prompt="s",
        user_content="u",
        max_tokens=100,
    )
    assert response.payload is None
    assert response.empty_response is True


async def test_nonzero_exit_is_unavailable(tmp_path: Path) -> None:
    port = KakouaiCliPort(helper_path=_write_helper(tmp_path, FAKE_OK, exit_code=1))
    with pytest.raises(SkillLLMUnavailable, match="exit 1"):
        await port.generate_json(
            template_id="redteam.challenge",
            system_prompt="s",
            user_content="u",
            max_tokens=100,
        )


async def test_unparseable_stdout_is_unavailable(tmp_path: Path) -> None:
    helper = tmp_path / "kakouai.py"
    helper.write_text("print('not json at all')\n", encoding="utf-8")
    port = KakouaiCliPort(helper_path=helper)
    with pytest.raises(SkillLLMUnavailable, match="unparseable"):
        await port.generate_json(
            template_id="redteam.challenge",
            system_prompt="s",
            user_content="u",
            max_tokens=100,
        )
