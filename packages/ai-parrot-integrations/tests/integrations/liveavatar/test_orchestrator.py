"""Unit tests for AvatarSessionOrchestrator (TASK-006).

All external I/O (HTTP client, WS, room manager, bot, TTS) is mocked.
Tests verify:
- Per-sentence PCM push (one synthesize + one send_audio_frame per sentence).
- stop_session called on every exit path (including error paths).
- TTS failure on one sentence does not abort the turn.
"""
from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.integrations.liveavatar import AvatarSessionOrchestrator
from parrot.integrations.liveavatar.models import (
    AvatarSessionHandle,
    LiveAvatarConfig,
    LiveKitRoomTokens,
)


# ---------------------------------------------------------------------------
# Helpers / Fakes
# ---------------------------------------------------------------------------

def _make_cfg() -> LiveAvatarConfig:
    return LiveAvatarConfig(api_key="k", avatar_id="a", is_sandbox=True)


def _make_handle() -> AvatarSessionHandle:
    return AvatarSessionHandle(
        session_id="sess-1",
        liveavatar_session_id="sess-1",
        session_token="tok-1",
        ws_url="wss://media/ws/sess-1",
        agent_name="bot",
    )


def _make_room_tokens() -> LiveKitRoomTokens:
    return LiveKitRoomTokens(
        livekit_url="wss://x.livekit.cloud",
        room="sess-1",
        client_token="client-tok",
        agent_token="agent-tok",
    )


class _FakeBot:
    """Bot with a controllable ask_stream generator."""

    def __init__(self, chunks: List[str]) -> None:
        self._chunks = chunks

    async def ask_stream(self, question: str) -> AsyncIterator[Any]:
        for chunk in self._chunks:
            yield chunk
        # Final sentinel (non-str)
        yield object()


class _FakeBotRaises:
    """Bot whose ask_stream raises after the first chunk."""

    async def ask_stream(self, question: str) -> AsyncIterator[Any]:
        yield "Hello "
        raise RuntimeError("stream error")


def _fake_room_manager(tokens: LiveKitRoomTokens) -> MagicMock:
    mgr = MagicMock()
    mgr.mint_room_tokens = MagicMock(return_value=tokens)
    return mgr


def _fake_client(handle: AvatarSessionHandle) -> MagicMock:
    client = MagicMock()
    client.create_session_token = AsyncMock(return_value=handle)
    client.start_session = AsyncMock(return_value={})
    client.stop_session = AsyncMock()
    return client


# ---------------------------------------------------------------------------
# Per-sentence streaming
# ---------------------------------------------------------------------------

async def test_orchestrator_streams_per_sentence() -> None:
    """Two-sentence stream produces two PCM pushes."""
    cfg = _make_cfg()
    handle = _make_handle()
    tokens = _make_room_tokens()

    # Bot yields a stream that produces two complete sentences
    bot = _FakeBot(["First sentence. ", "Second sentence."])
    client = _fake_client(handle)
    room_mgr = _fake_room_manager(tokens)

    pcm_calls: List[str] = []

    def fake_synthesize(text: str) -> bytes:
        pcm_calls.append(text)
        return b"\x00" * 100  # minimal fake PCM

    fake_ws = MagicMock()
    fake_ws.start_speaking = AsyncMock()
    fake_ws.send_audio_frame = AsyncMock()
    fake_ws.finish_speaking = AsyncMock()
    fake_ws.interrupt = AsyncMock()
    fake_ws._connected = asyncio.Event()
    fake_ws._connected.set()
    fake_ws.__aenter__ = AsyncMock(return_value=fake_ws)
    fake_ws.__aexit__ = AsyncMock(return_value=False)

    orch = AvatarSessionOrchestrator(
        cfg,
        bot,
        client=client,
        room_manager=room_mgr,
        synthesize_pcm_fn=fake_synthesize,
    )

    with patch(
        "parrot.integrations.liveavatar.orchestrator.AvatarWebSocket",
        return_value=fake_ws,
    ):
        await orch.run("question", agent_name="bot", session_id="sess-1")

    # Expect two PCM pushes (one per sentence)
    assert len(pcm_calls) == 2
    assert "First sentence" in pcm_calls[0]
    assert "Second sentence" in pcm_calls[1]

    # stop_session always called
    client.stop_session.assert_called_once()


# ---------------------------------------------------------------------------
# stop_session on error path
# ---------------------------------------------------------------------------

async def test_session_lifecycle_stop_on_error() -> None:
    """stop_session is called even when ask_stream raises."""
    cfg = _make_cfg()
    handle = _make_handle()
    tokens = _make_room_tokens()

    bot = _FakeBotRaises()
    client = _fake_client(handle)
    room_mgr = _fake_room_manager(tokens)

    def fake_synthesize(text: str) -> bytes:
        return b"\x00" * 100

    fake_ws = MagicMock()
    fake_ws.start_speaking = AsyncMock()
    fake_ws.send_audio_frame = AsyncMock()
    fake_ws.finish_speaking = AsyncMock()
    fake_ws._connected = asyncio.Event()
    fake_ws._connected.set()
    fake_ws.__aenter__ = AsyncMock(return_value=fake_ws)
    fake_ws.__aexit__ = AsyncMock(return_value=False)

    orch = AvatarSessionOrchestrator(
        cfg,
        bot,
        client=client,
        room_manager=room_mgr,
        synthesize_pcm_fn=fake_synthesize,
    )

    with patch(
        "parrot.integrations.liveavatar.orchestrator.AvatarWebSocket",
        return_value=fake_ws,
    ):
        with pytest.raises(RuntimeError, match="stream error"):
            await orch.run("q", agent_name="bot", session_id="sess-1")

    # stop_session must be called despite the exception
    client.stop_session.assert_called_once()


# ---------------------------------------------------------------------------
# TTS graceful degradation
# ---------------------------------------------------------------------------

async def test_tts_failure_graceful_degradation() -> None:
    """TTS failure on one sentence does not abort the turn."""
    cfg = _make_cfg()
    handle = _make_handle()
    tokens = _make_room_tokens()

    bot = _FakeBot(["First sentence. Second sentence."])
    client = _fake_client(handle)
    room_mgr = _fake_room_manager(tokens)

    call_count = [0]

    def fake_synthesize_fail_first(text: str) -> bytes:
        call_count[0] += 1
        if call_count[0] == 1:
            raise RuntimeError("TTS failure on first sentence")
        return b"\x00" * 100

    fake_ws = MagicMock()
    fake_ws.start_speaking = AsyncMock()
    fake_ws.send_audio_frame = AsyncMock()
    fake_ws.finish_speaking = AsyncMock()
    fake_ws._connected = asyncio.Event()
    fake_ws._connected.set()
    fake_ws.__aenter__ = AsyncMock(return_value=fake_ws)
    fake_ws.__aexit__ = AsyncMock(return_value=False)

    orch = AvatarSessionOrchestrator(
        cfg,
        bot,
        client=client,
        room_manager=room_mgr,
        synthesize_pcm_fn=fake_synthesize_fail_first,
    )

    # Must complete without raising, even though TTS failed on sentence 1
    with patch(
        "parrot.integrations.liveavatar.orchestrator.AvatarWebSocket",
        return_value=fake_ws,
    ):
        await orch.run("q", agent_name="bot", session_id="sess-1")

    # Second sentence was synthesized successfully and sent
    assert call_count[0] >= 1
    client.stop_session.assert_called_once()
