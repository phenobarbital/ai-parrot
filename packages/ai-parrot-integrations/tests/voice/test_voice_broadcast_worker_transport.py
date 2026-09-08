"""Cross-worker speaker relay tests (FEAT-537 TASK-2961).

This is the feature's most security-sensitive surface: anything that reaches the
owner's ``push_audio`` is about to be spoken by the agent to the whole audience.
The tests therefore concentrate on refusals — bad token, plaintext non-loopback,
oversize frame, stale owner epoch, revoked floor, arbitrary URL — as much as on
the happy path.
"""
from __future__ import annotations

import base64
import json
from typing import Any, Dict, List, Optional

import pytest
from aiohttp import web

from parrot.integrations.liveavatar.broadcast import (
    BroadcastDescriptor,
    BroadcastReason,
    FloorState,
    InMemoryBroadcastRegistry,
    ParticipantPrincipal,
)
from parrot.integrations.liveavatar.broadcast.worker_transport import (
    MAX_RELAY_MESSAGE_BYTES,
    RELAY_ROUTE,
    WORKER_TOKEN_ENV,
    WORKER_TOKEN_HEADER,
    WS_CLOSE_POLICY_VIOLATION,
    WS_CLOSE_TOO_BIG,
    LocalSpeakerInput,
    RelayFrame,
    RemoteSpeakerInput,
    WorkerAddressRegistry,
    WorkerRelayServer,
    WorkerTransportError,
    resolve_worker_token,
)

TENANT = "acme"
AGENT = "agent-1"
BROADCAST = "bc-relay-1"
TOKEN = "shared-service-token"


class FakeOwnerVoiceSession:
    """Records what the relay applied on the owner side."""

    def __init__(self) -> None:
        self.audio: List[bytes] = []
        self.started = 0
        self.ended = 0
        self.released = 0

    async def start_turn(self) -> None:
        self.started += 1

    async def end_turn(self) -> None:
        self.ended += 1

    def end_speaker_turn(self) -> None:
        self.released += 1

    async def push_audio(self, pcm: bytes) -> None:
        self.audio.append(pcm)


class FakeOwnerService:
    """Minimal owner-side service the relay server talks to."""

    def __init__(self, *, owner_epoch: int = 7) -> None:
        self.registry = InMemoryBroadcastRegistry()
        self.session = FakeOwnerVoiceSession()
        self._owner_epoch: Optional[int] = owner_epoch
        self.lease_id: str = ""

    def owner_epoch(self, tenant_id: str, broadcast_id: str) -> Optional[int]:
        return self._owner_epoch

    def voice_session(self, tenant_id: str, broadcast_id: str) -> Any:
        return self.session if self._owner_epoch is not None else None

    async def get_descriptor(self, tenant_id: str, broadcast_id: str) -> Any:
        return await self.registry.get(tenant_id, broadcast_id)

    async def get_lease(
        self, tenant_id: str, broadcast_id: str, lease_id: str
    ) -> Any:
        for lease in await self.registry.list_leases(tenant_id, broadcast_id):
            if lease.lease_id == lease_id:
                return lease
        return None

    async def seed(self) -> str:
        """Create a broadcast with one admitted, floor-holding participant."""
        await self.registry.create(
            BroadcastDescriptor(
                broadcast_id=BROADCAST,
                tenant_id=TENANT,
                agent_id=AGENT,
                creator_user_id="creator",
            )
        )
        admission = await self.registry.reserve_viewer(
            TENANT,
            BROADCAST,
            ParticipantPrincipal(
                user_id="speaker", tenant_id=TENANT, agent_id=AGENT
            ),
            "identity-speaker",
        )
        await self.registry.confirm_viewer(
            TENANT, BROADCAST, admission.lease.lease_id
        )
        await self.registry.heartbeat_control(
            TENANT, BROADCAST, admission.lease.lease_id
        )
        self.lease_id = admission.lease.lease_id
        return self.lease_id


@pytest.fixture
def owner_service() -> FakeOwnerService:
    return FakeOwnerService()


