"""Integration tests for FEAT-536 TASK-2946 — prove Nova's dual output
end-to-end through a REAL ``VoiceBot`` + REAL ``ToolManager``/``AbstractTool``
+ the actual ``_AskStreamVoiceClient``/``_HandlerVoiceSession`` relay (spec
§3 Modules 4 and 6).

Only Nova's own SDK-transport boundary is mocked (``_open_stream``/
``_send_event``/``_iter_events`` — the same boundary
``packages/ai-parrot/tests/voice/conftest.py``'s ``build_nova_client()``
already mocks for provider conformance). ``stream_voice()`` itself,
``ToolManager.execute_tool()``, and the tool's own ``_execute()`` all run
for real — nothing about tool execution or the dual-output mapping is
mocked. The LiveAvatar transport stack (``LiveKitRoomManager``/
``LiveAvatarClient``/``AvatarWebSocket``) is mocked via the shared
``patched_stack`` fixture (this directory's ``conftest.py``, FEAT-245) —
no real network, LiveKit, or LiveAvatar connection is made.
"""

from __future__ import annotations

import asyncio
import base64
import sys
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.bots.voice import VoiceBot
from parrot.integrations.liveavatar.voice_session import VoiceAvatarSession
from parrot.models.voice import VoiceConfig
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema, ToolResult
from parrot.voice.handler import (
    BotConfig,
    VoiceChatHandler,
    WebSocketConnection,
    _AskStreamVoiceClient,
    _HandlerVoiceSession,
)

# ---------------------------------------------------------------------
# Deterministic real voice-aware tools
# ---------------------------------------------------------------------


class _EchoArgs(AbstractToolArgsSchema):
    topic: str = ""


class _VoiceAwareEchoTool(AbstractTool):
    """Deterministic real tool returning both spoken and visual output.

    A bare ``AbstractTool`` subclass with no custom ``args_schema`` would
    silently drop the model-supplied ``topic`` kwarg (``validate_args()``/
    ``_shallow_dump()``) — see TASK-2939's completion note for the same
    gotcha.
    """

    name = "voice_echo"
    description = "Echo a topic back with spoken text and a visual chart."
    args_schema = _EchoArgs

    async def _execute(self, topic: str = "", **kwargs) -> ToolResult:
        return ToolResult(
            success=True,
            status="success",
            result={"topic": topic},
            voice_text=f"Echo: {topic}",
            display_data={"topic": topic, "kind": "echo"},
        )


class _GatedEchoTool(AbstractTool):
    """Same behavior as :class:`_VoiceAwareEchoTool`, but its ``_execute``
    only returns once an externally-controlled ``asyncio.Event`` is set —
    a causal gate (not a preloaded array/sleep) used to deterministically
    force Nova's "tool still running when completionEnd arrives" branch
    (``_drain_admitted_tools()``), instead of racing real wall-clock
    timing against the fake event iterator's instant reads."""

    name = "voice_echo"
    description = "Echo a topic once the test-controlled gate opens."
    args_schema = _EchoArgs

    def __init__(self, gate: asyncio.Event, **kwargs):
        super().__init__(**kwargs)
        self._gate = gate

    async def _execute(self, topic: str = "", **kwargs) -> ToolResult:
        await self._gate.wait()
        return ToolResult(
            success=True,
            status="success",
            result={"topic": topic},
            voice_text=f"Echo: {topic}",
            display_data={"topic": topic, "kind": "echo"},
        )


# ---------------------------------------------------------------------
# Real VoiceBot + real Nova client, SDK-transport boundary only
# ---------------------------------------------------------------------


def _stub_nova_sdk_import(monkeypatch) -> None:
    """Same ``sys.modules`` stub ``test_nova_dual_output.py`` and
    ``packages/ai-parrot/tests/voice/conftest.py`` use — the Pre-Alpha
    ``aws_sdk_bedrock_runtime`` package is not installed in this sandbox."""
    monkeypatch.setitem(sys.modules, "aws_sdk_bedrock_runtime", MagicMock())


def _make_bot(monkeypatch, *, name: str, tools: list) -> VoiceBot:
    _stub_nova_sdk_import(monkeypatch)
    return VoiceBot(
        name=name,
        tools=tools,
        voice_config=VoiceConfig(provider="nova", voice_name="matthew", model="nova-2-sonic"),
    )


