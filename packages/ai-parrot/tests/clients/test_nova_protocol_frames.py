import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from parrot.clients.amazon.nova import NovaClient


def _client():
    with patch.dict(sys.modules, {"aws_sdk_bedrock_runtime": MagicMock()}):
        return NovaClient(model="nova-2-sonic", region="us-east-1", voice_id="matthew")


async def _capture_opening_frames(client, system_prompt="be brief"):
    """Drive stream_voice() far enough to capture the opening sequence.

    ``stream_voice()`` calls the lazy ``_require_voice_sdk()`` guard before
    the mocked wrappers run (mirrors ``test_nova.py``'s ``nova_client``
    fixture), so ``sys.modules['aws_sdk_bedrock_runtime']`` is stubbed for
    the duration of the call — this exercises protocol logic only, on both
    Python 3.11 (SDK absent) and 3.13 (SDK present).
    """
    sent = []

    async def capture(_stream, event):
        sent.append(event)

    async def audio():
        yield b"\x00\x01" * 8
        yield None

    async def no_events(_stream):
        return
        yield  # pragma: no cover — makes this an async generator

    with (
        patch.dict(sys.modules, {"aws_sdk_bedrock_runtime": MagicMock()}),
        patch.object(client, "_open_stream", return_value=AsyncMock()),
        patch.object(client, "_send_event", new=capture),
        patch.object(client, "_iter_events", new=no_events),
        patch.object(client, "_close_stream", new=AsyncMock()),
    ):
        async for _ in client.stream_voice(audio(), system_prompt=system_prompt):
            pass
    return sent


def _frame(sent, name):
    return next(e["event"][name] for e in sent if name in e.get("event", {}))


class TestOpeningSequence:
    @pytest.mark.asyncio
    async def test_audio_output_declares_audio_type_speech(self):
        sent = await _capture_opening_frames(_client())
        assert _frame(sent, "promptStart")["audioOutputConfiguration"]["audioType"] == "SPEECH"

    @pytest.mark.asyncio
    async def test_prompt_start_declares_tool_use_output_configuration(self):
        sent = await _capture_opening_frames(_client())
        assert "toolUseOutputConfiguration" in _frame(sent, "promptStart")

    @pytest.mark.asyncio
    async def test_audio_content_start_is_interactive(self):
        sent = await _capture_opening_frames(_client())
        audio_starts = [
            e["event"]["contentStart"]
            for e in sent
            if "contentStart" in e.get("event", {}) and e["event"]["contentStart"].get("type") == "AUDIO"
        ]
        assert audio_starts[0]["interactive"] is True
        assert audio_starts[0]["audioInputConfiguration"]["audioType"] == "SPEECH"

    @pytest.mark.asyncio
    async def test_system_content_start_shape(self):
        sent = await _capture_opening_frames(_client())
        sys_starts = [
            e["event"]["contentStart"]
            for e in sent
            if "contentStart" in e.get("event", {}) and e["event"]["contentStart"].get("role") == "SYSTEM"
        ]
        assert sys_starts[0]["interactive"] is False
        assert sys_starts[0]["textInputConfiguration"] == {"mediaType": "text/plain"}
