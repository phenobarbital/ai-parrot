"""Broadcast voice relay tests (FEAT-537 TASK-2959).

Two halves:

1. :class:`BroadcastVoiceSession` — the broadcast-owned relay. Real
   ``LiveVoiceResponse`` objects against a fake ``BroadcastSession``.
2. A regression guard that the **single-user** ``_HandlerVoiceSession._relay``
   still sends inline audio and still tees to ``connection.avatar_session``.
   That path is FEAT-536's and must not change.
"""

from __future__ import annotations

import asyncio
import base64

import aiohttp
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
    return ParticipantPrincipal(user_id=user, tenant_id=TENANT, agent_id=AGENT, display_name=user)


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
            tool_calls=[LiveToolCall(id="tc-1", name="get_weather", arguments={"city": "Vigo"})],
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
    # `response_chunk` is audio-only on the wire: the assistant `transcription`
    # frame is the sole source of bubble text. Echoing the text in both
    # duplicated every delta in the browser, so the broadcast fan-out must
    # carry it exactly once, the same way the single-user path does.
    chunk = next(f for f in frames if f["type"] == "response_chunk")
    assert chunk["text"] == ""
    bubble = next(f for f in frames if f["type"] == "transcription" and not f["is_user"])
    assert bubble["text"] == "hello there"

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


async def test_interrupt_and_complete_forwarded(relay: BroadcastVoiceSession, broadcast: FakeBroadcastSession) -> None:
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
    await relay._relay(_response(metadata={"display_data": {"chart": "old"}}), turn_no=1)  # noqa: SLF001
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
    from parrot.voice.handler import WS_CLOSE_UNAUTHENTICATED, _HandlerVoiceSession

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

    stt_frames = build_voice_frames(_response(text="hi", role="user"), 1, stt_only=True, dedup_state=state)
    # STT-only gating is preserved: only the user transcription survives.
    assert _types(stt_frames) == ["transcription"]


# ---------------------------------------------------------------------------
# FEAT-537 (TASK-2960): /ws/voice/broadcast route
# ---------------------------------------------------------------------------

import json  # noqa: E402

from aiohttp import web  # noqa: E402

from parrot.integrations.liveavatar.broadcast import (  # noqa: E402
    BroadcastDescriptor,
    FloorState,
    InMemoryBroadcastRegistry,
    ViewerLease,
)
from parrot.integrations.liveavatar.broadcast.floor import (  # noqa: E402
    FloorCoordinator,
)
from parrot.voice.handler import (  # noqa: E402
    BROADCAST_MAX_AUDIO_B64_BYTES,
    WS_CLOSE_FORBIDDEN,
    WS_CLOSE_UNAUTHENTICATED,
    VoiceChatHandler,
)

BROADCAST_ID = "bc-ws-1"


class FakeVoiceSessionForRoute:
    """Captures what the route feeds into the broadcast voice session."""

    def __init__(self) -> None:
        self.turns: List[tuple] = []
        self.audio: List[bytes] = []
        self.started = 0
        self.ended = 0

    def begin_speaker_turn(self, lease_id: str, principal: Any, floor_epoch: int) -> int:
        self.turns.append((lease_id, principal.user_id, floor_epoch))
        return len(self.turns)

    async def start_turn(self) -> None:
        self.started += 1

    async def end_turn(self) -> None:
        self.ended += 1

    async def push_audio(self, pcm: bytes) -> None:
        self.audio.append(pcm)


