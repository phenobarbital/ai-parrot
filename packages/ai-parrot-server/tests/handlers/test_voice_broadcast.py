"""HTTP API tests for moderated voice broadcasts (FEAT-537 TASK-2962).

Runs the **real** :class:`BroadcastService` over the in-memory registry with
fake LiveKit/media factories, so these exercise the actual authority rules
rather than a mock's idea of them.  Spec §2's "New Public Interfaces" table
fixes the status codes; each one is asserted.
"""

from __future__ import annotations

import contextlib
import json
from typing import Any, Dict, List, Optional, Tuple

import pytest
from aiohttp import web

from parrot.handlers.voice_broadcast import (
    MAX_BODY_BYTES,
    RATE_LIMIT_REQUESTS,
    register_voice_broadcast_routes,
)
from parrot.integrations.liveavatar.broadcast import (
    MAX_VIEWERS,
    BroadcastState,
    InMemoryBroadcastRegistry,
    ParticipantPrincipal,
)
from parrot.integrations.liveavatar.broadcast.service import BroadcastService

AGENT = "agent-1"
TENANT = "default"
BASE = f"/api/v1/agents/{AGENT}/voice-broadcasts"

#: Keys that must never appear in any response except ``client_token`` in the
#: single connection endpoint.
_FORBIDDEN_KEYS = ("agent_token", "secret", "ws_url", "api_key", "session_token")


# ── Fakes ──────────────────────────────────────────────────────────────────


class FakeRoomManager:
    def __init__(self) -> None:
        self.url = "wss://fake.livekit.cloud"
        self.removed: List[str] = []

    async def create_room(self, room: str, *, max_participants: int = 12) -> None:
        return None

    def mint_publisher_token(self, room: str, identity: str, **_kw: Any) -> str:
        return f"pub-{identity}"

    def mint_viewer_token(self, room: str, identity: str, *, ttl_s: int = 60) -> str:
        return f"viewer-jwt-{identity}"

    async def list_participant_identities(self, room: str) -> List[str]:
        return []

    async def remove_participant(self, room: str, identity: str) -> None:
        self.removed.append(identity)

    async def delete_room(self, room: str) -> None:
        return None


class FakeMediaSession:
    """Media stand-in that reaches ``avatar`` immediately."""

    stall = False

    def __init__(
        self, descriptor: Any, registry: Any, room_manager: Any, worker_id: str, owner_epoch: int, **_kw: Any
    ) -> None:
        self.descriptor = descriptor
        self.registry = registry
        self.owner_epoch = owner_epoch
        self.output_epoch = 0
        self.floor_epoch = descriptor.floor_epoch
        self.room_name = descriptor.room_name or f"bcast-{descriptor.broadcast_id}"
        self.avatar_identity = "avatar-x"
        self.direct_identity = "direct-x"
        self.state = BroadcastState.PENDING

    async def start(self) -> BroadcastState:
        await self.registry.transition(
            self.descriptor.tenant_id,
            self.descriptor.broadcast_id,
            BroadcastState.STARTING,
            expected_owner_epoch=self.owner_epoch,
        )
        if FakeMediaSession.stall:
            self.state = BroadcastState.STARTING
            return self.state
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
            "liveavatar_session_id": "vendor-1",
        }

    async def switch_speaker(self, lease_id: str, floor_epoch: int) -> None:
        self.floor_epoch = floor_epoch

    async def aclose(self, *, final_state: Any = BroadcastState.ENDED, reason: Any = None, **_kw: Any) -> None:
        """Mirror the real session: teardown records the terminal state.

        Without this the fake would leave the broadcast joinable after a stop,
        which is a property of the fake rather than of the code under test.
        """
        with contextlib.suppress(Exception):
            await self.registry.transition(
                self.descriptor.tenant_id,
                self.descriptor.broadcast_id,
                final_state,
                reason=reason,
                expected_owner_epoch=self.owner_epoch,
            )
        self.state = final_state


class FakeVoiceSession:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs

    def set_fanout(self, fanout: Any) -> None:
        return None

    async def close(self) -> None:
        return None


class _StubResolver:
    """Maps an ``X-Test-User`` header to a principal (stands in for a session)."""

    async def __call__(self, request: web.Request, agent_id: str) -> ParticipantPrincipal:
        user = request.headers.get("X-Test-User")
        if not user:
            raise web.HTTPUnauthorized(reason="authentication required")
        return ParticipantPrincipal(user_id=user, tenant_id=TENANT, agent_id=agent_id, display_name=user)


