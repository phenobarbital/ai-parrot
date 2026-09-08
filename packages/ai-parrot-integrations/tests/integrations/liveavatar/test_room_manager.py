"""Unit tests for LiveKitRoomManager (TASK-004).

Uses env-driven credentials (monkeypatched) to verify token minting without
hitting the LiveKit Cloud API.
"""

from __future__ import annotations

import pytest

from parrot.integrations.liveavatar import LiveKitRoomManager
from parrot.integrations.liveavatar.models import LiveKitRoomTokens


@pytest.fixture
def mgr(monkeypatch: pytest.MonkeyPatch) -> LiveKitRoomManager:
    """LiveKitRoomManager with monkeypatched env credentials."""
    monkeypatch.setenv("LIVEKIT_URL", "wss://x.livekit.cloud")
    monkeypatch.setenv("LIVEKIT_API_KEY", "test-key")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "test-secret")
    return LiveKitRoomManager()


def test_room_manager_mints_tokens(mgr: LiveKitRoomManager) -> None:
    """mint_room_tokens returns a LiveKitRoomTokens with non-empty tokens."""
    tokens = mgr.mint_room_tokens(room="r1", identity="viewer-1")
    assert isinstance(tokens, LiveKitRoomTokens)
    assert tokens.client_token
    assert tokens.agent_token


def test_room_manager_tokens_distinct(mgr: LiveKitRoomManager) -> None:
    """client_token and agent_token are different JWTs."""
    tokens = mgr.mint_room_tokens(room="r1", identity="viewer-1")
    assert tokens.client_token != tokens.agent_token


def test_room_manager_correct_url(mgr: LiveKitRoomManager) -> None:
    """livekit_url is taken from LIVEKIT_URL env."""
    tokens = mgr.mint_room_tokens(room="r1", identity="v")
    assert tokens.livekit_url == "wss://x.livekit.cloud"


def test_room_manager_correct_room(mgr: LiveKitRoomManager) -> None:
    """room name is preserved in LiveKitRoomTokens."""
    tokens = mgr.mint_room_tokens(room="session-42", identity="v")
    assert tokens.room == "session-42"


