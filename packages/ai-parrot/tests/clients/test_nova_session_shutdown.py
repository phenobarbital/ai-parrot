import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from parrot.clients.nova import NovaClient

END = {"completionEnd": {}}


def _make_client():
    with patch.dict(sys.modules, {'aws_sdk_bedrock_runtime': MagicMock()}):
        return NovaClient(model="nova-2-sonic", region="us-east-1")


async def _run(frames, send_event=None):
    """Drive stream_voice() with already-unwrapped frames.

    ``stream_voice()`` calls the lazy ``_require_voice_sdk()`` guard before
    the mocked wrappers run, so ``sys.modules['aws_sdk_bedrock_runtime']`` is
    stubbed for the duration (mirrors ``test_nova.py``'s ``nova_client``
    fixture) — this exercises protocol logic only, on both Python 3.11 (SDK
    absent) and 3.13 (SDK present).
    """
    client = _make_client()
    calls = []

    async def capture(_stream, event):
        calls.append(("send", next(iter(event.get("event", {})), None)))
        if send_event is not None:
            await send_event(_stream, event)

    async def close(_stream):
        calls.append(("close", None))

    async def iter_events(_stream):
        for f in frames:
            yield f

    async def audio():
        yield b"\x00\x01" * 8
        yield None

    with patch.dict(sys.modules, {'aws_sdk_bedrock_runtime': MagicMock()}), \
         patch.object(client, "_open_stream", return_value=AsyncMock()), \
         patch.object(client, "_send_event", new=capture), \
         patch.object(client, "_iter_events", new=iter_events), \
         patch.object(client, "_close_stream", new=close):
        out = [r async for r in client.stream_voice(audio())]
    return out, calls


class TestGracefulShutdown:
    @pytest.mark.asyncio
    async def test_prompt_end_then_session_end_then_close(self):
        _, calls = await _run([END])
        names = [name for kind, name in calls if kind == "send"]
        assert names[-2:] == ["promptEnd", "sessionEnd"]
        assert calls[-1] == ("close", None)

    @pytest.mark.asyncio
    async def test_prompt_end_carries_prompt_name(self):
        client = _make_client()
        sent = []

        async def capture(_stream, event):
            sent.append(event)

        async def iter_events(_stream):
            yield END

        async def audio():
            yield None

        with patch.dict(sys.modules, {'aws_sdk_bedrock_runtime': MagicMock()}), \
             patch.object(client, "_open_stream", return_value=AsyncMock()), \
             patch.object(client, "_send_event", new=capture), \
             patch.object(client, "_iter_events", new=iter_events), \
             patch.object(client, "_close_stream", new=AsyncMock()):
            async for _ in client.stream_voice(audio()):
                pass

        prompt_start = next(e["event"]["promptStart"] for e in sent
                            if "promptStart" in e.get("event", {}))
        prompt_end = next(e["event"]["promptEnd"] for e in sent
                          if "promptEnd" in e.get("event", {}))
        assert prompt_end["promptName"] == prompt_start["promptName"]
        session_end = next(e["event"]["sessionEnd"] for e in sent
                           if "sessionEnd" in e.get("event", {}))
        assert session_end == {}

    @pytest.mark.asyncio
    async def test_shutdown_failure_does_not_raise(self):
        async def boom(_stream, event):
            if "promptEnd" in event.get("event", {}):
                raise RuntimeError("stream already closed")

        out, calls = await _run([END], send_event=boom)
        assert out[-1].is_complete is True
        assert calls[-1] == ("close", None)

    @pytest.mark.asyncio
    async def test_shutdown_does_not_mask_turn_error(self):
        """The turn's own failure must still reach the caller."""
        client = _make_client()

        async def failing_events(_stream):
            raise RuntimeError("original turn failure")
            yield  # pragma: no cover

        async def boom(_stream, event):
            if "promptEnd" in event.get("event", {}):
                raise RuntimeError("shutdown also failed")

        async def audio():
            yield None

        with patch.dict(sys.modules, {'aws_sdk_bedrock_runtime': MagicMock()}), \
             patch.object(client, "_open_stream", return_value=AsyncMock()), \
             patch.object(client, "_send_event", new=boom), \
             patch.object(client, "_iter_events", new=failing_events), \
             patch.object(client, "_close_stream", new=AsyncMock()):
            out = [r async for r in client.stream_voice(audio())]

        assert "original turn failure" in out[-1].metadata["error"]
