# TASK-751: JiraOAuthManager — OAuth 2.0 (3LO) Lifecycle

**Feature**: FEAT-107 — Jira OAuth 2.0 (3LO) Per-User Authentication
**Spec**: `sdd/specs/FEAT-107-jira-oauth2-3lo.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-747, TASK-748
**Assigned-to**: unassigned

---

## Context

Module 5 of the spec. This is the core OAuth implementation. `JiraOAuthManager` handles the complete Atlassian OAuth 2.0 (3LO) lifecycle: generating authorization URLs with CSRF state nonces, exchanging codes for tokens, discovering the cloud_id via accessible-resources, resolving user identity via /myself, storing/retrieving tokens from Redis, and handling Atlassian's rotating refresh tokens with distributed locking.

---

## Scope

- Create `JiraTokenSet` Pydantic model for per-user token storage.
- Create `JiraOAuthManager` class with:
  - `create_authorization_url(channel, user_id, extra_state)` → `(url, nonce)`
  - `handle_callback(code, state)` → `JiraTokenSet`
  - `get_valid_token(channel, user_id)` → `Optional[JiraTokenSet]`
  - `_refresh_tokens(key, token_set)` → `JiraTokenSet` (with Redis distributed lock)
  - `revoke(channel, user_id)` → `None`
  - `is_connected(channel, user_id)` → `bool`
- Redis key patterns: `jira:oauth:{channel}:{user_id}` for tokens, `jira:nonce:{nonce}` for CSRF state.
- Write unit tests with mocked httpx and Redis.

**NOT in scope**: HTTP callback routes (TASK-752), CredentialResolver wrapping (TASK-750), JiraToolkit integration (TASK-753).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/jira_oauth.py` | CREATE | JiraOAuthManager + JiraTokenSet |
| `packages/ai-parrot/tests/unit/test_jira_oauth_manager.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, Field  # standard
import httpx  # verified: used in codebase (e.g. parrot/clients/)
import redis.asyncio as aioredis  # verified: used in parrot/memory/
import time
import secrets
import json
```

### Existing Patterns to Follow
```python
# Redis usage pattern from parrot/memory/ — async Redis client
# Example key pattern: "jira:oauth:telegram:12345"
# Token TTL: 90 days (7_776_000 seconds)
# Nonce TTL: 10 minutes (600 seconds)
```

### Does NOT Exist
- ~~`parrot.auth.jira_oauth`~~ — module does NOT exist yet (this task creates it)
- ~~`JiraOAuthManager`~~ — does NOT exist yet (this task creates it)
- ~~`JiraTokenSet`~~ — does NOT exist yet (this task creates it)

---

## Implementation Notes

### JiraTokenSet Model
```python
class JiraTokenSet(BaseModel):
    access_token: str
    refresh_token: str
    expires_at: float  # epoch timestamp
    cloud_id: str
    site_url: str  # https://mysite.atlassian.net
    account_id: str
    display_name: str
    email: Optional[str] = None
    scopes: list[str] = []
    granted_at: float = 0
    last_refreshed_at: float = 0
    available_sites: list[dict] = []

    @property
    def is_expired(self) -> bool:
        return time.time() >= (self.expires_at - 60)

    @property
    def api_base_url(self) -> str:
        return f"https://api.atlassian.com/ex/jira/{self.cloud_id}"
```

### Atlassian OAuth 2.0 (3LO) Endpoints
- Authorization: `https://auth.atlassian.com/authorize`
- Token: `https://auth.atlassian.com/oauth/token`
- Accessible resources: `https://api.atlassian.com/oauth/token/accessible-resources`
- User identity: `{api_base_url}/rest/api/3/myself`

### State Nonce CSRF Flow
1. Generate `nonce = secrets.token_urlsafe(32)`
2. Store in Redis: `jira:nonce:{nonce}` → `{"channel": ..., "user_id": ..., "extra": ...}` with TTL 600s
3. Build authorization URL with `state=nonce`
4. On callback: retrieve and DELETE nonce from Redis (one-time use)
5. If nonce missing/expired → reject

### Rotating Refresh Token — Race Condition Mitigation
```python
async def _refresh_tokens(self, key: str, token_set: JiraTokenSet) -> JiraTokenSet:
    lock = self.redis.lock(f"lock:jira:refresh:{key}", timeout=10, blocking_timeout=5)
    async with lock:
        # Re-read from Redis (another request may have refreshed already)
        fresh = await self._read_token(key)
        if fresh and not fresh.is_expired:
            return fresh
        # Actually refresh
        response = await self._http.post(TOKEN_URL, data={
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": token_set.refresh_token,
        })
        # ... parse, update token_set, store in Redis
```

