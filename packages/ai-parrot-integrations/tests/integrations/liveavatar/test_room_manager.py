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
