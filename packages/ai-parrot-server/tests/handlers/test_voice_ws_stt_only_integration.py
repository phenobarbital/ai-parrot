"""Integration tests for the STT-only voice WebSocket session (FEAT-257, TASK-1632).

These tests exercise the full session pipeline end-to-end (start_session →
start_recording → audio_data → stop_recording → message forwarding) with
Gemini / VoiceBot fully mocked — no real network connections.

Turn-lifecycle note (FEAT-416 TASK-2152, repaired in FEAT-418): since the
``VoiceSession`` refactor, ``_run_voice_session()`` no longer drives turns —
it constructs ``connection.voice_session`` and then idles until shutdown.
The turn itself is driven by the client frames ``start_recording`` →
``audio_data`` → ``stop_recording``, which map onto
``VoiceSession.start_turn()`` / ``push_audio()`` / ``end_turn()``. A test
that calls only ``_handle_start_session()`` therefore never invokes
``bot.ask_stream`` at all and no frame is ever produced. Both tests below
drive the full frame sequence via :func:`_drive_one_turn`.

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
import base64
import contextlib
import importlib
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path
from typing import AsyncIterator, List, Optional
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
from parrot.models.voice import (  # noqa: E402
    AudioFormat,
    VoiceCapabilities,
    VoiceConfig,
    VoiceProvider,
)
from parrot.voice.handler import (  # noqa: E402
    BotConfig,
    VoiceChatHandler,
    WebSocketConnection,
)

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


def _make_mock_bot() -> MagicMock:
    """Return a bot double with a real ``voice_config`` and a real
    ``_llm.voice_capabilities`` descriptor.

    FEAT-418 (TASK-2172) added a construction-time audio-format preflight
    to ``VoiceSession.__init__``, which ``_run_voice_session()`` now
    reaches via ``_AskStreamVoiceClient`` (FEAT-418, TASK-2174) wrapping
    this bot — a bare ``MagicMock()``'s ``voice_config``/
    ``_llm.voice_capabilities`` are themselves empty-iterable Mocks and
    fail that preflight with a ``ValueError``.
    """
    bot = MagicMock()
    bot.close = AsyncMock()
    bot.voice_config = VoiceConfig()
    bot._llm.voice_capabilities = VoiceCapabilities(
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
    return bot


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
    """Return a LiveVoiceResponse carrying a user transcription.

    FEAT-418 (TASK-2175): the canonical envelope is a role="user" response
    carrying the actual transcript text, not
    metadata["user_transcription"] (removed, no deprecation window).
    """
    return LiveVoiceResponse(
        text=text,
        role="user",
        is_complete=False,
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
    """Return a LiveVoiceResponse carrying a model text chunk.

    Carries the canonical ``role="assistant"`` (FEAT-418) so it exercises
    ``build_frames``' assistant-transcription branch — the model-output
    path the STT-only guard must suppress alongside ``response_chunk``.
    """
    return LiveVoiceResponse(
        text=text,
        role="assistant",
        is_complete=False,
        session_id="integration-test-session",
        turn_id="turn-1",
    )


async def _await_voice_session(
    connection: WebSocketConnection,
    timeout: float = 2.0,
) -> None:
    """Block until ``_run_voice_session`` has built ``connection.voice_session``.

    ``_handle_start_session`` only *schedules* ``_run_voice_session`` as
    ``connection.voice_task``; the session object it constructs is not
    visible until that task gets its first slice of the event loop.

    Args:
        connection: The connection whose voice session to wait for.
        timeout: Seconds to wait before failing.

    Raises:
        AssertionError: If the session is not constructed within *timeout*.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while connection.voice_session is None:
        assert loop.time() < deadline, (
            "connection.voice_session was never constructed by "
            "_run_voice_session — the voice task may have died. "
            f"voice_task={connection.voice_task!r}"
        )
        await asyncio.sleep(0.01)


