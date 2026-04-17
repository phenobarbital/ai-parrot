"""Unit tests for :class:`JiraOAuthManager` and :class:`JiraTokenSet`.

Covers TASK-751 from FEAT-107 (Jira OAuth 2.0 3LO). The HTTP layer and
Redis are mocked so the tests run without any external services.
"""
from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.auth.jira_oauth import (
    AUTHORIZATION_URL,
    JiraOAuthManager,
    JiraTokenSet,
)


# ------------------------------------------------------------------ helpers

def _mock_response(
    status: int,
    json_data: Any = None,
    text_data: str = "",
) -> MagicMock:
    """Build a mock aiohttp response that works as an async context manager."""
    resp = MagicMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_data if json_data is not None else {})
    resp.text = AsyncMock(return_value=text_data)
    # Support ``async with session.post(...) as response:``
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)
    return resp


def _mock_session(*responses: MagicMock) -> MagicMock:
    """Return a mock aiohttp.ClientSession where post/get return successive responses."""
    session = MagicMock()
    session.closed = False  # prevents _get_session() from recreating it
    it = iter(responses)

    def _next_response(*args, **kwargs):
        try:
            return next(it)
        except StopIteration:
            return responses[-1]  # repeat last

    session.post.side_effect = _next_response
    session.get.side_effect = _next_response
    return session


# ------------------------------------------------------------------ fakes

