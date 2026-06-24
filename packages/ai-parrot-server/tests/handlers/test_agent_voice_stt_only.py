"""Unit tests for the STT-only mode of the Gemini voice WebSocket (FEAT-257, TASK-1631).

These tests verify:
- ``test_stt_only_emits_user_transcription``: STT-only mode forwards the
  ``transcription`` (is_user=True) frame from GeminiLiveClient to the client.
- ``test_stt_only_suppresses_model_response``: STT-only mode emits NO
  ``response_chunk`` and NO model audio frame (double-brain guard).
- ``test_default_still_full_duplex``: Without ``stt_only``, the full-duplex
  path is unchanged — ``response_chunk`` with model audio is forwarded.

All Gemini / bot internals are mocked — no real network connections.
``google.genai`` is injected into sys.modules so tests run without the optional
``google-genai`` distribution being installed.

Module loading note: the venv's editable-install for ``parrot.voice.handler``
and ``parrot.clients.live`` points to the *main* repo.  We extend
``parrot.__path__`` and ``parrot.voice.__path__`` with the worktree source
directories so Python resolves the worktree's modified copies.  This mirrors
the pattern used by the project's test suite (see conftest.py).
"""
from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from typing import List
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Locate the worktree source directories.
# File: packages/ai-parrot-server/tests/handlers/test_agent_voice_stt_only.py
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
    import parrot as _parrot_pkg  # noqa: E402
    for _src_dir in (_INTEGRATIONS_SRC / "parrot", _PARROT_SRC / "parrot"):
        _dir_str = str(_src_dir)
        if _dir_str not in _parrot_pkg.__path__:
            _parrot_pkg.__path__.insert(0, _dir_str)
    importlib.invalidate_caches()
except Exception:
    pass  # non-fatal — tests may still work

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

# Now import from the worktree's versions.
from parrot.clients.live import LiveVoiceResponse  # noqa: E402
from parrot.voice.handler import BotConfig, VoiceChatHandler, WebSocketConnection  # noqa: E402