async def _consume_until_end_of_turn(
    audio_input: Optional[AsyncIterator],
    received: List[bytes],
) -> None:
    """Drain *audio_input* until the ``None`` end-of-turn sentinel.

    Mirrors what a real provider's ``stream_voice()`` does: it does not
    begin replying until the user's turn is closed. Without this, a mock
    would answer before ``end_turn()`` ever ran and the test would not
    actually exercise the turn lifecycle.

    Args:
        audio_input: The handler's per-turn PCM iterator, or None.
        received: Mutable list every consumed PCM chunk is appended to, so
            the test can assert the mic audio really reached the provider.
    """
    if audio_input is None:
        return
    async for chunk in audio_input:
        if chunk is None:  # end-of-turn sentinel pushed by end_turn()
            return
        received.append(chunk)


_MIC_AUDIO = b"\x01\x02" * 512


async def _drive_one_turn(
    handler: VoiceChatHandler,
    connection: WebSocketConnection,
    audio: bytes = _MIC_AUDIO,
) -> None:
    """Drive one complete mic turn through the handler's frame protocol.

    Sends the ``start_recording`` → ``audio_data`` → ``stop_recording``
    sequence a real client sends, which is what actually opens, feeds and
    closes a ``VoiceSession`` turn (see this module's docstring).

    Args:
        handler: The handler under test.
        connection: An already-started session's connection.
        audio: Raw PCM bytes to push as one mic chunk.
    """
    await _await_voice_session(connection)

    await handler._handle_start_recording(connection, {"type": "start_recording"})
    await handler._handle_audio_data(connection, {
        "type": "audio_data",
        "data": base64.b64encode(audio).decode(),
    })

    # _handle_stop_recording discards any clip shorter than its
    # MIN_DURATION_MS (500 ms) guard by cancelling the turn outright.
    # Backdate the recording start so the guard passes without spending a
    # real 500 ms in the test.
    connection.recording_start_time = datetime.now() - timedelta(milliseconds=600)
    await handler._handle_stop_recording(connection, {"type": "stop_recording"})


async def _await_voice_task(connection: WebSocketConnection, timeout: float = 5.0) -> None:
    """Wait for the connection's voice task to exit on its own.

    The mock ``ask_stream`` sets ``shutdown_event`` once it has delivered
    its responses, so ``_run_voice_session`` must leave its shutdown loop
    and tear the session down unprompted. A task that has to be cancelled
    is a failure, not a cleanup step — otherwise a broken shutdown path
    would still pass on the frames sent before it hung.

    Args:
        connection: The connection whose ``voice_task`` to await.
        timeout: Seconds to wait before declaring the shutdown broken.

    Raises:
        AssertionError: If the task does not finish within *timeout*.
    """
    assert connection.voice_task is not None, "start_session did not create a voice task."
    try:
        await asyncio.wait_for(asyncio.shield(connection.voice_task), timeout=timeout)
    except asyncio.TimeoutError:
        connection.shutdown_event.set()
        connection.voice_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await connection.voice_task
        raise AssertionError(
            f"voice_task did not exit within {timeout}s after shutdown_event was "
            "set — _run_voice_session's shutdown/teardown path is broken."
        )
    assert connection.shutdown_event.is_set(), (
        "voice_task exited without shutdown_event being set — the mock never "
        "reached the end of its response stream, so the turn did not run."
    )


