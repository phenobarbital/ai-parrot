"""Unit tests for ``OpenAIClient``'s opt-in to ``max_completion_tokens``.

Hotfix ``openai-max-completion-tokens`` (no Jira ticket, FEAT-466) — see
``sdd/specs/openai-max-completion-tokens.spec.md`` §3 Module 2.
"""
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from parrot.clients.gpt import OpenAIClient


def test_openai_client_opts_in():
    assert OpenAIClient._uses_max_completion_tokens is True
    assert "gpt-5" in OpenAIClient._fixed_temperature_models


PATHS = ["ask", "ask_stream", "invoke"]


@pytest.fixture
def openai_payload_capture(bind_sdk_client):
    """Build an ``OpenAIClient`` with a fake SDK that records the kwargs
    the wire call receives, for each of the three kwargs-assembly paths.
    """

    def _factory(model: str):
        client = OpenAIClient(api_key="test-key")
        client.model = model

        seen: dict[str, Any] = {}

        async def _fake_create(*, model, messages, **kwargs):
            seen.clear()
            seen.update(kwargs)
            seen["model"] = model
            if kwargs.get("stream"):

                async def _empty_stream():
                    return
                    yield  # pragma: no cover - never reached, makes this an async generator

                return _empty_stream()
            message = SimpleNamespace(content="OK", tool_calls=None)
            choice = SimpleNamespace(message=message, finish_reason="stop")
            usage = SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2)
            return SimpleNamespace(choices=[choice], usage=usage)

        sdk = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(side_effect=_fake_create)))
        )
        bind_sdk_client(client, sdk)

        async def run(path: str, **kw):
            if path == "ask":
                await client.ask("hi", model=model, **kw)
            elif path == "ask_stream":
                async for _ in client.ask_stream("hi", model=model, **kw):
                    pass
            elif path == "invoke":
                await client.invoke("hi", model=model, **kw)
            else:
                raise ValueError(f"unknown path: {path}")

        return client, seen, run

    return _factory


@pytest.mark.asyncio
@pytest.mark.parametrize("path", PATHS)
async def test_gpt5_payload_uses_max_completion_tokens_and_drops_temperature(path, openai_payload_capture):
    """Each kwargs-assembly site reaches the SDK with the corrected payload.

    Uses a non-zero temperature deliberately: ``OpenAIClient.ask()`` has a
    pre-existing, unrelated ``if temperature:`` truthiness check
    (gpt.py) that already drops an explicit ``temperature=0.0`` before it
    ever reaches the funnel — on *every* model, not just reasoning ones.
    That is out of this hotfix's scope (spec: rename the key and drop
    temperature only for fixed-temperature models; not touch the number/
    truthiness resolution elsewhere). A non-zero value isolates the
    behaviour this task is responsible for: the hook dropping temperature
    for `gpt-5-mini` regardless of the value sent.
    """
    client, seen, run = openai_payload_capture(model="gpt-5-mini")
    await run(path, max_tokens=64, temperature=0.2)
    assert seen["max_completion_tokens"] == 64
    assert "max_tokens" not in seen
    assert "temperature" not in seen


@pytest.mark.asyncio
@pytest.mark.parametrize("path", PATHS)
async def test_gpt41_payload_keeps_temperature(path, openai_payload_capture):
    client, seen, run = openai_payload_capture(model="gpt-4.1")
    await run(path, max_tokens=64, temperature=0.5)
    assert seen["max_completion_tokens"] == 64
    assert seen["temperature"] == 0.5