@pytest.fixture
async def relay_client(aiohttp_client, owner_service: FakeOwnerService):
    """An internal app hosting the relay, plus the seeded owner service."""
    server = WorkerRelayServer(owner_service, token=TOKEN, require_tls=True)
    app = web.Application()
    server.setup_routes(app)
    client = await aiohttp_client(app)
    lease_id = await owner_service.seed()
    return client, owner_service, lease_id


def _frame(
    lease_id: str,
    *,
    kind: str = "audio",
    owner_epoch: int = 7,
    floor_epoch: int = 1,
    pcm: bytes = b"\x01\x02",
) -> str:
    return RelayFrame(
        kind=kind,
        owner_epoch=owner_epoch,
        lease_id=lease_id,
        floor_epoch=floor_epoch,
        pcm=pcm,
    ).to_wire()


# ── Token / URL hygiene ────────────────────────────────────────────────────


def test_relay_refuses_to_mount_without_a_token(owner_service) -> None:
    """An unauthenticated relay would let anything on the port speak."""
    server = WorkerRelayServer(owner_service, token=None)
    with pytest.raises(WorkerTransportError, match=WORKER_TOKEN_ENV):
        server.setup_routes(web.Application())


def test_token_resolution_prefers_the_explicit_value(monkeypatch) -> None:
    monkeypatch.setenv(WORKER_TOKEN_ENV, "from-env")
    assert resolve_worker_token("explicit") == "explicit"
    assert resolve_worker_token(None) == "from-env"
    monkeypatch.delenv(WORKER_TOKEN_ENV)
    assert resolve_worker_token(None) is None


@pytest.mark.parametrize(
    "url",
    [
        "http://evil.example/relay",
        "https://evil.example/relay",
        "file:///etc/passwd",
        "ws:///no-host",
        "not-a-url",
        "",
    ],
)
def test_arbitrary_urls_are_refused(url: str) -> None:
    """The single choke point that stops an influenced value being dialled."""
    with pytest.raises(WorkerTransportError):
        WorkerAddressRegistry.validate_url(url)


def test_websocket_urls_are_accepted() -> None:
    assert WorkerAddressRegistry.validate_url("ws://127.0.0.1:8080") is not None
    assert WorkerAddressRegistry.validate_url("wss://worker-2.internal") is not None


async def test_worker_registry_round_trip() -> None:
    registry = WorkerAddressRegistry()
    await registry.register("worker-a", "ws://127.0.0.1:9001")
    assert await registry.resolve("worker-a") == "ws://127.0.0.1:9001"
    assert await registry.resolve("worker-unknown") is None
    await registry.unregister("worker-a")
    assert await registry.resolve("worker-a") is None


async def test_worker_registry_refuses_to_register_a_bad_url() -> None:
    registry = WorkerAddressRegistry()
    with pytest.raises(WorkerTransportError):
        await registry.register("worker-a", "http://worker-a.internal")


def test_remote_input_requires_tls_off_loopback() -> None:
    with pytest.raises(WorkerTransportError, match="wss://"):
        RemoteSpeakerInput(
            "ws://worker-2.internal",
            tenant_id=TENANT,
            broadcast_id=BROADCAST,
            owner_epoch=1,
            lease_id="lease-a",
            floor_epoch=1,
            token=TOKEN,
        )
    # Loopback plaintext is fine, and so is real TLS.
    RemoteSpeakerInput(
        "ws://127.0.0.1:9001", tenant_id=TENANT, broadcast_id=BROADCAST,
        owner_epoch=1, lease_id="lease-a", floor_epoch=1, token=TOKEN,
    )
    RemoteSpeakerInput(
        "wss://worker-2.internal", tenant_id=TENANT, broadcast_id=BROADCAST,
        owner_epoch=1, lease_id="lease-a", floor_epoch=1, token=TOKEN,
    )


# ── Frame parsing ──────────────────────────────────────────────────────────