class FakeBroadcastService:
    """In-memory `BroadcastControlService` over the real registry."""

    def __init__(self) -> None:
        self.registry = InMemoryBroadcastRegistry()
        self.session = FakeVoiceSessionForRoute()
        self.coordinator = FloorCoordinator(notifier=self._notify)
        self.controls: Dict[str, Any] = {}
        self.detached: List[str] = []

    async def _notify(self, lease_id: str, frame: Dict[str, Any]) -> None:
        send = self.controls.get(lease_id)
        if send is not None:
            await send(frame)

    async def resolve_principal(self, user: Any, agent_id: str) -> ParticipantPrincipal:
        if user is None:
            raise PermissionError("unauthenticated")
        return ParticipantPrincipal(user_id=user.user_id, tenant_id=TENANT, agent_id=agent_id)

    async def get_descriptor(self, tenant_id: str, broadcast_id: str) -> Optional[BroadcastDescriptor]:
        return await self.registry.get(tenant_id, broadcast_id)

    async def get_lease(self, tenant_id: str, broadcast_id: str, lease_id: str) -> Optional[ViewerLease]:
        for lease in await self.registry.list_leases(tenant_id, broadcast_id):
            if lease.lease_id == lease_id:
                return lease
        return None

    async def heartbeat(self, tenant_id: str, broadcast_id: str, lease_id: str) -> None:
        await self.registry.heartbeat_control(tenant_id, broadcast_id, lease_id)

    async def attach_control(self, tenant_id: str, broadcast_id: str, lease_id: str, send: Any) -> None:
        self.controls[lease_id] = send

    async def detach_control(self, tenant_id: str, broadcast_id: str, lease_id: str) -> None:
        self.controls.pop(lease_id, None)
        self.detached.append(lease_id)

    async def public_state(self, tenant_id: str, broadcast_id: str) -> Dict[str, Any]:
        descriptor = await self.registry.get(tenant_id, broadcast_id)
        assert descriptor is not None
        leases = await self.registry.list_leases(tenant_id, broadcast_id)
        return descriptor.to_public_state(viewer_count=len(leases)).model_dump(mode="json")

    async def bind_speaker_socket(
        self,
        tenant_id: str,
        broadcast_id: str,
        lease_id: str,
        socket_id: str,
        floor_epoch: int,
    ) -> bool:
        return await self.registry.bind_speaker_socket(tenant_id, broadcast_id, lease_id, socket_id, floor_epoch)

    async def unbind_speaker_socket(self, tenant_id: str, broadcast_id: str, lease_id: str, socket_id: str) -> bool:
        return await self.registry.unbind_speaker_socket(tenant_id, broadcast_id, lease_id, socket_id)

    def voice_session(self, tenant_id: str, broadcast_id: str) -> Any:
        return self.session

    def media_session(self, tenant_id: str, broadcast_id: str) -> Any:
        return None

    async def attach_speaker_input(
        self,
        tenant_id: str,
        broadcast_id: str,
        lease_id: str,
        principal: Any,
        floor_epoch: int,
    ) -> Any:
        from parrot.integrations.liveavatar.broadcast.worker_transport import (
            LocalSpeakerInput,
        )

        return LocalSpeakerInput(self.session, lease_id, principal, floor_epoch)

    async def release_floor(self, tenant_id: str, broadcast_id: str, speaker_lease_id: str) -> Any:
        return await self.coordinator.release(
            self.registry,
            None,
            tenant_id=tenant_id,
            broadcast_id=broadcast_id,
            speaker_lease_id=speaker_lease_id,
        )

    async def seed(self, *names: str) -> Dict[str, Any]:
        await self.registry.create(
            BroadcastDescriptor(
                broadcast_id=BROADCAST_ID,
                tenant_id=TENANT,
                agent_id=AGENT,
                creator_user_id="creator",
            )
        )
        leases: Dict[str, Any] = {}
        for name in names:
            admission = await self.registry.reserve_viewer(
                TENANT,
                BROADCAST_ID,
                ParticipantPrincipal(user_id=name, tenant_id=TENANT, agent_id=AGENT, display_name=name),
                f"identity-{name}",
            )
            await self.registry.confirm_viewer(TENANT, BROADCAST_ID, admission.lease.lease_id)
            await self.registry.heartbeat_control(TENANT, BROADCAST_ID, admission.lease.lease_id)
            leases[name] = admission.lease
        return leases


class _AlwaysUser:
    """Token validator stub: any token maps to a user named after it."""

    async def validate(self, token: str) -> Any:
        from parrot.core.ws_auth import AuthenticatedUser

        return AuthenticatedUser(user_id=token, username=token)