class _FakeRedis:
    """Minimal in-memory Redis double that mimics the async API we use."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.deleted: list[str] = []
        self.set_calls: list[tuple] = []
        self.lock_mock = MagicMock()
        self._lock_released = False

    async def get(self, key: str):
        return self.store.get(key)

    async def set(self, key: str, value, ex: int | None = None):
        self.store[key] = value
        self.set_calls.append((key, value, ex))
        return True

    async def delete(self, *keys: str):
        removed = 0
        for key in keys:
            if key in self.store:
                del self.store[key]
                removed += 1
            self.deleted.append(key)
        return removed

    def lock(self, name: str, timeout: int = 10, blocking_timeout: int = 5):
        async def _acquire() -> bool:
            return True

        async def _release() -> None:
            self._lock_released = True

        lock = MagicMock()
        lock.name = name
        lock.acquire = _acquire
        lock.release = _release
        self.lock_mock(name, timeout=timeout, blocking_timeout=blocking_timeout)
        return lock


@pytest.fixture
def fake_redis() -> _FakeRedis:
    return _FakeRedis()


@pytest.fixture
def manager(fake_redis: _FakeRedis) -> JiraOAuthManager:
    return JiraOAuthManager(
        client_id="test-client-id",
        client_secret="test-secret",
        redirect_uri="https://test.example.com/api/auth/jira/callback",
        redis_client=fake_redis,
    )


class TestJiraTokenSet:
    def test_is_expired_true_for_past(self) -> None:
        ts = JiraTokenSet(
            access_token="at",
            refresh_token="rt",
            expires_at=0.0,
            cloud_id="c",
            site_url="https://x.atlassian.net",
            account_id="a",
            display_name="Test",
        )
        assert ts.is_expired is True

    def test_is_expired_false_for_future(self) -> None:
        ts = JiraTokenSet(
            access_token="at",
            refresh_token="rt",
            expires_at=time.time() + 3600,
            cloud_id="c",
            site_url="https://x.atlassian.net",
            account_id="a",
            display_name="Test",
        )
        assert ts.is_expired is False

    def test_api_base_url(self) -> None:
        ts = JiraTokenSet(
            access_token="at",
            refresh_token="rt",
            expires_at=9999999999,
            cloud_id="abc-123",
            site_url="https://x.atlassian.net",
            account_id="a",
            display_name="Test",
        )
        assert ts.api_base_url == "https://api.atlassian.com/ex/jira/abc-123"


class TestAuthorizationURL:
    @pytest.mark.asyncio
    async def test_create_authorization_url(
        self, manager: JiraOAuthManager, fake_redis: _FakeRedis
    ) -> None:
        url, nonce = await manager.create_authorization_url("telegram", "user-1")
        assert AUTHORIZATION_URL in url
        assert "client_id=test-client-id" in url
        assert "redirect_uri=https" in url
        assert f"state={nonce}" in url
        assert "prompt=consent" in url
        assert "audience=api.atlassian.com" in url
        assert nonce and len(nonce) > 10

    @pytest.mark.asyncio
    async def test_state_nonce_stored_with_ttl(
        self, manager: JiraOAuthManager, fake_redis: _FakeRedis
    ) -> None:
        _, nonce = await manager.create_authorization_url("tg", "u1")
        assert fake_redis.set_calls, "Expected nonce to be written to Redis"
        key, value, ttl = fake_redis.set_calls[0]
        assert key == f"jira:nonce:{nonce}"
        assert ttl == 10 * 60  # 10 minutes
        payload = json.loads(value)
        assert payload["channel"] == "tg"
        assert payload["user_id"] == "u1"

    @pytest.mark.asyncio
    async def test_extra_state_is_preserved(
        self, manager: JiraOAuthManager, fake_redis: _FakeRedis
    ) -> None:
        _, nonce = await manager.create_authorization_url(
            "tg", "u1", extra_state={"chat_id": 42}
        )
        payload = json.loads(fake_redis.store[f"jira:nonce:{nonce}"])
        assert payload["extra"] == {"chat_id": 42}


class TestHandleCallback:
    @pytest.mark.asyncio
    async def test_invalid_state_raises(
        self, manager: JiraOAuthManager, fake_redis: _FakeRedis
    ) -> None:
        with pytest.raises(ValueError, match="Invalid or expired state nonce"):
            await manager.handle_callback(code="abc", state="unknown")

    @pytest.mark.asyncio
    async def test_full_exchange_stores_token(
        self, manager: JiraOAuthManager, fake_redis: _FakeRedis
    ) -> None:
        # Seed a valid nonce first.
        _, nonce = await manager.create_authorization_url("telegram", "user-7")
        fake_redis.set_calls.clear()

        # Build aiohttp-style mock responses for the 3 HTTP calls:
        # 1. POST /oauth/token (exchange code)
        exchange_resp = _mock_response(200, json_data={
            "access_token": "at_123",
            "refresh_token": "rt_456",
            "expires_in": 3600,
            "scope": "read:jira-work write:jira-work offline_access",
        })
        # 2. GET /oauth/token/accessible-resources
        resources_resp = _mock_response(200, json_data=[
            {
                "id": "cloud-uuid-1",
                "name": "mysite",
                "url": "https://mysite.atlassian.net",
                "scopes": ["read:jira-work"],
            }
        ])
        # 3. GET /rest/api/3/myself
        myself_resp = _mock_response(200, json_data={
            "accountId": "acc-123",
            "displayName": "Jesus Garcia",
            "emailAddress": "jesus@example.com",
        })

        manager._http = _mock_session(exchange_resp, resources_resp, myself_resp)

        token, state_payload = await manager.handle_callback(code="auth-code", state=nonce)

        assert isinstance(token, JiraTokenSet)
        assert token.access_token == "at_123"
        assert token.refresh_token == "rt_456"
        assert token.cloud_id == "cloud-uuid-1"
        assert token.site_url == "https://mysite.atlassian.net"
        assert token.display_name == "Jesus Garcia"
        assert token.email == "jesus@example.com"
        assert "offline_access" in token.scopes

        # state_payload should contain channel and user_id
        assert state_payload["channel"] == "telegram"
        assert state_payload["user_id"] == "user-7"

        # Nonce deleted after use.
        assert f"jira:nonce:{nonce}" in fake_redis.deleted
        # Token persisted under the per-user key with 90-day TTL.
        assert fake_redis.set_calls, "Expected token set in Redis"
        key, _, ttl = fake_redis.set_calls[-1]
        assert key == "jira:oauth:telegram:user-7"
        assert ttl == 90 * 24 * 60 * 60


class TestGetValidToken:
    @pytest.mark.asyncio
    async def test_returns_none_when_empty(
        self, manager: JiraOAuthManager
    ) -> None:
        assert await manager.get_valid_token("tg", "u1") is None

    @pytest.mark.asyncio
    async def test_returns_cached_token_when_not_expired(
        self, manager: JiraOAuthManager, fake_redis: _FakeRedis
    ) -> None:
        token = JiraTokenSet(
            access_token="at",
            refresh_token="rt",
            expires_at=time.time() + 3600,
            cloud_id="c",
            site_url="https://x.atlassian.net",
            account_id="a",
            display_name="Test",
        )
        fake_redis.store["jira:oauth:tg:u1"] = token.model_dump_json()

        result = await manager.get_valid_token("tg", "u1")
        assert result is not None
        assert result.access_token == "at"

    @pytest.mark.asyncio
    async def test_refresh_on_expired_token(
        self, manager: JiraOAuthManager, fake_redis: _FakeRedis
    ) -> None:
        expired = JiraTokenSet(
            access_token="old",
            refresh_token="rt_old",
            expires_at=time.time() - 10,
            cloud_id="c",
            site_url="https://x.atlassian.net",
            account_id="a",
            display_name="Test",
        )
        fake_redis.store["jira:oauth:tg:u1"] = expired.model_dump_json()

        refresh_resp = _mock_response(200, json_data={
            "access_token": "new",
            "refresh_token": "rt_new",
            "expires_in": 3600,
        })
        manager._http = _mock_session(refresh_resp)

        refreshed = await manager.get_valid_token("tg", "u1")
        assert refreshed is not None
        assert refreshed.access_token == "new"
        assert refreshed.refresh_token == "rt_new"
        # Rotating refresh token must be persisted in Redis.
        stored = JiraTokenSet.model_validate_json(
            fake_redis.store["jira:oauth:tg:u1"]
        )
        assert stored.refresh_token == "rt_new"

    @pytest.mark.asyncio
    async def test_refresh_401_revokes_and_raises(
        self, manager: JiraOAuthManager, fake_redis: _FakeRedis
    ) -> None:
        expired = JiraTokenSet(
            access_token="old",
            refresh_token="rt_old",
            expires_at=time.time() - 10,
            cloud_id="c",
            site_url="https://x.atlassian.net",
            account_id="a",
            display_name="Test",
        )
        fake_redis.store["jira:oauth:tg:u1"] = expired.model_dump_json()

        bad_resp = _mock_response(401, text_data="refresh token rejected")
        manager._http = _mock_session(bad_resp)

        with pytest.raises(PermissionError, match="re-authorize"):
            await manager.get_valid_token("tg", "u1")

        assert "jira:oauth:tg:u1" not in fake_redis.store

    @pytest.mark.asyncio
    async def test_refresh_lock_not_acquired_re_reads_fresh_token(
        self, manager: JiraOAuthManager, fake_redis: _FakeRedis
    ) -> None:
        """When lock.acquire() returns False, the manager re-reads the token."""
        expired = JiraTokenSet(
            access_token="old",
            refresh_token="rt_old",
            expires_at=time.time() - 10,
            cloud_id="c",
            site_url="https://x.atlassian.net",
            account_id="a",
            display_name="Test",
        )
        fake_redis.store["jira:oauth:tg:u1"] = expired.model_dump_json()

        def patched_lock(name, **kwargs):
            lock = MagicMock()
            lock.acquire = AsyncMock(return_value=False)
            return lock

        fake_redis.lock = patched_lock

        # Simulate another process having refreshed the token in Redis
        fresh = expired.model_copy(update={
            "access_token": "refreshed_by_other",
            "expires_at": time.time() + 3600,
        })
        fake_redis.store["jira:oauth:tg:u1"] = fresh.model_dump_json()

        result = await manager.get_valid_token("tg", "u1")
        assert result is not None
        assert result.access_token == "refreshed_by_other"

    @pytest.mark.asyncio
    async def test_refresh_lock_not_acquired_raises_when_still_expired(
        self, manager: JiraOAuthManager, fake_redis: _FakeRedis
    ) -> None:
        """Lock not acquired + token still expired → PermissionError."""
        expired = JiraTokenSet(
            access_token="old",
            refresh_token="rt_old",
            expires_at=time.time() - 10,
            cloud_id="c",
            site_url="https://x.atlassian.net",
            account_id="a",
            display_name="Test",
        )
        fake_redis.store["jira:oauth:tg:u1"] = expired.model_dump_json()

        def patched_lock(name, **kwargs):
            lock = MagicMock()
            lock.acquire = AsyncMock(return_value=False)
            return lock

        fake_redis.lock = patched_lock

        with pytest.raises(PermissionError, match="lock unavailable"):
            await manager.get_valid_token("tg", "u1")


class TestRevokeAndIsConnected:
    @pytest.mark.asyncio
    async def test_revoke_deletes_key(
        self, manager: JiraOAuthManager, fake_redis: _FakeRedis
    ) -> None:
        fake_redis.store["jira:oauth:telegram:user-1"] = "x"
        await manager.revoke("telegram", "user-1")
        assert "jira:oauth:telegram:user-1" not in fake_redis.store
        assert "jira:oauth:telegram:user-1" in fake_redis.deleted

    @pytest.mark.asyncio
    async def test_is_connected_false(
        self, manager: JiraOAuthManager
    ) -> None:
        assert await manager.is_connected("tg", "u1") is False

    @pytest.mark.asyncio
    async def test_is_connected_true(
        self, manager: JiraOAuthManager, fake_redis: _FakeRedis
    ) -> None:
        token = JiraTokenSet(
            access_token="at",
            refresh_token="rt",
            expires_at=time.time() + 3600,
            cloud_id="c",
            site_url="https://x.atlassian.net",
            account_id="a",
            display_name="Test",
        )
        fake_redis.store["jira:oauth:tg:u1"] = token.model_dump_json()
        assert await manager.is_connected("tg", "u1") is True