def test_relay_frame_round_trip() -> None:
    frame = RelayFrame(
        kind="audio",
        owner_epoch=3,
        lease_id="lease-a",
        floor_epoch=5,
        turn_id="turn-1",
        seq=9,
        pcm=b"\x10\x20",
    )
    parsed = RelayFrame.parse(frame.to_wire())
    assert parsed.owner_epoch == 3
    assert parsed.lease_id == "lease-a"
    assert parsed.floor_epoch == 5
    assert parsed.turn_id == "turn-1"
    assert parsed.seq == 9
    assert parsed.pcm == b"\x10\x20"


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[]",
        json.dumps({"kind": "audio", "lease_id": "l", "floor_epoch": 1}),
        json.dumps({"kind": "audio", "owner_epoch": 1, "floor_epoch": 1}),
        json.dumps({"kind": "audio", "owner_epoch": 1, "lease_id": "l"}),
        json.dumps(
            {"kind": "audio", "owner_epoch": 1, "lease_id": "l", "floor_epoch": 1}
        ),
        json.dumps(
            {
                "kind": "audio",
                "owner_epoch": 1,
                "lease_id": "l",
                "floor_epoch": 1,
                "pcm_b64": "!!!not base64!!!",
            }
        ),
    ],
)
def test_malformed_frames_are_refused(raw: str) -> None:
    with pytest.raises(WorkerTransportError):
        RelayFrame.parse(raw)


# ── Relay server ───────────────────────────────────────────────────────────


async def test_relay_rejects_bad_token(relay_client) -> None:
    client, _service, _lease = relay_client
    response = await client.get(
        RELAY_ROUTE, headers={WORKER_TOKEN_HEADER: "wrong-token"}
    )
    assert response.status == 401
    response = await client.get(RELAY_ROUTE)
    assert response.status == 401


async def test_relay_forwards_authorized_pcm(relay_client) -> None:
    client, service, lease_id = relay_client
    ws = await client.ws_connect(
        f"{RELAY_ROUTE}?tenant_id={TENANT}&broadcast_id={BROADCAST}",
        headers={WORKER_TOKEN_HEADER: TOKEN},
    )
    await ws.send_str(_frame(lease_id, kind="start_turn"))
    await ws.send_str(_frame(lease_id, pcm=b"\xaa\xbb"))
    await ws.send_str(_frame(lease_id, kind="end_turn"))
    await ws.close()

    assert service.session.started == 1
    assert service.session.audio == [b"\xaa\xbb"]
    assert service.session.ended == 1


async def test_relay_revalidates_the_floor_on_the_owner(relay_client) -> None:
    """Passing ingress validation is not a permit: the owner checks again."""
    client, service, lease_id = relay_client
    ws = await client.ws_connect(
        f"{RELAY_ROUTE}?tenant_id={TENANT}&broadcast_id={BROADCAST}",
        headers={WORKER_TOKEN_HEADER: TOKEN},
    )
    # A revoke lands between ingress and the producer.
    descriptor = await service.registry.get(TENANT, BROADCAST)
    assert descriptor is not None
    await service.registry.grant_floor(
        TENANT, BROADCAST, lease_id, lease_id, descriptor.version
    )
    switching = await service.registry.get(TENANT, BROADCAST)
    assert switching is not None
    assert switching.floor_state is FloorState.SWITCHING

    await ws.send_str(_frame(lease_id, floor_epoch=1))
    error = json.loads((await ws.receive()).data)
    assert error["type"] == "error"
    assert error["code"] == BroadcastReason.FLOOR_NOT_GRANTED.value
    assert service.session.audio == []
    await ws.close()


async def test_relay_rejects_a_stale_floor_epoch(relay_client) -> None:
    client, service, lease_id = relay_client
    ws = await client.ws_connect(
        f"{RELAY_ROUTE}?tenant_id={TENANT}&broadcast_id={BROADCAST}",
        headers={WORKER_TOKEN_HEADER: TOKEN},
    )
    await ws.send_str(_frame(lease_id, floor_epoch=99))
    error = json.loads((await ws.receive()).data)
    assert error["code"] == BroadcastReason.STALE_FLOOR_EPOCH.value
    assert service.session.audio == []
    await ws.close()