def test_room_manager_missing_env_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing LIVEKIT_URL env raises KeyError."""
    monkeypatch.delenv("LIVEKIT_URL", raising=False)
    monkeypatch.delenv("LIVEKIT_API_KEY", raising=False)
    monkeypatch.delenv("LIVEKIT_API_SECRET", raising=False)
    with pytest.raises(KeyError):
        LiveKitRoomManager()


def test_room_manager_jwt_contains_room(mgr: LiveKitRoomManager) -> None:
    """Both JWTs are non-empty strings (basic JWT format check)."""
    tokens = mgr.mint_room_tokens(room="my-room", identity="viewer")
    # JWTs are dot-separated base64 segments
    assert tokens.client_token.count(".") >= 2
    assert tokens.agent_token.count(".") >= 2


def test_room_manager_inline_credentials() -> None:
    """Inline credentials override env vars."""
    mgr = LiveKitRoomManager(
        url="wss://inline.livekit.cloud",
        api_key="inline-key",
        api_secret="inline-secret",
    )
    tokens = mgr.mint_room_tokens(room="r", identity="v")
    assert tokens.livekit_url == "wss://inline.livekit.cloud"
    assert tokens.client_token


# ---------------------------------------------------------------------------
# Phase C (FEAT-243): publish-capable browser token + worker dispatch
# ---------------------------------------------------------------------------


def _jwt_payload(token: str) -> dict:
    """Decode a JWT payload without signature verification (test-only)."""
    import base64
    import json

    payload_b64 = token.split(".")[1]
    padding = "=" * (-len(payload_b64) % 4)
    return json.loads(base64.urlsafe_b64decode(payload_b64 + padding))


def test_client_token_remains_subscribe_only(mgr: LiveKitRoomManager) -> None:
    """The Phase A client_token must stay subscribe-only (regression guard)."""
    tokens = mgr.mint_room_tokens(room="sess-1", identity="viewer")
    grants = _jwt_payload(tokens.client_token)["video"]
    assert grants.get("canPublish") in (False, None)


# ---------------------------------------------------------------------------
# FEAT-537 (TASK-2954): role-specific tokens + room administration
# ---------------------------------------------------------------------------


def test_viewer_token_is_subscribe_only_with_ttl(mgr: LiveKitRoomManager) -> None:
    """A viewer credential can join and subscribe — nothing else."""
    token = mgr.mint_viewer_token("room-x", "viewer-abc", ttl_s=60)
    payload = _jwt_payload(token)
    grants = payload["video"]
    assert grants["canPublish"] is False
    assert grants["canPublishData"] is False
    assert grants["canSubscribe"] is True
    assert grants["roomJoin"] is True
    assert grants["room"] == "room-x"
    assert payload["sub"] == "viewer-abc"
    assert 55 <= payload["exp"] - payload["nbf"] <= 65
    # No administrative grants of any kind.
    for admin_grant in ("roomAdmin", "roomCreate", "roomList", "roomRecord"):
        assert grants.get(admin_grant) in (False, None)


def test_viewer_tokens_are_unique_per_identity(mgr: LiveKitRoomManager) -> None:
    """Each browser gets its own identity — reuse would evict the previous one."""
    first = _jwt_payload(mgr.mint_viewer_token("room-x", "viewer-1"))
    second = _jwt_payload(mgr.mint_viewer_token("room-x", "viewer-2"))
    assert first["sub"] != second["sub"]


def test_publisher_tokens_have_distinct_identities(mgr: LiveKitRoomManager) -> None:
    """The avatar and direct publishers must not share the fixed legacy identity."""
    avatar = _jwt_payload(mgr.mint_publisher_token("room-x", "avatar-1234"))
    direct = _jwt_payload(mgr.mint_publisher_token("room-x", "direct-1234"))
    assert avatar["sub"] == "avatar-1234"
    assert direct["sub"] == "direct-1234"
    assert avatar["sub"] != direct["sub"]
    assert "avatar-agent" not in (avatar["sub"], direct["sub"])
    assert avatar["video"]["canPublish"] is True
    assert direct["video"]["canPublish"] is True
    assert avatar["video"]["canPublishData"] is False


def test_publisher_token_refuses_the_legacy_fixed_identity(
    mgr: LiveKitRoomManager,
) -> None:
    """Spec §6: the fixed ``avatar-agent`` token must not be reused."""
    with pytest.raises(ValueError, match="avatar-agent"):
        mgr.mint_publisher_token("room-x", "avatar-agent")


def test_publisher_token_accepts_a_display_name(mgr: LiveKitRoomManager) -> None:
    payload = _jwt_payload(mgr.mint_publisher_token("room-x", "avatar-1234", name="Avatar"))
    assert payload["name"] == "Avatar"


def test_mint_room_tokens_is_unchanged(mgr: LiveKitRoomManager) -> None:
    """FEAT-245/536 callers keep the original two-token behaviour."""
    tokens = mgr.mint_room_tokens(room="r1", identity="viewer-1")
    assert _jwt_payload(tokens.agent_token)["sub"] == "avatar-agent"
    assert _jwt_payload(tokens.client_token)["sub"] == "viewer-1"


def test_http_url_derivation(mgr: LiveKitRoomManager) -> None:
    """``LiveKitAPI`` speaks HTTP on the same host the SDK reaches over ws."""
    assert mgr.http_url == "https://x.livekit.cloud"
    mgr.url = "ws://localhost:7880"
    assert mgr.http_url == "http://localhost:7880"
    mgr.url = "https://already-http"
    assert mgr.http_url == "https://already-http"


# ── Room administration (fake LiveKitAPI) ──────────────────────────────────


class _FakeRoomService:
    """Records room-service calls made by the manager."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.participants: list[object] = []

    async def create_room(self, request: object) -> object:
        self.calls.append(("create_room", request))
        return object()

    async def remove_participant(self, request: object) -> object:
        self.calls.append(("remove_participant", request))
        return object()

    async def list_participants(self, request: object) -> object:
        self.calls.append(("list_participants", request))

        class _Response:
            participants = self.participants

        return _Response()

    async def delete_room(self, request: object) -> object:
        self.calls.append(("delete_room", request))
        return object()


class _FakeLiveKitAPI:
    """Minimal stand-in for ``livekit.api.LiveKitAPI``."""

    last: "_FakeLiveKitAPI | None" = None

    def __init__(self, url: str, key: str, secret: str) -> None:
        self.url = url
        self.key = key
        self.secret = secret
        self.room = _FakeRoomService()
        self.closed = False
        _FakeLiveKitAPI.last = self

    async def aclose(self) -> None:
        self.closed = True


class _Identity:
    def __init__(self, identity: str) -> None:
        self.identity = identity