@pytest.fixture(autouse=True)
def _reset_stall() -> None:
    FakeMediaSession.stall = False


@pytest.fixture
async def client(aiohttp_client):
    """An app with the real service over the in-memory registry."""
    service = BroadcastService(
        InMemoryBroadcastRegistry(),
        FakeRoomManager(),  # type: ignore[arg-type]
        nova_bot_factory=lambda: None,
        worker_id="worker-test",
        session_factory=FakeMediaSession,
        voice_session_factory=FakeVoiceSession,
    )
    app = web.Application()
    register_voice_broadcast_routes(app, service, principal_resolver=_StubResolver())
    test_client = await aiohttp_client(app)
    test_client.service = service  # type: ignore[attr-defined]
    return test_client


def _as(user: str) -> Dict[str, str]:
    return {"X-Test-User": user}


async def _create(client: Any, user: str = "creator") -> str:
    response = await client.post(BASE, headers=_as(user), json={})
    assert response.status == 201
    return (await response.json())["broadcast_id"]


async def _join(client: Any, broadcast_id: str, user: str) -> Dict[str, Any]:
    response = await client.post(f"{BASE}/{broadcast_id}/viewers", headers=_as(user), json={})
    assert response.status == 201, await response.text()
    return await response.json()


def _assert_no_secrets(payload: Any, *, allow_client_token: bool = False) -> None:
    """Assert a response body carries nothing credential-like."""
    blob = json.dumps(payload)
    for key in _FORBIDDEN_KEYS:
        assert key not in blob, f"{key} leaked into {blob[:200]}"
    if not allow_client_token:
        assert "client_token" not in blob


# ── Create / read ──────────────────────────────────────────────────────────


async def test_create_returns_201_without_credentials(client) -> None:
    response = await client.post(BASE, headers=_as("creator"), json={})
    assert response.status == 201
    body = await response.json()
    assert body["broadcast_id"].startswith("bc-")
    # The share link carries the id and nothing else — no role, no credential.
    assert body["share_path"] == f"/?broadcast={body['broadcast_id']}"
    assert body["state"]["state"] == "pending"
    # Creation asserts no moderator.
    assert body["state"]["moderator_display_id"] is None
    _assert_no_secrets(body)


async def test_create_requires_authentication(client) -> None:
    response = await client.post(BASE, json={})
    assert response.status == 401


async def test_get_state_200_and_404(client) -> None:
    broadcast_id = await _create(client)
    response = await client.get(f"{BASE}/{broadcast_id}", headers=_as("viewer"))
    assert response.status == 200
    _assert_no_secrets(await response.json())

    response = await client.get(f"{BASE}/bc-unknown", headers=_as("viewer"))
    assert response.status == 404


async def test_out_of_scope_agent_is_404_not_403(client) -> None:
    """An out-of-scope id must be indistinguishable from a missing one."""
    broadcast_id = await _create(client)
    response = await client.get(
        f"/api/v1/agents/other-agent/voice-broadcasts/{broadcast_id}",
        headers=_as("viewer"),
    )
    assert response.status == 404


# ── Admission ──────────────────────────────────────────────────────────────


async def test_first_viewer_is_moderator_and_later_ones_are_not(client) -> None:
    broadcast_id = await _create(client, "creator")
    first = await _join(client, broadcast_id, "moderator")
    second = await _join(client, broadcast_id, "guest")
    assert first["role"] == "moderator"
    assert second["role"] == "viewer"
    assert first["media_ready"] is True
    _assert_no_secrets(first)


async def test_eleventh_viewer_409(client) -> None:
    broadcast_id = await _create(client)
    for index in range(MAX_VIEWERS):
        await _join(client, broadcast_id, f"user-{index}")
    response = await client.post(f"{BASE}/{broadcast_id}/viewers", headers=_as("late"), json={})
    assert response.status == 409
    body = await response.json()
    assert body["error"] == "viewer_limit_reached"
    # The current state accompanies the conflict so the client can render it.
    assert body["state"]["viewer_count"] == MAX_VIEWERS


async def test_join_terminal_broadcast_410(client) -> None:
    broadcast_id = await _create(client)
    joined = await _join(client, broadcast_id, "moderator")
    await client.post(f"{BASE}/{broadcast_id}/stop", headers=_as("moderator"), json={})
    response = await client.post(f"{BASE}/{broadcast_id}/viewers", headers=_as("late"), json={})
    assert response.status == 410
    assert joined["role"] == "moderator"