### Key Constraints
- Use `httpx.AsyncClient` for all HTTP calls.
- Token TTL in Redis: 90 days. Extended on each successful refresh.
- Failed refresh (401 from Atlassian) should delete the token and raise `PermissionError`.
- `create_authorization_url` must include `prompt=consent` for first-time and `audience=api.atlassian.com`.

---

## Acceptance Criteria

- [ ] `JiraTokenSet` model with `is_expired`, `api_base_url` properties
- [ ] `create_authorization_url()` generates valid URL with CSRF nonce in Redis
- [ ] `handle_callback()` exchanges code, discovers cloud_id, resolves user, stores tokens
- [ ] `get_valid_token()` returns tokens from Redis, auto-refreshes if expired
- [ ] Rotating refresh tokens handled with Redis distributed lock
- [ ] Failed refresh (401) deletes tokens and raises `PermissionError`
- [ ] `revoke()` deletes tokens from Redis
- [ ] CSRF nonce is single-use (deleted after callback)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/test_jira_oauth_manager.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/test_jira_oauth_manager.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.auth.jira_oauth import JiraOAuthManager, JiraTokenSet


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock()
    redis.delete = AsyncMock()
    redis.lock = MagicMock()
    return redis


@pytest.fixture
def manager(mock_redis):
    return JiraOAuthManager(
        client_id="test-client-id",
        client_secret="test-secret",
        redirect_uri="https://test.example.com/callback",
        redis_client=mock_redis,
    )


class TestJiraTokenSet:
    def test_is_expired_true(self):
        ts = JiraTokenSet(
            access_token="at", refresh_token="rt",
            expires_at=0, cloud_id="c", site_url="https://x.atlassian.net",
            account_id="a", display_name="Test",
        )
        assert ts.is_expired is True

    def test_api_base_url(self):
        ts = JiraTokenSet(
            access_token="at", refresh_token="rt",
            expires_at=9999999999, cloud_id="abc-123",
            site_url="https://x.atlassian.net",
            account_id="a", display_name="Test",
        )
        assert ts.api_base_url == "https://api.atlassian.com/ex/jira/abc-123"


class TestJiraOAuthManager:
    @pytest.mark.asyncio
    async def test_create_authorization_url(self, manager, mock_redis):
        url, nonce = await manager.create_authorization_url("telegram", "user-1")
        assert "auth.atlassian.com/authorize" in url
        assert "client_id=test-client-id" in url
        assert nonce
        mock_redis.set.assert_awaited_once()  # nonce stored

    @pytest.mark.asyncio
    async def test_state_nonce_stored_with_ttl(self, manager, mock_redis):
        _, nonce = await manager.create_authorization_url("tg", "u1")
        call_args = mock_redis.set.call_args
        assert "jira:nonce:" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_get_valid_token_returns_none_when_empty(self, manager, mock_redis):
        mock_redis.get.return_value = None
        result = await manager.get_valid_token("tg", "u1")
        assert result is None

    @pytest.mark.asyncio
    async def test_revoke_deletes_key(self, manager, mock_redis):
        await manager.revoke("telegram", "user-1")
        mock_redis.delete.assert_awaited()

    @pytest.mark.asyncio
    async def test_is_connected_false(self, manager, mock_redis):
        mock_redis.get.return_value = None
        assert await manager.is_connected("tg", "u1") is False
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-107-jira-oauth2-3lo.spec.md` Sections 2, 7
2. **Check dependencies** — verify TASK-747 and TASK-748 are in `tasks/completed/`
3. **Verify the Codebase Contract** — check how Redis is used in `parrot/memory/`
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-751-jira-oauth-manager.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Opus)
**Date**: 2026-04-17
**Notes**:
- Created ``parrot.auth.jira_oauth`` with ``JiraTokenSet`` (Pydantic model
  with ``is_expired`` and ``api_base_url`` properties) and
  ``JiraOAuthManager``.
- ``create_authorization_url`` persists the CSRF nonce under
  ``jira:nonce:<nonce>`` with a 10-minute TTL; URL includes ``prompt=consent``
  and ``audience=api.atlassian.com``.
- ``handle_callback`` validates the nonce (single-use delete), exchanges the
  code, discovers ``cloud_id`` via ``accessible-resources``, resolves the
  user via ``/rest/api/3/myself``, and stores the token with 90-day TTL.
- ``get_valid_token`` triggers ``_refresh_tokens`` transparently when the
  token is expired.  Refresh uses a Redis distributed lock so concurrent
  refreshes don't invalidate each other (Atlassian rotates refresh tokens).
  A 401 on refresh revokes the token and raises ``PermissionError``.
- Tests: ``packages/ai-parrot/tests/unit/test_jira_oauth_manager.py`` —
  15 passing with HTTP and Redis mocked.

**Deviations from spec**: none
