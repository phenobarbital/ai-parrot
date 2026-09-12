"""Regression tests for the authenticated user WebSocket registry."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.handlers.user import UserSocketManager


class FakeWebSocket:
    """Minimal socket used to exercise manager state without a network server."""

    def __init__(self) -> None:
        self.closed = False
        self.sent: list[str] = []

    async def send_str(self, message: str) -> None:
        """Record a delivered message."""
        self.sent.append(message)


def make_manager() -> UserSocketManager:
    """Build a manager without registering routes or external resources."""
    manager = object.__new__(UserSocketManager)
    manager.authenticated_users = {}
    manager.user_sockets = {}
    manager.pending_auth = set()
    manager.default_channels = []
    manager.channel_subscriptions = {}
    manager.redis = None
    manager.logger = MagicMock()
    return manager


@pytest.mark.asyncio
async def test_repeated_authentication_of_one_socket_is_idempotent() -> None:
    """A duplicate auth frame must not mint a suffixed username or extra success frame."""
    manager = make_manager()
    socket = FakeWebSocket()
    manager._validate_token = AsyncMock(return_value={"username": "user@example.com", "user_id": "1"})
    manager._store_user_info = AsyncMock()

    assert await manager._handle_auth(socket, {"token": "token"}, {})
    assert await manager._handle_auth(socket, {"token": "token"}, {})

    assert list(manager.user_sockets) == ["user@example.com"]
    assert manager.user_sockets["user@example.com"] == {socket}
    assert len(socket.sent) == 1
    manager._validate_token.assert_awaited_once()
    manager._store_user_info.assert_awaited_once()


@pytest.mark.asyncio
async def test_multiple_sockets_share_canonical_username_and_cleanup_last_socket() -> None:
    """Multiple tabs remain reachable as one user until the final disconnect."""
    manager = make_manager()
    first_socket = FakeWebSocket()
    second_socket = FakeWebSocket()
    user_info: dict[str, Any] = {"username": "user@example.com", "user_id": "1"}
    manager.authenticated_users[first_socket] = user_info.copy()
    manager.authenticated_users[second_socket] = user_info.copy()
    manager.user_sockets["user@example.com"] = {first_socket, second_socket}
    manager._remove_user_info = AsyncMock()

    assert await manager.send_direct_message("sender", "user@example.com", "hello")
    assert len(first_socket.sent) == 1
    assert len(second_socket.sent) == 1

    await manager.on_disconnect(first_socket, "default", {})
    assert manager.user_sockets["user@example.com"] == {second_socket}
    manager._remove_user_info.assert_not_awaited()

    await manager.on_disconnect(second_socket, "default", {})
    assert "user@example.com" not in manager.user_sockets
    manager._remove_user_info.assert_awaited_once_with("user@example.com")
