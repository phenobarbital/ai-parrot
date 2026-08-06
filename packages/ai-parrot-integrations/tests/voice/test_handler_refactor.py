"""Tests for VoiceChatHandler's VoiceSession-based refactor (FEAT-416,
TASK-2152 — spec §3 Module 8).

Follows the ``test_voicechat_avatar_integration.py`` fixture pattern in
this same directory (real ``VoiceChatHandler``/``WebSocketConnection``
instantiation, mocked WebSocket) rather than AST source inspection — this
integrations-side test suite does not hit the Cython
``parrot.utils.types`` blocker that the core ``ai-parrot`` `tests/bots/`
suite works around.
"""
from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.clients.live import LiveVoiceResponse
from parrot.voice.handler import (
    BotConfig,
    VoiceChatHandler,
    WebSocketConnection,
    _HandlerVoiceSession,
)


@pytest.fixture
def handler():
    """VoiceChatHandler with a no-op bot factory."""

    def _bot_factory():
        bot = MagicMock()
        bot.close = AsyncMock()
        return bot

    return VoiceChatHandler(
        bot_factory=_bot_factory,
        default_config=BotConfig(name="test-agent"),
    )


@pytest.fixture
def connection():
    """Minimal WebSocketConnection with a mock WebSocket."""
    mock_ws = MagicMock()
    mock_ws.send_json = AsyncMock()
    mock_ws.closed = False
    conn = WebSocketConnection(ws=mock_ws, session_id="sess-1")
    conn.authenticated = True
    return conn


def _sent_types(connection) -> list:
    return [
        c.args[0]["type"]
        for c in connection.ws.send_json.await_args_list
        if c.args
    ]


class TestHandlerRefactor:
    def test_imports_unified_voiceconfig(self):
        """Handler imports VoiceConfig from core, not integrations."""
        import parrot.voice.handler as h
        source = inspect.getsource(h)
        assert "from parrot.models.voice import" in source

    def test_imports_unified_voiceprovider(self):
        """Handler's runtime VoiceProvider import is also from core now
        (TASK-2146 unified it; previously imported from
        parrot.voice.models, the integrations shim)."""
        import parrot.voice.handler as h
        source = inspect.getsource(h)
        assert "from parrot.models.voice import VoiceProvider" in source
        assert "from parrot.voice.models import VoiceProvider" not in source

    def test_voice_provider_reexport_still_works(self):
        """Acceptance criterion: VoiceProvider re-export from integrations
        still works (unaffected — TASK-2146 made this a plain re-export,
        no deprecation warning, since it's a move not a rename)."""
        from parrot.models.voice import VoiceProvider as CoreVoiceProvider
        from parrot.voice.models import VoiceProvider as ReexportedVoiceProvider
        assert ReexportedVoiceProvider is CoreVoiceProvider

    def test_run_voice_session_uses_voice_session(self):
        """_run_voice_session() constructs a _HandlerVoiceSession (a
        VoiceSession subclass) — no inlined audio-queue-polling generator
        remains."""
        src = inspect.getsource(VoiceChatHandler._run_voice_session)
        assert "_HandlerVoiceSession(" in src
        assert "audio_from_queue" not in src

    def test_handler_voice_session_is_a_voice_session(self):
        from parrot.voice.session import VoiceSession
        assert issubclass(_HandlerVoiceSession, VoiceSession)

    def test_handle_websocket_still_exists_unchanged_signature(self):
        """No breaking changes to handle_websocket()'s API."""
        sig = inspect.signature(VoiceChatHandler.handle_websocket)
        assert list(sig.parameters) == ["self", "request"]


