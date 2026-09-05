import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from parrot.clients.amazon.nova import NovaClient

ASSISTANT = {
    "contentStart": {"role": "ASSISTANT", "type": "TEXT", "additionalModelFields": '{"generationStage": "SPECULATIVE"}'}
}


async def _run(frames):
    """Feed already-unwrapped frames through stream_voice().

    ``stream_voice()`` calls the lazy ``_require_voice_sdk()`` guard before
    the mocked wrappers run, so ``sys.modules['aws_sdk_bedrock_runtime']`` is
    stubbed for the duration (mirrors ``test_nova.py``'s ``nova_client``
    fixture) — this exercises protocol logic only, on both Python 3.11 (SDK
    absent) and 3.13 (SDK present).
    """
    with patch.dict(sys.modules, {"aws_sdk_bedrock_runtime": MagicMock()}):
        client = NovaClient(model="nova-2-sonic", region="us-east-1")

    async def iter_events(_stream):
        for f in frames:
            yield f

    async def audio():
        yield b"\x00\x01" * 8
        yield None

    with (
        patch.dict(sys.modules, {"aws_sdk_bedrock_runtime": MagicMock()}),
        patch.object(client, "_open_stream", return_value=AsyncMock()),
        patch.object(client, "_send_event", new=AsyncMock()),
        patch.object(client, "_iter_events", new=iter_events),
        patch.object(client, "_close_stream", new=AsyncMock()),
    ):
        return [r async for r in client.stream_voice(audio())]


class TestBargeIn:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "payload",
        [
            '{ "interrupted" : true }',  # exact sample spacing
            '{"interrupted":true}',  # compact
            '{\n  "interrupted": true\n}',
        ],
    )
    async def test_detected_from_payload(self, payload):
        out = await _run([ASSISTANT, {"textOutput": {"content": payload}}])
        interrupted = [r for r in out if r.is_interrupted]
        assert len(interrupted) == 1
        assert interrupted[0].is_complete is True
        assert interrupted[0].turn_metadata.was_interrupted is True

    @pytest.mark.asyncio
    async def test_payload_not_emitted_as_text(self):
        out = await _run([ASSISTANT, {"textOutput": {"content": '{"interrupted":true}'}}])
        assert all("interrupted" not in (r.text or "") for r in out)

    @pytest.mark.asyncio
    async def test_ordinary_text_mentioning_interrupted_not_misdetected(self):
        out = await _run([ASSISTANT, {"textOutput": {"content": "Sorry, I interrupted you."}}, {"completionEnd": {}}])
        assert not any(r.is_interrupted for r in out)

    def test_legacy_keys_removed_from_source(self):
        """Regression guard: neither phantom key drives detection any more."""
        from pathlib import Path

        from parrot.clients.amazon.nova import audio as audio_mod

        source = Path(audio_mod.__file__).read_text(encoding="utf-8")
        assert '"interruption" in event' not in source
        assert 'stopReason") == "INTERRUPTED"' not in source
