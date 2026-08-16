import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from parrot.clients.nova import NovaClient


def _client():
    with patch.dict(sys.modules, {'aws_sdk_bedrock_runtime': MagicMock()}):
        return NovaClient(model="nova-2-sonic", region="us-east-1", voice_id="matthew")


async def _run(frames):
    """Feed already-unwrapped frames through stream_voice().

    ``stream_voice()`` calls the lazy ``_require_voice_sdk()`` guard before
    the mocked wrappers run, so ``sys.modules['aws_sdk_bedrock_runtime']`` is
    stubbed for the duration (mirrors ``test_nova.py``'s ``nova_client``
    fixture) — this exercises protocol logic only, on both Python 3.11 (SDK
    absent) and 3.13 (SDK present).
    """
    client = _client()

    async def iter_events(_stream):
        for frame in frames:
            yield frame

    async def audio():
        yield b"\x00\x01" * 8
        yield None

    with patch.dict(sys.modules, {'aws_sdk_bedrock_runtime': MagicMock()}), \
         patch.object(client, "_open_stream", return_value=AsyncMock()), \
         patch.object(client, "_send_event", new=AsyncMock()), \
         patch.object(client, "_iter_events", new=iter_events), \
         patch.object(client, "_close_stream", new=AsyncMock()):
        return [r async for r in client.stream_voice(audio())]


SPECULATIVE = {"contentStart": {"role": "ASSISTANT", "type": "TEXT",
               "additionalModelFields": '{"generationStage": "SPECULATIVE"}'}}
FINAL = {"contentStart": {"role": "ASSISTANT", "type": "TEXT",
         "additionalModelFields": '{"generationStage": "FINAL"}'}}
USER = {"contentStart": {"role": "USER", "type": "TEXT"}}
END = {"completionEnd": {}}


class TestRoleAttribution:
    @pytest.mark.asyncio
    async def test_user_text_attributed_to_user(self):
        """FEAT-418 (TASK-2170): role is canonicalized to lowercase on the
        yielded LiveVoiceResponse — was "USER" before TASK-2170."""
        out = await _run([USER, {"textOutput": {"content": "weather?"}}, END])
        assert [r.role for r in out if r.text] == ["user"]

    @pytest.mark.asyncio
    async def test_assistant_speculative_text_emitted(self):
        """FEAT-418 (TASK-2170): role is canonicalized to lowercase — was
        "ASSISTANT" before TASK-2170."""
        out = await _run([SPECULATIVE, {"textOutput": {"content": "Sunny."}}, END])
        texts = [(r.role, r.text) for r in out if r.text]
        assert texts == [("assistant", "Sunny.")]

    @pytest.mark.asyncio
    async def test_assistant_non_speculative_text_suppressed(self):
        out = await _run([FINAL, {"textOutput": {"content": "Sunny."}}, END])
        assert [r for r in out if r.text and r.role == "ASSISTANT"] == []

    @pytest.mark.asyncio
    async def test_missing_stage_still_emits(self):
        """Regression guard: a strict == SPECULATIVE test would drop everything."""
        no_stage = {"contentStart": {"role": "ASSISTANT", "type": "TEXT"}}
        out = await _run([no_stage, {"textOutput": {"content": "Sunny."}}, END])
        assert any(r.text == "Sunny." for r in out)

    @pytest.mark.asyncio
    async def test_malformed_additional_model_fields_does_not_raise(self):
        bad = {"contentStart": {"role": "ASSISTANT", "type": "TEXT",
                                "additionalModelFields": "not json{"}}
        out = await _run([bad, {"textOutput": {"content": "Sunny."}}, END])
        assert any(r.text == "Sunny." for r in out)


class TestAccumulation:
    @pytest.mark.asyncio
    async def test_terminal_text_excludes_user_transcription(self):
        out = await _run([
            USER, {"textOutput": {"content": "what is the weather"}},
            SPECULATIVE, {"textOutput": {"content": "It is sunny."}},
            END,
        ])
        terminal = [r for r in out if r.is_complete][-1]
        assert "what is the weather" not in terminal.text

    @pytest.mark.asyncio
    async def test_assistant_reply_not_duplicated(self):
        out = await _run([
            SPECULATIVE, {"textOutput": {"content": "It is sunny."}},
            FINAL, {"textOutput": {"content": "It is sunny."}},
            END,
        ])
        assert [r.text for r in out if r.text] == ["It is sunny."]
