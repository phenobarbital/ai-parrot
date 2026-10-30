"""End-to-end Telegram OAuth parity through principal adapters."""
from __future__ import annotations

from typing import Any

import pytest

from parrot.auth.credentials import OAuthCredentialResolver
from parrot.auth.oauth2.events import ChannelNotifierRegistry, ConnectionEventPublisher
from parrot.auth.principal import Principal

from .test_connections_isolation_matrix import (
    FakeCredentialStore,
    FakeManager,
    FakePrincipalResolver,
    MemRedis,
)


@pytest.mark.asyncio
async def test_e2e_telegram_jira_parity() -> None:
    """A Telegram connection is durable and reusable from web and A2A adapters."""
    principal = Principal(
        user_id="1042",
        canonical_identity="jlara@example.com",
        channel="telegram",
        channel_user_id="88123",
    )
    resolver = FakePrincipalResolver(
        {
            ("telegram", "88123"): principal,
            ("web", "1042"): principal,
            ("a2a", "jlara@example.com"): principal,
        }
    )
    store = FakeCredentialStore()
    manager = FakeManager(
        "client",
        "https://idp.example/callback",
        client_secret="secret",
        redis_client=MemRedis(),
        credential_store=store,
    )
    manager.exchange_payload = {
        "access_token": "telegram-access",
        "refresh_token": "telegram-refresh",
        "expires_in": 3600,
        "scope": "read",
    }
    _, nonce = await manager.create_authorization_url("telegram", "88123", principal=principal)
    await manager.handle_callback("telegram-code", nonce)

    credential_resolver = OAuthCredentialResolver(manager, principal_resolver=resolver)
    web_token = await credential_resolver.resolve("web", "1042")
    a2a_token = await credential_resolver.resolve("a2a", "jlara@example.com")

    assert web_token is not None
    assert a2a_token is not None
    assert web_token.access_token == "telegram-access"
    assert a2a_token.access_token == web_token.access_token
    assert store.rows[("1042", "fake")]["access_token"] == "telegram-access"


@pytest.mark.asyncio
async def test_telegram_notifier_adapter_isolated_from_callback() -> None:
    """A notifier failure is swallowed after the connection has been persisted."""
    registry = ChannelNotifierRegistry()

    class FailingTelegramNotifier:
        """Notifier double representing the Telegram adapter."""

        channel = "telegram"

        async def notify(self, event: Any, state: dict[str, Any]) -> None:
            del event, state
            raise RuntimeError("telegram unavailable")

    registry.register(FailingTelegramNotifier())
    publisher = ConnectionEventPublisher(notifiers=registry)
    manager = FakeManager(
        "client",
        "https://idp.example/callback",
        client_secret="secret",
        redis_client=MemRedis(),
        credential_store=FakeCredentialStore(),
        event_publisher=publisher,
    )
    principal = Principal(user_id="1042", channel="telegram", channel_user_id="88123")
    _, nonce = await manager.create_authorization_url("telegram", "88123", principal=principal)

    token_set, _ = await manager.handle_callback("telegram-code", nonce)

    assert token_set.access_token == "access-token"
    assert await manager.get_valid_token("telegram", "1042") is not None
    ChannelNotifierRegistry._reset()
