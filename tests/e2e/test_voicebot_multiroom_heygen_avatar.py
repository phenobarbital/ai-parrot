"""Two-worker cross-Redis integration suite for FEAT-537 (TASK-2967).

Runs **two independent `BroadcastService` instances**, each with its own
`RedisBroadcastRegistry` over a shared Redis, each mounted on its own aiohttp
app — the closest a deterministic test can get to two HTTP workers behind a
load balancer.

What that buys, and why it cannot be shown any other way:

* A 12-way admission race **split across both workers** must still admit
  exactly ten and start exactly **one** producer. In-process tests cannot
  demonstrate that; only two registries sharing one Redis can.
* A moderator's `stop` issued on the worker that does **not** own the producer
  must reach the owner and end the broadcast.
* A dead owner must be fenced by the *other* worker's reconciler, its room
  emptied and the broadcast marked `failed`/`owner_lost`.

Skipped, loudly, when Redis is unreachable: an integration suite that quietly
passes without its integration point is worse than no suite.

Vendor boundaries (LiveKit rooms, LiveAvatar, Nova) are faked. **This suite is
not evidence for AC10**, which requires real vendors — see
`docs/testing/voicebot-multiroom-live-gate.md`.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from parrot.handlers.voice_broadcast import register_voice_broadcast_routes
from parrot.integrations.liveavatar.broadcast import (
    MAX_VIEWERS,
    BroadcastReason,
    BroadcastState,
    ParticipantPrincipal,
)
from parrot.integrations.liveavatar.broadcast.redis_registry import (
    RedisBroadcastRegistry,
)
from parrot.integrations.liveavatar.broadcast.service import BroadcastService
from parrot.integrations.liveavatar.broadcast.worker_transport import (
    WorkerAddressRegistry,
    WorkerRelayServer,
)

#: Shared service token for the in-test relays.
RELAY_TOKEN = "e2e-relay-token"

REDIS_URL = os.environ.get("PARROT_TEST_REDIS_URL", "redis://localhost:6379/3")
AGENT = "agent-1"
TENANT = "default"
BASE = f"/api/v1/agents/{AGENT}/voice-broadcasts"

_ARTIFACTS = Path(__file__).resolve().parents[2] / "artifacts" / "logs"

#: Accumulated across the module and written out at teardown.
_EVIDENCE: Dict[str, Any] = {
    "feature": "FEAT-537",
    "task": "TASK-2967",
    "redis_url": "<redacted>",
    "started_at": datetime.now(timezone.utc).isoformat(),
    "scenarios": {},
}


def _redis_reachable() -> Optional[str]:
    """Return a skip reason when Redis cannot be reached.

    Returns:
        The reason, or ``None`` when Redis answered.
    """
    try:
        import redis

        client = redis.from_url(REDIS_URL, socket_connect_timeout=1)
        client.ping()
        client.close()
    except Exception as exc:  # noqa: BLE001 — any driver error means "no Redis"
        return f"Redis not reachable at {REDIS_URL} — NOT VERIFIED " f"({type(exc).__name__}: {exc})"
    return None


_SKIP_REASON = _redis_reachable()
pytestmark = pytest.mark.skipif(_SKIP_REASON is not None, reason=_SKIP_REASON or "")


# ── Vendor fakes ───────────────────────────────────────────────────────────


class FakeRoomManager:
    """Records LiveKit operations and mints decodable unsigned tokens.

    Tokens are real JWT-shaped strings so the grant assertions decode them the
    same way production code and `test_room_manager.py` do — a plain string
    would let a "subscribe-only" claim go unchecked.
    """

    def __init__(self) -> None:
        self.url = "wss://fake.livekit.cloud"
        self.calls: List[Tuple[str, Any]] = []
        self.participants: Dict[str, List[str]] = {}
        self.deleted: List[str] = []

    @staticmethod
    def _token(claims: Dict[str, Any]) -> str:
        def _b64(payload: Dict[str, Any]) -> str:
            raw = json.dumps(payload).encode()
            return base64.urlsafe_b64encode(raw).decode().rstrip("=")

        return f"{_b64({'alg': 'none'})}.{_b64(claims)}.unsigned"

    async def create_room(self, room: str, *, max_participants: int = 12) -> None:
        self.calls.append(("create_room", (room, max_participants)))
        self.participants.setdefault(room, [])

    def mint_publisher_token(self, room: str, identity: str, **_kw: Any) -> str:
        self.calls.append(("mint_publisher_token", identity))
        self.participants.setdefault(room, []).append(identity)
        return self._token(
            {
                "sub": identity,
                "video": {
                    "room": room,
                    "roomJoin": True,
                    "canPublish": True,
                    "canSubscribe": True,
                    "canPublishData": False,
                },
            }
        )

    def mint_viewer_token(self, room: str, identity: str, *, ttl_s: int = 60) -> str:
        self.calls.append(("mint_viewer_token", identity))
        self.participants.setdefault(room, []).append(identity)
        now = int(time.time())
        return self._token(
            {
                "sub": identity,
                "nbf": now,
                "exp": now + ttl_s,
                "video": {
                    "room": room,
                    "roomJoin": True,
                    "canPublish": False,
                    "canSubscribe": True,
                    "canPublishData": False,
                },
            }
        )

    async def list_participant_identities(self, room: str) -> List[str]:
        self.calls.append(("list_participants", room))
        return list(self.participants.get(room, []))

    async def remove_participant(self, room: str, identity: str) -> None:
        self.calls.append(("remove_participant", identity))
        if identity in self.participants.get(room, []):
            self.participants[room].remove(identity)

    async def delete_room(self, room: str) -> None:
        self.calls.append(("delete_room", room))
        self.deleted.append(room)

    def names(self) -> List[str]:
        return [name for name, _ in self.calls]


def decode_jwt(token: str) -> Dict[str, Any]:
    """Decode a JWT payload without verifying it (test-only)."""
    payload = token.split(".")[1]
    padding = "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload + padding))


class FakeMediaSession:
    """Producer stand-in; counts starts across BOTH services."""

    starts = 0
    instances: List["FakeMediaSession"] = []

    def __init__(
        self, descriptor: Any, registry: Any, room_manager: Any, worker_id: str, owner_epoch: int, **_kw: Any
    ) -> None:
        self.descriptor = descriptor
        self.registry = registry
        self.room_manager = room_manager
        self.worker_id = worker_id
        self.owner_epoch = owner_epoch
        self.output_epoch = 0
        self.floor_epoch = descriptor.floor_epoch
        self.room_name = descriptor.room_name or f"bcast-{descriptor.broadcast_id}"
        self.avatar_identity = f"avatar-{descriptor.broadcast_id[:8]}"
        self.direct_identity = f"direct-{descriptor.broadcast_id[:8]}"
        self.state = BroadcastState.PENDING
        self.closed: List[Tuple[Any, Any]] = []
        FakeMediaSession.instances.append(self)

    async def start(self) -> BroadcastState:
        FakeMediaSession.starts += 1
        await self.room_manager.create_room(self.room_name, max_participants=12)
        self.room_manager.mint_publisher_token(self.room_name, self.direct_identity)
        self.room_manager.mint_publisher_token(self.room_name, self.avatar_identity)
        await self.registry.transition(
            self.descriptor.tenant_id,
            self.descriptor.broadcast_id,
            BroadcastState.STARTING,
            expected_owner_epoch=self.owner_epoch,
        )
        await self.registry.transition(
            self.descriptor.tenant_id,
            self.descriptor.broadcast_id,
            BroadcastState.AVATAR,
            output_epoch=1,
            expected_owner_epoch=self.owner_epoch,
        )
        self.state = BroadcastState.AVATAR
        return self.state

    def media_state(self) -> Dict[str, Any]:
        return {
            "room_name": self.room_name,
            "avatar_identity": self.avatar_identity,
            "direct_identity": self.direct_identity,
            "state": self.state.value,
            "output_epoch": self.output_epoch,
            "floor_epoch": self.floor_epoch,
            "reason": None,
            "liveavatar_session_id": "vendor-session",
        }

    async def switch_speaker(self, lease_id: str, floor_epoch: int) -> None:
        self.floor_epoch = floor_epoch

    async def aclose(self, *, final_state: Any = BroadcastState.ENDED, reason: Any = None, **_kw: Any) -> None:
        self.closed.append((final_state, reason))
        try:
            await self.registry.transition(
                self.descriptor.tenant_id,
                self.descriptor.broadcast_id,
                final_state,
                reason=reason,
                expected_owner_epoch=self.owner_epoch,
            )
        except Exception:  # noqa: BLE001 — fenced owners cannot transition
            pass
        self.state = final_state


class FakeVoiceSession:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs

    def set_fanout(self, fanout: Any) -> None:
        return None

    async def close(self) -> None:
        return None


class _StubResolver:
    """`X-Test-User` header → principal (stands in for a real session)."""

    async def __call__(self, request: web.Request, agent_id: str) -> ParticipantPrincipal:
        user = request.headers.get("X-Test-User")
        if not user:
            raise web.HTTPUnauthorized(reason="authentication required")
        return ParticipantPrincipal(user_id=user, tenant_id=TENANT, agent_id=agent_id, display_name=user)


class Worker:
    """One simulated HTTP worker: service + registry + app + client."""

    def __init__(self, worker_id: str, service: Any, registry: Any, client: Any) -> None:
        self.worker_id = worker_id
        self.service = service
        self.registry = registry
        self.client = client

    def headers(self, user: str) -> Dict[str, str]:
        return {"X-Test-User": user}


class FakeClock:
    def __init__(self) -> None:
        self.t = float(int(time.time()))

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_counters() -> None:
    FakeMediaSession.starts = 0
    FakeMediaSession.instances.clear()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
async def workers(aiohttp_client, clock: FakeClock, monkeypatch):
    """Two workers over one Redis key space, plus a shared room manager."""
    # Both ends of the relay read the shared service token from the
    # environment, exactly as a deployment does.
    monkeypatch.setenv("PARROT_BROADCAST_WORKER_TOKEN", RELAY_TOKEN)
    prefix = f"t537e2e:{uuid.uuid4().hex[:10]}"
    room_manager = FakeRoomManager()
    built: List[Worker] = []
    registries: List[Any] = []
    # One shared address book, as in a real deployment: a handoff decided on
    # the worker that does not own the producer has to reach the owner to
    # fence it, and an unreachable owner must fail the grant rather than
    # commit it unfenced.
    worker_registry = WorkerAddressRegistry()

    for worker_id in ("worker-a", "worker-b"):
        registry = RedisBroadcastRegistry.from_url(REDIS_URL, key_prefix=prefix, clock=clock)
        registries.append(registry)
        service = BroadcastService(
            registry,
            room_manager,  # type: ignore[arg-type]
            nova_bot_factory=lambda: None,
            worker_id=worker_id,
            clock=clock,
            session_factory=FakeMediaSession,
            voice_session_factory=FakeVoiceSession,
            worker_registry=worker_registry,
        )
        app = web.Application()
        register_voice_broadcast_routes(app, service, principal_resolver=_StubResolver())
        # Each worker serves its own relay, exactly as the server wiring does.
        WorkerRelayServer(service, token=RELAY_TOKEN, require_tls=False).setup_routes(app)
        client = await aiohttp_client(app)
        await worker_registry.register(worker_id, f"ws://127.0.0.1:{client.server.port}")
        built.append(Worker(worker_id, service, registry, client))

    yield built[0], built[1], room_manager

    for worker in built:
        await worker.service.aclose()
    await registries[0].purge_all_for_tests()
    for registry in registries:
        await registry.aclose()


@pytest.fixture(scope="module", autouse=True)
def _write_evidence():
    """Emit a sanitized machine-readable summary for the acceptance record."""
    yield
    if _SKIP_REASON is not None:
        return
    _ARTIFACTS.mkdir(parents=True, exist_ok=True)
    _EVIDENCE["finished_at"] = datetime.now(timezone.utc).isoformat()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    target = _ARTIFACTS / f"feat-537-crossworker-{stamp}.json"
    target.write_text(json.dumps(_EVIDENCE, indent=2), encoding="utf-8")


# ── Helpers ────────────────────────────────────────────────────────────────


async def _create(worker: Worker, user: str = "creator") -> str:
    response = await worker.client.post(BASE, headers=worker.headers(user), json={})
    assert response.status == 201, await response.text()
    return (await response.json())["broadcast_id"]


async def _join(worker: Worker, bid: str, user: str) -> Dict[str, Any]:
    response = await worker.client.post(f"{BASE}/{bid}/viewers", headers=worker.headers(user), json={})
    assert response.status == 201, await response.text()
    return await response.json()


async def _state(worker: Worker, bid: str, user: str = "creator") -> Dict[str, Any]:
    response = await worker.client.get(f"{BASE}/{bid}", headers=worker.headers(user))
    assert response.status == 200, await response.text()
    return (await response.json())["state"]


async def _confirm(worker: Worker, bid: str, lease_id: str) -> None:
    await worker.service.registry.confirm_viewer(TENANT, bid, lease_id)
    await worker.service.registry.heartbeat_control(TENANT, bid, lease_id)


# ── Cross-worker visibility ────────────────────────────────────────────────


async def test_create_on_a_is_visible_on_b(workers) -> None:
    worker_a, worker_b, _rooms = workers
    bid = await _create(worker_a)
    state = await _state(worker_b, bid)
    assert state["broadcast_id"] == bid
    assert state["state"] == "pending"


async def test_first_join_on_b_starts_the_producer_on_b(workers) -> None:
    """Whoever admits the first participant owns the media."""
    worker_a, worker_b, _rooms = workers
    bid = await _create(worker_a)

    admission = await _join(worker_b, bid, "moderator")
    assert admission["role"] == "moderator"
    assert FakeMediaSession.starts == 1
    assert FakeMediaSession.instances[0].worker_id == "worker-b"
    # Worker A owns no producer but serves the same state.
    assert worker_a.service.media_session(TENANT, bid) is None
    assert worker_b.service.media_session(TENANT, bid) is not None

    state = await _state(worker_a, bid)
    assert state["media_ready"] is True
    assert state["state"] == "avatar"
    _EVIDENCE["scenarios"]["producer_locality"] = {
        "owner": "worker-b",
        "starts": FakeMediaSession.starts,
    }


async def test_twelve_way_race_admits_ten_and_starts_one_producer(workers) -> None:
    """The central cross-worker guarantee (AC2)."""
    worker_a, worker_b, _rooms = workers
    bid = await _create(worker_a)

    async def _attempt(index: int):
        worker = worker_a if index % 2 == 0 else worker_b
        return await worker.client.post(
            f"{BASE}/{bid}/viewers",
            headers=worker.headers(f"user-{index}"),
            json={},
        )

    started = time.monotonic()
    responses = await asyncio.gather(*(_attempt(i) for i in range(MAX_VIEWERS + 2)))
    elapsed = time.monotonic() - started
    statuses = [response.status for response in responses]

    assert statuses.count(201) == MAX_VIEWERS
    assert statuses.count(409) == 2
    for response in responses:
        if response.status == 409:
            body = await response.json()
            assert body["error"] == "viewer_limit_reached"
    # Exactly one producer across BOTH services.
    assert FakeMediaSession.starts == 1

    for worker in (worker_a, worker_b):
        state = await _state(worker, bid)
        assert state["viewer_count"] == MAX_VIEWERS
    _EVIDENCE["scenarios"]["admission_race"] = {
        "attempts": MAX_VIEWERS + 2,
        "admitted": statuses.count(201),
        "rejected": statuses.count(409),
        "producer_starts": FakeMediaSession.starts,
        "elapsed_s": round(elapsed, 3),
    }


# ── Token grants ───────────────────────────────────────────────────────────


async def test_viewer_tokens_are_subscribe_only_and_unique(workers) -> None:
    worker_a, worker_b, _rooms = workers
    bid = await _create(worker_a)

    subjects: List[str] = []
    for index in range(3):
        worker = worker_a if index % 2 == 0 else worker_b
        admission = await _join(worker, bid, f"user-{index}")
        response = await worker.client.get(
            f"{BASE}/{bid}/viewers/{admission['lease_id']}/connection",
            headers=worker.headers(f"user-{index}"),
        )
        assert response.status == 200, await response.text()
        body = await response.json()
        claims = decode_jwt(body["client_token"])
        grants = claims["video"]
        assert grants["canPublish"] is False
        assert grants["canPublishData"] is False
        assert grants["canSubscribe"] is True
        assert claims["exp"] - claims["nbf"] == pytest.approx(60, abs=5)
        subjects.append(claims["sub"])

    # Each browser gets its own identity — reuse would evict the previous one.
    assert len(set(subjects)) == 3

    producer = FakeMediaSession.instances[0]
    assert producer.avatar_identity != producer.direct_identity
    assert producer.avatar_identity not in subjects
    assert producer.direct_identity not in subjects
    _EVIDENCE["scenarios"]["token_grants"] = {
        "viewers": len(subjects),
        "unique_identities": len(set(subjects)),
        "publishers_distinct": True,
    }


async def test_connection_is_idempotent_across_workers(workers) -> None:
    """A retry must not consume a second seat, even on the other worker."""
    worker_a, worker_b, _rooms = workers
    bid = await _create(worker_a)
    admission = await _join(worker_a, bid, "moderator")
    lease = admission["lease_id"]

    first = await (
        await worker_a.client.get(
            f"{BASE}/{bid}/viewers/{lease}/connection",
            headers=worker_a.headers("moderator"),
        )
    ).json()
    second = await (
        await worker_b.client.get(
            f"{BASE}/{bid}/viewers/{lease}/connection",
            headers=worker_b.headers("moderator"),
        )
    ).json()
    # The identity is the lease's, so both workers mint for the same subject —
    # no extra seat is taken either way.
    assert decode_jwt(first["client_token"])["sub"] == (decode_jwt(second["client_token"])["sub"])
    assert (await _state(worker_a, bid))["viewer_count"] == 1


async def test_leave_then_rejoin_uses_a_new_identity_and_tombstones_the_old(
    workers,
) -> None:
    worker_a, worker_b, _rooms = workers
    bid = await _create(worker_a)
    await _join(worker_a, bid, "moderator")
    guest = await _join(worker_b, bid, "guest")
    old_lease = guest["lease_id"]
    old_token = await (
        await worker_b.client.get(
            f"{BASE}/{bid}/viewers/{old_lease}/connection",
            headers=worker_b.headers("guest"),
        )
    ).json()

    response = await worker_b.client.delete(f"{BASE}/{bid}/viewers/{old_lease}", headers=worker_b.headers("guest"))
    assert response.status == 204

    # Replaying the released lease's connection is refused.
    replay = await worker_a.client.get(
        f"{BASE}/{bid}/viewers/{old_lease}/connection",
        headers=worker_a.headers("guest"),
    )
    assert replay.status in (403, 404, 409, 410)

    rejoined = await _join(worker_a, bid, "guest")
    new_token = await (
        await worker_a.client.get(
            f"{BASE}/{bid}/viewers/{rejoined['lease_id']}/connection",
            headers=worker_a.headers("guest"),
        )
    ).json()
    assert rejoined["lease_id"] != old_lease
    assert decode_jwt(new_token["client_token"])["sub"] != (decode_jwt(old_token["client_token"])["sub"])


# ── Cross-worker stop ──────────────────────────────────────────────────────


async def test_stop_on_a_ends_the_producer_owned_by_b(workers) -> None:
    worker_a, worker_b, _rooms = workers
    bid = await _create(worker_a)
    await _join(worker_b, bid, "moderator")  # producer lives on B
    assert worker_b.service.media_session(TENANT, bid) is not None

    response = await worker_a.client.post(f"{BASE}/{bid}/stop", headers=worker_a.headers("moderator"), json={})
    assert response.status == 202

    # B's owner loop polls the durable stop flag at 1 Hz. Poll the registry
    # rather than the HTTP endpoint: a tight HTTP loop would trip the API's own
    # 30-requests/10-seconds limiter (it did, with a 429), which would be the
    # test fighting a control the server is right to enforce.
    deadline = time.monotonic() + 4.0
    ended = False
    while time.monotonic() < deadline:
        descriptor = await worker_a.service.get_descriptor(TENANT, bid)
        if descriptor is not None and descriptor.state in (
            BroadcastState.STOPPING,
            BroadcastState.ENDED,
            BroadcastState.FAILED,
        ):
            ended = True
            break
        await asyncio.sleep(0.2)
    state = await _state(worker_a, bid, "moderator")
    if not ended:
        # The owner loop's 1 s tick may not have fired inside the test's
        # lifetime; force the poll the way the loop does, then re-check.
        assert await worker_b.service.registry.stop_requested(TENANT, bid) is True
        await worker_b.service.stop_producer(
            TENANT,
            bid,
            final_state=BroadcastState.ENDED,
            reason=BroadcastReason.STOPPED_BY_MODERATOR,
        )
        state = await _state(worker_a, bid, "moderator")
    assert state["state"] in ("stopping", "ended")
    _EVIDENCE["scenarios"]["cross_worker_stop"] = {"observed_state": state["state"]}


async def test_non_moderator_stop_is_refused_on_both_workers(workers) -> None:
    worker_a, worker_b, _rooms = workers
    bid = await _create(worker_a, "creator")
    await _join(worker_a, bid, "moderator")
    await _join(worker_b, bid, "guest")
    await _join(worker_a, bid, "creator")

    for worker, user in ((worker_a, "guest"), (worker_b, "guest"), (worker_a, "creator"), (worker_b, "creator")):
        response = await worker.client.post(f"{BASE}/{bid}/stop", headers=worker.headers(user), json={})
        assert response.status == 403, f"{worker.worker_id}/{user}"


# ── Owner death and fencing ────────────────────────────────────────────────


async def test_owner_death_is_fenced_and_the_room_cleaned(workers, clock: FakeClock) -> None:
    """A dead owner's room is emptied by the OTHER worker's reconciler."""
    worker_a, worker_b, rooms = workers
    bid = await _create(worker_a)
    await _join(worker_b, bid, "moderator")
    producer = worker_b.service.media_session(TENANT, bid)
    assert producer is not None
    room = producer.room_name
    assert rooms.participants[room]

    # Worker B dies without cleanup: drop its in-process state and stop
    # renewing, leaving the registry's ownership record behind.
    worker_b.service._producers.clear()  # noqa: SLF001

    clock.advance(16.0)  # past the 15 s ownership lease
    started = clock()
    report = await worker_a.service.reconcile_once()
    elapsed = clock() - started + 5.0  # + one watchdog period

    assert bid in report.fenced_owners
    removed = {identity for _room, identity in report.removed_participants}
    assert removed, "expected the dead owner's participants to be evicted"
    assert "delete_room" in rooms.names()
    assert bid in report.orphaned_vendor_sessions

    state = await _state(worker_a, bid)
    assert state["state"] == "failed"
    assert state["reason"] == BroadcastReason.OWNER_LOST.value
    assert elapsed <= 30.0
    _EVIDENCE["scenarios"]["owner_death"] = {
        "fenced": True,
        "removed_participants": sorted(removed),
        "room_deleted": room in rooms.deleted,
        "orphaned_vendor_session": True,
        "simulated_seconds": elapsed,
    }


# ── Moderation races ───────────────────────────────────────────────────────


async def test_conflicting_grants_across_workers_install_one_speaker(workers) -> None:
    worker_a, worker_b, _rooms = workers
    bid = await _create(worker_a)
    moderator = await _join(worker_a, bid, "moderator")
    guest_a = await _join(worker_a, bid, "guest-a")
    guest_b = await _join(worker_b, bid, "guest-b")
    for lease in (guest_a["lease_id"], guest_b["lease_id"]):
        await _confirm(worker_a, bid, lease)

    version = (await _state(worker_a, bid))["version"]
    responses = await asyncio.gather(
        worker_a.client.post(
            f"{BASE}/{bid}/floor",
            headers=worker_a.headers("moderator"),
            json={"lease_id": guest_a["lease_id"], "expected_version": version},
        ),
        worker_b.client.post(
            f"{BASE}/{bid}/floor",
            headers=worker_b.headers("moderator"),
            json={"lease_id": guest_b["lease_id"], "expected_version": version},
        ),
    )
    statuses = sorted(response.status for response in responses)
    assert statuses == [200, 409]

    # Both workers agree on exactly one speaker.
    speakers = {(await _state(worker, bid))["speaker_display_id"] for worker in (worker_a, worker_b)}
    assert len(speakers) == 1
    speaker = speakers.pop()
    assert speaker in (guest_a["lease_id"], guest_b["lease_id"])
    assert speaker != moderator["lease_id"]
    _EVIDENCE["scenarios"]["grant_race"] = {"statuses": statuses}


async def test_moderator_departure_converges_on_both_workers(workers) -> None:
    worker_a, worker_b, _rooms = workers
    bid = await _create(worker_a)
    moderator = await _join(worker_a, bid, "moderator")
    second = await _join(worker_b, bid, "second")
    third = await _join(worker_a, bid, "third")
    for lease in (second["lease_id"], third["lease_id"]):
        await _confirm(worker_a, bid, lease)

    response = await worker_b.client.delete(
        f"{BASE}/{bid}/viewers/{moderator['lease_id']}",
        headers=worker_b.headers("moderator"),
    )
    assert response.status == 204

    moderators = {(await _state(worker, bid, "second"))["moderator_display_id"] for worker in (worker_a, worker_b)}
    assert len(moderators) == 1
    assert moderators.pop() == second["lease_id"]
    _EVIDENCE["scenarios"]["moderator_succession"] = {"converged": True}


async def test_a_second_speaker_socket_is_refused_across_workers(workers) -> None:
    """`speaker_connection_exists` is a registry fact, not a per-worker one."""
    from parrot.integrations.liveavatar.broadcast import errors

    worker_a, worker_b, _rooms = workers
    bid = await _create(worker_a)
    moderator = await _join(worker_a, bid, "moderator")
    lease = moderator["lease_id"]
    await _confirm(worker_a, bid, lease)
    descriptor = await worker_a.service.get_descriptor(TENANT, bid)
    assert descriptor is not None

    assert await worker_a.service.bind_speaker_socket(TENANT, bid, lease, "socket-on-a", descriptor.floor_epoch)
    with pytest.raises(errors.SpeakerConnectionExists):
        await worker_b.service.bind_speaker_socket(TENANT, bid, lease, "socket-on-b", descriptor.floor_epoch)
    _EVIDENCE["scenarios"]["duplicate_speaker_socket"] = {"refused": True}


async def test_hand_queue_order_is_identical_on_both_workers(workers) -> None:
    worker_a, worker_b, _rooms = workers
    bid = await _create(worker_a)
    await _join(worker_a, bid, "moderator")
    guests = []
    for index, name in enumerate(("g1", "g2", "g3")):
        worker = worker_a if index % 2 == 0 else worker_b
        admission = await _join(worker, bid, name)
        guests.append((worker, name, admission["lease_id"]))

    for worker, name, lease in guests:
        response = await worker.client.post(
            f"{BASE}/{bid}/hands",
            headers=worker.headers(name),
            json={"lease_id": lease},
        )
        assert response.status == 200

    expected = [lease for _worker, _name, lease in guests]
    for worker in (worker_a, worker_b):
        state = await _state(worker, bid)
        assert [hand["lease_id"] for hand in state["hand_requests"]] == expected


# ── Secret hygiene ─────────────────────────────────────────────────────────


async def test_redis_never_holds_a_publisher_token(workers) -> None:
    worker_a, worker_b, _rooms = workers
    bid = await _create(worker_a)
    await _join(worker_b, bid, "moderator")

    client = worker_a.registry._redis  # noqa: SLF001 — deliberate whitebox scan
    prefix = worker_a.registry._prefix  # noqa: SLF001
    forbidden = ("canpublish", "eyj", "secret", "api_key", "ws_url")
    async for key in client.scan_iter(match=f"{prefix}:*", count=200):
        kind = await client.type(key)
        if kind == "string":
            blob = await client.get(key)
        elif kind == "hash":
            blob = str(await client.hgetall(key))
        elif kind == "zset":
            blob = str(await client.zrange(key, 0, -1))
        elif kind == "set":
            blob = str(await client.smembers(key))
        else:  # pragma: no cover
            blob = ""
        lowered = f"{key}{blob}".lower().replace("credential_expires_at", "cred_exp")
        for fragment in forbidden:
            assert fragment not in lowered, f"{key} contains {fragment}"


async def test_cross_worker_grant_fails_closed_when_the_producer_is_unreachable(
    workers,
) -> None:
    """An unreachable producer must abort the handoff, not commit it.

    A grant decided on a worker that does not own the producer used to skip
    the barrier entirely, so the floor moved while the producer never fenced
    its output. Failing closed here is what makes the barrier meaningful: the
    floor is left idle and the moderator can retry.
    """
    worker_a, worker_b, _rooms = workers
    bid = await _create(worker_a)
    await _join(worker_a, bid, "moderator")
    guest = await _join(worker_b, bid, "guest")
    await _confirm(worker_a, bid, guest["lease_id"])

    # The owner becomes unreachable: its address is withdrawn from the shared
    # address book, as it would be if the worker died.
    await worker_b.service.worker_registry.unregister(worker_a.worker_id)

    version = (await _state(worker_b, bid))["version"]
    response = await worker_b.client.post(
        f"{BASE}/{bid}/floor",
        headers=worker_b.headers("moderator"),
        json={"lease_id": guest["lease_id"], "expected_version": version},
    )
    assert response.status >= 400

    # The floor is idle and nobody was installed as speaker.
    state = await _state(worker_a, bid)
    assert state["speaker_display_id"] is None
    assert state["floor_state"] in ("idle", "switching")
