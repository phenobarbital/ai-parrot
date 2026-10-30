"""Shared fakes for FEAT-773 OAuth2 tests without a Redis dependency."""

from __future__ import annotations

import asyncio
import fnmatch
import time
from typing import Any, AsyncIterator, Dict, Optional, Tuple

from parrot.auth.oauth2_base import AbstractOAuth2Manager, AbstractOAuth2TokenSet
from parrot.auth.principal import Principal


class _MemLock:
    """Small async lock adapter matching the Redis lock methods used by the manager."""

    def __init__(self, lock: asyncio.Lock, blocking_timeout: Optional[float]) -> None:
        self._lock = lock
        self._blocking_timeout = blocking_timeout

    async def acquire(self) -> bool:
        """Acquire within the configured blocking timeout."""
        if self._blocking_timeout is None:
            await self._lock.acquire()
            return True
        try:
            await asyncio.wait_for(self._lock.acquire(), timeout=self._blocking_timeout)
        except asyncio.TimeoutError:
            return False
        return True

    async def release(self) -> None:
        """Release the lock."""
        self._lock.release()


class MemRedis:
    """In-memory subset of Redis used by the OAuth2 manager."""

    def __init__(self) -> None:
        self.rows: Dict[str, str] = {}
        self._locks: Dict[str, asyncio.Lock] = {}

    async def get(self, key: str) -> Optional[str]:
        """Return a stored value."""
        return self.rows.get(key)

    async def set(self, key: str, value: str, *, ex: Optional[int] = None) -> bool:
        """Store a value; expiry is intentionally ignored."""
        del ex
        self.rows[key] = value
        return True

    async def delete(self, *keys: str) -> int:
        """Delete keys and return the number that existed."""
        deleted = 0
        for key in keys:
            if key in self.rows:
                deleted += 1
                del self.rows[key]
        return deleted

    async def scan_iter(self, match: str = "*") -> AsyncIterator[str]:
        """Yield keys matching a Redis-style glob."""
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
        """Return a named async lock."""
        del timeout
        return _MemLock(self._locks.setdefault(name, asyncio.Lock()), blocking_timeout)


class FakeCredentialStore:
    """In-memory credential store with failure injection and call recording."""

    def __init__(self) -> None:
        self.rows: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self.calls: list[Tuple[str, str, str]] = []
        self.fail_next_save = False

    async def load(self, user_id: str, provider: str) -> Optional[Dict[str, Any]]:
        """Load a copied payload when present."""
        self.calls.append(("load", user_id, provider))
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
        """Save a copied payload or raise once when requested."""
        del minted, principal, state_payload
        self.calls.append(("save", user_id, provider))
        if self.fail_next_save:
            self.fail_next_save = False
            raise RuntimeError("scripted durable-store failure")
        self.rows[(user_id, provider)] = dict(payload)

    async def delete(self, user_id: str, provider: str) -> None:
        """Delete a payload."""
        self.calls.append(("delete", user_id, provider))
        self.rows.pop((user_id, provider), None)


class FakePrincipalResolver:
    """Map channel identities to principals for resolver tests."""

    def __init__(self, principals: Optional[Dict[Tuple[str, str], Principal]] = None) -> None:
        self.principals = principals or {}

    async def resolve(self, channel: str, channel_user_id: str) -> Optional[Principal]:
        """Return the mapped principal, if any."""
        return self.principals.get((channel, channel_user_id))


class FakeManager(AbstractOAuth2Manager):
    """Concrete OAuth manager with scripted provider hooks."""

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
        self.refresh_result: Any = dict(self.exchange_payload)
        self.identity: Dict[str, Any] = {"id": "account-1", "display_name": "Test Account"}
        self.exchange_calls: list[Tuple[str, Optional[str]]] = []

    async def _exchange_code(self, code: str, code_verifier: Optional[str]) -> Dict[str, Any]:
        self.exchange_calls.append((code, code_verifier))
        return dict(self.exchange_payload)

    async def _refresh_request(self, refresh_token: str) -> Dict[str, Any]:
        del refresh_token
        if isinstance(self.refresh_result, Exception):
            raise self.refresh_result
        return dict(self.refresh_result)

    async def _discover_identity(self, access_token: str) -> Dict[str, Any]:
        del access_token
        return dict(self.identity)

    def _build_token_set(
        self,
        token_response: Dict[str, Any],
        identity: Dict[str, Any],
    ) -> AbstractOAuth2TokenSet:
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