async def test_relay_closes_on_a_stale_owner_epoch(relay_client) -> None:
    """Talking to a producer that no longer exists ends the connection."""
    client, service, lease_id = relay_client
    ws = await client.ws_connect(
        f"{RELAY_ROUTE}?tenant_id={TENANT}&broadcast_id={BROADCAST}",
        headers={WORKER_TOKEN_HEADER: TOKEN},
    )
    await ws.send_str(_frame(lease_id, owner_epoch=1))
    await ws.receive()
    assert ws.close_code == WS_CLOSE_POLICY_VIOLATION
    assert service.session.audio == []


async def test_relay_closes_when_this_worker_is_not_the_producer(
    aiohttp_client,
) -> None:
    service = FakeOwnerService(owner_epoch=None)  # type: ignore[arg-type]
    await service.seed()
    server = WorkerRelayServer(service, token=TOKEN, require_tls=False)
    app = web.Application()
    server.setup_routes(app)
    client = await aiohttp_client(app)

    ws = await client.ws_connect(
        f"{RELAY_ROUTE}?tenant_id={TENANT}&broadcast_id={BROADCAST}",
        headers={WORKER_TOKEN_HEADER: TOKEN},
    )
    await ws.send_str(_frame(service.lease_id))
    await ws.receive()
    assert ws.close_code == WS_CLOSE_POLICY_VIOLATION


async def test_relay_refuses_an_oversize_frame(relay_client) -> None:
    client, service, lease_id = relay_client
    ws = await client.ws_connect(
        f"{RELAY_ROUTE}?tenant_id={TENANT}&broadcast_id={BROADCAST}",
        headers={WORKER_TOKEN_HEADER: TOKEN},
        max_msg_size=0,
    )
    oversized = RelayFrame(
        kind="audio",
        owner_epoch=7,
        lease_id=lease_id,
        floor_epoch=1,
        pcm=b"\x00" * MAX_RELAY_MESSAGE_BYTES,
    ).to_wire()
    assert len(oversized) > MAX_RELAY_MESSAGE_BYTES
    await ws.send_str(oversized)
    await ws.receive()
    assert ws.close_code in (WS_CLOSE_TOO_BIG, WS_CLOSE_POLICY_VIOLATION)
    assert service.session.audio == []


async def test_relay_reports_a_malformed_frame_without_closing(relay_client) -> None:
    client, service, lease_id = relay_client
    ws = await client.ws_connect(
        f"{RELAY_ROUTE}?tenant_id={TENANT}&broadcast_id={BROADCAST}",
        headers={WORKER_TOKEN_HEADER: TOKEN},
    )
    await ws.send_str("{ not json")
    error = json.loads((await ws.receive()).data)
    assert error["type"] == "error"
    # The connection survives, and a good frame still works.
    await ws.send_str(_frame(lease_id, pcm=b"\x05\x06"))
    await ws.close()
    assert service.session.audio == [b"\x05\x06"]


async def test_relay_ignores_binary_frames(relay_client) -> None:
    client, service, lease_id = relay_client
    ws = await client.ws_connect(
        f"{RELAY_ROUTE}?tenant_id={TENANT}&broadcast_id={BROADCAST}",
        headers={WORKER_TOKEN_HEADER: TOKEN},
    )
    await ws.send_bytes(b"\x00\x01\x02")
    await ws.send_str(_frame(lease_id, pcm=b"\x07\x08"))
    await ws.close()
    assert service.session.audio == [b"\x07\x08"]


async def test_relay_requires_tls_off_loopback(aiohttp_client, monkeypatch) -> None:
    """A plaintext non-loopback peer is refused even with the right token."""
    service = FakeOwnerService()
    await service.seed()
    server = WorkerRelayServer(service, token=TOKEN, require_tls=True)

    class _Request:
        secure = False
        remote = "10.0.0.5"
        headers = {WORKER_TOKEN_HEADER: TOKEN}

    assert server._transport_allowed(_Request()) is False  # noqa: SLF001

    class _Loopback(_Request):
        remote = "127.0.0.1"

    assert server._transport_allowed(_Loopback()) is True  # noqa: SLF001

    class _Tls(_Request):
        secure = True

    assert server._transport_allowed(_Tls()) is True  # noqa: SLF001