class TestFrameProtocolUnchanged:
    """The refactored relay (_HandlerVoiceSession._relay ->
    VoiceChatHandler._send_voice_response) must emit the exact same wire
    frames as before — NOT VoiceSession's own generic vocabulary
    (text/audio/turn_complete/...)."""

    @pytest.mark.asyncio
    async def test_text_response_uses_response_chunk_not_text(self, handler, connection):
        session = _HandlerVoiceSession(
            client=MagicMock(),
            send_fn=AsyncMock(),
            system_prompt="hi",
            handler=handler,
            connection=connection,
        )
        await session._relay(
            LiveVoiceResponse(text="hello", is_complete=False), turn_no=1,
        )
        types = _sent_types(connection)
        assert "response_chunk" in types
        assert "text" not in types

    @pytest.mark.asyncio
    async def test_completion_uses_response_complete_not_turn_complete(self, handler, connection):
        session = _HandlerVoiceSession(
            client=MagicMock(),
            send_fn=AsyncMock(),
            system_prompt="hi",
            handler=handler,
            connection=connection,
        )
        await session._relay(
            LiveVoiceResponse(text="done", is_complete=True), turn_no=1,
        )
        types = _sent_types(connection)
        assert "response_complete" in types
        assert "ready_to_speak" in types
        assert "turn_complete" not in types

    @pytest.mark.asyncio
    async def test_user_transcription_still_forwarded(self, handler, connection):
        """Verifies the richer metadata VoiceSession's own _relay would
        have dropped (user_transcription) is preserved."""
        session = _HandlerVoiceSession(
            client=MagicMock(),
            send_fn=AsyncMock(),
            system_prompt="hi",
            handler=handler,
            connection=connection,
        )
        await session._relay(
            LiveVoiceResponse(
                text="",
                metadata={"user_transcription": "what's the weather"},
            ),
            turn_no=1,
        )
        types = _sent_types(connection)
        assert "transcription" in types

    @pytest.mark.asyncio
    async def test_stt_only_gating_preserved(self, handler, connection):
        """stt_only suppresses response_chunk/response_complete — a
        VoiceBot-level concept VoiceSession's own _relay knows nothing
        about; must still work here."""
        connection.stt_only = True
        session = _HandlerVoiceSession(
            client=MagicMock(),
            send_fn=AsyncMock(),
            system_prompt="hi",
            handler=handler,
            connection=connection,
        )
        await session._relay(
            LiveVoiceResponse(text="hello", is_complete=False), turn_no=1,
        )
        types = _sent_types(connection)
        assert "response_chunk" not in types


class TestGoAwayReconnectBridge:
    @pytest.mark.asyncio
    async def test_go_away_sends_session_warning(self, handler, connection):
        session = _HandlerVoiceSession(
            client=MagicMock(),
            send_fn=AsyncMock(),
            system_prompt="hi",
            handler=handler,
            connection=connection,
        )
        resp = LiveVoiceResponse(text="", metadata={"go_away": True})
        await session._relay(resp, turn_no=1)
        assert "session_warning" in _sent_types(connection)

    @pytest.mark.asyncio
    async def test_go_away_sets_reconnect_required_for_inherited_loop(self, handler, connection):
        """go_away piggybacks on VoiceSession's own (inherited,
        unmodified) reconnect_required-driven reconnection loop —
        verified by checking the mutation _relay makes on the response
        object _run_turn() reads immediately afterward."""
        session = _HandlerVoiceSession(
            client=MagicMock(),
            send_fn=AsyncMock(),
            system_prompt="hi",
            handler=handler,
            connection=connection,
        )
        resp = LiveVoiceResponse(text="", metadata={"go_away": True})
        await session._relay(resp, turn_no=1)
        assert resp.metadata.get("reconnect_required") is True

    @pytest.mark.asyncio
    async def test_no_go_away_does_not_set_reconnect_required(self, handler, connection):
        session = _HandlerVoiceSession(
            client=MagicMock(),
            send_fn=AsyncMock(),
            system_prompt="hi",
            handler=handler,
            connection=connection,
        )
        resp = LiveVoiceResponse(text="hi", is_complete=False)
        await session._relay(resp, turn_no=1)
        assert "reconnect_required" not in resp.metadata


class TestNamespacePackagingFix:
    """Regression guard for the packaging bug this task had to fix:
    ``parrot.voice`` is split across two installed distributions
    (core ai-parrot + ai-parrot-integrations); both sides' submodules
    must be importable together in the same process."""

    def test_core_and_integrations_voice_submodules_coexist(self):
        import parrot.voice.handler  # noqa: F401 — this file, via its canonical path
        import parrot.voice.session  # noqa: F401 — core, TASK-2149
        import parrot.voice.models  # noqa: F401 — integrations

    def test_voice_synthesizer_convenience_reexport_still_works(self):
        """The one real __init__.py content (TTS convenience re-export)
        must survive the pkgutil.extend_path namespace-merge fix."""
        from parrot.voice import VoiceSynthesizer
        from parrot.voice.tts import VoiceSynthesizer as VS2
        assert VoiceSynthesizer is VS2

    def test_core_voice_package_has_no_init_file(self):
        """Core's parrot/voice/ must stay a bare PEP 420 namespace
        directory (no __init__.py) — that's the other half of the fix."""
        import os
        import parrot.voice.session as core_session
        core_voice_dir = os.path.dirname(core_session.__file__)
        assert not os.path.exists(os.path.join(core_voice_dir, "__init__.py"))