def _fake_iter_events(events: list):
    async def _iter_events(_stream):
        for event in events:
            yield event

    return _iter_events


def _wire_fake_nova_transport(bot: VoiceBot, events: list):
    """Build the REAL NovaClient VoiceBot would build for itself
    (``_resolve_llm_config()``/``_create_llm_client()`` — the same calls
    ``VoiceChatHandler._run_voice_session()`` makes), with only its own
    SDK-transport boundary mocked. ``bot.tool_manager`` (already populated
    by ``VoiceBot.__init__``'s real tool registration) is wired in by
    ``_create_llm_client()`` itself — never replaced."""
    config = bot._resolve_llm_config()
    client = bot._create_llm_client(config)
    client._open_stream = AsyncMock(return_value=AsyncMock())
    client._send_event = AsyncMock()
    client._iter_events = _fake_iter_events(events)
    bot._llm = client
    return client


async def _empty_audio() -> AsyncIterator[bytes]:
    return
    yield  # pragma: no cover — makes this an async generator


def _tool_call_events(tool_use_id: str, tool_name: str, args_json: str, *, audio_b64: str | None = None) -> list:
    events: list = [
        {"contentStart": {"role": "ASSISTANT"}},
        {"toolUse": {"toolUseId": tool_use_id, "toolName": tool_name, "content": args_json}},
        {"contentEnd": {"type": "TOOL"}},
    ]
    if audio_b64 is not None:
        events.append({"audioOutput": {"content": audio_b64}})
    events.append({"completionEnd": {}})
    return events


def _pcm_b64(payload: bytes) -> str:
    return base64.b64encode(payload).decode()


# ---------------------------------------------------------------------
# Handler/session/connection scaffolding (real _AskStreamVoiceClient +
# _HandlerVoiceSession — never mocked)
# ---------------------------------------------------------------------


def _make_handler() -> VoiceChatHandler:
    def _unused_bot_factory():
        raise AssertionError("bot_factory should not be invoked — bot is injected directly in these tests")

    return VoiceChatHandler(bot_factory=_unused_bot_factory, default_config=BotConfig(name="test-agent"))


def _make_connection(session_id: str) -> WebSocketConnection:
    mock_ws = MagicMock()
    mock_ws.send_json = AsyncMock()
    mock_ws.closed = False
    conn = WebSocketConnection(ws=mock_ws, session_id=session_id)
    conn.authenticated = True
    return conn


def _make_handler_session(handler: VoiceChatHandler, bot: VoiceBot, connection: WebSocketConnection) -> _HandlerVoiceSession:
    client = _AskStreamVoiceClient(bot, user_id=connection.user_id)

    async def send_fn(payload: dict) -> None:
        if not connection.ws.closed:
            await connection.ws.send_json(payload)

    return _HandlerVoiceSession(
        client=client,
        send_fn=send_fn,
        system_prompt=bot.system_prompt,
        voice_config=bot.voice_config,
        session_id=connection.session_id,
        stt_only=connection.stt_only,
        handler=handler,
        connection=connection,
    )


async def _drive_turn(session: _HandlerVoiceSession, connection: WebSocketConnection, turn_no: int) -> list:
    """Drive one turn through the session's own ``client``
    (``_AskStreamVoiceClient`` → ``VoiceBot.ask_stream()`` → the real Nova
    ``stream_voice()``) and relay every response through
    ``_HandlerVoiceSession._relay()`` — build_frames()'s dedup, the
    avatar tee, and every WebSocket frame all run for real. Returns the
    list of ``LiveVoiceResponse`` objects observed."""
    responses = []
    async for resp in session.client.stream_voice(
        _empty_audio(), session_id=connection.session_id, user_id=connection.user_id
    ):
        responses.append(resp)
        await session._relay(resp, turn_no)
    return responses


def _sent_frames(connection: WebSocketConnection) -> list:
    return [c.args[0] for c in connection.ws.send_json.await_args_list if c.args]


def _frames_of_type(connection: WebSocketConnection, frame_type: str) -> list:
    return [f for f in _sent_frames(connection) if f.get("type") == frame_type]


# ── test_voicebot_nova_websocket_tool_audio_display ───────────────────────


