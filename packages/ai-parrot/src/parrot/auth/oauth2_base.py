"""Generic OAuth 2.0 / PKCE manager for AI-Parrot toolkits.

Provides :class:`AbstractOAuth2Manager`, a reusable parallel of
:class:`parrot.auth.jira_oauth.JiraOAuthManager` from which any provider
(Office365, GitHub, Slack, …) can inherit. Concrete subclasses only need
to implement the four provider-specific hooks
(``_exchange_code``, ``_refresh_request``, ``_discover_identity``,
``_build_token_set``); the base class handles:

- Authorization URL generation with CSRF state nonces and optional PKCE
  ``code_verifier`` / ``code_challenge``.
- Token persistence in two layers: navigator-session vault (encrypted,
  long-lived) as source of truth + Redis (TTL-bounded) as hot cache.
- Distributed-lock-protected refresh so concurrent requests do not race
  on rotating refresh tokens.
- aiohttp setup/cleanup wiring.

The Jira-specific manager intentionally stays untouched (decision from
the planning phase) — this module is a parallel surface.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import time
from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable, ClassVar, Dict, List, Optional, Tuple, Type
from urllib.parse import urlencode

import aiohttp
from aiohttp import web
from pydantic import BaseModel, Field


# Token storage key schema (Redis cache layer).
_TOKEN_KEY_TEMPLATE = "oauth2:{provider}:{channel}:{user_id}"
_NONCE_KEY_TEMPLATE = "oauth2:{provider}:nonce:{nonce}"
_LOCK_KEY_TEMPLATE = "lock:oauth2:{provider}:refresh:{channel}:{user_id}"

# Vault key (navigator-session encrypted store).
_VAULT_NAME_TEMPLATE = "oauth2_{provider}_{channel}_{user_id}"

# TTLs.
_TOKEN_TTL_SECONDS = 90 * 24 * 60 * 60   # 90 days hot cache
_NONCE_TTL_SECONDS = 10 * 60             # 10 minutes
_REFRESH_LOCK_TIMEOUT = 10               # seconds
_REFRESH_LOCK_BLOCKING_TIMEOUT = 5       # seconds


logger = logging.getLogger(__name__)


VaultWriter = Callable[[str, str, Dict[str, Any]], Awaitable[None]]
VaultReader = Callable[[str, str], Awaitable[Dict[str, Any]]]
VaultDeleter = Callable[[str, str], Awaitable[None]]


class AbstractOAuth2TokenSet(BaseModel):
    """Provider-agnostic OAuth 2.0 token set.

    Subclasses extend with provider-specific identity fields
    (e.g. ``tenant_id``, ``cloud_id``).
    """

    access_token: str
    refresh_token: str = ""
    expires_at: float = 0.0  # epoch seconds
    scopes: List[str] = Field(default_factory=list)
    granted_at: float = 0.0
    last_refreshed_at: float = 0.0
    account_id: str = ""
    display_name: str = ""
    email: Optional[str] = None

    # Class-level expiration leeway in seconds — subclasses can override.
    _EXPIRY_LEEWAY_SECONDS: ClassVar[int] = 60

    @property
    def is_expired(self) -> bool:
        """Return ``True`` if the access token is at/past expiry (with leeway)."""
        if not self.expires_at:
            return False
        return time.time() >= (self.expires_at - self._EXPIRY_LEEWAY_SECONDS)


class AbstractOAuth2Manager(ABC):
    """OAuth 2.0 lifecycle manager — provider-agnostic base.

    Subclasses must set the following class attributes:

    - ``provider_id``: short, unique string (``"o365"``, ``"github"``, …).
    - ``authorization_url``: the provider's consent URL.
    - ``token_url``: the provider's token endpoint.
    - ``default_scopes``: scopes to request by default.
    - ``token_set_cls``: subclass of :class:`AbstractOAuth2TokenSet`.

    And implement the four hooks:

    - :meth:`_exchange_code` — code + verifier → raw token JSON.
    - :meth:`_refresh_request` — refresh_token → raw token JSON.
    - :meth:`_discover_identity` — access_token → identity dict.
    - :meth:`_build_token_set` — raw token JSON + identity → token set.
    """

    # Subclasses MUST override these class attributes.
    provider_id: ClassVar[str] = ""
    authorization_url: ClassVar[str] = ""
    token_url: ClassVar[str] = ""
    default_scopes: ClassVar[List[str]] = []
    token_set_cls: ClassVar[Type[AbstractOAuth2TokenSet]] = AbstractOAuth2TokenSet

    # Whether to enable PKCE (code_verifier + code_challenge) on the auth URL.
    use_pkce: ClassVar[bool] = True
    # Whether the token endpoint requires ``client_secret`` (confidential clients).
    require_client_secret: ClassVar[bool] = True

    def __init__(
        self,
        client_id: str,
        redirect_uri: str,
        *,
        client_secret: Optional[str] = None,
        app: Optional[web.Application] = None,
        redis_url: Optional[str] = None,
        redis_client: Any = None,
        scopes: Optional[List[str]] = None,
        http_session: Optional[aiohttp.ClientSession] = None,
        vault_writer: Optional[VaultWriter] = None,
        vault_reader: Optional[VaultReader] = None,
        vault_deleter: Optional[VaultDeleter] = None,
        callback_path: Optional[str] = None,
    ) -> None:
        if not self.provider_id:
            raise NotImplementedError(
                f"{type(self).__name__} must set the class attribute "
                "`provider_id` (e.g., 'o365')."
            )
        if app is None and redis_client is None and not redis_url:
            raise ValueError(
                f"{type(self).__name__} requires one of: app (with "
                "app['redis']), redis_client, or redis_url"
            )
        if self.require_client_secret and not client_secret:
            raise ValueError(
                f"{type(self).__name__} requires client_secret"
            )

        self.client_id = client_id
        self.client_secret = client_secret or ""
        self.redirect_uri = redirect_uri
        self._app: Optional[web.Application] = app
        self._redis_url: Optional[str] = redis_url
        self.redis = redis_client
        self._redis_owned: bool = redis_client is None
        self.scopes: List[str] = list(scopes) if scopes else list(self.default_scopes)
        self._http: Optional[aiohttp.ClientSession] = http_session
        self._http_owned: bool = http_session is None
        self._setup_done: bool = False
        self.logger = logger

        # Vault wiring — defaults use the navigator_session-backed helpers.
        if vault_writer is None or vault_reader is None or vault_deleter is None:
            from parrot.security.vault_utils import (  # local import: tests may mock
                delete_vault_credential,
                retrieve_vault_credential,
                store_vault_credential,
            )

            self._vault_writer: VaultWriter = vault_writer or store_vault_credential
            self._vault_reader: VaultReader = vault_reader or retrieve_vault_credential
            self._vault_deleter: VaultDeleter = vault_deleter or delete_vault_credential
        else:
            self._vault_writer = vault_writer
            self._vault_reader = vault_reader
            self._vault_deleter = vault_deleter

        self._callback_path: str = (
            callback_path or f"/api/auth/oauth2/{self.provider_id}/callback"
        )

    # ------------------------------------------------------------------ setup

    def setup(self) -> None:
        """Wire this manager into the aiohttp app passed at construction.

        Idempotent. Stores the manager at
        ``app[f'oauth2_manager_{provider_id}']``, appends startup/cleanup
        signals, and mounts ``GET {callback_path}`` via
        :func:`parrot.auth.oauth2_routes.setup_oauth2_routes`.
        """
        if self._setup_done:
            return
        if self._app is None:
            raise RuntimeError(
                f"{type(self).__name__}.setup() requires app= in the constructor."
            )
        app = self._app
        slot = f"oauth2_manager_{self.provider_id}"
        existing = app.get(slot)
        if existing is not None and existing is not self:
            raise RuntimeError(
                f"app['{slot}'] is already set to a different "
                f"{type(self).__name__} instance."
            )
        app[slot] = self
        app.on_startup.append(self._on_startup)
        app.on_cleanup.append(self._on_cleanup)
        from parrot.auth.oauth2_routes import setup_oauth2_routes

        setup_oauth2_routes(app, self.provider_id, self._callback_path)
        self._setup_done = True

    async def _on_startup(self, app: web.Application) -> None:
        """aiohttp startup hook: resolve Redis client and ping it."""
        if self.redis is None:
            shared = self._app.get("redis") if self._app is not None else None
            if shared is not None:
                self.redis = shared
                self._redis_owned = False
            elif self._redis_url:
                import redis.asyncio as aioredis

                self.redis = aioredis.from_url(
                    self._redis_url, decode_responses=True,
                )
                self._redis_owned = True
            else:
                raise RuntimeError(
                    f"{type(self).__name__}: no Redis source at startup."
                )
        if self.redis is not None:
            await self.redis.ping()

    async def _on_cleanup(self, app: web.Application) -> None:
        """aiohttp cleanup hook: close owned Redis client + aiohttp session."""
        if self._redis_owned and self.redis is not None:
            close = getattr(self.redis, "aclose", None) or self.redis.close
            result = close()
            if hasattr(result, "__await__"):
                await result
            self.redis = None
        if self._http_owned and self._http is not None and not self._http.closed:
            await self._http.close()
            self._http = None

    # ------------------------------------------------------------------ keys

    def _token_key(self, channel: str, user_id: str) -> str:
        return _TOKEN_KEY_TEMPLATE.format(
            provider=self.provider_id, channel=channel, user_id=user_id,
        )

    def _nonce_key(self, nonce: str) -> str:
        return _NONCE_KEY_TEMPLATE.format(provider=self.provider_id, nonce=nonce)

    def _lock_key(self, channel: str, user_id: str) -> str:
        return _LOCK_KEY_TEMPLATE.format(
            provider=self.provider_id, channel=channel, user_id=user_id,
        )

    def _vault_name(self, channel: str, user_id: str) -> str:
        return _VAULT_NAME_TEMPLATE.format(
            provider=self.provider_id, channel=channel, user_id=user_id,
        )

    # ------------------------------------------------------------------ http

    async def _get_session(self) -> aiohttp.ClientSession:
        """Return the shared aiohttp session, creating it lazily if needed."""
        if self._http is None or self._http.closed:
            self._http = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
            )
            self._http_owned = True
        return self._http

    async def aclose(self) -> None:
        """Close the underlying aiohttp session if this manager owns it."""
        if self._http_owned and self._http and not self._http.closed:
            await self._http.close()
        self._http = None

    # ------------------------------------------------------------------ pkce

    @staticmethod
    def _new_pkce_pair() -> Tuple[str, str]:
        """Return a ``(code_verifier, code_challenge)`` pair (S256 method)."""
        verifier = secrets.token_urlsafe(64)
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        return verifier, challenge

    # ------------------------------------------------------------------ URL

    async def create_authorization_url(
        self,
        channel: str,
        user_id: str,
        extra_state: Optional[Dict[str, Any]] = None,
    ) -> Tuple[str, str]:
        """Generate a provider consent URL with a CSRF state nonce.

        Stores a Redis record under ``oauth2:{provider}:nonce:<nonce>`` with
        a 10-minute TTL. The record carries ``channel``, ``user_id``, the
        caller-supplied ``extra_state`` payload, and (if PKCE is enabled)
        the ``code_verifier`` so the callback can complete the exchange.

        Returns:
            ``(url, nonce)`` — the authorization URL and the state nonce.
        """
        nonce = secrets.token_urlsafe(32)
        state_payload: Dict[str, Any] = {
            "channel": channel,
            "user_id": user_id,
            "extra": extra_state or {},
        }
        params: Dict[str, str] = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(self.scopes),
            "state": nonce,
        }
        if self.use_pkce:
            verifier, challenge = self._new_pkce_pair()
            state_payload["code_verifier"] = verifier
            params["code_challenge"] = challenge
            params["code_challenge_method"] = "S256"

        extra_params = self.authorization_url_extra_params()
        if extra_params:
            params.update(extra_params)

        await self.redis.set(
            self._nonce_key(nonce),
            json.dumps(state_payload),
            ex=_NONCE_TTL_SECONDS,
        )
        url = f"{self.authorization_url}?{urlencode(params)}"
        return url, nonce

    def authorization_url_extra_params(self) -> Dict[str, str]:
        """Provider hook for adding extra query params (e.g. ``prompt=consent``).

        Default returns an empty dict; subclasses override as needed.
        """
        return {}

    # ------------------------------------------------------------------ callback

    async def handle_callback(
        self, code: str, state: str,
    ) -> Tuple[AbstractOAuth2TokenSet, Dict[str, Any]]:
        """Validate state, exchange code for tokens, persist, return token+state.

        Args:
            code: Authorization code from the provider.
            state: CSRF nonce that was sent in the authorization URL.

        Returns:
            ``(token_set, state_payload)``.

        Raises:
            ValueError: If the nonce is missing/expired or the exchange fails.
        """
        nonce_key = self._nonce_key(state)
        raw_state = await self.redis.get(nonce_key)
        if not raw_state:
            raise ValueError("Invalid or expired state nonce.")
        if isinstance(raw_state, bytes):
            raw_state = raw_state.decode("utf-8")
        await self.redis.delete(nonce_key)  # one-shot

        try:
            state_payload = json.loads(raw_state)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Corrupted state payload: {exc}") from exc

        channel = state_payload.get("channel")
        user_id = state_payload.get("user_id")
        if not channel or not user_id:
            raise ValueError("State payload missing channel or user_id.")
        code_verifier = state_payload.get("code_verifier")

        # 1. Exchange code → raw token.
        token_response = await self._exchange_code(code, code_verifier)

        # 2. Discover identity (provider-specific).
        access_token = token_response["access_token"]
        identity = await self._discover_identity(access_token)

        # 3. Build provider-specific token set.
        token_set = self._build_token_set(token_response, identity)

        # 4. Persist: vault (source of truth) + Redis cache.
        await self._persist_token(channel, user_id, token_set)

        self.logger.info(
            "Stored %s token for %s:%s (%s)",
            self.provider_id, channel, user_id, token_set.display_name or token_set.account_id,
        )
        return token_set, state_payload

    # ------------------------------------------------------------------ persist

    async def _persist_token(
        self, channel: str, user_id: str, token_set: AbstractOAuth2TokenSet,
    ) -> None:
        """Write token to vault (encrypted) AND Redis cache (TTL bounded)."""
        payload = token_set.model_dump(mode="json")
        # Vault is the source of truth — survives Redis flushes.
        try:
            await self._vault_writer(user_id, self._vault_name(channel, user_id), payload)
        except Exception:  # pragma: no cover - swallow vault failure but log
            self.logger.exception(
                "Vault write failed for %s:%s — token will only live in Redis cache",
                channel, user_id,
            )
        # Redis hot cache.
        await self.redis.set(
            self._token_key(channel, user_id),
            json.dumps(payload),
            ex=_TOKEN_TTL_SECONDS,
        )

    async def _read_token_from_cache(
        self, channel: str, user_id: str,
    ) -> Optional[AbstractOAuth2TokenSet]:
        raw = await self.redis.get(self._token_key(channel, user_id))
        if not raw:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            return self.token_set_cls.model_validate_json(raw)
        except Exception as exc:  # pragma: no cover - corrupted payload
            self.logger.warning("Corrupted token cache for %s:%s: %s", channel, user_id, exc)
            return None

    async def _read_token_from_vault(
        self, channel: str, user_id: str,
    ) -> Optional[AbstractOAuth2TokenSet]:
        try:
            payload = await self._vault_reader(user_id, self._vault_name(channel, user_id))
        except KeyError:
            return None
        except Exception:  # pragma: no cover
            self.logger.exception("Vault read failed for %s:%s", channel, user_id)
            return None
        try:
            return self.token_set_cls.model_validate(payload)
        except Exception as exc:  # pragma: no cover
            self.logger.warning("Corrupted vault payload for %s:%s: %s", channel, user_id, exc)
            return None

    # ------------------------------------------------------------------ read

    async def get_valid_token(
        self, channel: str, user_id: str,
    ) -> Optional[AbstractOAuth2TokenSet]:
        """Return a non-expired token, hydrating from vault if cache is cold.

        Resolution order:
            1. Redis cache.
            2. Vault (re-hydrates cache on hit).

        Refreshes transparently if expired and a ``refresh_token`` is present.
        Returns ``None`` if no token exists at any layer (user must re-auth).
        """
        token = await self._read_token_from_cache(channel, user_id)
        if token is None:
            token = await self._read_token_from_vault(channel, user_id)
            if token is not None:
                # Re-populate the hot cache.
                await self.redis.set(
                    self._token_key(channel, user_id),
                    token.model_dump_json(),
                    ex=_TOKEN_TTL_SECONDS,
                )
        if token is None:
            return None
        if not token.is_expired:
            return token
        if not token.refresh_token:
            # Expired and unrefreshable — revoke locally.
            await self.revoke(channel, user_id)
            return None
        return await self._refresh_tokens(channel, user_id, token)

    async def is_connected(self, channel: str, user_id: str) -> bool:
        """Cheap connectivity check — does not call the provider."""
        return (await self.get_valid_token(channel, user_id)) is not None

    async def revoke(self, channel: str, user_id: str) -> None:
        """Delete the user's token from both vault and Redis."""
        await self.redis.delete(self._token_key(channel, user_id))
        try:
            await self._vault_deleter(user_id, self._vault_name(channel, user_id))
        except Exception:  # pragma: no cover
            self.logger.exception("Vault delete failed for %s:%s", channel, user_id)

    # ------------------------------------------------------------------ refresh

    async def _refresh_tokens(
        self,
        channel: str,
        user_id: str,
        token_set: AbstractOAuth2TokenSet,
    ) -> AbstractOAuth2TokenSet:
        """Refresh tokens under a Redis distributed lock.

        Pattern mirrored from :class:`parrot.auth.jira_oauth.JiraOAuthManager`
        — concurrent refreshes coalesce on the lock, and a rotated refresh
        token never gets consumed twice.
        """
        lock = self.redis.lock(
            self._lock_key(channel, user_id),
            timeout=_REFRESH_LOCK_TIMEOUT,
            blocking_timeout=_REFRESH_LOCK_BLOCKING_TIMEOUT,
        )
        acquired = await lock.acquire()
        if not acquired:
            self.logger.warning(
                "Could not acquire %s refresh lock for %s:%s — re-reading",
                self.provider_id, channel, user_id,
            )
            fresh = await self._read_token_from_cache(channel, user_id)
            if fresh and not fresh.is_expired:
                return fresh
            raise PermissionError(
                f"{self.provider_id} token refresh lock unavailable for "
                f"{channel}:{user_id}. Retry after a moment."
            )

        try:
            # Another waiter may have refreshed while we blocked.
            fresh = await self._read_token_from_cache(channel, user_id)
            if fresh and not fresh.is_expired:
                return fresh

            current = fresh or token_set
            try:
                payload = await self._refresh_request(current.refresh_token)
            except PermissionError:
                await self.revoke(channel, user_id)
                raise
            except aiohttp.ClientError as exc:
                raise PermissionError(
                    f"{self.provider_id} token refresh network error: {exc}"
                ) from exc

            now = time.time()
            updates: Dict[str, Any] = {
                "access_token": payload["access_token"],
                "refresh_token": payload.get(
                    "refresh_token", current.refresh_token,
                ),
                "expires_at": now + int(payload.get("expires_in", 3600)),
                "last_refreshed_at": now,
            }
            if payload.get("scope"):
                updates["scopes"] = payload["scope"].split()
            refreshed = current.model_copy(update=updates)
            await self._persist_token(channel, user_id, refreshed)
            return refreshed
        finally:
            try:
                await lock.release()
            except Exception:  # pragma: no cover - lock already released
                pass

    # ------------------------------------------------------------------ HOOKS

    @abstractmethod
    async def _exchange_code(
        self, code: str, code_verifier: Optional[str],
    ) -> Dict[str, Any]:
        """Exchange the authorization code for a raw token response.

        Subclasses POST to the provider's token endpoint with whatever
        body the provider requires (``grant_type=authorization_code``,
        ``client_id``, ``client_secret``, ``redirect_uri``, ``code``,
        ``code_verifier`` if PKCE).

        Returns:
            The raw JSON token response — must contain ``access_token``
            and ideally ``refresh_token``, ``expires_in``, ``scope``.
        """

    @abstractmethod
    async def _refresh_request(self, refresh_token: str) -> Dict[str, Any]:
        """Exchange a refresh token for a new token response.

        Raises:
            PermissionError: When the provider returns 401 / invalid_grant
                — :meth:`_refresh_tokens` propagates and revokes locally.
        """

    @abstractmethod
    async def _discover_identity(self, access_token: str) -> Dict[str, Any]:
        """Resolve the user's identity from the provider (e.g. ``/me``).

        Returns:
            Dict of provider-specific identity fields. Forwarded to
            :meth:`_build_token_set`.
        """

    @abstractmethod
    def _build_token_set(
        self,
        token_response: Dict[str, Any],
        identity: Dict[str, Any],
    ) -> AbstractOAuth2TokenSet:
        """Build the provider-specific :class:`AbstractOAuth2TokenSet` subclass.

        Subclasses construct their token model with provider-specific
        fields (``tenant_id``, ``cloud_id``, …) populated from
        ``identity`` and the token timestamps populated from
        ``token_response``.
        """
