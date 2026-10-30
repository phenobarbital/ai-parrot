"""S11 isolation matrix for FEAT-773 (AC-17)."""
from __future__ import annotations

import asyncio
import fnmatch
import time
from typing import Any, AsyncIterator, Dict, Optional, Tuple

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from parrot.auth.credentials import CredentialRequired, OAuthCredentialResolver
from parrot.auth.exceptions import AuthorizationRequired
from parrot.auth.oauth2.events import ChannelNotifierRegistry, ConnectionEventPublisher
from parrot.auth.oauth2.models import AuthRequiredEnvelope
from parrot.auth.oauth2_routes import make_oauth2_callback
from parrot.auth.oauth2_base import (
    AbstractOAuth2Manager,
    AbstractOAuth2TokenSet,
)
from parrot.auth.principal import Principal
from parrot.tools import tool
from parrot.tools.manager import ToolManager


class _MemLock:
    """Async lock adapter matching the manager's Redis lock calls."""

    def __init__(self, lock: asyncio.Lock, blocking_timeout: Optional[float]) -> None:
        self._lock = lock
        self._blocking_timeout = blocking_timeout

    async def acquire(self) -> bool:
        """Acquire within the configured timeout."""
        try:
            await asyncio.wait_for(self._lock.acquire(), timeout=self._blocking_timeout)
        except asyncio.TimeoutError:
            return False
        return True

    async def release(self) -> None:
        """Release the lock."""
        self._lock.release()


class MemRedis:
    """In-memory Redis subset used by the matrix."""

    def __init__(self) -> None:
        self.rows: Dict[str, str] = {}
        self._locks: Dict[str, asyncio.Lock] = {}

    async def get(self, key: str) -> Optional[str]:
        """Return a value."""
        return self.rows.get(key)

    async def set(self, key: str, value: str, *, ex: Optional[int] = None) -> bool:
        """Store a value."""
        del ex
        self.rows[key] = value
        return True

    async def delete(self, *keys: str) -> int:
        """Delete values."""
        deleted = 0
        for key in keys:
            deleted += int(key in self.rows)
            self.rows.pop(key, None)
        return deleted

    async def scan_iter(self, match: str = "*") -> AsyncIterator[str]:
        """Yield matching keys."""
        for key in list(self.rows):
            if fnmatch.fnmatch(key, match):
                yield key

    def lock(
        self,
        name: str,
        *,
        timeout: Optional[float] = None,
        blocking_timeout: Optional[float] = None,
    ) -> _MemLock:
        """Return a named lock."""
        del timeout
        return _MemLock(self._locks.setdefault(name, asyncio.Lock()), blocking_timeout)


class FakeCredentialStore:
    """Durable in-memory credential store with failure injection."""

    def __init__(self) -> None:
        self.rows: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self.fail_next_save = False

    async def load(self, user_id: str, provider: str) -> Optional[Dict[str, Any]]:
        """Load a copied token payload."""
        payload = self.rows.get((user_id, provider))
        return dict(payload) if payload is not None else None

    async def save(
        self,
        user_id: str,
        provider: str,
        payload: Dict[str, Any],
        *,
        minted: bool,
        principal: Optional[Principal],
        state_payload: Optional[Dict[str, Any]],
    ) -> None:
        """Save a token payload or fail once."""
        del minted, principal, state_payload
        if self.fail_next_save:
            self.fail_next_save = False
            raise RuntimeError("durable store unavailable")
        self.rows[(user_id, provider)] = dict(payload)

    async def delete(self, user_id: str, provider: str) -> None:
        """Delete a token payload."""
        self.rows.pop((user_id, provider), None)


class FakePrincipalResolver:
    """Resolve channel identities to principals."""

    def __init__(self, principals: Dict[Tuple[str, str], Principal]) -> None:
        self.principals = principals

    async def resolve(self, channel: str, channel_user_id: str) -> Optional[Principal]:
        """Return the mapped principal, if present."""
        return self.principals.get((channel, channel_user_id))


class FakeManager(AbstractOAuth2Manager):
    """Scripted provider manager exercising the real base implementation."""

    provider_id = "fake"
    authorization_url = "https://idp.example/authorize"
    token_url = "https://idp.example/token"
    default_scopes = ["read"]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.exchange_payload: Dict[str, Any] = {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "expires_in": 3600,
            "scope": "read",
        }
        self.identity = {"id": "account-1", "display_name": "Test Account"}

    async def _exchange_code(self, code: str, code_verifier: Optional[str]) -> Dict[str, Any]:
        """Return a scripted token response."""
        del code, code_verifier
        return dict(self.exchange_payload)

    async def _refresh_request(self, refresh_token: str) -> Dict[str, Any]:
        """Return a scripted refresh response."""
        del refresh_token
        return dict(self.exchange_payload)

    async def _discover_identity(self, access_token: str) -> Dict[str, Any]:
        """Return a scripted provider identity."""
        del access_token
        return dict(self.identity)

    def _build_token_set(
        self,
        token_response: Dict[str, Any],
        identity: Dict[str, Any],
    ) -> AbstractOAuth2TokenSet:
        """Build the base token model."""
        now = time.time()
        return AbstractOAuth2TokenSet(
            access_token=token_response["access_token"],
            refresh_token=token_response.get("refresh_token", ""),
            expires_at=now + int(token_response.get("expires_in", 3600)),
            scopes=token_response.get("scope", "").split(),
            granted_at=now,
            last_refreshed_at=now,
            account_id=identity.get("id", ""),
            display_name=identity.get("display_name", ""),
        )


class _RecordingPublisher:
    """Record manager publications."""

    def __init__(self) -> None:
        self.calls: list[Any] = []

    async def publish(self, event: Any, state_payload: Optional[Dict[str, Any]] = None) -> None:
        """Record an event."""
        self.calls.append((event, state_payload or {}))


