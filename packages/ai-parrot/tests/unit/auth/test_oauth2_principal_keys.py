"""Principal-key and durable-first tests for the abstract OAuth2 manager."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import pytest

from parrot.auth.oauth2_base import CredentialPersistenceError
from parrot.auth.principal import Principal, set_principal_resolver

from ._oauth2_fakes import FakeCredentialStore, FakeManager, FakePrincipalResolver, MemRedis


class _RecordingPublisher:
    """Record connection events published by the manager."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, Dict[str, Any]]] = []

    async def publish(self, event: Any, state_payload: Optional[Dict[str, Any]] = None) -> None:
        """Record one event and its state payload."""
        self.calls.append((event, state_payload or {}))


@pytest.fixture
def principal() -> Principal:
    """Return a principal bound to a Telegram identity."""
    return Principal(
        user_id="1042",
        canonical_identity="jlara@example.com",
        channel="telegram",
        channel_user_id="88123",
    )


@pytest.fixture(autouse=True)
def reset_principal_resolver() -> None:
    """Prevent resolver registration from leaking across tests."""
    set_principal_resolver(None)
    yield
    set_principal_resolver(None)


@pytest.mark.asyncio
async def test_manager_keys_are_principal_scoped(principal: Principal) -> None:
    """Token and lock keys contain the principal but never the channel."""
    manager = FakeManager(
        "cid",
        "https://cb",
        client_secret="s",
        redis_client=MemRedis(),
        credential_store=FakeCredentialStore(),
    )

    assert manager._token_key(principal.user_id) == "oauth2:fake:1042"
    assert manager._lock_key(principal.user_id) == "lock:oauth2:fake:refresh:1042"
    assert "telegram" not in manager._token_key(principal.user_id)
    assert "telegram" not in manager._lock_key(principal.user_id)


@pytest.mark.asyncio
async def test_state_binds_principal_and_callback_verifies(principal: Principal) -> None:
    """A callback fails closed before exchange when principal binding is absent."""
    redis = MemRedis()
    store = FakeCredentialStore()
    manager = FakeManager(
        "cid",
        "https://cb",
        client_secret="s",
        redis_client=redis,
        credential_store=store,
    )

    _, nonce = await manager.create_authorization_url("telegram", "88123", principal=principal)
    state = json.loads(await redis.get(manager._nonce_key(nonce)))
    assert state["nav_user_id"] == "1042"
    assert state["channel_user_id"] == "88123"
    assert state["canonical_identity"] == "jlara@example.com"

    for invalid_nav_user_id in (None, "not-a-number"):
        _, tampered_nonce = await manager.create_authorization_url("telegram", "88123", principal=principal)
        tampered_key = manager._nonce_key(tampered_nonce)
        tampered_state = json.loads(await redis.get(tampered_key))
        if invalid_nav_user_id is None:
            tampered_state.pop("nav_user_id")
        else:
            tampered_state["nav_user_id"] = invalid_nav_user_id
        await redis.set(tampered_key, json.dumps(tampered_state))

        with pytest.raises(ValueError, match="nav_user_id"):
            await manager.handle_callback("code", tampered_nonce)

    assert manager.exchange_calls == []
    assert store.rows == {}
    assert await redis.get(manager._token_key(principal.user_id)) is None


@pytest.mark.asyncio
async def test_persist_durable_first_then_redis(principal: Principal) -> None:
    """A failed durable save prevents both cache and completion publication."""
    store = FakeCredentialStore()
    store.fail_next_save = True
    redis = MemRedis()
    publisher = _RecordingPublisher()
    manager = FakeManager(
        "cid",
        "https://cb",
        client_secret="s",
        redis_client=redis,
        credential_store=store,
        event_publisher=publisher,
    )
    _, nonce = await manager.create_authorization_url("telegram", "88123", principal=principal)

    with pytest.raises(CredentialPersistenceError):
        await manager.handle_callback("code", nonce)

    assert await redis.get(manager._token_key(principal.user_id)) is None
    assert publisher.calls == []


@pytest.mark.asyncio
async def test_successful_callback_publishes_completed_once(principal: Principal) -> None:
    """Completion is published exactly once after both persistence layers succeed."""
    store = FakeCredentialStore()
    redis = MemRedis()
    publisher = _RecordingPublisher()
    manager = FakeManager(
        "cid",
        "https://cb",
        client_secret="s",
        redis_client=redis,
        credential_store=store,
        event_publisher=publisher,
    )
    _, nonce = await manager.create_authorization_url("telegram", "88123", principal=principal)

    await manager.handle_callback("code", nonce)

    assert (principal.user_id, manager.provider_id) in store.rows
    assert await redis.get(manager._token_key(principal.user_id)) is not None
    assert len(publisher.calls) == 1
    event, state_payload = publisher.calls[0]
    assert event.kind == "connection.completed"
    assert event.user_id == principal.user_id
    assert state_payload["connection_meta"] == {}


@pytest.mark.asyncio
async def test_authorization_url_resolves_principal(principal: Principal) -> None:
    """The manager uses the registered resolver when no principal is supplied."""
    resolver = FakePrincipalResolver({("telegram", "88123"): principal})
    set_principal_resolver(resolver)
    redis = MemRedis()
    manager = FakeManager(
        "cid",
        "https://cb",
        client_secret="s",
        redis_client=redis,
        credential_store=FakeCredentialStore(),
    )

    _, nonce = await manager.create_authorization_url("telegram", "88123")

    state = json.loads(await redis.get(manager._nonce_key(nonce)))
    assert state["nav_user_id"] == principal.user_id
