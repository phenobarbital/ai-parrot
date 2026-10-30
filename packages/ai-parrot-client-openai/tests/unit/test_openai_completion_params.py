"""FEAT-770: OpenAI reasoning models need ``max_completion_tokens`` and their default temperature.

Covers ``OpenAIBaseClient._adapt_completion_params`` and that every ``OpenAIClient`` chat path
reaches the SDK through the ``_chat_completion`` funnel with adapted kwargs.
"""

import io
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.clients.openai import OpenAIClient
from parrot.clients.openai_base import OpenAIBaseClient


class _WireCaptured(Exception):
    """Raised by the fake SDK after recording the request kwargs."""


def _fake_sdk(captured: list[dict[str, Any]], *, raise_after: bool) -> MagicMock:
    """Build a fake ``AsyncOpenAI`` whose create/parse record their kwargs."""
    response = MagicMock()
    choice = MagicMock()
    choice.message.content = "OK"
    choice.message.tool_calls = None
    choice.message.function_call = None
    choice.finish_reason = "stop"
    response.choices = [choice]
    response.id = "chatcmpl-1"
    response.model = "gpt-5-mini"
    response.usage = MagicMock(prompt_tokens=3, completion_tokens=1, total_tokens=4)

    async def _record(**kwargs: Any) -> Any:
        captured.append(kwargs)
        if raise_after:
            raise _WireCaptured()
        return response

    sdk = MagicMock()
    sdk.chat.completions.create = AsyncMock(side_effect=_record)
    sdk.chat.completions.parse = AsyncMock(side_effect=_record)
    return sdk


async def _client(sdk: MagicMock) -> OpenAIClient:
    """An ``OpenAIClient`` whose per-loop SDK client is ``sdk``."""
    client = OpenAIClient(api_key="fake-key")
    client.get_client = AsyncMock(return_value=sdk)
    await client._ensure_client()
    return client


# ---------------------------------------------------------------- hook unit tests


def test_adapt_renames_and_drops_temperature_for_gpt5() -> None:
    client = OpenAIClient(api_key="fake-key")
    out = client._adapt_completion_params("gpt-5-mini", {"max_tokens": 512, "temperature": 0.0, "tools": []})
    assert out == {"max_completion_tokens": 512, "tools": []}


@pytest.mark.parametrize("model", ["o3-mini", "o4-mini", "o1", "GPT-5.4"])
def test_adapt_drops_temperature_for_reasoning_prefixes(model: str) -> None:
    client = OpenAIClient(api_key="fake-key")
    out = client._adapt_completion_params(model, {"max_tokens": 10, "temperature": 0.2})
    assert "temperature" not in out
    assert out["max_completion_tokens"] == 10


def test_adapt_keeps_temperature_for_gpt41() -> None:
    client = OpenAIClient(api_key="fake-key")
    out = client._adapt_completion_params("gpt-4.1", {"max_tokens": 256, "temperature": 0.3})
    assert out == {"max_completion_tokens": 256, "temperature": 0.3}


def test_adapt_prefix_match_is_not_substring() -> None:
    client = OpenAIClient(api_key="fake-key")
    out = client._adapt_completion_params("gpt-4o-mini", {"temperature": 0.3})
    assert out == {"temperature": 0.3}


def test_adapt_is_inert_on_base_client() -> None:
    client = OpenAIBaseClient(api_key="x", base_url="http://localhost:1/v1")
    kwargs = {"max_tokens": 512, "temperature": 0.0}
    assert client._adapt_completion_params("gpt-5-mini", kwargs) == kwargs


def test_adapt_does_not_mutate_input() -> None:
    client = OpenAIClient(api_key="fake-key")
    kwargs = {"max_tokens": 512, "temperature": 0.0}
    client._adapt_completion_params("gpt-5-mini", kwargs)
    assert kwargs == {"max_tokens": 512, "temperature": 0.0}


def test_adapt_drops_none_max_tokens() -> None:
    client = OpenAIClient(api_key="fake-key")
    out = client._adapt_completion_params("gpt-4.1", {"max_tokens": None})
    assert "max_tokens" not in out and "max_completion_tokens" not in out


def test_adapt_explicit_max_completion_tokens_wins() -> None:
    client = OpenAIClient(api_key="fake-key")
    out = client._adapt_completion_params("gpt-4.1", {"max_tokens": 10, "max_completion_tokens": 99})
    assert out == {"max_completion_tokens": 99}


# ---------------------------------------------------------------- wire tests


@pytest.mark.asyncio
async def test_ask_default_model_payload() -> None:
    captured: list[dict[str, Any]] = []
    client = await _client(_fake_sdk(captured, raise_after=True))
    with pytest.raises(_WireCaptured):
        await client.ask(prompt="Say OK.", max_tokens=128, temperature=0.4)
    assert captured, "SDK was never called"
    wire = captured[0]
    assert wire["model"] == "gpt-5-mini"
    assert "max_tokens" not in wire
    assert wire["max_completion_tokens"] == 128
    assert "temperature" not in wire


@pytest.mark.asyncio
async def test_invoke_gpt5_drops_temperature() -> None:
    captured: list[dict[str, Any]] = []
    client = await _client(_fake_sdk(captured, raise_after=True))
    with pytest.raises(Exception):
        await client.invoke("Say OK.", model="gpt-5-mini", max_tokens=64)
    assert captured, "SDK was never called"
    wire = captured[0]
    assert "temperature" not in wire
    assert "max_tokens" not in wire
    assert wire["max_completion_tokens"] == 64


@pytest.mark.asyncio
async def test_ask_to_image_routes_through_funnel() -> None:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(buf, format="PNG")
    captured: list[dict[str, Any]] = []
    client = await _client(_fake_sdk(captured, raise_after=True))
    with pytest.raises(_WireCaptured):
        await client.ask_to_image(prompt="What is this?", image=buf.getvalue(), max_tokens=32, temperature=0.5)
    assert captured, "SDK was never called"
    wire = captured[0]
    assert wire["model"] == "gpt-5-mini"
    assert "max_tokens" not in wire
    assert wire["max_completion_tokens"] == 32
    assert "temperature" not in wire
