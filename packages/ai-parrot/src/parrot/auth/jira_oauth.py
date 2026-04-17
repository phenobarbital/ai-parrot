"""Jira OAuth 2.0 (3LO) manager for per-user authentication.

This module implements the complete Atlassian OAuth 2.0 (3LO) lifecycle
for per-user Jira access:

- Generate authorization URLs with CSRF state nonces.
- Exchange authorization codes for tokens.
- Discover ``cloud_id`` via the ``accessible-resources`` endpoint.
- Resolve user identity via ``/rest/api/3/myself``.
- Store and retrieve tokens from Redis, keyed by ``channel:user_id``.
- Handle Atlassian's rotating refresh tokens with a Redis distributed
  lock to avoid losing tokens when two requests refresh concurrently.

The manager never holds credentials in memory — everything flows through
Redis so the HTTP callback process and the agent session can share state.
"""
from __future__ import annotations

import json
import logging
import secrets
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

import aiohttp
from pydantic import BaseModel, Field


# Atlassian OAuth 2.0 (3LO) endpoints.
AUTHORIZATION_URL = "https://auth.atlassian.com/authorize"
TOKEN_URL = "https://auth.atlassian.com/oauth/token"
ACCESSIBLE_RESOURCES_URL = "https://api.atlassian.com/oauth/token/accessible-resources"

# Redis key prefixes.
_TOKEN_KEY_PREFIX = "jira:oauth"       # jira:oauth:{channel}:{user_id}
_NONCE_KEY_PREFIX = "jira:nonce"       # jira:nonce:{nonce}
_LOCK_KEY_PREFIX = "lock:jira:refresh"  # lock:jira:refresh:{channel}:{user_id}

# TTLs.
_TOKEN_TTL_SECONDS = 90 * 24 * 60 * 60  # 90 days
_NONCE_TTL_SECONDS = 10 * 60            # 10 minutes
_REFRESH_LOCK_TIMEOUT = 10              # seconds
_REFRESH_LOCK_BLOCKING_TIMEOUT = 5      # seconds

# Default scopes for Jira 3LO integrations.
DEFAULT_SCOPES: List[str] = [
    "read:jira-work",
    "write:jira-work",
    "read:jira-user",
    "offline_access",
]


logger = logging.getLogger(__name__)


class JiraTokenSet(BaseModel):
    """Per-user Jira OAuth 2.0 token set persisted in Redis."""

    access_token: str
    refresh_token: str
    expires_at: float  # epoch timestamp
    cloud_id: str
    site_url: str
    account_id: str
    display_name: str
    email: Optional[str] = None
    scopes: List[str] = Field(default_factory=list)
    granted_at: float = 0.0
    last_refreshed_at: float = 0.0
    available_sites: List[Dict[str, Any]] = Field(default_factory=list)

    @property
    def is_expired(self) -> bool:
        """Return True if the access token has expired (with 60s leeway)."""
        return time.time() >= (self.expires_at - 60)

    @property
    def api_base_url(self) -> str:
        """Return the Atlassian REST API base URL for this cloud_id."""
        return f"https://api.atlassian.com/ex/jira/{self.cloud_id}"


