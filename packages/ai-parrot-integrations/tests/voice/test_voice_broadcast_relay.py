"""Broadcast voice relay tests (FEAT-537 TASK-2959).

Two halves:

1. :class:`BroadcastVoiceSession` — the broadcast-owned relay. Real
   ``LiveVoiceResponse`` objects against a fake ``BroadcastSession``.
2. A regression guard that the **single-user** ``_HandlerVoiceSession._relay``
   still sends inline audio and still tees to ``connection.avatar_session``.
   That path is FEAT-536's and must not change.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.integrations.liveavatar.broadcast import (
    BroadcastReason,
    ParticipantPrincipal,
    errors,
)
from parrot.integrations.liveavatar.broadcast.voice_relay import BroadcastVoiceSession
from parrot.models.voice import (
    AudioFormat,
    LiveToolCall,
    LiveVoiceResponse,
    VoiceCapabilities,
    VoiceConfig,
    VoiceProvider,
)

TENANT = "acme"
AGENT = "agent-1"


def _capabilities() -> VoiceCapabilities:
    """Nova-shaped capability descriptor matching ``VoiceConfig()``'s defaults.

    ``VoiceSession.__init__`` runs an audio-format preflight (FEAT-418
    TASK-2172), so a bare mock is rejected.
    """
    return VoiceCapabilities(
        provider=VoiceProvider.NOVA,
        native_stt_only=True,
        supports_top_p=True,
        supports_per_call_voice=True,
        supports_per_call_inference=True,
        parallel_tool_execution=True,
        emits_reconnect_signal=True,
        supports_session_resumption=True,
        max_session_seconds=None,
        max_output_tokens=4096,
        input_formats=frozenset({AudioFormat.PCM_16K}),
        output_formats=frozenset({AudioFormat.PCM_24K}),
        input_sample_rates=frozenset({16000}),
        output_sample_rates=frozenset({24000}),
        voice_catalog=frozenset({"matthew"}),
        default_voice="matthew",
    )


# ── Fakes ──────────────────────────────────────────────────────────────────


class FakeBroadcastSession:
    """Records the media-routing calls the relay makes."""

    def __init__(self) -> None:
        self.owner_epoch = 3
        self.output_epoch = 5
        self.pushed: List[Any] = []
        self.interrupts: List[str] = []
        self.finished: List[str] = []

    async def push_audio(self, frame: Any) -> None:
        self.pushed.append(frame)

    async def interrupt(self, reason: str = "barge_in") -> None:
        self.interrupts.append(reason)

    async def finish_turn(self, turn_id: str) -> None:
        self.finished.append(turn_id)


class FakeVoiceClient:
    """Minimal ``VoiceCapable`` stand-in with the FEAT-537 user-id setter."""

    def __init__(self) -> None:
        self.user_ids: List[Optional[str]] = []

    @property
    def voice_capabilities(self) -> VoiceCapabilities:
        return _capabilities()

    def set_user_id(self, user_id: Optional[str]) -> None:
        self.user_ids.append(user_id)

    async def stream_voice(self, *_args: Any, **_kwargs: Any) -> Any:  # pragma: no cover
        raise AssertionError("the relay tests never start a real provider turn")


def _principal(user: str = "speaker-1") -> ParticipantPrincipal:
    return ParticipantPrincipal(
        user_id=user, tenant_id=TENANT, agent_id=AGENT, display_name=user
    )


def _response(**overrides: Any) -> LiveVoiceResponse:
    payload: Dict[str, Any] = {
        "text": "hello there",
        "role": "assistant",
        "turn_id": "turn-abc",
    }
    payload.update(overrides)
    return LiveVoiceResponse(**payload)


@pytest.fixture
def broadcast() -> FakeBroadcastSession:
    return FakeBroadcastSession()


@pytest.fixture
def relay(broadcast: FakeBroadcastSession) -> BroadcastVoiceSession:
    sent: List[Dict[str, Any]] = []

    async def _fanout(frame: Dict[str, Any]) -> None:
        sent.append(frame)

    session = BroadcastVoiceSession(
        client=FakeVoiceClient(),
        send_fn=_fanout,
        system_prompt="you are a broadcast agent",
        voice_config=VoiceConfig(),
        session_id="conversation-1",
        broadcast=broadcast,
    )
    session.sent_frames = sent  # type: ignore[attr-defined]
    return session


def _types(frames: List[Dict[str, Any]]) -> List[str]:
    return [frame["type"] for frame in frames]


# ── Relay behaviour ────────────────────────────────────────────────────────


async def test_relay_strips_pcm_from_wire_and_pushes_once(
    relay: BroadcastVoiceSession, broadcast: FakeBroadcastSession
) -> None:
    """Audio goes to the room exactly once and never down a participant socket."""
    relay.begin_speaker_turn("lease-a", _principal(), floor_epoch=7)
    pcm = b"\x01\x02" * 480

    await relay._relay(  # noqa: SLF001
        _response(
            audio_data=pcm,
            tool_calls=[
                LiveToolCall(id="tc-1", name="get_weather", arguments={"city": "Vigo"})
            ],
        ),
        turn_no=1,
    )

    frames: List[Dict[str, Any]] = relay.sent_frames  # type: ignore[attr-defined]
    assert "response_chunk" in _types(frames)
    assert "tool_call" in _types(frames)
    # The text/tool protocol is intact; only the inline PCM is gone.
    for frame in frames:
        assert "audio_base64" not in frame
        assert "audio_format" not in frame
    chunk = next(f for f in frames if f["type"] == "response_chunk")
    assert chunk["text"] == "hello there"

    assert len(broadcast.pushed) == 1
    pushed = broadcast.pushed[0]
    assert pushed.pcm == pcm
    assert pushed.sample_count == 480
    assert pushed.speaker_lease_id == "lease-a"
    assert pushed.floor_epoch == 7
    assert pushed.turn_id == "turn-abc"
    # Epochs are read from the broadcast at send time, not cached.
    assert pushed.owner_epoch == 3
    assert pushed.output_epoch == 5


async def test_sequence_numbers_restart_per_speaker_turn(
    relay: BroadcastVoiceSession, broadcast: FakeBroadcastSession
) -> None:
    relay.begin_speaker_turn("lease-a", _principal(), floor_epoch=1)
    for _ in range(3):
        await relay._relay(_response(audio_data=b"\x00\x00" * 10), turn_no=1)  # noqa: SLF001
    assert [frame.sequence for frame in broadcast.pushed] == [0, 1, 2]

    relay.begin_speaker_turn("lease-b", _principal("speaker-2"), floor_epoch=2)
    await relay._relay(_response(audio_data=b"\x00\x00" * 10), turn_no=2)  # noqa: SLF001
    assert broadcast.pushed[-1].sequence == 0


async def test_interrupt_and_complete_forwarded(
    relay: BroadcastVoiceSession, broadcast: FakeBroadcastSession
) -> None:
    relay.begin_speaker_turn("lease-a", _principal(), floor_epoch=1)

    await relay._relay(_response(is_interrupted=True, audio_data=b"\x00\x00"), turn_no=1)  # noqa: SLF001
    assert broadcast.interrupts == ["provider_interruption"]
    # Interrupted audio is NOT also pushed — that would be the stale speech the
    # interrupt exists to stop.
    assert broadcast.pushed == []

    await relay._relay(_response(is_complete=True), turn_no=1)  # noqa: SLF001
    assert broadcast.finished == ["turn-abc"]


async def test_completion_frames_still_reach_participants(
    relay: BroadcastVoiceSession,
) -> None:
    relay.begin_speaker_turn("lease-a", _principal(), floor_epoch=1)
    await relay._relay(_response(is_complete=True, text="done"), turn_no=1)  # noqa: SLF001
    frames: List[Dict[str, Any]] = relay.sent_frames  # type: ignore[attr-defined]
    assert "response_complete" in _types(frames)
    assert "ready_to_speak" in _types(frames)


async def test_speaker_attribution_lands_in_metadata(
    relay: BroadcastVoiceSession,
) -> None:
    """Audit/transcript records must carry who actually spoke."""
    relay.begin_speaker_turn("lease-a", _principal("ada"), floor_epoch=9)
    resp = _response()
    await relay._relay(resp, turn_no=1)  # noqa: SLF001
    assert resp.metadata["broadcast"] == {
        "speaker_lease_id": "lease-a",
        "speaker_user_id": "ada",
        "floor_epoch": 9,
    }


async def test_tool_calls_are_deduped_per_turn(relay: BroadcastVoiceSession) -> None:
    """Same shared dedup rule as the single-user path (FEAT-536 TASK-2942)."""
    relay.begin_speaker_turn("lease-a", _principal(), floor_epoch=1)
    call = LiveToolCall(id="tc-1", name="get_weather", arguments={})
    await relay._relay(_response(tool_calls=[call]), turn_no=1)  # noqa: SLF001
    await relay._relay(_response(tool_calls=[call], is_complete=True), turn_no=1)  # noqa: SLF001
    frames: List[Dict[str, Any]] = relay.sent_frames  # type: ignore[attr-defined]
    assert _types(frames).count("tool_call") == 1


# ── Speaker context: fail closed ───────────────────────────────────────────


async def test_turn_without_speaker_context_fails_closed(
    relay: BroadcastVoiceSession,
) -> None:
    """No provider call may happen for an unattributable turn."""
    with pytest.raises(errors.BroadcastError) as excinfo:
        await relay.start_turn()
    assert excinfo.value.reason is BroadcastReason.FLOOR_NOT_GRANTED

    with pytest.raises(errors.BroadcastError):
        await relay.push_audio(b"\x00\x00" * 160)


async def test_input_refused_after_the_speaker_is_cleared(
    relay: BroadcastVoiceSession,
) -> None:
    relay.begin_speaker_turn("lease-a", _principal(), floor_epoch=1)
    relay.end_speaker_turn()
    with pytest.raises(errors.BroadcastError):
        await relay.push_audio(b"\x00\x00" * 160)


async def test_per_turn_user_id_follows_the_speaker(
    relay: BroadcastVoiceSession,
) -> None:
    """The bot must resolve tools as the speaker, not as whoever started it."""
    client: FakeVoiceClient = relay.client  # type: ignore[assignment]
    relay.begin_speaker_turn("lease-a", _principal("ada"), floor_epoch=1)
    relay.begin_speaker_turn("lease-b", _principal("grace"), floor_epoch=2)
    relay.end_speaker_turn()
    assert client.user_ids == ["ada", "grace", None]


# ── Stale suppression ──────────────────────────────────────────────────────


async def test_stale_generation_frames_suppressed(
    relay: BroadcastVoiceSession, broadcast: FakeBroadcastSession
) -> None:
    """A response arriving after the floor moved produces nothing at all."""
    relay.begin_speaker_turn("lease-a", _principal(), floor_epoch=1)
    relay.end_speaker_turn()

    await relay._relay(  # noqa: SLF001
        _response(audio_data=b"\x00\x00" * 10, is_complete=True),
        turn_no=1,
    )
    assert relay.sent_frames == []  # type: ignore[attr-defined]
    assert broadcast.pushed == []
    assert broadcast.finished == []
    assert relay.suppressed_stale_responses == 1


async def test_late_display_event_from_a_previous_floor_is_suppressed(
    relay: BroadcastVoiceSession,
) -> None:
    relay.begin_speaker_turn("lease-a", _principal(), floor_epoch=1)
    relay.end_speaker_turn()
    await relay._relay(  # noqa: SLF001
        _response(metadata={"display_data": {"chart": "old"}}), turn_no=1
    )
    assert relay.sent_frames == []  # type: ignore[attr-defined]


async def test_misaligned_pcm_is_dropped_not_pushed(
    relay: BroadcastVoiceSession, broadcast: FakeBroadcastSession
) -> None:
    """An odd-length block would fail model validation; drop it instead."""
    relay.begin_speaker_turn("lease-a", _principal(), floor_epoch=1)
    await relay._relay(_response(audio_data=b"\x00\x01\x02"), turn_no=1)  # noqa: SLF001
    assert broadcast.pushed == []


async def test_fanout_can_be_attached_after_construction(
    broadcast: FakeBroadcastSession,
) -> None:
    """TASK-2960 attaches the real fan-out once control sockets exist."""
    session = BroadcastVoiceSession(
        client=FakeVoiceClient(),
        system_prompt="p",
        voice_config=VoiceConfig(),
        session_id="conversation-1",
        broadcast=broadcast,
    )
    seen: List[Dict[str, Any]] = []

    async def _fanout(frame: Dict[str, Any]) -> None:
        seen.append(frame)

    session.set_fanout(_fanout)
    session.begin_speaker_turn("lease-a", _principal(), floor_epoch=1)
    await session._relay(_response(), turn_no=1)  # noqa: SLF001
    assert seen


# ── Single-user regression (FEAT-536 path must not change) ─────────────────


def _handler_session() -> Any:
    """Build a ``_HandlerVoiceSession`` over mocks, as the FEAT-536 tests do."""
    from parrot.voice.handler import _HandlerVoiceSession

    handler = MagicMock()
    handler._send_message = AsyncMock()
    connection = MagicMock()
    connection.stt_only = False
    connection.avatar_session = MagicMock()
    connection.avatar_session.speak = AsyncMock()
    connection.avatar_session.interrupt = AsyncMock()
    connection.avatar_session.finish_turn = AsyncMock()

    client = MagicMock()
    client.voice_capabilities = _capabilities()
    session = _HandlerVoiceSession(
        client=client,
        send_fn=AsyncMock(),
        system_prompt="p",
        voice_config=VoiceConfig(),
        session_id="s1",
        handler=handler,
        connection=connection,
    )
    return session, handler, connection


async def test_legacy_relay_still_sends_audio_and_tees() -> None:
    """The single-user path keeps inline PCM and the connection-local tee."""
    session, handler, connection = _handler_session()
    pcm = b"\x07\x08" * 100

    await session._relay(_response(audio_data=pcm), turn_no=1)  # noqa: SLF001

    sent = [call.args[1] for call in handler._send_message.await_args_list]
    chunk = next(frame for frame in sent if frame["type"] == "response_chunk")
    # Inline audio is still there — unlike the broadcast path.
    assert chunk["audio_base64"]
    assert chunk["audio_format"] == "audio/pcm;rate=24000"
    connection.avatar_session.speak.assert_awaited_once_with(pcm)


async def test_legacy_relay_still_tees_interrupt_and_completion() -> None:
    session, _handler, connection = _handler_session()
    await session._relay(_response(is_interrupted=True), turn_no=1)  # noqa: SLF001
    connection.avatar_session.interrupt.assert_awaited_once()

    await session._relay(_response(is_complete=True), turn_no=1)  # noqa: SLF001
    connection.avatar_session.finish_turn.assert_awaited_once()


async def test_legacy_dedup_attributes_still_exposed() -> None:
    """Extraction kept the instance attributes existing code/tests read."""
    session, _handler, _connection = _handler_session()
    call = LiveToolCall(id="tc-9", name="x", arguments={})
    session.build_frames(_response(tool_calls=[call]), turn_no=4)
    assert session._tool_dedup_turn_no == 4  # noqa: SLF001
    assert "tc-9" in session._sent_tool_call_ids  # noqa: SLF001


def test_build_voice_frames_is_a_pure_module_function() -> None:
    """Both relays share one implementation of the wire protocol."""
    from parrot.voice.handler import ToolCallDedupState, build_voice_frames

    state = ToolCallDedupState()
    frames = build_voice_frames(
        _response(text="hi", audio_data=b"\x00\x00"),
        1,
        stt_only=False,
        dedup_state=state,
    )
    assert _types(frames)[0] == "response_chunk"

    stt_frames = build_voice_frames(
        _response(text="hi", role="user"), 1, stt_only=True, dedup_state=state
    )
    # STT-only gating is preserved: only the user transcription survives.
    assert _types(stt_frames) == ["transcription"]
