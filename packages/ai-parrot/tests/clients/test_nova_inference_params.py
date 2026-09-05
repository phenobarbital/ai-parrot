"""Tests for VoiceConfig inference-parameter threading into Nova Sonic's
sessionStart event (FEAT-416, TASK-2147).

Note: the task file names this
``tests/clients/nova/test_nova_inference_params.py``, but no
``tests/clients/nova/`` subpackage exists anywhere in this repo — every
sibling Nova test lives flat under ``tests/clients/`` as
``test_nova_*.py`` (see ``test_nova_protocol_frames.py``,
``test_nova_tool_configuration.py``, etc.). This file follows that
existing convention instead of introducing a new subdirectory.
"""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from parrot.clients.amazon.nova import NovaClient


def _client():
    with patch.dict(sys.modules, {"aws_sdk_bedrock_runtime": MagicMock()}):
        return NovaClient(model="nova-2-sonic", region="us-east-1", voice_id="matthew")


async def _capture_opening_frames(client, **stream_voice_kwargs):
    """Drive stream_voice() far enough to capture the opening sequence.

    Mirrors the ``_capture_opening_frames`` helper in
    ``test_nova_protocol_frames.py``.
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
        async for _ in client.stream_voice(audio(), **stream_voice_kwargs):
            pass
    return sent


def _session_start(sent):
    return next(e["event"]["sessionStart"] for e in sent if "sessionStart" in e.get("event", {}))


class TestNovaInferenceParams:
    @pytest.mark.asyncio
    async def test_custom_inference_params_in_session_start(self):
        """stream_voice() sends custom maxTokens/topP/temperature."""
        sent = await _capture_opening_frames(
            _client(),
            temperature=0.5,
            max_tokens=2048,
            top_p=0.95,
        )
        inference_config = _session_start(sent)["inferenceConfiguration"]
        assert inference_config["maxTokens"] == 2048
        assert inference_config["topP"] == 0.95
        assert inference_config["temperature"] == 0.5

    @pytest.mark.asyncio
    async def test_default_inference_params(self):
        """stream_voice() uses 4096/0.9/0.7 when no kwargs given.

        FEAT-418 (TASK-2170): the hardcoded max_tokens fallback of 1024
        was replaced with the shared VoiceConfig default of 4096 (spec §8
        resolved decision) — this was 1024 before TASK-2170.
        """
        sent = await _capture_opening_frames(_client())
        inference_config = _session_start(sent)["inferenceConfiguration"]
        assert inference_config["maxTokens"] == 4096
        assert inference_config["topP"] == 0.9
        assert inference_config["temperature"] == 0.7