class JiraOAuthManager:
    """OAuth 2.0 (3LO) lifecycle manager for Jira Cloud.

    The manager exposes primitives for starting an authorization flow,
    exchanging codes for tokens, reading valid tokens from Redis (with
    transparent refresh), and revoking a user's tokens.
    """

    authorization_url = AUTHORIZATION_URL
    token_url = TOKEN_URL
    accessible_resources_url = ACCESSIBLE_RESOURCES_URL

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        redis_client: Any,
        scopes: Optional[List[str]] = None,
        http_session: Optional[aiohttp.ClientSession] = None,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.redis = redis_client
        self.scopes: List[str] = list(scopes) if scopes else list(DEFAULT_SCOPES)
        self._http: Optional[aiohttp.ClientSession] = http_session
        self._http_owned: bool = http_session is None  # True if we must close it
        self.logger = logger

    # ------------------------------------------------------------------ utils

    @staticmethod
    def _token_key(channel: str, user_id: str) -> str:
        return f"{_TOKEN_KEY_PREFIX}:{channel}:{user_id}"

    @staticmethod
    def _nonce_key(nonce: str) -> str:
        return f"{_NONCE_KEY_PREFIX}:{nonce}"

    @staticmethod
    def _lock_key(channel: str, user_id: str) -> str:
        return f"{_LOCK_KEY_PREFIX}:{channel}:{user_id}"

    async def _get_session(self) -> aiohttp.ClientSession:
        """Return the shared aiohttp session, creating it lazily if needed."""
        if self._http is None or self._http.closed:
            self._http = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
            )
            self._http_owned = True
        return self._http

    async def _read_token(self, key: str) -> Optional[JiraTokenSet]:
        raw = await self.redis.get(key)
        if not raw:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            return JiraTokenSet.model_validate_json(raw)
        except Exception as exc:  # pragma: no cover - corrupted payload
            self.logger.warning("Corrupted token payload at %s: %s", key, exc)
            return None

    async def _write_token(self, key: str, token: JiraTokenSet) -> None:
        payload = token.model_dump_json()
        # redis-py async supports ``ex=`` for TTL on set.
        await self.redis.set(key, payload, ex=_TOKEN_TTL_SECONDS)

    # ------------------------------------------------------------------ URL

    async def create_authorization_url(
        self,
        channel: str,
        user_id: str,
        extra_state: Optional[Dict[str, Any]] = None,
    ) -> Tuple[str, str]:
        """Generate an Atlassian consent URL with a CSRF state nonce.

        Stores a Redis record under ``jira:nonce:<nonce>`` mapping to the
        (channel, user_id, extra) triple with a 10-minute TTL. The nonce is
        single-use — it is deleted the first time the callback retrieves it.

        Args:
            channel: Originating channel (``"telegram"``, ``"agentalk"``, …).
            user_id: User identifier scoped to the channel.
            extra_state: Optional metadata echoed back on the callback.

        Returns:
            ``(url, nonce)`` — the authorization URL and the state nonce.
        """
        nonce = secrets.token_urlsafe(32)
        state_payload = {
            "channel": channel,
            "user_id": user_id,
            "extra": extra_state or {},
        }
        await self.redis.set(
            self._nonce_key(nonce),
            json.dumps(state_payload),
            ex=_NONCE_TTL_SECONDS,
        )

        params = {
            "audience": "api.atlassian.com",
            "client_id": self.client_id,
            "scope": " ".join(self.scopes),
            "redirect_uri": self.redirect_uri,
            "state": nonce,
            "response_type": "code",
            "prompt": "consent",
        }
        url = f"{self.authorization_url}?{urlencode(params)}"
        return url, nonce

    # ------------------------------------------------------------------ callback

    async def handle_callback(self, code: str, state: str) -> Tuple[JiraTokenSet, Dict[str, Any]]:
        """Process the OAuth callback: validate state, exchange code, store.

        Args:
            code: Authorization code returned by Atlassian.
            state: CSRF state nonce that was sent in the authorization URL.

        Returns:
            A tuple of ``(JiraTokenSet, state_payload)`` where ``state_payload``
            contains ``channel``, ``user_id``, and ``extra`` decoded from the nonce.

        Raises:
            ValueError: If the state nonce is missing/expired or the token
                exchange fails.
        """
        nonce_key = self._nonce_key(state)
        raw_state = await self.redis.get(nonce_key)
        if not raw_state:
            raise ValueError("Invalid or expired state nonce.")
        if isinstance(raw_state, bytes):
            raw_state = raw_state.decode("utf-8")
        # One-time use: delete immediately.
        await self.redis.delete(nonce_key)

        try:
            state_payload = json.loads(raw_state)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Corrupted state payload: {exc}") from exc

        channel = state_payload.get("channel")
        user_id = state_payload.get("user_id")
        if not channel or not user_id:
            raise ValueError("State payload missing channel or user_id.")

        # 1. Exchange code for tokens.
        token_response = await self._exchange_code(code)
        access_token = token_response["access_token"]
        refresh_token = token_response.get("refresh_token", "")
        expires_in = int(token_response.get("expires_in", 3600))
        granted_scopes = token_response.get("scope", "").split() if token_response.get("scope") else list(self.scopes)

        # 2. Discover accessible resources (cloud_id + site_url).
        resources = await self._fetch_accessible_resources(access_token)
        if not resources:
            raise ValueError("No accessible Atlassian resources for this user.")
        primary = resources[0]
        cloud_id = primary["id"]
        site_url = primary["url"]

        # 3. Resolve user identity.
        myself = await self._fetch_myself(access_token, cloud_id)
        account_id = myself.get("accountId", "")
        display_name = myself.get("displayName", "")
        email = myself.get("emailAddress")

        now = time.time()
        token = JiraTokenSet(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=now + expires_in,
            cloud_id=cloud_id,
            site_url=site_url,
            account_id=account_id,
            display_name=display_name,
            email=email,
            scopes=granted_scopes,
            granted_at=now,
            last_refreshed_at=now,
            available_sites=resources,
        )

        await self._write_token(self._token_key(channel, user_id), token)
        self.logger.info(
            "Stored Jira token for %s:%s (%s @ %s)",
            channel, user_id, display_name, site_url,
        )
        return token, state_payload

    # ------------------------------------------------------------------ reads

    async def get_valid_token(
        self, channel: str, user_id: str
    ) -> Optional[JiraTokenSet]:
        """Return a non-expired token, refreshing it transparently if needed."""
        key = self._token_key(channel, user_id)
        token = await self._read_token(key)
        if token is None:
            return None
        if not token.is_expired:
            return token
        return await self._refresh_tokens(channel, user_id, token)

    async def is_connected(self, channel: str, user_id: str) -> bool:
        """Return True when a valid token is available for the user."""
        return (await self.get_valid_token(channel, user_id)) is not None

    async def revoke(self, channel: str, user_id: str) -> None:
        """Delete the user's token from Redis."""
        await self.redis.delete(self._token_key(channel, user_id))

    # ------------------------------------------------------------------ refresh

    async def _refresh_tokens(
        self, channel: str, user_id: str, token_set: JiraTokenSet
    ) -> JiraTokenSet:
        """Refresh a user's tokens using the rotating refresh token.

        Uses a Redis distributed lock so that concurrent refresh requests
        do not both consume the old refresh token (Atlassian rotates it on
        each successful refresh; the second request would otherwise be
        rejected).

        If the lock cannot be acquired within ``_REFRESH_LOCK_BLOCKING_TIMEOUT``
        seconds, the method re-reads the token (another process may have
        refreshed already) and returns it if still valid, or raises
        ``PermissionError`` so the caller can surface the issue rather than
        silently proceeding without lock protection.
        """
        key = self._token_key(channel, user_id)
        lock_name = self._lock_key(channel, user_id)
        lock = self.redis.lock(
            lock_name,
            timeout=_REFRESH_LOCK_TIMEOUT,
            blocking_timeout=_REFRESH_LOCK_BLOCKING_TIMEOUT,
        )
        acquired = await lock.acquire()
        if not acquired:
            # Another process is holding the lock.  Re-read — it may have
            # just finished refreshing and stored a fresh token.
            self.logger.warning(
                "Could not acquire refresh lock for %s:%s within %ss; re-reading",
                channel, user_id, _REFRESH_LOCK_BLOCKING_TIMEOUT,
            )
            fresh = await self._read_token(key)
            if fresh and not fresh.is_expired:
                return fresh
            raise PermissionError(
                f"Jira token refresh lock unavailable for {channel}:{user_id}. "
                "Another refresh may be in progress — retry after a moment."
            )

        try:
            # Another request may have refreshed already while we waited.
            fresh = await self._read_token(key)
            if fresh and not fresh.is_expired:
                return fresh

            current = fresh or token_set
            try:
                session = await self._get_session()
                async with session.post(
                    self.token_url,
                    data={
                        "grant_type": "refresh_token",
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "refresh_token": current.refresh_token,
                    },
                ) as response:
                    if response.status == 401:
                        # Atlassian rejected the refresh token — revoke locally.
                        await self.revoke(channel, user_id)
                        raise PermissionError(
                            "Jira refresh token rejected (401); user must re-authorize."
                        )
                    if response.status != 200:
                        text = await response.text()
                        raise PermissionError(
                            f"Jira token refresh failed with status {response.status}: {text}"
                        )
                    payload = await response.json()

            except aiohttp.ClientError as exc:
                raise PermissionError(
                    f"Jira token refresh network error: {exc}"
                ) from exc

            now = time.time()
            refreshed = token_set.model_copy(update={
                "access_token": payload["access_token"],
                "refresh_token": payload.get("refresh_token", token_set.refresh_token),
                "expires_at": now + int(payload.get("expires_in", 3600)),
                "last_refreshed_at": now,
            })
            await self._write_token(key, refreshed)
            return refreshed
        finally:
            # lock.release() is only reached when acquired is True —
            # the not-acquired path raises PermissionError before entering
            # this try block.
            try:
                await lock.release()
            except Exception:  # pragma: no cover - lock already released
                pass

    # ------------------------------------------------------------------ HTTP

    async def _exchange_code(self, code: str) -> Dict[str, Any]:
        session = await self._get_session()
        async with session.post(
            self.token_url,
            data={
                "grant_type": "authorization_code",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "code": code,
                "redirect_uri": self.redirect_uri,
            },
        ) as response:
            if response.status != 200:
                text = await response.text()
                raise ValueError(
                    f"Token exchange failed with status {response.status}: {text}"
                )
            return await response.json()

    async def _fetch_accessible_resources(self, access_token: str) -> List[Dict[str, Any]]:
        session = await self._get_session()
        async with session.get(
            self.accessible_resources_url,
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        ) as response:
            if response.status != 200:
                text = await response.text()
                raise ValueError(
                    f"accessible-resources failed with status {response.status}: {text}"
                )
            data = await response.json()
            if not isinstance(data, list):
                raise ValueError("accessible-resources returned a non-list payload.")
            return data

    async def _fetch_myself(self, access_token: str, cloud_id: str) -> Dict[str, Any]:
        url = f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/myself"
        session = await self._get_session()
        async with session.get(
            url,
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        ) as response:
            if response.status != 200:
                text = await response.text()
                raise ValueError(
                    f"/myself failed with status {response.status}: {text}"
                )
            return await response.json()

    async def aclose(self) -> None:
        """Close the underlying aiohttp session if this manager owns it."""
        if self._http_owned and self._http and not self._http.closed:
            await self._http.close()
        self._http = None
