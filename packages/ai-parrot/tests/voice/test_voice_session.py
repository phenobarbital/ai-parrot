"""Unit tests for VoiceSession (FEAT-416, TASK-2149 — spec §3 Module 5)."""
import asyncio

import pytest
from parrot.clients.live import LiveVoiceResponse
from parrot.voice.session import VoiceSession


class MockVoiceClient:
    """Minimal VoiceCapable for testing."""
    async def stream_voice(self, audio_iterator, system_prompt=None,
                            session_id=None, user_id=None, **kwargs):
        async for chunk in audio_iterator:
            if chunk is None:
                break
        yield LiveVoiceResponse(text="Hello", role="ASSISTANT")
        yield LiveVoiceResponse(text="", is_complete=True)


@pytest.fixture
def mock_send_fn():
    frames = []

    async def send(payload):
        frames.append(payload)
    send.frames = frames
    return send


class TestVoiceSession:
    @pytest.mark.asyncio
    async def test_turn_lifecycle(self, mock_send_fn):
        session = VoiceSession(
            client=MockVoiceClient(),
            send_fn=mock_send_fn,
            system_prompt="You are a test bot.",
        )
        await session.start_turn()
        await session.push_audio(b"\x00" * 2048)
        await session.end_turn()
        # Wait for turn task to complete
        await asyncio.sleep(0.5)
        types = [f["type"] for f in mock_send_fn.frames]
        assert "turn_started" in types
        assert "text" in types or "turn_complete" in types

    @pytest.mark.asyncio
    async def test_cancel_turn(self, mock_send_fn):
        session = VoiceSession(
            client=MockVoiceClient(),
            send_fn=mock_send_fn,
            system_prompt="Test",
        )
        await session.start_turn()
        await session.close()
        assert session._task is None
        assert session._queue is None

    @pytest.mark.asyncio
    async def test_silence_injection_pacing(self, mock_send_fn):
        """end_turn() injects paced silence frames."""
        session = VoiceSession(
            client=MockVoiceClient(),
            send_fn=mock_send_fn,
            system_prompt="Test",
        )
        await session.start_turn()
        await session.push_audio(b"\x00" * 1024)
        start = asyncio.get_event_loop().time()
        await session.end_turn()
        elapsed = asyncio.get_event_loop().time() - start
        # ~23 frames × 20ms = ~460ms minimum
        assert elapsed >= 0.3  # some margin for test environments

    @pytest.mark.asyncio
    async def test_send_fn_called_not_ws(self, mock_send_fn):
        """VoiceSession is transport-agnostic — it calls send_fn, not any
        ws.send_json() (acceptance criterion; also verifies no aiohttp
        coupling by construction, since VoiceSession never references a
        `ws`/`WebSocketResponse` attribute at all)."""
        session = VoiceSession(
            client=MockVoiceClient(),
            send_fn=mock_send_fn,
            system_prompt="Test",
        )
        assert not hasattr(session, "ws")
        await session.start_turn()
        await asyncio.sleep(0.1)
        assert mock_send_fn.frames  # at least turn_started was relayed

    @pytest.mark.asyncio
    async def test_new_turn_cancels_previous(self, mock_send_fn):
        """start_turn() cancels any turn still running (single in-flight
        turn per session)."""
        session = VoiceSession(
            client=MockVoiceClient(),
            send_fn=mock_send_fn,
            system_prompt="Test",
        )
        await session.start_turn()
        first_task = session._task
        await session.start_turn()
        assert first_task.done()
        assert session._turn_no == 2

    def test_no_aiohttp_import(self):
        """Acceptance criterion: VoiceSession is transport-agnostic (no
        aiohttp import) — verified via source inspection since aiohttp may
        legitimately be installed as a transitive dependency elsewhere."""
        import inspect
        from parrot.voice import session as session_module
        src = inspect.getsource(session_module)
        assert "aiohttp" not in src