@pytest.fixture
def fake_api(mocker):
    """Patch ``_require_livekit_api`` so no real LiveKit call is attempted."""
    from parrot.integrations.liveavatar import room_manager as room_manager_module

    module = mocker.MagicMock()
    module.LiveKitAPI = _FakeLiveKitAPI
    module.CreateRoomRequest = lambda **kw: ("CreateRoomRequest", kw)
    module.RoomParticipantIdentity = lambda **kw: ("RoomParticipantIdentity", kw)
    module.ListParticipantsRequest = lambda **kw: ("ListParticipantsRequest", kw)
    module.DeleteRoomRequest = lambda **kw: ("DeleteRoomRequest", kw)
    mocker.patch.object(room_manager_module, "_require_livekit_api", return_value=module)
    return module


async def test_create_room_uses_api_and_closes(mgr: LiveKitRoomManager, fake_api) -> None:
    await mgr.create_room("room-x")
    api = _FakeLiveKitAPI.last
    assert api is not None
    assert api.url == "https://x.livekit.cloud"
    name, request = api.room.calls[0]
    assert name == "create_room"
    # 12, not 10: ten viewer seats plus both producers (spec §7).
    assert request == (
        "CreateRoomRequest",
        {"name": "room-x", "max_participants": 12, "empty_timeout": 60},
    )
    assert api.closed is True


async def test_remove_participant_uses_api_and_closes(mgr: LiveKitRoomManager, fake_api) -> None:
    await mgr.remove_participant("room-x", "viewer-7")
    api = _FakeLiveKitAPI.last
    assert api is not None
    assert api.room.calls[0] == (
        "remove_participant",
        ("RoomParticipantIdentity", {"room": "room-x", "identity": "viewer-7"}),
    )
    assert api.closed is True


async def test_list_participant_identities(mgr: LiveKitRoomManager, fake_api, mocker) -> None:
    def _factory(url: str, key: str, secret: str) -> _FakeLiveKitAPI:
        api = _FakeLiveKitAPI(url, key, secret)
        api.room.participants = [_Identity("viewer-1"), _Identity("avatar-abc")]
        return api

    fake_api.LiveKitAPI = _factory
    identities = await mgr.list_participant_identities("room-x")
    assert identities == ["viewer-1", "avatar-abc"]
    assert _FakeLiveKitAPI.last is not None
    assert _FakeLiveKitAPI.last.closed is True


async def test_delete_room_uses_api_and_closes(mgr: LiveKitRoomManager, fake_api) -> None:
    await mgr.delete_room("room-x")
    api = _FakeLiveKitAPI.last
    assert api is not None
    assert api.room.calls[0] == ("delete_room", ("DeleteRoomRequest", {"room": "room-x"}))
    assert api.closed is True


async def test_room_admin_closes_the_client_even_on_failure(mgr: LiveKitRoomManager, fake_api, mocker) -> None:
    """A failing room-service call must not leak the aiohttp client."""

    async def _boom(_request: object) -> object:
        raise RuntimeError("livekit unavailable")

    def _factory(url: str, key: str, secret: str) -> _FakeLiveKitAPI:
        api = _FakeLiveKitAPI(url, key, secret)
        api.room.delete_room = _boom  # type: ignore[method-assign]
        return api

    fake_api.LiveKitAPI = _factory
    with pytest.raises(RuntimeError, match="livekit unavailable"):
        await mgr.delete_room("room-x")
    assert _FakeLiveKitAPI.last is not None
    assert _FakeLiveKitAPI.last.closed is True


# ── Vendor token grants (live-run regressions) ─────────────────────────────


def test_avatar_publisher_token_can_grant_data_publishing(mgr: LiveKitRoomManager) -> None:
    """LiveAvatar refuses a token without ``canPublishData``.

    Found only by running the demo against the real vendor:
    ``422 Bad LiveKit configuration. Input Livekit token needs to grant
    canPublishData permission.`` Avatar startup degrades instead of raising,
    so this turned every broadcast into a silent audio-only fallback.
    """
    token = mgr.mint_publisher_token("room-1", "avatar-x", can_publish_data=True)
    grants = _jwt_payload(token)["video"]
    assert grants["canPublishData"] is True
    assert grants["canPublish"] is True


def test_publisher_token_withholds_data_publishing_by_default(mgr: LiveKitRoomManager) -> None:
    """Least privilege: only the caller that needs it asks for it."""
    grants = _jwt_payload(mgr.mint_publisher_token("room-1", "direct-x"))["video"]
    assert grants.get("canPublishData", False) is False


def test_viewer_token_never_grants_data_publishing(mgr: LiveKitRoomManager) -> None:
    """Viewers stay subscribe-only regardless of the publisher change (AC3)."""
    grants = _jwt_payload(mgr.mint_viewer_token("room-1", "viewer-x"))["video"]
    assert grants.get("canPublish", False) is False
    assert grants.get("canPublishData", False) is False