@pytest.fixture
async def broadcast_app(aiohttp_client):
    """A handler with a fake broadcast service, mounted on a test client."""
    service = FakeBroadcastService()
    handler = VoiceChatHandler(
        require_auth=True,
        token_validator=_AlwaysUser(),
        broadcast_service=service,
    )
    app = web.Application()
    handler.setup_routes(app, include_static=False)
    client = await aiohttp_client(app)
    return client, service, handler


async def _connect(client: Any, user: str) -> Any:
    """Connect the way a browser does: credentials in the subprotocol.

    Not ``?token=``: the broadcast route deliberately refuses query-string
    credentials, because they are written to access, proxy and history logs
    (spec §2, "Keep credentials out of URL query strings").
    """
    return await client.ws_connect(
        f"/ws/voice/broadcast/{AGENT}/{BROADCAST_ID}",
        protocols=("jwt", user),
    )


async def _drain_until(ws: Any, wanted: str, limit: int = 12) -> Dict[str, Any]:
    """Read frames until one of ``wanted`` type arrives."""
    for _ in range(limit):
        frame = json.loads((await ws.receive()).data)
        if frame.get("type") == wanted:
            return frame
    raise AssertionError(f"never saw a {wanted!r} frame")


async def test_route_is_not_mounted_without_a_service(aiohttp_client) -> None:
    """An ordinary voice deployment exposes exactly the routes it did before."""
    handler = VoiceChatHandler()
    app = web.Application()
    handler.setup_routes(app, include_static=False)
    paths = {getattr(route.resource, "canonical", "") for route in app.router.routes()}
    assert not any("broadcast" in path for path in paths)
    assert handler.broadcast_enabled is False


async def test_route_is_mounted_with_a_service(broadcast_app) -> None:
    _client, _service, handler = broadcast_app
    assert handler.broadcast_enabled is True


async def test_ws_attach_wrong_owner_closes_4403(broadcast_app) -> None:
    """A lease id is not a bearer token."""
    client, service, _handler = broadcast_app
    leases = await service.seed("moderator", "guest")

    ws = await _connect(client, "guest")
    await ws.send_json({"type": "attach", "lease_id": leases["moderator"].lease_id})
    msg = await ws.receive()
    assert msg.type.name == "CLOSE"
    assert ws.close_code == WS_CLOSE_FORBIDDEN


async def test_ws_attach_unknown_lease_closes_4403(broadcast_app) -> None:
    client, service, _handler = broadcast_app
    await service.seed("moderator")
    ws = await _connect(client, "moderator")
    await ws.send_json({"type": "attach", "lease_id": "lease-ghost"})
    await ws.receive()
    assert ws.close_code == WS_CLOSE_FORBIDDEN


async def test_ws_attach_pushes_state_and_floor_permission(broadcast_app) -> None:
    client, service, _handler = broadcast_app
    leases = await service.seed("moderator", "guest")

    ws = await _connect(client, "moderator")
    await ws.send_json({"type": "attach", "lease_id": leases["moderator"].lease_id})
    attached = await _drain_until(ws, "attached")
    assert attached["is_moderator"] is True

    state = await _drain_until(ws, "broadcast_state")
    assert state["state"]["broadcast_id"] == BROADCAST_ID
    # The projection is credential-free.
    assert "token" not in json.dumps(state).lower()

    floor = await _drain_until(ws, "floor_state")
    assert floor["granted"] is True

    # A non-speaker is told so explicitly, not left to infer it.
    ws2 = await _connect(client, "guest")
    await ws2.send_json({"type": "attach", "lease_id": leases["guest"].lease_id})
    guest_floor = await _drain_until(ws2, "floor_state")
    assert guest_floor["granted"] is False
    await ws.close()
    await ws2.close()