async def test_join_unknown_broadcast_404(client) -> None:
    response = await client.post(f"{BASE}/bc-unknown/viewers", headers=_as("viewer"), json={})
    assert response.status == 404


# ── Connection credentials ─────────────────────────────────────────────────


async def test_connection_409_while_starting_then_200(client) -> None:
    FakeMediaSession.stall = True
    broadcast_id = await _create(client)
    joined = await _join(client, broadcast_id, "moderator")
    lease_id = joined["lease_id"]

    response = await client.get(
        f"{BASE}/{broadcast_id}/viewers/{lease_id}/connection",
        headers=_as("moderator"),
    )
    assert response.status == 409
    assert response.headers["Retry-After"] == "1"
    body = await response.json()
    assert body["retryable"] is True

    # Media becomes ready; the same lease now gets its credentials.
    service = client.service  # type: ignore[attr-defined]
    session = service.media_session(TENANT, broadcast_id)
    await service.registry.transition(
        TENANT,
        broadcast_id,
        BroadcastState.AVATAR,
        output_epoch=1,
        expected_owner_epoch=session.owner_epoch,
    )
    session.state = BroadcastState.AVATAR

    response = await client.get(
        f"{BASE}/{broadcast_id}/viewers/{lease_id}/connection",
        headers=_as("moderator"),
    )
    assert response.status == 200
    body = await response.json()
    assert body["client_token"].startswith("viewer-jwt-")
    assert body["lease_id"] == lease_id
    # This is the ONE place a token may appear, and only the viewer's own.
    _assert_no_secrets(body, allow_client_token=True)


async def test_connection_is_idempotent(client) -> None:
    broadcast_id = await _create(client)
    joined = await _join(client, broadcast_id, "moderator")
    url = f"{BASE}/{broadcast_id}/viewers/{joined['lease_id']}/connection"
    first = await (await client.get(url, headers=_as("moderator"))).json()
    second = await (await client.get(url, headers=_as("moderator"))).json()
    assert first["client_token"] == second["client_token"]


async def test_connection_for_another_principals_lease_is_refused(client) -> None:
    broadcast_id = await _create(client)
    owner = await _join(client, broadcast_id, "moderator")
    await _join(client, broadcast_id, "intruder")
    response = await client.get(
        f"{BASE}/{broadcast_id}/viewers/{owner['lease_id']}/connection",
        headers=_as("intruder"),
    )
    assert response.status in (403, 409)


# ── Leave ──────────────────────────────────────────────────────────────────


async def test_leave_is_204_and_idempotent(client) -> None:
    broadcast_id = await _create(client)
    await _join(client, broadcast_id, "moderator")
    guest = await _join(client, broadcast_id, "guest")
    url = f"{BASE}/{broadcast_id}/viewers/{guest['lease_id']}"
    assert (await client.delete(url, headers=_as("guest"))).status == 204
    assert (await client.delete(url, headers=_as("guest"))).status == 204


# ── Hands ──────────────────────────────────────────────────────────────────


async def test_raise_and_cancel_own_hand(client) -> None:
    broadcast_id = await _create(client)
    await _join(client, broadcast_id, "moderator")
    guest = await _join(client, broadcast_id, "guest")

    response = await client.post(
        f"{BASE}/{broadcast_id}/hands",
        headers=_as("guest"),
        json={"lease_id": guest["lease_id"]},
    )
    assert response.status == 200
    body = await response.json()
    assert [h["lease_id"] for h in body["state"]["hand_requests"]] == [guest["lease_id"]]
    # Raising a hand grants no microphone permission.
    assert body["state"]["speaker_display_id"] != guest["lease_id"]

    response = await client.delete(
        f"{BASE}/{broadcast_id}/hands/me?lease_id={guest['lease_id']}",
        headers=_as("guest"),
    )
    assert response.status == 200
    assert (await response.json())["state"]["hand_requests"] == []


async def test_a_participant_cannot_raise_another_hand(client) -> None:
    broadcast_id = await _create(client)
    moderator = await _join(client, broadcast_id, "moderator")
    await _join(client, broadcast_id, "guest")
    response = await client.post(
        f"{BASE}/{broadcast_id}/hands",
        headers=_as("guest"),
        json={"lease_id": moderator["lease_id"]},
    )
    assert response.status in (403, 409)


