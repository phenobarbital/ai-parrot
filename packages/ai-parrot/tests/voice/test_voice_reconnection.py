"""Unit tests for VoiceSession automatic reconnection (FEAT-416, TASK-2150
— spec §3 Module 6)."""
import asyncio

import pytest
from parrot.clients.live import LiveVoiceResponse
from parrot.models.voice import VoiceConfig
from parrot.voice.session import VoiceSession


class ReconnectingMockClient:
    """Mock that signals reconnect_required on first turn."""
    def __init__(self):
        self.call_count = 0

    async def stream_voice(self, audio_iterator, **kwargs):
        self.call_count += 1
        async for chunk in audio_iterator:
            if chunk is None:
                break
        yield LiveVoiceResponse(
            text="response",
            is_complete=True,
            metadata={"reconnect_required": self.call_count <= 1},
        )


class AlwaysReconnectMockClient:
    """Mock that always signals reconnect_required."""
    def __init__(self):
        self.call_count = 0

    async def stream_voice(self, audio_iterator, **kwargs):
        self.call_count += 1
        async for chunk in audio_iterator:
            if chunk is None:
                break
        yield LiveVoiceResponse(
            text="", is_complete=True,
            metadata={"reconnect_required": True},
        )


class TestReconnection:
    @pytest.mark.asyncio
    async def test_reconnect_on_limit(self):
        """Session re-opens stream_voice after reconnect_required."""
        frames = []

        async def send(p):
            frames.append(p)
        client = ReconnectingMockClient()
        config = VoiceConfig(reconnect_on_limit=True)
        session = VoiceSession(client=client, send_fn=send,
                                system_prompt="test", voice_config=config)
        # First turn triggers reconnect
        await session.start_turn()
        await session.end_turn()
        await asyncio.sleep(0.5)
        types = [f["type"] for f in frames]
        assert "reconnect" in types

    @pytest.mark.asyncio
    async def test_reconnect_disabled(self):
        frames = []

        async def send(p):
            frames.append(p)
        client = ReconnectingMockClient()
        config = VoiceConfig(reconnect_on_limit=False)
        session = VoiceSession(client=client, send_fn=send,
                                system_prompt="test", voice_config=config)
        await session.start_turn()
        await session.end_turn()
        await asyncio.sleep(0.5)
        types = [f["type"] for f in frames]
        assert "reconnect" not in types

    @pytest.mark.asyncio
    async def test_max_reconnects_exhausted(self):
        frames = []

        async def send(p):
            frames.append(p)
        client = AlwaysReconnectMockClient()
        config = VoiceConfig(reconnect_on_limit=True, max_reconnects=2)
        session = VoiceSession(client=client, send_fn=send,
                                system_prompt="test", voice_config=config)
        # Simulate enough turns to exhaust max_reconnects
        for _ in range(3):
            await session.start_turn()
            await session.end_turn()
            await asyncio.sleep(0.3)
        types = [f["type"] for f in frames]
        assert "error" in types

    @pytest.mark.asyncio
    async def test_reconnect_count_persists_across_turns(self):
        """_reconnect_count is a session-lifetime counter (resets only on
        __init__), not reset per-turn (spec §3 Module 6 Key Constraints)."""
        frames = []

        async def send(p):
            frames.append(p)
        client = AlwaysReconnectMockClient()
        config = VoiceConfig(reconnect_on_limit=True, max_reconnects=5)
        session = VoiceSession(client=client, send_fn=send,
                                system_prompt="test", voice_config=config)
        assert session._reconnect_count == 0
        await session.start_turn()
        await session.end_turn()
        await asyncio.sleep(0.3)
        assert session._reconnect_count == 1
        await session.start_turn()
        await session.end_turn()
        await asyncio.sleep(0.3)
        assert session._reconnect_count == 2

    @pytest.mark.asyncio
    async def test_reconnect_frame_includes_session_and_count(self):
        frames = []

        async def send(p):
            frames.append(p)
        client = ReconnectingMockClient()
        config = VoiceConfig(reconnect_on_limit=True)
        session = VoiceSession(client=client, send_fn=send,
                                system_prompt="test", voice_config=config,
                                session_id="sess-123")
        await session.start_turn()
        await session.end_turn()
        await asyncio.sleep(0.5)
        reconnect_frames = [f for f in frames if f["type"] == "reconnect"]
        assert reconnect_frames
        assert reconnect_frames[0]["session_id"] == "sess-123"
        assert reconnect_frames[0]["reconnect_count"] == 1