# ── RemoteSpeakerInput end to end ──────────────────────────────────────────


async def test_remote_speaker_input_reaches_the_owner(relay_client) -> None:
    """The ingress-side client and the owner-side server actually interoperate."""
    client, service, lease_id = relay_client
    url = f"ws://127.0.0.1:{client.server.port}"

    sink = RemoteSpeakerInput(
        url,
        tenant_id=TENANT,
        broadcast_id=BROADCAST,
        owner_epoch=7,
        lease_id=lease_id,
        floor_epoch=1,
        token=TOKEN,
    )
    try:
        await sink.start_turn()
        await sink.push_audio(b"\x0a\x0b")
        await sink.end_turn()
    finally:
        await sink.aclose()

    for _ in range(50):
        if service.session.audio:
            break
        await pytest.importorskip("asyncio").sleep(0.01)
    assert service.session.started == 1
    assert service.session.audio == [b"\x0a\x0b"]


async def test_remote_speaker_input_requires_a_token(relay_client) -> None:
    client, _service, lease_id = relay_client
    sink = RemoteSpeakerInput(
        f"ws://127.0.0.1:{client.server.port}",
        tenant_id=TENANT,
        broadcast_id=BROADCAST,
        owner_epoch=7,
        lease_id=lease_id,
        floor_epoch=1,
        token="",
    )
    with pytest.raises(WorkerTransportError, match=WORKER_TOKEN_ENV):
        await sink.start_turn()
    await sink.aclose()


async def test_remote_speaker_input_drops_an_oversized_block(relay_client) -> None:
    client, service, lease_id = relay_client
    sink = RemoteSpeakerInput(
        f"ws://127.0.0.1:{client.server.port}",
        tenant_id=TENANT,
        broadcast_id=BROADCAST,
        owner_epoch=7,
        lease_id=lease_id,
        floor_epoch=1,
        token=TOKEN,
    )
    try:
        await sink.push_audio(b"\x00" * MAX_RELAY_MESSAGE_BYTES)
        assert sink.dropped_frames == 1
        assert service.session.audio == []
    finally:
        await sink.aclose()


async def test_remote_speaker_input_aclose_is_idempotent(relay_client) -> None:
    client, _service, lease_id = relay_client
    sink = RemoteSpeakerInput(
        f"ws://127.0.0.1:{client.server.port}",
        tenant_id=TENANT,
        broadcast_id=BROADCAST,
        owner_epoch=7,
        lease_id=lease_id,
        floor_epoch=1,
        token=TOKEN,
    )
    await sink.aclose()
    await sink.aclose()
    with pytest.raises(WorkerTransportError, match="closed"):
        await sink.start_turn()


# ── LocalSpeakerInput ──────────────────────────────────────────────────────


async def test_local_speaker_input_begins_the_turn_once() -> None:
    class _Session(FakeOwnerVoiceSession):
        def __init__(self) -> None:
            super().__init__()
            self.turns: List[Any] = []

        def begin_speaker_turn(self, lease_id, principal, floor_epoch):
            self.turns.append((lease_id, principal.user_id, floor_epoch))
            return len(self.turns)

    session = _Session()
    principal = ParticipantPrincipal(
        user_id="ada", tenant_id=TENANT, agent_id=AGENT
    )
    sink = LocalSpeakerInput(session, "lease-a", principal, 4)
    await sink.start_turn()
    await sink.start_turn()
    assert session.turns == [("lease-a", "ada", 4)]
    assert session.started == 2

    await sink.push_audio(b"\x01\x02")
    await sink.end_turn()
    await sink.aclose()
    assert session.audio == [b"\x01\x02"]
    assert session.ended == 1
    assert session.released == 1