async def test_only_the_moderator_dismisses_a_hand(client) -> None:
    broadcast_id = await _create(client)
    await _join(client, broadcast_id, "moderator")
    guest = await _join(client, broadcast_id, "guest")
    await client.post(
        f"{BASE}/{broadcast_id}/hands",
        headers=_as("guest"),
        json={"lease_id": guest["lease_id"]},
    )
    response = await client.delete(f"{BASE}/{broadcast_id}/hands/{guest['lease_id']}", headers=_as("guest"))
    assert response.status == 403
    response = await client.delete(f"{BASE}/{broadcast_id}/hands/{guest['lease_id']}", headers=_as("moderator"))
    assert response.status == 200
    assert (await response.json())["state"]["hand_requests"] == []


# ── Floor ──────────────────────────────────────────────────────────────────


async def _confirm(client: Any, broadcast_id: str, lease_id: str) -> None:
    service = client.service  # type: ignore[attr-defined]
    await service.registry.confirm_viewer(TENANT, broadcast_id, lease_id)
    await service.registry.heartbeat_control(TENANT, broadcast_id, lease_id)


async def test_floor_grant_and_release(client) -> None:
    broadcast_id = await _create(client)
    moderator = await _join(client, broadcast_id, "moderator")
    guest = await _join(client, broadcast_id, "guest")
    await _confirm(client, broadcast_id, guest["lease_id"])

    state = (await (await client.get(f"{BASE}/{broadcast_id}", headers=_as("moderator"))).json())["state"]
    response = await client.post(
        f"{BASE}/{broadcast_id}/floor",
        headers=_as("moderator"),
        json={"lease_id": guest["lease_id"], "expected_version": state["version"]},
    )
    assert response.status == 200
    body = await response.json()
    assert body["state"]["speaker_display_id"] == guest["lease_id"]
    _assert_no_secrets(body)

    # Finish Speaking, by the speaker.
    response = await client.post(
        f"{BASE}/{broadcast_id}/floor/release",
        headers=_as("guest"),
        json={"lease_id": guest["lease_id"]},
    )
    assert response.status == 200
    assert (await response.json())["state"]["speaker_display_id"] == (moderator["lease_id"])


async def test_floor_stale_version_409_with_state(client) -> None:
    broadcast_id = await _create(client)
    await _join(client, broadcast_id, "moderator")
    guest = await _join(client, broadcast_id, "guest")
    await _confirm(client, broadcast_id, guest["lease_id"])

    response = await client.post(
        f"{BASE}/{broadcast_id}/floor",
        headers=_as("moderator"),
        json={"lease_id": guest["lease_id"], "expected_version": 0},
    )
    assert response.status == 409
    body = await response.json()
    assert body["error"] == "stale_version"
    assert "state" in body


async def test_floor_requires_moderator(client) -> None:
    broadcast_id = await _create(client, "creator")
    await _join(client, broadcast_id, "moderator")
    guest = await _join(client, broadcast_id, "guest")
    await _confirm(client, broadcast_id, guest["lease_id"])
    state = (await (await client.get(f"{BASE}/{broadcast_id}", headers=_as("guest"))).json())["state"]
    response = await client.post(
        f"{BASE}/{broadcast_id}/floor",
        headers=_as("guest"),
        json={"lease_id": guest["lease_id"], "expected_version": state["version"]},
    )
    assert response.status == 403


async def test_floor_requires_expected_version(client) -> None:
    broadcast_id = await _create(client)
    await _join(client, broadcast_id, "moderator")
    response = await client.post(f"{BASE}/{broadcast_id}/floor", headers=_as("moderator"), json={})
    assert response.status == 400


async def test_release_floor_by_a_non_speaker_is_refused(client) -> None:
    broadcast_id = await _create(client)
    await _join(client, broadcast_id, "moderator")
    guest = await _join(client, broadcast_id, "guest")
    response = await client.post(
        f"{BASE}/{broadcast_id}/floor/release",
        headers=_as("guest"),
        json={"lease_id": guest["lease_id"]},
    )
    assert response.status == 403


# ── Stop ───────────────────────────────────────────────────────────────────


async def test_stop_requires_moderator_not_creator(client) -> None:
    """Spec §2: "Other participants get 403 even if they created the broadcast"."""
    broadcast_id = await _create(client, "creator")
    await _join(client, broadcast_id, "moderator")
    await _join(client, broadcast_id, "creator")

    response = await client.post(f"{BASE}/{broadcast_id}/stop", headers=_as("creator"), json={})
    assert response.status == 403

    response = await client.post(f"{BASE}/{broadcast_id}/stop", headers=_as("moderator"), json={})
    assert response.status == 202
    body = await response.json()
    assert body["state"]["state"] in ("stopping", "ended")


