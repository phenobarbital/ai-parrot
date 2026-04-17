# TASK-750: CredentialResolver Abstraction

**Feature**: FEAT-107 — Jira OAuth 2.0 (3LO) Per-User Authentication
**Spec**: `sdd/specs/FEAT-107-jira-oauth2-3lo.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-751
**Assigned-to**: unassigned

---

## Context

Module 4 of the spec. The `CredentialResolver` is the bridge between a toolkit and its credential storage. It abstracts whether credentials come from a static config (legacy) or from per-user OAuth tokens in Redis. This separation lets `JiraToolkit` call `resolver.resolve(channel, user_id)` without knowing the auth strategy.

---

## Scope

- Create `CredentialResolver` ABC with `resolve(channel, user_id)` and `get_auth_url(channel, user_id)`.
- Create `OAuthCredentialResolver` that wraps `JiraOAuthManager`.
- Create `StaticCredentialResolver` that returns fixed credentials (for basic_auth/token_auth mode).
- Write unit tests.

**NOT in scope**: `JiraOAuthManager` implementation (TASK-751), JiraToolkit integration (TASK-753), callback routes (TASK-752).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/credentials.py` | CREATE | CredentialResolver ABC + implementations |
| `packages/ai-parrot/src/parrot/auth/__init__.py` | MODIFY | Export CredentialResolver, OAuthCredentialResolver, StaticCredentialResolver |
| `packages/ai-parrot/tests/unit/test_credential_resolver.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.permission import PermissionContext, UserSession  # verified: packages/ai-parrot/src/parrot/auth/permission.py
from parrot.auth.resolver import AbstractPermissionResolver  # verified: packages/ai-parrot/src/parrot/auth/resolver.py:25
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/resolver.py:25
class AbstractPermissionResolver(ABC):
    # Pattern to follow for CredentialResolver (ABC with async abstract methods)

# packages/ai-parrot/src/parrot/auth/__init__.py — exports:
# UserSession, PermissionContext, AbstractPermissionResolver,
# DefaultPermissionResolver, AllowAllResolver, DenyAllResolver,
# PBACPermissionResolver, setup_pbac, PolicyRuleConfig
```

### Does NOT Exist
- ~~`parrot.auth.credentials`~~ — module does NOT exist yet (this task creates it)
- ~~`CredentialResolver`~~ — does NOT exist yet (this task creates it)
- ~~`OAuthCredentialResolver`~~ — does NOT exist yet (this task creates it)
- ~~`StaticCredentialResolver`~~ — does NOT exist yet (this task creates it)
- ~~`JiraOAuthManager`~~ — does NOT exist yet (TASK-751 creates it); this task uses it via TYPE_CHECKING

---

## Implementation Notes

### Design
```python
# packages/ai-parrot/src/parrot/auth/credentials.py
from abc import ABC, abstractmethod
from typing import Any, Optional, TYPE_CHECKING
from dataclasses import dataclass

if TYPE_CHECKING:
    from .jira_oauth import JiraOAuthManager


class CredentialResolver(ABC):
    """Resolves credentials for a given user and channel."""

    @abstractmethod
    async def resolve(self, channel: str, user_id: str) -> Optional[Any]:
        """Return credentials or None if user hasn't authorized."""
        ...

    @abstractmethod
    async def get_auth_url(self, channel: str, user_id: str) -> str:
        """Generate authorization URL for the user."""
        ...

    async def is_connected(self, channel: str, user_id: str) -> bool:
        """Check if user has valid credentials."""
        return (await self.resolve(channel, user_id)) is not None


class OAuthCredentialResolver(CredentialResolver):
    """Resolves credentials from OAuth token store (Redis)."""

    def __init__(self, oauth_manager: "JiraOAuthManager"):
        self._manager = oauth_manager

    async def resolve(self, channel: str, user_id: str) -> Optional[Any]:
        return await self._manager.get_valid_token(channel, user_id)

    async def get_auth_url(self, channel: str, user_id: str) -> str:
        url, _ = await self._manager.create_authorization_url(channel, user_id)
        return url


@dataclass
class StaticCredentials:
    server_url: str
    username: Optional[str] = None
    password: Optional[str] = None
    token: Optional[str] = None
    auth_type: str = "basic_auth"


class StaticCredentialResolver(CredentialResolver):
    """Returns static credentials (legacy basic_auth/token_auth)."""

    def __init__(self, server_url: str, username: str = None, password: str = None,
                 token: str = None, auth_type: str = "basic_auth"):
        self._creds = StaticCredentials(
            server_url=server_url, username=username, password=password,
            token=token, auth_type=auth_type,
        )

    async def resolve(self, channel: str, user_id: str) -> StaticCredentials:
        return self._creds

    async def get_auth_url(self, channel: str, user_id: str) -> str:
        raise NotImplementedError("Static credentials do not require authorization")
```