class TestVoicebotNovaWebsocketToolAudioDisplay:
    """Real VoiceBot + manager -> Nova stream -> _AskStreamVoiceClient /
    _HandlerVoiceSession; capture tool result, audio chunk and exactly one
    display frame."""

    @pytest.mark.asyncio
    async def test_voicebot_nova_websocket_tool_audio_display(self, monkeypatch):
        tool = _VoiceAwareEchoTool()
        bot = _make_bot(monkeypatch, name="dual-output-agent", tools=[tool])
        pcm = b"\x11\x22" * 480
        events = _tool_call_events("tu_1", "voice_echo", '{"topic": "weather"}', audio_b64=_pcm_b64(pcm))
        _wire_fake_nova_transport(bot, events)

        handler = _make_handler()
        connection = _make_connection("sess-1")
        session = _make_handler_session(handler, bot, connection)

        responses = await _drive_turn(session, connection, turn_no=1)

        # No mock replaces stream_voice/_execute_tool/ToolManager.execute_tool
        # on this path — the tool actually ran exactly once.
        all_tool_calls = [tc for r in responses for tc in r.tool_calls]
        assert len({tc.id for tc in all_tool_calls}) == 1
        assert all_tool_calls[0].result == {"output": "Echo: weather"}

        tool_call_frames = _frames_of_type(connection, "tool_call")
        display_frames = _frames_of_type(connection, "display_data")
        response_chunk_frames = _frames_of_type(connection, "response_chunk")

        assert len(tool_call_frames) == 1, "the delta and final snapshot must not both emit the tool_call frame"
        assert tool_call_frames[0]["name"] == "voice_echo"
        assert tool_call_frames[0]["result"] == {"output": "Echo: weather"}

        assert len(display_frames) == 1, "display_data is delivered on the successful tool delta, not repeated"
        assert display_frames[0]["data"] == {"topic": "weather", "kind": "echo"}

        audio_chunks = [f for f in response_chunk_frames if f.get("audio_base64")]
        assert len(audio_chunks) >= 1
        assert base64.b64decode(audio_chunks[0]["audio_base64"]) == pcm


# ── test_voicebot_nova_avatar_audio_and_lifecycle ─────────────────────────


class TestVoicebotNovaAvatarAudioAndLifecycle:
    """Same real path plus a real VoiceAvatarSession over mocked
    AvatarWebSocket/HTTP/room transports (patched_stack, FEAT-245):
    identical PCM delivered, interruption and completion forwarded."""

    @pytest.mark.asyncio
    async def test_voicebot_nova_avatar_audio_and_lifecycle(self, patched_stack, monkeypatch):
        _, _, avatar_ws, _ = patched_stack

        tool = _VoiceAwareEchoTool()
        bot = _make_bot(monkeypatch, name="dual-output-agent", tools=[tool])
        pcm = b"\xaa\xbb" * 480
        events = _tool_call_events("tu_1", "voice_echo", '{"topic": "traffic"}', audio_b64=_pcm_b64(pcm))
        _wire_fake_nova_transport(bot, events)

        handler = _make_handler()
        connection = _make_connection("sess-2")
        connection.avatar_session = await VoiceAvatarSession.start(agent_id="ag", session_id="sess-2", tenant_id=None)
        session = _make_handler_session(handler, bot, connection)

        await _drive_turn(session, connection, turn_no=1)

        # Identical PCM delivered to the avatar mouth — no resample/copy.
        avatar_ws.send_audio_frame.assert_awaited_once_with(pcm)
        # The final (is_complete=True) response flushes the avatar buffer.
        avatar_ws.finish_speaking.assert_awaited_once()
        avatar_ws.interrupt.assert_not_awaited()

        # The browser WebSocket path is unaffected by the avatar tee.
        assert len(_frames_of_type(connection, "response_chunk")) >= 1
        assert len(_frames_of_type(connection, "tool_call")) == 1

        await connection.avatar_session.aclose()

    @pytest.mark.asyncio
    async def test_barge_in_interrupts_avatar_through_real_path(self, patched_stack, monkeypatch):
        """An interrupted response (barge-in) tees to
        ``avatar_session.interrupt()`` — not ``speak()``/``finish_turn()``
        — through the same real relay path."""
        _, _, avatar_ws, _ = patched_stack

        tool = _VoiceAwareEchoTool()
        bot = _make_bot(monkeypatch, name="dual-output-agent", tools=[tool])
        # _HandlerVoiceSession.__init__'s audio-format preflight reads
        # self.client.voice_capabilities -> bot._llm.voice_capabilities —
        # wire the real (SDK-mocked) Nova client even though this test
        # never drives a turn through it.
        _wire_fake_nova_transport(bot, events=[])
        handler = _make_handler()
        connection = _make_connection("sess-2b")
        connection.avatar_session = await VoiceAvatarSession.start(agent_id="ag", session_id="sess-2b", tenant_id=None)
        session = _make_handler_session(handler, bot, connection)

        from parrot.models.voice import LiveVoiceResponse

        await session._relay(
            LiveVoiceResponse(text="", is_interrupted=True, session_id="sess-2b", turn_id="t1"),
            turn_no=1,
        )

        avatar_ws.interrupt.assert_awaited_once()
        avatar_ws.send_audio_frame.assert_not_awaited()

        await connection.avatar_session.aclose()