async def test_stop_is_idempotent(client) -> None:
    broadcast_id = await _create(client)
    await _join(client, broadcast_id, "moderator")
    first = await client.post(f"{BASE}/{broadcast_id}/stop", headers=_as("moderator"), json={})
    assert first.status == 202
    second = await client.post(f"{BASE}/{broadcast_id}/stop", headers=_as("moderator"), json={})
    assert second.status in (202, 403, 410)


# ── Hardening ──────────────────────────────────────────────────────────────


async def test_oversized_body_is_refused(client) -> None:
    broadcast_id = await _create(client)
    response = await client.post(
        f"{BASE}/{broadcast_id}/hands",
        headers=_as("moderator"),
        data=b"x" * (MAX_BODY_BYTES + 100),
    )
    assert response.status == 413


async def test_malformed_json_is_400(client) -> None:
    broadcast_id = await _create(client)
    response = await client.post(f"{BASE}/{broadcast_id}/hands", headers=_as("moderator"), data=b"{not json")
    assert response.status == 400


async def test_cross_origin_state_change_is_refused(client) -> None:
    broadcast_id = await _create(client)
    headers = _as("moderator")
    headers["Origin"] = "https://evil.example"
    response = await client.post(f"{BASE}/{broadcast_id}/viewers", headers=headers, json={})
    assert response.status == 403


async def test_rate_limit_returns_429(client) -> None:
    broadcast_id = await _create(client, "spammer")
    statuses = []
    for _ in range(RATE_LIMIT_REQUESTS + 5):
        response = await client.get(f"{BASE}/{broadcast_id}", headers=_as("spammer"))
        statuses.append(response.status)
    assert 429 in statuses


async def test_no_secret_keys_in_any_response(client) -> None:
    """One sweep over every non-connection endpoint."""
    broadcast_id = await _create(client)
    moderator = await _join(client, broadcast_id, "moderator")
    guest = await _join(client, broadcast_id, "guest")
    await _confirm(client, broadcast_id, guest["lease_id"])

    payloads: List[Any] = []
    payloads.append(await (await client.get(f"{BASE}/{broadcast_id}", headers=_as("guest"))).json())
    payloads.append(
        await (
            await client.post(
                f"{BASE}/{broadcast_id}/hands",
                headers=_as("guest"),
                json={"lease_id": guest["lease_id"]},
            )
        ).json()
    )
    state = payloads[0]["state"]
    payloads.append(
        await (
            await client.post(
                f"{BASE}/{broadcast_id}/floor",
                headers=_as("moderator"),
                json={
                    "lease_id": guest["lease_id"],
                    "expected_version": state["version"],
                },
            )
        ).json()
    )
    payloads.append(await (await client.post(f"{BASE}/{broadcast_id}/stop", headers=_as("moderator"), json={})).json())
    for payload in payloads:
        _assert_no_secrets(payload)
    assert moderator["role"] == "moderator"


def test_rate_limiter_does_not_grow_without_bound() -> None:
    """Quiet principals must be forgotten, not accumulated forever.

    The map kept one deque per distinct `tenant:user` for the lifetime of the
    process, so a long-running server leaked an entry for every principal that
    ever called.
    """
    from parrot.handlers.voice_broadcast import _RateLimiter

    limiter = _RateLimiter(limit=5, window_s=1.0)
    for index in range(500):
        assert limiter.allow(f"tenant:user-{index}") is True
    assert len(limiter._hits) == 500  # noqa: SLF001

    # After a window with no traffic from them, they are swept.
    limiter._last_sweep -= 10.0  # noqa: SLF001
    for hits in limiter._hits.values():  # noqa: SLF001
        hits[-1] -= 10.0
    assert limiter.allow("tenant:someone-new") is True
    assert len(limiter._hits) == 1  # noqa: SLF001


def test_rate_limiter_still_limits_an_active_principal() -> None:
    """Eviction must not hand a busy caller a fresh budget."""
    from parrot.handlers.voice_broadcast import _RateLimiter

    limiter = _RateLimiter(limit=3, window_s=60.0)
    assert [limiter.allow("tenant:ada") for _ in range(4)] == [True, True, True, False]