def _manager(
    *,
    store: Optional[FakeCredentialStore] = None,
    redis: Optional[MemRedis] = None,
    publisher: Any = None,
) -> FakeManager:
    """Construct a manager with isolated stores."""
    return FakeManager(
        "client",
        "https://idp.example/callback",
        client_secret="secret",
        redis_client=redis or MemRedis(),
        credential_store=store or FakeCredentialStore(),
        event_publisher=publisher,
    )


@pytest.mark.asyncio
async def test_cross_channel_reuse() -> None:
    """A Telegram connection resolves through web and A2A for one principal."""
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
    manager = _manager()
    _, nonce = await manager.create_authorization_url("telegram", "88123", principal=principal)
    await manager.handle_callback("code", nonce)
    credentials = OAuthCredentialResolver(manager, principal_resolver=resolver)

    web_token = await credentials.resolve("web", "1042")
    a2a_token = await credentials.resolve("a2a", "jlara@example.com")

    assert web_token is not None
    assert a2a_token is not None
    assert web_token.access_token == a2a_token.access_token


@pytest.mark.asyncio
async def test_isolation_between_principals() -> None:
    """A principal cannot resolve another principal's cached or durable token."""
    principal_a = Principal(user_id="1042", channel="telegram", channel_user_id="a")
    principal_b = Principal(user_id="2048", channel="telegram", channel_user_id="b")
    resolver = FakePrincipalResolver({("web", "a"): principal_a, ("web", "b"): principal_b})
    manager = _manager()
    _, nonce = await manager.create_authorization_url("telegram", "a", principal=principal_a)
    await manager.handle_callback("code", nonce)
    credentials = OAuthCredentialResolver(manager, principal_resolver=resolver)

    assert await credentials.resolve("web", "a") is not None
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr("parrot.auth.oauth2_base._legacy_window_open", lambda: False)
        assert await credentials.resolve("web", "b") is None


@pytest.mark.asyncio
async def test_unlinked_user_rejected() -> None:
    """An unknown channel identity fails closed without a channel-keyed fallback."""
    manager = _manager()
    credentials = OAuthCredentialResolver(manager, principal_resolver=FakePrincipalResolver({}))

    assert await credentials.resolve("telegram", "unknown") is None
    with pytest.raises(AuthorizationRequired, match="Link your account"):
        await credentials.get_auth_url("telegram", "unknown")


@pytest.mark.asyncio
async def test_callback_fails_without_durable_write() -> None:
    """A durable failure produces an error response and no cache or event."""
    store = FakeCredentialStore()
    store.fail_next_save = True
    redis = MemRedis()
    publisher = _RecordingPublisher()
    manager = _manager(store=store, redis=redis, publisher=publisher)
    principal = Principal(user_id="1042", channel="telegram", channel_user_id="88123")
    _, nonce = await manager.create_authorization_url("telegram", "88123", principal=principal)
    app = web.Application()
    app["oauth2_manager_fake"] = manager
    request = make_mocked_request("GET", f"/callback?code=code&state={nonce}", app=app)

    response = await make_oauth2_callback("fake")(request)

    assert response.status == 500
    assert await redis.get(manager._token_key(principal.user_id)) is None
    assert publisher.calls == []


@pytest.mark.asyncio
async def test_notifier_failure_does_not_fail_callback() -> None:
    """A failing channel notifier cannot fail durable callback completion."""
    registry = ChannelNotifierRegistry()

    class BrokenNotifier:
        """Notifier that simulates a channel outage."""

        channel = "telegram"

        async def notify(self, event: Any, state: Dict[str, Any]) -> None:
            del event, state
            raise RuntimeError("channel down")

    registry.register(BrokenNotifier())
    manager = _manager(publisher=ConnectionEventPublisher(notifiers=registry))
    principal = Principal(user_id="1042", channel="telegram", channel_user_id="88123")
    _, nonce = await manager.create_authorization_url("telegram", "88123", principal=principal)

    token_set, _ = await manager.handle_callback("code", nonce)

    assert token_set.account_id == "account-1"
    assert await manager.get_valid_token("telegram", principal.user_id) is not None
    ChannelNotifierRegistry._reset()


@pytest.mark.asyncio
async def test_credential_required_serialization() -> None:
    """CredentialRequired and AuthorizationRequired serialize as auth_required."""

    @tool
    async def authorization_tool() -> str:
        """Raise AuthorizationRequired."""
        raise AuthorizationRequired(
            tool_name="authorization_tool",
            message="Authorize Jira",
            provider="jira",
            auth_url="https://idp.example/authorize",
            scopes=["read:jira-work"],
        )

    @tool
    async def credential_tool() -> str:
        """Raise CredentialRequired."""
        raise CredentialRequired("jira", "https://idp.example/authorize", "oauth2")

    manager = ToolManager()
    manager.register_tool(authorization_tool)
    manager.register_tool(credential_tool)
    authorization_result = await manager.execute_tool("authorization_tool", {}, return_tool_result=True)
    credential_result = await manager.execute_tool("credential_tool", {}, return_tool_result=True)
    authorization_envelope = AuthRequiredEnvelope(**authorization_result.metadata)
    credential_envelope = AuthRequiredEnvelope(**credential_result.metadata)

    assert authorization_result.status == credential_result.status == "authorization_required"
    assert authorization_envelope.type == credential_envelope.type == "auth_required"
    assert authorization_envelope.provider == credential_envelope.provider == "jira"
    assert authorization_envelope.auth_url == credential_envelope.auth_url
    assert authorization_envelope.scopes == ["read:jira-work"]