# Sanity check: make sure we loaded the worktree's handler (not the main repo).
_handler_file = sys.modules.get("parrot.voice.handler", None)
_handler_path = getattr(_handler_file, "__file__", "") or ""
assert str(_WORKTREE_ROOT) in _handler_path, (
    f"parrot.voice.handler was loaded from the wrong location: {_handler_path!r}. "
    f"Expected a path inside {_WORKTREE_ROOT}."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_ws() -> MagicMock:
    """Return a minimal fake aiohttp.WebSocketResponse."""
    ws = MagicMock()
    ws.send_json = AsyncMock()
    return ws


def _make_connection(stt_only: bool = False) -> WebSocketConnection:
    """Return a minimal WebSocketConnection for testing.

    Args:
        stt_only: Whether to enable STT-only mode on the connection.

    Returns:
        A pre-configured WebSocketConnection instance.
    """
    conn = WebSocketConnection(
        ws=_make_mock_ws(),
        session_id="test-session-stt",
    )
    conn.authenticated = True
    conn.stt_only = stt_only
    conn.avatar_session = None
    return conn


def _make_handler() -> VoiceChatHandler:
    """Return a VoiceChatHandler with a no-op bot factory."""

    def _bot_factory() -> MagicMock:
        bot = MagicMock()
        bot.close = AsyncMock()
        return bot

    return VoiceChatHandler(
        bot_factory=_bot_factory,
        default_config=BotConfig(name="test-agent"),
    )


def _transcription_response(text: str) -> LiveVoiceResponse:
    """Return a LiveVoiceResponse carrying a user transcription frame."""
    return LiveVoiceResponse(
        text="",
        is_complete=False,
        metadata={"user_transcription": text},
        session_id="test-session-stt",
        turn_id="turn-1",
    )


def _model_audio_response(audio: bytes = b"\x00" * 100) -> LiveVoiceResponse:
    """Return a LiveVoiceResponse carrying a model audio chunk."""
    return LiveVoiceResponse(
        text="",
        audio_data=audio,
        is_complete=False,
        session_id="test-session-stt",
        turn_id="turn-1",
    )


def _model_text_response(text: str = "Hi there!") -> LiveVoiceResponse:
    """Return a LiveVoiceResponse carrying a model text chunk."""
    return LiveVoiceResponse(
        text=text,
        is_complete=False,
        session_id="test-session-stt",
        turn_id="turn-1",
    )


def _sent_types(connection: WebSocketConnection) -> List[str]:
    """Return the list of message type strings sent to the WS client."""
    return [
        call.args[0]["type"]
        for call in connection.ws.send_json.await_args_list
        if call.args and isinstance(call.args[0], dict) and "type" in call.args[0]
    ]


# ---------------------------------------------------------------------------
# TASK-1631 Unit Tests — VoiceChatHandler._send_voice_response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stt_only_emits_user_transcription():
    """STT-only mode forwards the ``transcription`` (is_user=True) frame.

    When a LiveVoiceResponse carries ``metadata["user_transcription"]``, the
    handler must emit a ``{"type": "transcription", "is_user": True, ...}``
    message even in STT-only mode.
    """
    handler = _make_handler()
    connection = _make_connection(stt_only=True)

    response = _transcription_response("Hello world")
    await handler._send_voice_response(connection, response)

    msg_types = _sent_types(connection)
    assert "transcription" in msg_types, (
        "Expected a 'transcription' frame to be sent in STT-only mode."
    )

    sent_msgs = [
        call.args[0]
        for call in connection.ws.send_json.await_args_list
        if call.args and isinstance(call.args[0], dict)
    ]
    transcription_msgs = [m for m in sent_msgs if m.get("type") == "transcription"]
    assert transcription_msgs, "No transcription message found."
    assert transcription_msgs[0].get("is_user") is True, (
        "transcription frame must have is_user=True for user speech."
    )
    assert transcription_msgs[0].get("text") == "Hello world"


@pytest.mark.asyncio
async def test_stt_only_suppresses_model_response():
    """STT-only mode emits NO ``response_chunk`` or model audio (double-brain guard).

    Both a model audio chunk and a model text chunk are passed through
    ``_send_voice_response``; neither must produce a ``response_chunk`` message
    when ``connection.stt_only=True``.
    """
    handler = _make_handler()
    connection = _make_connection(stt_only=True)

    # Feed both a model audio response and a model text response
    await handler._send_voice_response(connection, _model_audio_response())
    await handler._send_voice_response(connection, _model_text_response())

    msg_types = _sent_types(connection)
    assert "response_chunk" not in msg_types, (
        "STT-only mode must NOT emit response_chunk frames (double-brain guard). "
        f"Sent types: {msg_types}"
    )


@pytest.mark.asyncio
async def test_stt_only_suppresses_response_complete():
    """STT-only mode does NOT emit ``response_complete`` or ``ready_to_speak``.

    These frames are part of the model-response lifecycle and must be
    suppressed in STT-only mode.
    """
    handler = _make_handler()
    connection = _make_connection(stt_only=True)

    response = LiveVoiceResponse(
        text="This is a model reply.",
        audio_data=b"\x00" * 100,
        is_complete=True,
        session_id="test-session-stt",
        turn_id="turn-1",
    )
    await handler._send_voice_response(connection, response)

    msg_types = _sent_types(connection)
    assert "response_complete" not in msg_types, (
        "STT-only mode must NOT emit response_complete. Got: %s" % msg_types
    )
    assert "ready_to_speak" not in msg_types, (
        "STT-only mode must NOT emit ready_to_speak from model turn. Got: %s" % msg_types
    )


@pytest.mark.asyncio
async def test_default_still_full_duplex():
    """Without ``stt_only``, the full-duplex path is unchanged.

    A model audio response must produce a ``response_chunk`` frame when
    ``connection.stt_only=False`` (the default).
    """
    handler = _make_handler()
    connection = _make_connection(stt_only=False)  # Default full-duplex

    await handler._send_voice_response(connection, _model_audio_response())

    msg_types = _sent_types(connection)
    assert "response_chunk" in msg_types, (
        "Full-duplex mode must emit response_chunk for model audio. "
        f"Sent types: {msg_types}"
    )


@pytest.mark.asyncio
async def test_stt_only_parsed_from_start_session():
    """``start_session`` with ``stt_only: true`` sets ``connection.stt_only=True``.

    Verifies that ``_handle_start_session`` reads the ``stt_only`` field from
    the message payload and stores it on the connection.
    """
    import asyncio as _asyncio
    import contextlib

    bot = MagicMock()
    bot.close = AsyncMock()

    # ask_stream must be an async generator that terminates immediately so
    # the voice session task doesn't block the test.
    async def _empty_stream(*args, **kwargs):
        return
        yield  # make it an async generator

    bot.ask_stream = _empty_stream

    handler = VoiceChatHandler(
        bot_factory=lambda: bot,
        default_config=BotConfig(name="test-agent"),
    )
    connection = _make_connection(stt_only=False)

    message = {
        "type": "start_session",
        "stt_only": True,
        "config": {},
    }
    await handler._handle_start_session(connection, message)

    assert connection.stt_only is True, (
        "connection.stt_only must be True after start_session with stt_only=true."
    )

    sent_msgs = [
        call.args[0]
        for call in connection.ws.send_json.await_args_list
        if call.args and isinstance(call.args[0], dict)
    ]
    session_started = next(
        (m for m in sent_msgs if m.get("type") == "session_started"), None
    )
    assert session_started is not None, "session_started message not sent."
    assert session_started.get("stt_only") is True, (
        "session_started message must echo stt_only=true."
    )

    # Clean up the voice task.
    connection.shutdown_event.set()
    if connection.voice_task and not connection.voice_task.done():
        connection.voice_task.cancel()
        with contextlib.suppress(_asyncio.CancelledError):
            await connection.voice_task


@pytest.mark.asyncio
async def test_stt_only_absent_defaults_to_false():
    """``start_session`` without ``stt_only`` defaults to full-duplex (False)."""
    bot = MagicMock()
    bot.close = AsyncMock()
    # ask_stream must be an async generator that terminates immediately so
    # the voice session task doesn't block the test.
    async def _empty_stream(*args, **kwargs):
        return
        yield  # make it an async generator

    bot.ask_stream = _empty_stream

    handler = VoiceChatHandler(
        bot_factory=lambda: bot,
        default_config=BotConfig(name="test-agent"),
    )
    connection = _make_connection(stt_only=False)

    message = {
        "type": "start_session",
        # stt_only absent
        "config": {},
    }
    await handler._handle_start_session(connection, message)

    assert connection.stt_only is False, (
        "connection.stt_only must default to False when absent from start_session."
    )

    # Clean up the voice task to avoid leaving dangling asyncio tasks.
    connection.shutdown_event.set()
    if connection.voice_task and not connection.voice_task.done():
        connection.voice_task.cancel()
        import contextlib
        import asyncio as _asyncio
        with contextlib.suppress(_asyncio.CancelledError):
            await connection.voice_task


# ---------------------------------------------------------------------------
# GeminiLiveClient._build_live_config tests (unit — stubbed google.genai)
# ---------------------------------------------------------------------------


def test_build_live_config_stt_only_sets_empty_modalities():
    """``_build_live_config(stt_only=True)`` sets response_modalities to [].

    This tells Gemini not to generate a model response at all.
    """
    from parrot.clients.live import GeminiLiveClient

    client = GeminiLiveClient.__new__(GeminiLiveClient)
    # Minimal attribute setup to avoid __init__ side-effects
    client.language = "en-US"
    client.voice_name = "Puck"
    client.temperature = None
    client.max_tokens = None
    client.enable_tools = False
    client.logger = MagicMock()

    config = client._build_live_config(stt_only=True)

    assert config.response_modalities == [], (
        "STT-only mode must set response_modalities=[] to suppress model output."
    )
    assert config.input_audio_transcription is not None, (
        "input_audio_transcription must be set in STT-only mode."
    )
    assert config.output_audio_transcription is None, (
        "output_audio_transcription must be None in STT-only mode (no model output)."
    )


def test_build_live_config_default_full_duplex():
    """``_build_live_config()`` (default) uses AUDIO modality for full-duplex."""
    from parrot.clients.live import GeminiLiveClient

    client = GeminiLiveClient.__new__(GeminiLiveClient)
    client.language = "en-US"
    client.voice_name = "Puck"
    client.temperature = None
    client.max_tokens = None
    client.enable_tools = False
    client.logger = MagicMock()

    config = client._build_live_config(stt_only=False)

    assert "AUDIO" in config.response_modalities, (
        "Default full-duplex mode must include AUDIO in response_modalities."
    )
    assert config.input_audio_transcription is not None
    assert config.output_audio_transcription is not None
