"""Integration tests for the STT-only voice WebSocket session (FEAT-257, TASK-1632).

These tests exercise the full session pipeline end-to-end (start_session →
audio queue → _run_voice_session → message forwarding) with Gemini / VoiceBot
fully mocked — no real network connections.

Tests:
- ``test_voice_ws_stt_only_session``:
  Open a voice WS session with ``start_session {stt_only: true}``, drive mic
  audio frames through the audio queue, and verify ONLY user transcription
  frames are emitted — no ``response_chunk`` / model audio.

- ``test_voice_ws_full_duplex_session``:
  Without the flag the full-duplex path still emits a model ``response_chunk``.

Module loading note: the venv's editable-install for ``parrot.voice.handler``
points to the *main* repo.  We extend ``parrot.__path__`` and
``parrot.voice.__path__`` with the worktree source directories so Python
resolves the worktree's modified copies (same pattern as the unit tests).
"""
from __future__ import annotations

import asyncio
import contextlib
import importlib
import sys
import types
from pathlib import Path
from typing import AsyncIterator, List
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Locate the worktree source directories.
# File: packages/ai-parrot-server/tests/handlers/test_voice_ws_stt_only_integration.py
# parents[4] → feat-257-livekit-gemini-voice-input/ (worktree root)
# ---------------------------------------------------------------------------

_WORKTREE_ROOT = Path(__file__).resolve().parents[4]
_INTEGRATIONS_SRC = _WORKTREE_ROOT / "packages" / "ai-parrot-integrations" / "src"
_PARROT_SRC = _WORKTREE_ROOT / "packages" / "ai-parrot" / "src"


def _prepend_path(directory: Path) -> None:
    """Prepend *directory* to sys.path if not already present."""
    p = str(directory)
    if p not in sys.path:
        sys.path.insert(0, p)


# Prepend worktree sources so sub-package lookups find the worktree files.
_prepend_path(_INTEGRATIONS_SRC)
_prepend_path(_PARROT_SRC)

# Extend the already-imported ``parrot`` namespace package path so Python's
# sub-package resolution finds the worktree versions even when ``parrot``
# was already loaded from the main-repo editable install.
try:
    import parrot as _parrot_pkg
    for _src_dir in (_INTEGRATIONS_SRC / "parrot", _PARROT_SRC / "parrot"):
        _dir_str = str(_src_dir)
        if _dir_str not in _parrot_pkg.__path__:
            _parrot_pkg.__path__.insert(0, _dir_str)
    importlib.invalidate_caches()
except Exception:
    pass  # non-fatal

# Drop cached module entries for the modules we need to reload from worktree.
for _key in list(sys.modules):
    if _key in (
        "parrot.voice.handler",
        "parrot.voice",
        "parrot.clients.live",
    ):
        del sys.modules[_key]
importlib.invalidate_caches()


# ---------------------------------------------------------------------------
# Inject google.genai stub so parrot.clients.live can be imported without the
# real google-genai distribution (which may not be installed in the test env).
# ---------------------------------------------------------------------------