async def test_ws_audio_requires_a_current_floor_epoch(broadcast_app) -> None:
    client, service, _handler = broadcast_app
    leases = await service.seed("moderator")
    ws = await _connect(client, "moderator")
    await ws.send_json({"type": "attach", "lease_id": leases["moderator"].lease_id})
    await _drain_until(ws, "floor_state")

    # Omitted epoch → stale, not waved through.
    await ws.send_json({"type": "audio_data", "data": "AAAA"})
    error = await _drain_until(ws, "error")
    assert error["code"] == "stale_floor_epoch"

    # Superseded epoch → stale.
    await ws.send_json({"type": "audio_data", "data": "AAAA", "floor_epoch": 99})
    error = await _drain_until(ws, "error")
    assert error["code"] == "stale_floor_epoch"

    assert service.session.audio == []
    await ws.close()


async def test_ws_non_speaker_audio_is_rejected(broadcast_app) -> None:
    client, service, _handler = broadcast_app
    leases = await service.seed("moderator", "guest")
    ws = await _connect(client, "guest")
    await ws.send_json({"type": "attach", "lease_id": leases["guest"].lease_id})
    await _drain_until(ws, "floor_state")

    await ws.send_json({"type": "audio_data", "data": "AAAA", "floor_epoch": 1})
    error = await _drain_until(ws, "error")
    assert error["code"] == "floor_not_granted"
    assert service.session.audio == []
    await ws.close()


async def test_ws_speaker_audio_reaches_the_broadcast_session(broadcast_app) -> None:
    client, service, _handler = broadcast_app
    leases = await service.seed("moderator")
    ws = await _connect(client, "moderator")
    await ws.send_json({"type": "attach", "lease_id": leases["moderator"].lease_id})
    await _drain_until(ws, "floor_state")

    await ws.send_json({"type": "start_recording", "floor_epoch": 1})
    await _drain_until(ws, "recording_started")
    assert service.session.turns == [(leases["moderator"].lease_id, "moderator", 1)]
    assert service.session.started == 1

    await ws.send_json({"type": "audio_data", "data": base64.b64encode(b"\x01\x02").decode(), "floor_epoch": 1})
    await ws.send_json({"type": "stop_recording", "floor_epoch": 1})
    await _drain_until(ws, "recording_stopped")
    assert service.session.audio == [b"\x01\x02"]
    assert service.session.ended == 1
    await ws.close()


async def test_ws_duplicate_speaker_socket_409(broadcast_app) -> None:
    """The first capture socket keeps the floor; the second is refused."""
    client, service, _handler = broadcast_app
    leases = await service.seed("moderator")
    lease_id = leases["moderator"].lease_id

    first = await _connect(client, "moderator")
    await first.send_json({"type": "attach", "lease_id": lease_id})
    await _drain_until(first, "floor_state")
    await first.send_json({"type": "start_recording", "floor_epoch": 1})
    await _drain_until(first, "recording_started")

    second = await _connect(client, "moderator")
    await second.send_json({"type": "attach", "lease_id": lease_id})
    await _drain_until(second, "floor_state")
    await second.send_json({"type": "start_recording", "floor_epoch": 1})
    error = await _drain_until(second, "error")
    assert error["code"] == "speaker_connection_exists"

    # The original binding survived.
    await first.send_json({"type": "audio_data", "data": base64.b64encode(b"\x03\x04").decode(), "floor_epoch": 1})
    await first.send_json({"type": "stop_recording", "floor_epoch": 1})
    await _drain_until(first, "recording_stopped")
    assert b"\x03\x04" in service.session.audio
    await first.close()
    await second.close()