# ── test_avatar_failure_preserves_websocket_delivery ──────────────────────


class TestAvatarFailurePreservesWebsocketDelivery:
    """Avatar send/finish raises through the REAL Nova dual-output path;
    the browser still receives audio/display/completion — the inherited
    VoiceSession relay continues driving VoiceBot regardless."""

    @pytest.mark.asyncio
    async def test_avatar_failure_preserves_websocket_delivery(self, patched_stack, monkeypatch):
        _, _, avatar_ws, _ = patched_stack
        avatar_ws.send_audio_frame.side_effect = RuntimeError("avatar transport exploded")

        tool = _VoiceAwareEchoTool()
        bot = _make_bot(monkeypatch, name="dual-output-agent", tools=[tool])
        pcm = b"\x01\x02" * 480
        events = _tool_call_events("tu_1", "voice_echo", '{"topic": "weather"}', audio_b64=_pcm_b64(pcm))
        _wire_fake_nova_transport(bot, events)

        handler = _make_handler()
        connection = _make_connection("sess-3")
        connection.avatar_session = await VoiceAvatarSession.start(agent_id="ag", session_id="sess-3", tenant_id=None)
        session = _make_handler_session(handler, bot, connection)

        # Must not raise — the avatar tee is best-effort/isolated.
        await _drive_turn(session, connection, turn_no=1)

        avatar_ws.send_audio_frame.assert_awaited()
        # ... but the browser still received its audio, tool and display frames.
        assert len(_frames_of_type(connection, "response_chunk")) >= 1
        assert len(_frames_of_type(connection, "tool_call")) == 1
        assert len(_frames_of_type(connection, "display_data")) == 1

        await connection.avatar_session.aclose()


# ── test_two_voice_sessions_do_not_mix_results ────────────────────────────


class TestTwoVoiceSessionsDoNotMixResults:
    """Interleave two real, concurrent voice sessions and tool
    completions; identities, visual payloads and relay dedup state stay
    isolated (separate VoiceBot/ToolManager/tool instance per session,
    per spec §3 Module 6: "Instantiate tools per bot factory")."""

    @pytest.mark.asyncio
    async def test_two_voice_sessions_do_not_mix_results(self, monkeypatch):
        bot_a = _make_bot(monkeypatch, name="agent-a", tools=[_VoiceAwareEchoTool()])
        bot_b = _make_bot(monkeypatch, name="agent-b", tools=[_VoiceAwareEchoTool()])

        events_a = _tool_call_events("tu_a", "voice_echo", '{"topic": "weather"}')
        events_b = _tool_call_events("tu_b", "voice_echo", '{"topic": "traffic"}')
        _wire_fake_nova_transport(bot_a, events_a)
        _wire_fake_nova_transport(bot_b, events_b)

        handler = _make_handler()
        connection_a = _make_connection("sess-a")
        connection_b = _make_connection("sess-b")
        session_a = _make_handler_session(handler, bot_a, connection_a)
        session_b = _make_handler_session(handler, bot_b, connection_b)

        await asyncio.gather(
            _drive_turn(session_a, connection_a, turn_no=1),
            _drive_turn(session_b, connection_b, turn_no=1),
        )

        tool_calls_a = _frames_of_type(connection_a, "tool_call")
        tool_calls_b = _frames_of_type(connection_b, "tool_call")

        assert len(tool_calls_a) == 1 and len(tool_calls_b) == 1
        assert tool_calls_a[0]["arguments"] == {"topic": "weather"}
        assert tool_calls_b[0]["arguments"] == {"topic": "traffic"}
        assert tool_calls_a[0]["result"] == {"output": "Echo: weather"}
        assert tool_calls_b[0]["result"] == {"output": "Echo: traffic"}

        display_a = _frames_of_type(connection_a, "display_data")
        display_b = _frames_of_type(connection_b, "display_data")
        assert display_a[0]["data"] == {"topic": "weather", "kind": "echo"}
        assert display_b[0]["data"] == {"topic": "traffic", "kind": "echo"}

        # No cross-talk: connection A never saw connection B's topic or vice versa.
        assert "traffic" not in str(_sent_frames(connection_a))
        assert "weather" not in str(_sent_frames(connection_b))