# ---------------------------------------------------------------------------
# Integration test: STT-only session — start_session → voice task → assertions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_voice_ws_stt_only_session() -> None:
    """STT-only voice session emits user transcription only — no model response.

    End-to-end integration scenario:
    1. Open a session via ``_handle_start_session`` with ``stt_only=True``.
    2. Drive a real mic turn (start_recording → audio_data → stop_recording).
    3. The bot's ``ask_stream`` waits for end-of-turn, then yields: one user
       transcription frame, then one model audio frame (simulating Gemini
       firing despite STT-only config; the handler must suppress this at the
       forwarding layer).
    4. The voice session task runs until the mock signals shutdown.
    5. Assertions: ``transcription`` (is_user=True) in output; no ``response_chunk``.
    """
    # Build a bot whose ask_stream yields one transcription + one model audio,
    # then signals shutdown so the outer voice loop exits cleanly.
    connection_ref: List[WebSocketConnection] = []  # populated after connection is created
    received_audio: List[bytes] = []
    seen_stt_only: List[bool] = []

    async def _mock_ask_stream(
        *args,
        audio_input=None,
        session_id=None,
        user_id=None,
        stt_only: bool = False,
        **kwargs,
    ) -> AsyncIterator[LiveVoiceResponse]:
        """Yield canned responses then signal shutdown to exit the voice loop."""
        seen_stt_only.append(stt_only)
        await _consume_until_end_of_turn(audio_input, received_audio)
        yield _make_transcription_response("How are you?")
        yield _make_model_audio_response()  # must be suppressed in STT-only
        # An assistant-role text frame — the other model-output branch the
        # STT-only guard must also suppress (build_frames emits it as
        # transcription/is_user=False when stt_only is off).
        yield _make_model_text_response("I am well, thank you.")
        # Signal shutdown after delivering responses so _run_voice_session exits.
        if connection_ref:
            connection_ref[0].shutdown_event.set()

    bot = _make_mock_bot()
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

    # --- Drive a real mic turn, then wait for the voice task to complete ---
    await _drive_one_turn(handler, connection)
    await _await_voice_task(connection)

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

    # The double-brain guard covers every model-output branch, not just
    # response_chunk: the assistant-role text frame yielded above must not
    # surface as an is_user=False transcription either.
    assert all(m.get("is_user") is True for m in transcription_msgs), (
        "STT-only session leaked an assistant transcription (is_user=False). "
        f"Transcription frames: {transcription_msgs}"
    )
    for leaked in ("display_data", "tool_call", "response_complete"):
        assert leaked not in all_types, (
            f"STT-only session must NOT emit '{leaked}' (double-brain guard). "
            f"All sent types: {all_types}"
        )

    # The turn really carried the mic audio through
    # _handle_audio_data → push_audio → the provider's audio iterator.
    assert _MIC_AUDIO in received_audio, (
        "The pushed mic audio never reached the provider's audio iterator — "
        f"got {len(received_audio)} chunk(s) totalling "
        f"{sum(len(c) for c in received_audio)} bytes."
    )

    # stt_only must propagate down to the bot, not merely gate the frames
    # on the way back out (_AskStreamVoiceClient.stream_voice → ask_stream).
    assert seen_stt_only == [True], (
        f"ask_stream should have been called once with stt_only=True, got {seen_stt_only}."
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
    received_audio: List[bytes] = []
    seen_stt_only: List[bool] = []

    async def _mock_ask_stream(
        *args,
        audio_input=None,
        session_id=None,
        user_id=None,
        stt_only: bool = False,
        **kwargs,
    ) -> AsyncIterator[LiveVoiceResponse]:
        """Yield one model audio response then signal shutdown."""
        seen_stt_only.append(stt_only)
        await _consume_until_end_of_turn(audio_input, received_audio)
        yield _make_model_audio_response()
        if connection_ref:
            connection_ref[0].shutdown_event.set()

    bot = _make_mock_bot()
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

    # Drive a real mic turn, then wait for the voice task to process the
    # model audio response.
    await _drive_one_turn(handler, connection)
    await _await_voice_task(connection)

    all_types = _sent_types(connection)

    assert "response_chunk" in all_types, (
        "Full-duplex session must emit 'response_chunk' for model audio. "
        f"All sent types: {all_types}"
    )

    assert _MIC_AUDIO in received_audio, (
        "The pushed mic audio never reached the provider's audio iterator — "
        f"got {len(received_audio)} chunk(s) totalling "
        f"{sum(len(c) for c in received_audio)} bytes."
    )

    assert seen_stt_only == [False], (
        f"ask_stream should have been called once with stt_only=False, got {seen_stt_only}."
    )
