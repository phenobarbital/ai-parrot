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
from parrot.models.voice import AudioFormat, VoiceCapabilities, VoiceProvider
from parrot.voice.handler import (
    BotConfig,
    VoiceChatHandler,
    WebSocketConnection,
    _HandlerVoiceSession,
)


def _capable_mock_client() -> MagicMock:
    """A MagicMock VoiceCapable client with a real ``voice_capabilities``
    descriptor matching ``VoiceConfig()``'s PCM defaults.

    FEAT-418 (TASK-2172) added a construction-time audio-format preflight
    to ``VoiceSession.__init__`` — a bare ``MagicMock()`` (whose
    ``voice_capabilities.input_formats`` etc. are themselves empty-iterable
    Mocks) now fails that preflight with a ``ValueError``.
    """
    client = MagicMock()
    client.voice_capabilities = VoiceCapabilities(
        provider=VoiceProvider.GOOGLE_LIVE,
        native_stt_only=True, supports_top_p=True, supports_per_call_voice=True,
        supports_per_call_inference=True, parallel_tool_execution=True,
        emits_reconnect_signal=True, supports_session_resumption=True,
        max_session_seconds=None, max_output_tokens=4096,
        input_formats=frozenset({AudioFormat.PCM_16K}),
        output_formats=frozenset({AudioFormat.PCM_24K}),
        input_sample_rates=frozenset({16000}), output_sample_rates=frozenset({24000}),
        voice_catalog=frozenset({"Puck"}), default_voice="Puck",
    )
    return client


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

    def test_binary_audio_frames_route_through_voice_session(self):
        """Code-review regression guard: raw binary WS audio frames
        (WSMsgType.BINARY, as opposed to base64-in-JSON audio_data
        messages) must be routed through connection.voice_session
        .push_audio() — not connection.audio_queue, which nothing has
        drained since _run_voice_session() stopped reading it (this was
        found and fixed as a CRITICAL finding in the TASK-2152 code
        review: that path previously left binary-frame audio silently
        dropped in streaming mode)."""
        src = inspect.getsource(VoiceChatHandler.handle_websocket)
        assert "connection.voice_session.push_audio(msg.data)" in src
        assert "connection.audio_queue.put(msg.data)" not in src


class TestFrameProtocolUnchanged:
    """The refactored relay (_HandlerVoiceSession._relay ->
    VoiceChatHandler._send_voice_response) must emit the exact same wire
    frames as before — NOT VoiceSession's own generic vocabulary
    (text/audio/turn_complete/...)."""

    @pytest.mark.asyncio
    async def test_text_response_uses_response_chunk_not_text(self, handler, connection):
        session = _HandlerVoiceSession(
            client=_capable_mock_client(),
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
            client=_capable_mock_client(),
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
        """Verifies the richer transcription frame VoiceSession's own
        _relay would have dropped is preserved — now driven by canonical
        role="user" (FEAT-418, TASK-2174) instead of the removed
        metadata["user_transcription"] key."""
        session = _HandlerVoiceSession(
            client=_capable_mock_client(),
            send_fn=AsyncMock(),
            system_prompt="hi",
            handler=handler,
            connection=connection,
        )
        await session._relay(
            LiveVoiceResponse(text="what's the weather", role="user"),
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
            client=_capable_mock_client(),
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
            client=_capable_mock_client(),
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
            client=_capable_mock_client(),
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
            client=_capable_mock_client(),
            send_fn=AsyncMock(),
            system_prompt="hi",
            handler=handler,
            connection=connection,
        )
        resp = LiveVoiceResponse(text="hi", is_complete=False)
        await session._relay(resp, turn_no=1)
        assert "reconnect_required" not in resp.metadata


class TestDeduplication:
    """FEAT-418, TASK-2174: _run_turn() is gone — VoiceSession's inherited
    reconnection loop (voice/session.py) is the only one in the codebase."""

    def test_run_turn_not_overridden(self):
        """The duplicated loop (handler.py, pre-TASK-2174) must be gone."""
        assert "_run_turn" not in _HandlerVoiceSession.__dict__

    def test_build_frames_overridden(self):
        assert "build_frames" in _HandlerVoiceSession.__dict__

    def test_relay_still_overridden_for_avatar_tee(self):
        """_relay() stays overridden (cooperatively, via super()._relay())
        only for the LiveAvatar audio tee — the one genuinely async side
        effect build_frames() (sync) cannot perform."""
        assert "_relay" in _HandlerVoiceSession.__dict__

    def test_inherits_run_turn_from_voice_session(self):
        from parrot.voice.session import VoiceSession
        assert _HandlerVoiceSession._run_turn is VoiceSession._run_turn


class TestEnvelopeMigration:
    """FEAT-418, TASK-2174: no user_transcription/assistant_transcription
    metadata reads remain — canonical role drives every transcription
    frame."""

    @pytest.mark.asyncio
    async def test_transcription_frame_from_role(self, handler, connection):
        """Replaces test_user_transcription_still_forwarded's old
        metadata-key-based scenario with a direct role-based one."""
        session = _HandlerVoiceSession(
            client=_capable_mock_client(),
            send_fn=AsyncMock(),
            system_prompt="hi",
            handler=handler,
            connection=connection,
        )
        resp = LiveVoiceResponse(text="what's the weather", role="user")
        frames = session.build_frames(resp, turn_no=1)
        assert {"type": "transcription", "text": "what's the weather", "is_user": True} in frames

    @pytest.mark.asyncio
    async def test_assistant_transcription_frame_from_role(self, handler, connection):
        session = _HandlerVoiceSession(
            client=_capable_mock_client(),
            send_fn=AsyncMock(),
            system_prompt="hi",
            handler=handler,
            connection=connection,
        )
        resp = LiveVoiceResponse(text="It's sunny", role="assistant", is_complete=False)
        frames = session.build_frames(resp, turn_no=1)
        assert {"type": "transcription", "text": "It's sunny", "is_user": False} in frames

    @pytest.mark.asyncio
    async def test_stt_only_suppresses_assistant(self, handler, connection):
        connection.stt_only = True
        session = _HandlerVoiceSession(
            client=_capable_mock_client(),
            send_fn=AsyncMock(),
            system_prompt="hi",
            handler=handler,
            connection=connection,
        )
        frames = session.build_frames(
            LiveVoiceResponse(text="hi", role="assistant"), turn_no=1,
        )
        assert not any(f.get("is_user") is False for f in frames)
        assert not any(f["type"] == "response_chunk" for f in frames)

    def test_no_user_transcription_reference_in_handler(self):
        """No functional read of the removed metadata key remains — every
        original call site used ``.metadata.get("user_transcription")``.
        Explanatory comments naming the OLD key (e.g. "replaces the
        removed metadata['user_transcription'] key", using bracket
        notation, not ``.get(...)``) are expected and intentional."""
        import parrot.voice.handler as h
        source = inspect.getsource(h)
        assert 'get("user_transcription")' not in source

    def test_no_assistant_transcription_reference_in_handler(self):
        import parrot.voice.handler as h
        source = inspect.getsource(h)
        assert 'get("assistant_transcription")' not in source


class TestNamespacePackagingFix:
    """Regression guard for the packaging bug this task had to fix:
    ``parrot.voice`` is split across two installed distributions
    (core ai-parrot + ai-parrot-integrations); both sides' submodules
    must be importable together in the same process."""

    def test_core_and_integrations_voice_submodules_coexist(self):
        import parrot.voice.handler  # noqa: F401 — this file, via its canonical path
        import parrot.voice.models  # noqa: F401 — integrations
        import parrot.voice.session  # noqa: F401 — core, TASK-2149

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