# ── test_tool_final_only_and_next_turn_id_reuse ───────────────────────────


class TestToolFinalOnlyAndNextTurnIdReuse:
    """Final-only tool is delivered (no duplicate delta), and the same
    tool_use_id may be reused in a LATER turn without being treated as an
    already-relayed duplicate — proven through the real admit/drain
    machinery (TASK-2940/2941), not a synthetic LiveVoiceResponse."""

    @pytest.mark.asyncio
    async def test_tool_final_only_and_next_turn_id_reuse(self, monkeypatch):
        gate = asyncio.Event()
        tool = _GatedEchoTool(gate)
        bot = _make_bot(monkeypatch, name="dual-output-agent", tools=[tool])

        # Turn 1: contentEnd(TOOL) immediately followed by completionEnd —
        # with the gate held closed, the real admit/drain loop (audio.py's
        # _drain_admitted_tools()) MUST still be waiting on the tool when
        # completionEnd is processed, forcing the "final-only" branch
        # instead of an intermediate per-tool delta.
        events_turn1 = _tool_call_events("tu_1", "voice_echo", '{"topic": "weather"}')
        client = _wire_fake_nova_transport(bot, events_turn1)

        handler = _make_handler()
        connection = _make_connection("sess-4")
        session = _make_handler_session(handler, bot, connection)

        async def _open_gate_soon() -> None:
            await asyncio.sleep(0.05)
            gate.set()

        opener = asyncio.create_task(_open_gate_soon())
        responses_turn1 = await _drive_turn(session, connection, turn_no=1)
        await opener

        # The tool was admitted at contentEnd(TOOL) but only actually
        # completed inside the drain-on-completionEnd branch
        # (_drain_admitted_tools()) — i.e. it never had a chance to be
        # harvested mid-stream before the stream ended. No re-execution:
        # every LiveVoiceResponse that carries it agrees on the exact same
        # single result/id, and the final (is_complete=True) snapshot
        # includes it.
        turn1_tool_bearing = [r for r in responses_turn1 if r.tool_calls]
        assert turn1_tool_bearing, "the admitted tool must still be delivered once the stream ends"
        all_ids = {tc.id for r in turn1_tool_bearing for tc in r.tool_calls}
        assert all_ids == {"tu_1"}
        assert all(tc.result == {"output": "Echo: weather"} for r in turn1_tool_bearing for tc in r.tool_calls)
        final_responses = [r for r in responses_turn1 if r.is_complete]
        assert len(final_responses) == 1
        assert {tc.id for tc in final_responses[0].tool_calls} == {"tu_1"}

        # The "final-only" WS-frame guarantee: build_frames()'s per-turn
        # dedup (TASK-2942) must still deliver the tool_call frame exactly
        # ONCE even though it is present on both the drained-delta-shaped
        # response and the final snapshot's tool_calls list.
        turn1_tool_call_frames = _frames_of_type(connection, "tool_call")
        assert len(turn1_tool_call_frames) == 1, "the delivered final snapshot must not ALSO repeat as a delta"
        assert turn1_tool_call_frames[0]["result"] == {"output": "Echo: weather"}

        # Turn 2 reuses the SAME tool_use_id ("tu_1") in a fresh Nova
        # stream — a later turn's dedup bookkeeping must not treat it as
        # an already-relayed id from turn 1. The gate is already open
        # (set above), so the same tool instance resolves immediately —
        # this turn is proving id-reuse-across-turns, not timing.
        client._iter_events = _fake_iter_events(
            _tool_call_events("tu_1", "voice_echo", '{"topic": "commute"}')
        )

        await _drive_turn(session, connection, turn_no=2)

        turn2_tool_call_frames = [f for f in _frames_of_type(connection, "tool_call") if f.get("arguments") == {"topic": "commute"}]
        assert len(turn2_tool_call_frames) == 1, "reuse of the same id in a later turn must still be delivered"
