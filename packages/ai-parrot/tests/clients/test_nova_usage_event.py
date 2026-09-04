import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from parrot.clients.amazon.nova import NovaClient

END = {"completionEnd": {}}


async def _run(frames):
    """Feed already-unwrapped frames through stream_voice().

    ``stream_voice()`` calls the lazy ``_require_voice_sdk()`` guard before
    the mocked wrappers run, so ``sys.modules['aws_sdk_bedrock_runtime']`` is
    stubbed for the duration (mirrors ``test_nova.py``'s ``nova_client``
    fixture) — this exercises protocol logic only, on both Python 3.11 (SDK
    absent) and 3.13 (SDK present).
    """
    with patch.dict(sys.modules, {'aws_sdk_bedrock_runtime': MagicMock()}):
        client = NovaClient(model="nova-2-sonic", region="us-east-1")

    async def iter_events(_stream):
        for f in frames:
            yield f

    async def audio():
        yield b"\x00\x01" * 8
        yield None

    with patch.dict(sys.modules, {'aws_sdk_bedrock_runtime': MagicMock()}), \
         patch.object(client, "_open_stream", return_value=AsyncMock()), \
         patch.object(client, "_send_event", new=AsyncMock()), \
         patch.object(client, "_iter_events", new=iter_events), \
         patch.object(client, "_close_stream", new=AsyncMock()):
        return [r async for r in client.stream_voice(audio())]


def _terminal_usage(out):
    return [r for r in out if r.is_complete][-1].usage


class TestUsageEvent:
    @pytest.mark.asyncio
    async def test_populates_token_counts(self):
        out = await _run([
            {"usageEvent": {"inputTokens": 12, "outputTokens": 30, "totalTokens": 42}},
            END,
        ])
        usage = _terminal_usage(out)
        assert usage.prompt_tokens == 12
        assert usage.completion_tokens == 30
        assert usage.total_tokens == 42

    @pytest.mark.asyncio
    async def test_total_derived_when_absent(self):
        out = await _run([{"usageEvent": {"inputTokens": 5, "outputTokens": 7}}, END])
        assert _terminal_usage(out).total_tokens == 12

    @pytest.mark.asyncio
    async def test_unknown_shape_tolerated(self):
        """The real schema is unverified — a wrong guess must not break voice."""
        out = await _run([{"usageEvent": {"somethingElse": {"nested": True}}}, END])
        usage = _terminal_usage(out)
        assert usage.total_tokens == 0
        assert out[-1].is_complete is True

    @pytest.mark.asyncio
    async def test_raw_frame_preserved_for_schema_discovery(self):
        frame = {"inputTokens": 1, "outputTokens": 2}
        out = await _run([{"usageEvent": frame}, END])
        assert _terminal_usage(out).extra["usage_event"] == frame

    @pytest.mark.asyncio
    async def test_websocket_usage_not_all_zero(self):
        out = await _run([
            {"usageEvent": {"inputTokens": 3, "outputTokens": 4}}, END,
        ])
        msg = [r for r in out if r.is_complete][-1].to_websocket_message()
        assert msg["usage"]["total_tokens"] == 7