async def test_ws_revoke_stops_old_speaker_audio(broadcast_app) -> None:
    """After a handoff the previous speaker's next frame is refused."""
    client, service, _handler = broadcast_app
    leases = await service.seed("moderator", "guest")
    ws = await _connect(client, "moderator")
    await ws.send_json({"type": "attach", "lease_id": leases["moderator"].lease_id})
    await _drain_until(ws, "floor_state")
    await ws.send_json({"type": "start_recording", "floor_epoch": 1})
    await _drain_until(ws, "recording_started")

    current = await service.registry.get(TENANT, BROADCAST_ID)
    assert current is not None
    await service.coordinator.handoff(
        service.registry,
        None,
        tenant_id=TENANT,
        broadcast_id=BROADCAST_ID,
        moderator_lease_id=leases["moderator"].lease_id,
        target_lease_id=leases["guest"].lease_id,
        expected_version=current.version,
    )

    # The outgoing speaker is told to stop...
    revoked = await _drain_until(ws, "floor_revoked")
    assert revoked["floor_epoch"] == 2

    # ...and its audio is refused even at what WAS a valid epoch.
    before = len(service.session.audio)
    await ws.send_json({"type": "audio_data", "data": "AAAA", "floor_epoch": 1})
    error = await _drain_until(ws, "error")
    assert error["code"] == "floor_not_granted"
    assert len(service.session.audio) == before
    await ws.close()


async def test_ws_finish_speaking_returns_the_floor(broadcast_app) -> None:
    client, service, _handler = broadcast_app
    leases = await service.seed("moderator", "guest")
    current = await service.registry.get(TENANT, BROADCAST_ID)
    assert current is not None
    await service.coordinator.handoff(
        service.registry,
        None,
        tenant_id=TENANT,
        broadcast_id=BROADCAST_ID,
        moderator_lease_id=leases["moderator"].lease_id,
        target_lease_id=leases["guest"].lease_id,
        expected_version=current.version,
    )

    ws = await _connect(client, "guest")
    await ws.send_json({"type": "attach", "lease_id": leases["guest"].lease_id})
    await _drain_until(ws, "floor_state")
    await ws.send_json({"type": "finish_speaking"})
    await _drain_until(ws, "broadcast_state")

    descriptor = await service.registry.get(TENANT, BROADCAST_ID)
    assert descriptor is not None
    assert descriptor.speaker_lease_id == leases["moderator"].lease_id
    await ws.close()


async def test_ws_speaker_disconnect_returns_the_floor(broadcast_app) -> None:
    client, service, _handler = broadcast_app
    leases = await service.seed("moderator", "guest")
    current = await service.registry.get(TENANT, BROADCAST_ID)
    assert current is not None
    await service.coordinator.handoff(
        service.registry,
        None,
        tenant_id=TENANT,
        broadcast_id=BROADCAST_ID,
        moderator_lease_id=leases["moderator"].lease_id,
        target_lease_id=leases["guest"].lease_id,
        expected_version=current.version,
    )

    ws = await _connect(client, "guest")
    await ws.send_json({"type": "attach", "lease_id": leases["guest"].lease_id})
    await _drain_until(ws, "floor_state")
    await ws.close()

    for _ in range(50):
        await asyncio.sleep(0.01)
        descriptor = await service.registry.get(TENANT, BROADCAST_ID)
        if descriptor and descriptor.speaker_lease_id == leases["moderator"].lease_id:
            break
    assert descriptor is not None
    assert descriptor.speaker_lease_id == leases["moderator"].lease_id
    assert leases["guest"].lease_id in service.detached


async def test_ws_ping_records_a_heartbeat(broadcast_app) -> None:
    client, service, _handler = broadcast_app
    leases = await service.seed("moderator")
    ws = await _connect(client, "moderator")
    await ws.send_json({"type": "attach", "lease_id": leases["moderator"].lease_id})
    await _drain_until(ws, "floor_state")
    await ws.send_json({"type": "ping"})
    pong = await _drain_until(ws, "pong")
    assert pong["type"] == "pong"
    lease = await service.get_lease(TENANT, BROADCAST_ID, leases["moderator"].lease_id)
    assert lease is not None
    assert lease.last_control_heartbeat is not None
    await ws.close()