### Key Constraints
- `OAuthCredentialResolver` uses TYPE_CHECKING import for `JiraOAuthManager` (created by TASK-751, which this task depends on).
- The ABC must be generic enough for future OAuth providers (GitHub, O365).
- `StaticCredentialResolver` always returns credentials (never None) — it represents the legacy mode.

---

## Acceptance Criteria

- [ ] `CredentialResolver` ABC exists with `resolve()`, `get_auth_url()`, `is_connected()`
- [ ] `OAuthCredentialResolver` wraps a manager's `get_valid_token` and `create_authorization_url`
- [ ] `StaticCredentialResolver` always returns fixed credentials
- [ ] `StaticCredentialResolver.get_auth_url()` raises `NotImplementedError`
- [ ] All types exported from `parrot.auth`
- [ ] Tests pass: `pytest packages/ai-parrot/tests/unit/test_credential_resolver.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/test_credential_resolver.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.auth.credentials import (
    CredentialResolver,
    OAuthCredentialResolver,
    StaticCredentialResolver,
    StaticCredentials,
)


class TestStaticCredentialResolver:
    @pytest.mark.asyncio
    async def test_always_returns_credentials(self):
        resolver = StaticCredentialResolver(
            server_url="https://jira.example.com",
            username="bot",
            password="secret",
        )
        creds = await resolver.resolve("telegram", "user-1")
        assert isinstance(creds, StaticCredentials)
        assert creds.server_url == "https://jira.example.com"

    @pytest.mark.asyncio
    async def test_is_connected_always_true(self):
        resolver = StaticCredentialResolver(server_url="https://jira.example.com")
        assert await resolver.is_connected("any", "any") is True

    @pytest.mark.asyncio
    async def test_get_auth_url_raises(self):
        resolver = StaticCredentialResolver(server_url="https://jira.example.com")
        with pytest.raises(NotImplementedError):
            await resolver.get_auth_url("telegram", "user-1")


class TestOAuthCredentialResolver:
    @pytest.mark.asyncio
    async def test_resolve_delegates_to_manager(self):
        manager = MagicMock()
        token = MagicMock()
        manager.get_valid_token = AsyncMock(return_value=token)
        resolver = OAuthCredentialResolver(oauth_manager=manager)
        result = await resolver.resolve("telegram", "user-123")
        assert result == token
        manager.get_valid_token.assert_awaited_once_with("telegram", "user-123")

    @pytest.mark.asyncio
    async def test_resolve_returns_none_when_no_token(self):
        manager = MagicMock()
        manager.get_valid_token = AsyncMock(return_value=None)
        resolver = OAuthCredentialResolver(oauth_manager=manager)
        result = await resolver.resolve("telegram", "user-123")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_auth_url(self):
        manager = MagicMock()
        manager.create_authorization_url = AsyncMock(return_value=("https://auth.url", "nonce"))
        resolver = OAuthCredentialResolver(oauth_manager=manager)
        url = await resolver.get_auth_url("telegram", "user-123")
        assert url == "https://auth.url"

    @pytest.mark.asyncio
    async def test_is_connected_false_when_no_token(self):
        manager = MagicMock()
        manager.get_valid_token = AsyncMock(return_value=None)
        resolver = OAuthCredentialResolver(oauth_manager=manager)
        assert await resolver.is_connected("tg", "u1") is False
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-107-jira-oauth2-3lo.spec.md` for full context
2. **Check dependencies** — verify TASK-751 is in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm `parrot.auth.__init__` exports
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-750-credential-resolver-abstraction.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any
