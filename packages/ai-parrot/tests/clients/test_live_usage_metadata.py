"""Gemini Live token usage + first-token timing on the streaming path.

The Live API delivers ``usage_metadata`` on the SAME server message as
``server_content.turn_complete``. ``stream_voice()`` used to handle usage
AFTER the server_content branch, whose turn_complete ``continue`` skipped
it — so every ``response_complete`` reported 0/0 tokens. On top of that
``LiveCompletionUsage.from_gemini_usage`` read ``candidates_token_count``
(GenerateContent naming) while Live's ``UsageMetadata`` exposes
``response_token_count``.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from parrot.clients.google.live import GeminiLiveClient
from parrot.models.voice import LiveCompletionUsage


class _FakeLiveSession:
    def __init__(self, responses):
        self._responses = responses
        self.send_realtime_input = AsyncMock()
        self.send_tool_response = AsyncMock()
        self.send = AsyncMock()

    async def receive(self):
        for response in self._responses:
            yield response


class _FakeConnectCM:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc_info):
        return False


class _FakeSdkClient:
    def __init__(self, session):
        self.aio = SimpleNamespace(live=SimpleNamespace(connect=lambda model=None, config=None: _FakeConnectCM(session)))


async def _empty_audio_iterator():
    return
    yield  # pragma: no cover


def _mock_client(monkeypatch, client, responses):
    session = _FakeLiveSession(responses)
    monkeypatch.setattr(client, "get_client", AsyncMock(return_value=_FakeSdkClient(session)))
    return session


def _live_usage(prompt: int, response: int, total: int):
    # Mirrors google.genai.types.UsageMetadata field names (Live API).
    return SimpleNamespace(
        prompt_token_count=prompt,
        response_token_count=response,
        total_token_count=total,
        cached_content_token_count=None,
    )


def _msg(*, server_content=None, usage_metadata=None):
    return SimpleNamespace(
        server_content=server_content,
        tool_call=None,
        usage_metadata=usage_metadata,
        go_away=None,
    )


def _audio_content(data: bytes):
    return SimpleNamespace(
        model_turn=SimpleNamespace(parts=[SimpleNamespace(text=None, inline_data=SimpleNamespace(data=data))]),
    )


@pytest.fixture
def client():
    return GeminiLiveClient(voice_name="Puck")


class TestFromGeminiUsage:
    def test_reads_live_response_token_count(self):
        usage = LiveCompletionUsage.from_gemini_usage(_live_usage(12, 34, 46))
        assert (usage.prompt_tokens, usage.completion_tokens, usage.total_tokens) == (12, 34, 46)
        assert (usage.input_tokens, usage.output_tokens) == (12, 34)

    def test_still_reads_generate_content_candidates_count(self):
        um = SimpleNamespace(prompt_token_count=5, candidates_token_count=7, total_token_count=12)
        usage = LiveCompletionUsage.from_gemini_usage(um)
        assert (usage.prompt_tokens, usage.completion_tokens, usage.total_tokens) == (5, 7, 12)

    def test_total_falls_back_to_sum(self):
        um = SimpleNamespace(prompt_token_count=5, response_token_count=7, total_token_count=None)
        assert LiveCompletionUsage.from_gemini_usage(um).total_tokens == 12

    def test_merge_tokens_keeps_turn_counters(self):
        usage = LiveCompletionUsage(response_time_ms=800.0, first_token_time_ms=120.0, output_audio_duration_ms=1500.0)
        usage.merge_tokens(LiveCompletionUsage.from_gemini_usage(_live_usage(12, 34, 46)))
        assert (usage.prompt_tokens, usage.completion_tokens, usage.total_tokens) == (12, 34, 46)
        assert usage.response_time_ms == 800.0
        assert usage.first_token_time_ms == 120.0
        assert usage.output_audio_duration_ms == 1500.0


class TestStreamVoiceUsage:
    @pytest.mark.asyncio
    async def test_usage_on_turn_complete_message_reaches_final_frame(self, monkeypatch, client):
        _mock_client(
            monkeypatch,
            client,
            [
                _msg(server_content=_audio_content(b"\x00\x00" * 480)),
                # usage_metadata rides on the same message as turn_complete
                _msg(server_content=SimpleNamespace(turn_complete=True), usage_metadata=_live_usage(12, 34, 46)),
            ],
        )
        responses = [r async for r in client.stream_voice(_empty_audio_iterator())]
        final = next(r for r in responses if r.is_complete)
        assert final.usage is not None
        assert (final.usage.prompt_tokens, final.usage.completion_tokens, final.usage.total_tokens) == (12, 34, 46)
        # turn-level counters accumulated during the turn survive the merge
        assert final.usage.output_audio_duration_ms > 0
        assert final.usage.first_token_time_ms > 0

    @pytest.mark.asyncio
    async def test_usage_on_separate_message_before_turn_complete(self, monkeypatch, client):
        _mock_client(
            monkeypatch,
            client,
            [
                _msg(server_content=_audio_content(b"\x00\x00" * 480)),
                _msg(usage_metadata=_live_usage(3, 4, 7)),
                _msg(server_content=SimpleNamespace(turn_complete=True)),
            ],
        )
        responses = [r async for r in client.stream_voice(_empty_audio_iterator())]
        final = next(r for r in responses if r.is_complete)
        assert (final.usage.prompt_tokens, final.usage.completion_tokens, final.usage.total_tokens) == (3, 4, 7)

    @pytest.mark.asyncio
    async def test_first_token_time_stays_zero_without_model_output(self, monkeypatch, client):
        _mock_client(
            monkeypatch,
            client,
            [_msg(server_content=SimpleNamespace(turn_complete=True), usage_metadata=_live_usage(1, 0, 1))],
        )
        responses = [r async for r in client.stream_voice(_empty_audio_iterator())]
        final = next(r for r in responses if r.is_complete)
        assert final.usage.first_token_time_ms == 0.0