def _inject_genai_stub() -> None:
    """Inject a minimal google.genai stub into sys.modules."""
    if "google.genai" in sys.modules:
        return  # already present (real or stub)

    google_mod = sys.modules.get("google") or types.ModuleType("google")
    if not hasattr(google_mod, "__path__"):
        google_mod.__path__ = []

    genai_mod = types.ModuleType("google.genai")
    types_mod = types.ModuleType("google.genai.types")

    class _Stub:
        """Generic stub that records constructor kwargs as attributes."""

        def __init__(self, *args, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
            self._args = args

    class _StubEnum:
        START_SENSITIVITY_HIGH = "high"
        END_SENSITIVITY_HIGH = "high"
        MEDIA_RESOLUTION_LOW = "low"

    for _name in [
        "AudioTranscriptionConfig", "LiveConnectConfig", "SpeechConfig",
        "VoiceConfig", "PrebuiltVoiceConfig", "ContextWindowCompressionConfig",
        "SlidingWindow", "RealtimeInputConfig", "AutomaticActivityDetection",
        "Tool", "FunctionDeclaration", "FunctionResponse", "Content", "Part",
    ]:
        setattr(types_mod, _name, _Stub)

    types_mod.StartSensitivity = _StubEnum()
    types_mod.EndSensitivity = _StubEnum()
    types_mod.MediaResolution = _StubEnum()

    genai_mod.Client = MagicMock
    genai_mod.types = types_mod

    oauth2_mod = types.ModuleType("google.oauth2")
    sa_mod = types.ModuleType("google.oauth2.service_account")
    sa_mod.Credentials = MagicMock

    sys.modules.setdefault("google", google_mod)
    sys.modules["google.genai"] = genai_mod
    sys.modules["google.genai.types"] = types_mod
    sys.modules["google.oauth2"] = oauth2_mod
    sys.modules["google.oauth2.service_account"] = sa_mod


_inject_genai_stub()

# Import from worktree versions.
from parrot.clients.live import LiveVoiceResponse  # noqa: E402
from parrot.voice.handler import BotConfig, VoiceChatHandler, WebSocketConnection  # noqa: E402

# Sanity check: make sure we loaded the worktree's handler (not the main repo).
_handler_mod = sys.modules.get("parrot.voice.handler", None)
_handler_path = getattr(_handler_mod, "__file__", "") or ""
assert str(_WORKTREE_ROOT) in _handler_path, (
    f"parrot.voice.handler was loaded from the wrong location: {_handler_path!r}. "
    f"Expected a path inside {_WORKTREE_ROOT}."
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_mock_ws() -> MagicMock:
    """Return a minimal fake aiohttp.WebSocketResponse."""
    ws = MagicMock()
    ws.send_json = AsyncMock()
    return ws


def _make_connection(stt_only: bool = False) -> WebSocketConnection:
    """Return a pre-configured WebSocketConnection for testing.

    Args:
        stt_only: Whether to enable STT-only mode on the connection.

    Returns:
        A WebSocketConnection ready for use in integration tests.
    """
    conn = WebSocketConnection(
        ws=_make_mock_ws(),
        session_id="integration-test-session",
    )
    conn.authenticated = True
    conn.stt_only = stt_only
    conn.avatar_session = None
    return conn


def _sent_types(connection: WebSocketConnection) -> List[str]:
    """Return the list of message type strings sent to the WS client."""
    return [
        call.args[0]["type"]
        for call in connection.ws.send_json.await_args_list
        if call.args and isinstance(call.args[0], dict) and "type" in call.args[0]
    ]


def _sent_messages(connection: WebSocketConnection) -> List[dict]:
    """Return all messages sent to the WS client."""
    return [
        call.args[0]
        for call in connection.ws.send_json.await_args_list
        if call.args and isinstance(call.args[0], dict)
    ]


def _make_transcription_response(text: str = "Hello world") -> LiveVoiceResponse:
    """Return a LiveVoiceResponse carrying a user transcription."""
    return LiveVoiceResponse(
        text="",
        is_complete=False,
        metadata={"user_transcription": text},
        session_id="integration-test-session",
        turn_id="turn-1",
    )


def _make_model_audio_response(audio: bytes = b"\x00" * 100) -> LiveVoiceResponse:
    """Return a LiveVoiceResponse carrying a model audio chunk."""
    return LiveVoiceResponse(
        text="",
        audio_data=audio,
        is_complete=False,
        session_id="integration-test-session",
        turn_id="turn-1",
    )


def _make_model_text_response(text: str = "Here is my answer.") -> LiveVoiceResponse:
    """Return a LiveVoiceResponse carrying a model text chunk."""
    return LiveVoiceResponse(
        text=text,
        is_complete=False,
        session_id="integration-test-session",
        turn_id="turn-1",
    )


# ---------------------------------------------------------------------------
# Integration test: STT-only session — start_session → voice task → assertions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_voice_ws_stt_only_session() -> None:
    """STT-only voice session emits user transcription only — no model response.

    End-to-end integration scenario:
    1. Open a session via ``_handle_start_session`` with ``stt_only=True``.
    2. The bot's ``ask_stream`` yields: one user transcription frame, then one
       model audio frame (simulating Gemini firing despite STT-only config;
       the handler must suppress this at the forwarding layer).
    3. The voice session task runs until the mock signals shutdown.
    4. Assertions: ``transcription`` (is_user=True) in output; no ``response_chunk``.
    """
    # Build a bot whose ask_stream yields one transcription + one model audio,
    # then signals shutdown so the outer voice loop exits cleanly.
    connection_ref: List[WebSocketConnection] = []  # populated after connection is created

    async def _mock_ask_stream(
        *args,
        audio_input=None,
        session_id=None,
        user_id=None,
        stt_only: bool = False,
        **kwargs,
    ) -> AsyncIterator[LiveVoiceResponse]:
        """Yield canned responses then signal shutdown to exit the voice loop."""
        yield _make_transcription_response("How are you?")
        yield _make_model_audio_response()  # must be suppressed in STT-only
        # Signal shutdown after delivering responses so _run_voice_session exits.
        if connection_ref:
            connection_ref[0].shutdown_event.set()

    bot = MagicMock()
    bot.close = AsyncMock()
    bot.ask_stream = _mock_ask_stream

    handler = VoiceChatHandler(
        bot_factory=lambda: bot,
        default_config=BotConfig(name="integration-agent"),
    )

    connection = _make_connection(stt_only=False)  # start_session will set it to True
    connection_ref.append(connection)

    # --- Drive start_session with stt_only=True ---
    message = {
        "type": "start_session",
        "stt_only": True,
        "config": {},
    }
    await handler._handle_start_session(connection, message)

    # Verify start_session set the flag and sent session_started with stt_only.
    assert connection.stt_only is True, (
        "connection.stt_only must be True after start_session with stt_only=True."
    )
    sent_msgs = _sent_messages(connection)
    session_started = next(
        (m for m in sent_msgs if m.get("type") == "session_started"), None
    )
    assert session_started is not None, "session_started message not sent."
    assert session_started.get("stt_only") is True, (
        "session_started must echo stt_only=True."
    )

    # --- Wait for the voice task to complete (the mock sets shutdown after yields) ---
    if connection.voice_task and not connection.voice_task.done():
        try:
            await asyncio.wait_for(connection.voice_task, timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            connection.shutdown_event.set()
            connection.voice_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await connection.voice_task

    # --- Verify output: transcription present, no response_chunk ---
    all_types = _sent_types(connection)

    assert "transcription" in all_types, (
        "STT-only session must emit 'transcription' (user speech). "
        f"All sent types: {all_types}"
    )

    # Verify the transcription frame carries is_user=True and the correct text.
    transcription_msgs = [m for m in _sent_messages(connection) if m.get("type") == "transcription"]
    assert transcription_msgs, "No transcription message found."
    assert transcription_msgs[0].get("is_user") is True, (
        "transcription frame must have is_user=True for user speech."
    )
    assert transcription_msgs[0].get("text") == "How are you?", (
        f"Expected transcription text 'How are you?', got: {transcription_msgs[0].get('text')!r}"
    )

    assert "response_chunk" not in all_types, (
        "STT-only session must NOT emit 'response_chunk' (double-brain guard). "
        f"All sent types: {all_types}"
    )


# ---------------------------------------------------------------------------
# Integration test: full-duplex session — model response IS emitted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_voice_ws_full_duplex_session() -> None:
    """Full-duplex voice session (no stt_only flag) emits model response_chunk.

    Verifies that the default full-duplex path is unchanged — removing the
    stt_only flag from start_session must still produce model audio frames.
    """
    connection_ref: List[WebSocketConnection] = []

    async def _mock_ask_stream(
        *args,
        audio_input=None,
        session_id=None,
        user_id=None,
        stt_only: bool = False,
        **kwargs,
    ) -> AsyncIterator[LiveVoiceResponse]:
        """Yield one model audio response then signal shutdown."""
        yield _make_model_audio_response()
        if connection_ref:
            connection_ref[0].shutdown_event.set()

    bot = MagicMock()
    bot.close = AsyncMock()
    bot.ask_stream = _mock_ask_stream

    handler = VoiceChatHandler(
        bot_factory=lambda: bot,
        default_config=BotConfig(name="integration-agent"),
    )

    connection = _make_connection(stt_only=False)
    connection_ref.append(connection)

    message = {
        "type": "start_session",
        # stt_only absent — full-duplex default
        "config": {},
    }
    await handler._handle_start_session(connection, message)

    assert connection.stt_only is False, (
        "connection.stt_only must default to False when absent from start_session."
    )

    # Wait for voice task to process the model audio response.
    if connection.voice_task and not connection.voice_task.done():
        try:
            await asyncio.wait_for(connection.voice_task, timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            connection.shutdown_event.set()
            connection.voice_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await connection.voice_task

    all_types = _sent_types(connection)

    assert "response_chunk" in all_types, (
        "Full-duplex session must emit 'response_chunk' for model audio. "
        f"All sent types: {all_types}"
    )