async def test_ws_oversized_audio_is_refused(broadcast_app) -> None:
    client, service, _handler = broadcast_app
    leases = await service.seed("moderator")
    ws = await _connect(client, "moderator")
    await ws.send_json({"type": "attach", "lease_id": leases["moderator"].lease_id})
    await _drain_until(ws, "floor_state")
    await ws.send_json(
        {
            "type": "audio_data",
            "data": "A" * (BROADCAST_MAX_AUDIO_B64_BYTES + 4),
            "floor_epoch": 1,
        }
    )
    error = await _drain_until(ws, "error")
    assert error["code"] == "payload_too_large"
    assert service.session.audio == []
    await ws.close()


async def test_ws_start_session_never_creates_a_bot(broadcast_app) -> None:
    client, service, _handler = broadcast_app
    leases = await service.seed("moderator")
    ws = await _connect(client, "moderator")
    await ws.send_json({"type": "attach", "lease_id": leases["moderator"].lease_id})
    await _drain_until(ws, "floor_state")
    await ws.send_json({"type": "start_session"})
    started = await _drain_until(ws, "session_started")
    assert started["broadcast_id"] == BROADCAST_ID
    assert started["producer_local"] is True
    await ws.close()


async def test_ws_binary_audio_is_ignored(broadcast_app) -> None:
    """Raw binary cannot carry a floor_epoch, so it cannot be fenced."""
    client, service, _handler = broadcast_app
    leases = await service.seed("moderator")
    ws = await _connect(client, "moderator")
    await ws.send_json({"type": "attach", "lease_id": leases["moderator"].lease_id})
    await _drain_until(ws, "floor_state")
    await ws.send_bytes(b"\x00\x01\x02\x03")
    await ws.send_json({"type": "ping"})
    await _drain_until(ws, "pong")
    assert service.session.audio == []
    await ws.close()


async def test_ws_errors_never_leak_operator_detail(broadcast_app) -> None:
    """Adversarial-review regression: WS errors said more than HTTP ones.

    ``BroadcastError.message`` is operator-facing by contract (``errors.py``:
    "Never returned to a client verbatim") and embeds epochs, version numbers
    and timings.  The HTTP surface already emitted only ``reason.value``; the
    WebSocket surface forwarded ``str(exc)``, so the same rejection was more
    revealing over one transport than the other.
    """
    client, service, _handler = broadcast_app
    leases = await service.seed("moderator")
    ws = await _connect(client, "moderator")
    await ws.send_json({"type": "attach", "lease_id": leases["moderator"].lease_id})
    await _drain_until(ws, "floor_state")

    await ws.send_json({"type": "audio_data", "data": "AAAA", "floor_epoch": 99})
    error = await _drain_until(ws, "error")

    # The client still gets the branchable code …
    assert error["code"] == "stale_floor_epoch"
    # … but the message is the sanitized reason, not the internal detail.
    assert error["message"] == "stale_floor_epoch"
    assert "99" not in error["message"]
    await ws.close()


def test_public_broadcast_message_falls_back_for_reasonless_errors() -> None:
    """Authorization failures carry no public reason — and must stay opaque."""
    from parrot.integrations.liveavatar.broadcast.errors import NotModerator
    from parrot.voice.handler import _public_broadcast_message

    exc = NotModerator(message="alice is the moderator, not bob")
    # NotModerator deliberately has no reason: revealing who holds the role
    # would defeat the point of the 403.
    assert _public_broadcast_message(exc) == "request rejected"
    assert "alice" not in _public_broadcast_message(exc)


async def test_ws_refuses_query_string_credentials(broadcast_app) -> None:
    """Credentials must not be accepted from the URL (spec §2).

    Query strings are written to access logs, proxy logs and browser history.
    The route used to accept `?token=` "for parity" with the legacy voice
    route, which handed every participant an easy way to leak their own
    credential. The shipped browser client has always used the subprotocol.
    """
    client, service, _handler = broadcast_app
    await service.seed("moderator")

    ws = await client.ws_connect(f"/ws/voice/broadcast/{AGENT}/{BROADCAST_ID}?token=moderator")
    msg = await ws.receive()
    assert msg.type is aiohttp.WSMsgType.CLOSE
    assert msg.data == WS_CLOSE_UNAUTHENTICATED
