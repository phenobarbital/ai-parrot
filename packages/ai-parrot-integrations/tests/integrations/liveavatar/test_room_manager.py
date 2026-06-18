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


def test_mint_browser_token_allows_publish(mgr: LiveKitRoomManager) -> None:
    """mint_browser_token grants can_publish (vs subscribe-only client_token)."""
    token = mgr.mint_browser_token(room="sess-1", identity="browser-1")
    assert token.count(".") >= 2
    grants = _jwt_payload(token)["video"]
    assert grants.get("canPublish") is True
    assert grants.get("canSubscribe") is True
    assert grants.get("room") == "sess-1"


def test_mint_browser_token_audio_only_restricts_sources(
    mgr: LiveKitRoomManager,
) -> None:
    """audio_only (default) restricts publish to the microphone source."""
    token = mgr.mint_browser_token(room="sess-1", identity="b")
    grants = _jwt_payload(token)["video"]
    assert grants.get("canPublishSources") == ["microphone"]


def test_mint_browser_token_full_publish_when_not_audio_only(
    mgr: LiveKitRoomManager,
) -> None:
    """audio_only=False does not restrict publish sources."""
    token = mgr.mint_browser_token(room="sess-1", identity="b", audio_only=False)
    grants = _jwt_payload(token)["video"]
    assert not grants.get("canPublishSources")


def test_client_token_remains_subscribe_only(mgr: LiveKitRoomManager) -> None:
    """The Phase A client_token must stay subscribe-only (regression guard)."""
    tokens = mgr.mint_room_tokens(room="sess-1", identity="viewer")
    grants = _jwt_payload(tokens.client_token)["video"]
    assert grants.get("canPublish") in (False, None)


async def test_dispatch_worker_issues_create_dispatch(
    mgr: LiveKitRoomManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """dispatch_worker builds a CreateAgentDispatchRequest and returns the id."""
    from unittest.mock import AsyncMock, MagicMock

    captured: dict = {}

    fake_dispatch = MagicMock()
    fake_dispatch.id = "disp-123"

    fake_service = MagicMock()
    fake_service.create_dispatch = AsyncMock(return_value=fake_dispatch)

    fake_lkapi = MagicMock()
    fake_lkapi.agent_dispatch = fake_service
    fake_lkapi.aclose = AsyncMock()

    def _fake_create_request(*, agent_name, room, metadata):
        captured["agent_name"] = agent_name
        captured["room"] = room
        captured["metadata"] = metadata
        return MagicMock()

    from livekit import api as livekit_api

    monkeypatch.setattr(
        livekit_api, "LiveKitAPI", MagicMock(return_value=fake_lkapi)
    )
    monkeypatch.setattr(
        livekit_api, "CreateAgentDispatchRequest", _fake_create_request
    )

    dispatch_id = await mgr.dispatch_worker(
        room="sess-1",
        worker_agent_name="liveavatar-voice",
        metadata_json='{"session_id": "sess-1"}',
    )

    assert dispatch_id == "disp-123"
    assert captured == {
        "agent_name": "liveavatar-voice",
        "room": "sess-1",
        "metadata": '{"session_id": "sess-1"}',
    }
    fake_lkapi.aclose.assert_awaited_once()
    fake_service.create_dispatch.assert_awaited_once()


async def test_delete_dispatch_calls_service_and_closes(
    mgr: LiveKitRoomManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """delete_dispatch forwards (dispatch_id, room) and closes the API client."""
    from unittest.mock import AsyncMock, MagicMock

    fake_service = MagicMock()
    fake_service.delete_dispatch = AsyncMock(return_value=MagicMock())

    fake_lkapi = MagicMock()
    fake_lkapi.agent_dispatch = fake_service
    fake_lkapi.aclose = AsyncMock()

    from livekit import api as livekit_api

    monkeypatch.setattr(
        livekit_api, "LiveKitAPI", MagicMock(return_value=fake_lkapi)
    )

    await mgr.delete_dispatch(room="sess-1", dispatch_id="disp-123")

    fake_service.delete_dispatch.assert_awaited_once_with("disp-123", "sess-1")
    fake_lkapi.aclose.assert_awaited_once()
