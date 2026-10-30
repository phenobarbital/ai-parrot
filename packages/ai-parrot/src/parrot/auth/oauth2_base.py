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
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator, ClassVar, Dict, List, Optional, Protocol, Tuple, Type, runtime_checkable
from urllib.parse import urlencode

import aiohttp
from aiohttp import web
from pydantic import BaseModel, Field

from parrot.auth.oauth2.events import ConnectionEvent, ConnectionEventPublisher
from parrot.auth.principal import Principal, resolve_principal
from parrot.conf import OAUTH2_LEGACY_KEYS_UNTIL
from parrot.security.vault_utils import delete_vault_credential, retrieve_vault_credential, store_vault_credential

# Token storage key schema (Redis cache layer).
_TOKEN_KEY_TEMPLATE = "oauth2:{provider}:{user_id}"
_NONCE_KEY_TEMPLATE = "oauth2:{provider}:nonce:{nonce}"
_LOCK_KEY_TEMPLATE = "lock:oauth2:{provider}:refresh:{user_id}"

# Legacy channel-scoped layout — read-only during the migration window.
_LEGACY_TOKEN_KEY_TEMPLATE = "oauth2:{provider}:{channel}:{user_id}"
_LEGACY_VAULT_NAME_TEMPLATE = "oauth2_{provider}_{channel}_{user_id}"
_VAULT_NAME_TEMPLATE = "oauth2_{provider}_{user_id}"

# TTLs.
_TOKEN_TTL_SECONDS = 90 * 24 * 60 * 60   # 90 days hot cache
_NONCE_TTL_SECONDS = 10 * 60             # 10 minutes
_REFRESH_LOCK_TIMEOUT = 10               # seconds
_REFRESH_LOCK_BLOCKING_TIMEOUT = 5       # seconds


logger = logging.getLogger(__name__)
_legacy_window_parse_error_logged = False


def _legacy_window_open(now: Optional[datetime] = None) -> bool:
    """Return whether channel-scoped OAuth2 credentials may still be migrated."""
    cutoff = OAUTH2_LEGACY_KEYS_UNTIL.strip()
    if not cutoff:
        return True
    try:
        parsed = datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
    except ValueError:
        global _legacy_window_parse_error_logged
        if not _legacy_window_parse_error_logged:
            logger.error("Invalid OAUTH2_LEGACY_KEYS_UNTIL; legacy OAuth2 reads are disabled")
            _legacy_window_parse_error_logged = True
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current <= parsed


class CredentialPersistenceError(RuntimeError):
    """The durable credential write failed; the operation must not report success."""


class InvalidGrantError(PermissionError):
    """Provider rejected the refresh token; the grant is revoked locally."""


class RefreshTransientError(RuntimeError):
    """A transient refresh failure occurred; the grant is kept."""


@runtime_checkable
class CredentialStore(Protocol):
    """Durable owner of an OAuth2 grant."""

    async def load(self, user_id: str, provider: str) -> Optional[Dict[str, Any]]: ...

    async def save(
        self,
        user_id: str,
        provider: str,
        payload: Dict[str, Any],
        *,
        minted: bool,
        principal: Optional[Principal],
        state_payload: Optional[Dict[str, Any]],
    ) -> None: ...

    async def delete(self, user_id: str, provider: str) -> None: ...


class VaultUtilsCredentialStore:
    """Default store over vault helpers using a principal-scoped name."""

    @staticmethod
    def _vault_name(provider: str, user_id: str) -> str:
        return _VAULT_NAME_TEMPLATE.format(provider=provider, user_id=user_id)

    async def load(self, user_id: str, provider: str) -> Optional[Dict[str, Any]]:
        """Load a credential, returning ``None`` when it is absent."""
        try:
            return await retrieve_vault_credential(user_id, self._vault_name(provider, user_id))
        except KeyError:
            return None

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
        """Save a credential; metadata arguments support richer injected stores."""
        del minted, principal, state_payload
        await store_vault_credential(user_id, self._vault_name(provider, user_id), payload)

    async def delete(self, user_id: str, provider: str) -> None:
        """Delete a credential."""
        await delete_vault_credential(user_id, self._vault_name(provider, user_id))


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
        credential_store: Optional[CredentialStore] = None,
        event_publisher: Optional[ConnectionEventPublisher] = None,
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

        self._store: CredentialStore = credential_store or VaultUtilsCredentialStore()
        self._events = event_publisher

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

    def _token_key(self, user_id: str) -> str:
        return _TOKEN_KEY_TEMPLATE.format(provider=self.provider_id, user_id=user_id)

    def _nonce_key(self, nonce: str) -> str:
        return _NONCE_KEY_TEMPLATE.format(provider=self.provider_id, nonce=nonce)

    def _lock_key(self, user_id: str) -> str:
        return _LOCK_KEY_TEMPLATE.format(provider=self.provider_id, user_id=user_id)

    @asynccontextmanager
    async def principal_lock(self, user_id: str) -> AsyncIterator[None]:
        """Serialize operations for one provider and principal; never nest."""
        lock = self.redis.lock(
            self._lock_key(user_id),
            timeout=_REFRESH_LOCK_TIMEOUT,
            blocking_timeout=_REFRESH_LOCK_BLOCKING_TIMEOUT,
        )
        acquired = await lock.acquire()
        if not acquired:
            raise TimeoutError(f"Could not acquire {self.provider_id} principal lock")
        try:
            yield
        finally:
            try:
                await lock.release()
            except Exception:  # pragma: no cover - lock may already be released
                pass

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
        *,
        principal: Optional[Principal] = None,
    ) -> Tuple[str, str]:
        """Generate a provider consent URL with a CSRF state nonce.

        Stores a Redis record under ``oauth2:{provider}:nonce:<nonce>`` with
        a 10-minute TTL. The record carries ``channel``, ``user_id``, the
        caller-supplied ``extra_state`` payload, and (if PKCE is enabled)
        the ``code_verifier`` so the callback can complete the exchange.

        Returns:
            ``(url, nonce)`` — the authorization URL and the state nonce.
        """
        if principal is None:
            principal = await resolve_principal(channel, user_id)
        if principal is None:
            raise ValueError(f"No platform principal bound to this {channel} user; link the account first.")

        nonce = secrets.token_urlsafe(32)
        state_payload: Dict[str, Any] = {
            "channel": channel,
            "user_id": user_id,
            "extra": extra_state or {},
            "nav_user_id": principal.user_id,
            "channel_user_id": principal.channel_user_id,
            "canonical_identity": principal.canonical_identity,
            "tenant_id": principal.tenant_id,
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
        channel_user_id = state_payload.get("channel_user_id") or state_payload.get("user_id")
        nav_user_id = state_payload.get("nav_user_id")
        if not channel or not channel_user_id:
            raise ValueError("State payload missing channel or user_id.")
        if nav_user_id is None or not str(nav_user_id).isdigit():
            raise ValueError("State payload missing a valid nav_user_id.")
        principal = Principal(
            user_id=str(nav_user_id),
            channel=channel,
            channel_user_id=str(channel_user_id),
            canonical_identity=state_payload.get("canonical_identity"),
            tenant_id=state_payload.get("tenant_id"),
        )
        code_verifier = state_payload.get("code_verifier")

        # 1. Exchange code → raw token.
        token_response = await self._exchange_code(code, code_verifier)

        # 2. Discover identity (provider-specific).
        access_token = token_response["access_token"]
        identity = await self._discover_identity(access_token)

        # 3. Build provider-specific token set.
        token_set = self._build_token_set(token_response, identity)
        token_set = await self._post_exchange(token_response, token_set)

        # 4. Persist durable state before the hot cache while serialized.
        async with self.principal_lock(principal.user_id):
            await self._persist_token(principal, token_set, minted=True, state_payload=state_payload)

        await self._publish(
            "connection.completed",
            principal,
            token_set,
            state_payload={**state_payload, "connection_meta": self._public_metadata(token_set)},
        )

        self.logger.info(
            "Stored %s token for principal %s (%s)",
            self.provider_id,
            principal.user_id,
            token_set.display_name or token_set.account_id,
        )
        return token_set, state_payload

    def _public_metadata(self, token_set: AbstractOAuth2TokenSet) -> Dict[str, Any]:
        """Return non-secret token attributes made available to notifiers."""
        return {}

    async def _post_exchange(
        self,
        token_response: Dict[str, Any],
        token_set: AbstractOAuth2TokenSet,
    ) -> AbstractOAuth2TokenSet:
        """Run the provider post-exchange hook; the default is identity."""
        return token_set

    async def _publish(
        self,
        kind: str,
        principal: Principal,
        token_set: Optional[AbstractOAuth2TokenSet],
        *,
        reason: Optional[str] = None,
        state_payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Publish a connection event when a publisher is attached."""
        if self._events is None:
            return
        event = ConnectionEvent(
            kind=kind,
            user_id=principal.user_id,
            canonical_identity=principal.canonical_identity,
            tenant_id=principal.tenant_id,
            provider=self.provider_id,
            account_id=token_set.account_id if token_set is not None else "",
            display_name=token_set.display_name if token_set is not None else "",
            channel=principal.channel,
            occurred_at=time.time(),
            reason=reason,
        )
        await self._events.publish(event, state_payload or {})

    # ------------------------------------------------------------------ persist

    async def _persist_token(
        self,
        principal: Principal,
        token_set: AbstractOAuth2TokenSet,
        *,
        minted: bool,
        state_payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Write the durable credential before the Redis hot cache."""
        payload = token_set.model_dump(mode="json")
        try:
            await self._store.save(
                principal.user_id,
                self.provider_id,
                payload,
                minted=minted,
                principal=principal,
                state_payload=state_payload,
            )
        except Exception as exc:  # noqa: BLE001 - every durable failure is fatal
            self.logger.error(
                "Durable %s credential write failed for principal %s: %s",
                self.provider_id,
                principal.user_id,
                type(exc).__name__,
            )
            raise CredentialPersistenceError(f"{self.provider_id} credential could not be persisted") from None
        await self.redis.set(
            self._token_key(principal.user_id),
            json.dumps(payload),
            ex=_TOKEN_TTL_SECONDS,
        )

    async def _read_token_from_cache(self, user_id: str) -> Optional[AbstractOAuth2TokenSet]:
        raw = await self.redis.get(self._token_key(user_id))
        if not raw:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            return self.token_set_cls.model_validate_json(raw)
        except Exception as exc:  # pragma: no cover - corrupted payload
            self.logger.warning("Corrupted token cache for %s principal %s: %s", self.provider_id, user_id, exc)
            return None

    async def _read_token_from_store(self, user_id: str) -> Optional[AbstractOAuth2TokenSet]:
        try:
            payload = await self._store.load(user_id, self.provider_id)
        except Exception:  # pragma: no cover - durable read failure is treated as unavailable
            self.logger.exception("Credential store read failed for %s principal %s", self.provider_id, user_id)
            return None
        if payload is None:
            return None
        try:
            return self.token_set_cls.model_validate(payload)
        except Exception as exc:  # pragma: no cover
            self.logger.warning("Corrupted store payload for %s principal %s: %s", self.provider_id, user_id, exc)
            return None

    # ------------------------------------------------------------------ read

    async def get_valid_token(
        self,
        channel: str,
        user_id: str,
        *,
        channel_user_id: Optional[str] = None,
    ) -> Optional[AbstractOAuth2TokenSet]:
        """Return a principal's valid token from cache, store, or legacy storage."""
        token = await self._read_token_from_cache(user_id)
        if token is None:
            async with self.principal_lock(user_id):
                token = await self._read_token_from_cache(user_id)
                if token is None:
                    token = await self._read_token_from_store(user_id)
                    if token is not None:
                        await self.redis.set(
                            self._token_key(user_id),
                            token.model_dump_json(),
                            ex=_TOKEN_TTL_SECONDS,
                        )
                if token is None and _legacy_window_open():
                    token = await self._read_legacy_token(channel, channel_user_id or user_id, user_id)
        if token is None:
            return None
        if not token.is_expired:
            return token
        if not token.refresh_token:
            await self.revoke(channel, user_id, channel_user_id=channel_user_id)
            return None
        return await self._refresh_tokens(channel, user_id, token)

    async def _read_legacy_token(
        self,
        channel: str,
        channel_user_id: str,
        user_id: str,
    ) -> Optional[AbstractOAuth2TokenSet]:
        """Migrate a channel-scoped credential to principal-scoped storage once."""
        if not _legacy_window_open():
            return None

        legacy_key = _LEGACY_TOKEN_KEY_TEMPLATE.format(
            provider=self.provider_id,
            channel=channel,
            user_id=channel_user_id,
        )
        legacy_vault_name = _LEGACY_VAULT_NAME_TEMPLATE.format(
            provider=self.provider_id,
            channel=channel,
            user_id=channel_user_id,
        )
        raw = await self.redis.get(legacy_key)
        payload: Any = raw
        if payload is None:
            try:
                payload = await retrieve_vault_credential(channel_user_id, legacy_vault_name)
            except KeyError:
                return None
        try:
            if isinstance(payload, bytes):
                payload = payload.decode("utf-8")
            token = (
                self.token_set_cls.model_validate_json(payload)
                if isinstance(payload, str)
                else self.token_set_cls.model_validate(payload)
            )
        except Exception as exc:
            self.logger.warning(
                "Corrupted legacy token for %s channel %s: %s",
                self.provider_id,
                channel,
                type(exc).__name__,
            )
            return None

        principal = Principal(user_id=user_id, channel=channel, channel_user_id=channel_user_id)
        await self._persist_token(principal, token, minted=False)
        try:
            await self.redis.delete(legacy_key)
        except Exception as exc:
            self.logger.warning(
                "Legacy cache delete failed for %s principal %s: %s",
                self.provider_id,
                user_id,
                type(exc).__name__,
            )
        try:
            await delete_vault_credential(channel_user_id, legacy_vault_name)
        except Exception as exc:
            self.logger.warning(
                "Legacy vault delete failed for %s principal %s: %s",
                self.provider_id,
                user_id,
                type(exc).__name__,
            )
        return token

    async def is_connected(self, channel: str, user_id: str) -> bool:
        """Cheap connectivity check — does not call the provider."""
        return (await self.get_valid_token(channel, user_id)) is not None

    async def revoke(
        self,
        channel: str,
        user_id: str,
        *,
        channel_user_id: Optional[str] = None,
    ) -> None:
        """Revoke remotely best effort, delete all local copies, then publish."""
        raw_channel_user_id = channel_user_id or user_id
        principal = Principal(user_id=user_id, channel=channel, channel_user_id=raw_channel_user_id)
        token: Optional[AbstractOAuth2TokenSet] = None
        async with self.principal_lock(user_id):
            token = await self._read_token_from_cache(user_id) or await self._read_token_from_store(user_id)
            if token is not None:
                try:
                    await self._revoke_remote(token)
                except Exception as exc:
                    self.logger.warning(
                        "Remote revoke failed for %s principal %s: %s",
                        self.provider_id,
                        user_id,
                        type(exc).__name__,
                    )
            try:
                await self._store.delete(user_id, self.provider_id)
            except Exception as exc:
                self.logger.error(
                    "Credential store delete failed for %s principal %s: %s",
                    self.provider_id,
                    user_id,
                    type(exc).__name__,
                )
                raise CredentialPersistenceError(f"{self.provider_id} credential could not be deleted") from None

            legacy_user_ids = {raw_channel_user_id, user_id}
            legacy_keys = [
                _LEGACY_TOKEN_KEY_TEMPLATE.format(
                    provider=self.provider_id,
                    channel=channel,
                    user_id=legacy_user_id,
                )
                for legacy_user_id in legacy_user_ids
            ]
            await self.redis.delete(self._token_key(user_id), *legacy_keys)
            for legacy_user_id in legacy_user_ids:
                legacy_vault_name = _LEGACY_VAULT_NAME_TEMPLATE.format(
                    provider=self.provider_id,
                    channel=channel,
                    user_id=legacy_user_id,
                )
                try:
                    await delete_vault_credential(legacy_user_id, legacy_vault_name)
                except Exception as exc:
                    self.logger.warning(
                        "Legacy vault delete failed for %s principal %s: %s",
                        self.provider_id,
                        user_id,
                        type(exc).__name__,
                    )
        if token is not None:
            await self._publish("connection.revoked", principal, token)

    async def _revoke_remote(self, token_set: AbstractOAuth2TokenSet) -> None:
        """Provider-side revocation hook. Default no-op."""
        return None

    async def _delete_token(self, user_id: str) -> None:
        """Delete both layers while the caller owns the principal lock."""
        try:
            await self._store.delete(user_id, self.provider_id)
        except Exception:  # pragma: no cover
            self.logger.exception("Credential store delete failed for %s principal %s", self.provider_id, user_id)
        await self.redis.delete(self._token_key(user_id))

    # ------------------------------------------------------------------ refresh

    async def _refresh_tokens(
        self,
        channel: str,
        user_id: str,
        token_set: AbstractOAuth2TokenSet,
    ) -> Optional[AbstractOAuth2TokenSet]:
        """Refresh once per principal while preserving replacements and transient grants."""
        principal = Principal(user_id=user_id, channel=channel, channel_user_id=user_id)
        try:
            async with self.principal_lock(user_id):
                current = await self._read_token_from_cache(user_id) or await self._read_token_from_store(user_id)
                if current is None:
                    return None
                if current.account_id != token_set.account_id:
                    return current if not current.is_expired else None
                if not current.is_expired:
                    return current
                try:
                    payload = await self._refresh_request(current.refresh_token)
                except aiohttp.ClientError as exc:
                    raise RefreshTransientError(f"{self.provider_id} refresh network error") from exc
                except InvalidGrantError:
                    try:
                        await self._store.delete(user_id, self.provider_id)
                    except Exception as exc:
                        self.logger.error(
                            "Credential store delete failed after invalid grant for %s principal %s: %s",
                            self.provider_id,
                            user_id,
                            type(exc).__name__,
                        )
                    await self.redis.delete(self._token_key(user_id))
                    raise

                now = time.time()
                updates: Dict[str, Any] = {
                    "access_token": payload["access_token"],
                    "refresh_token": payload.get("refresh_token", current.refresh_token),
                    "expires_at": now + int(payload.get("expires_in", 3600)),
                    "last_refreshed_at": now,
                }
                if payload.get("scope"):
                    updates["scopes"] = payload["scope"].split()
                refreshed = current.model_copy(update=updates)
                await self._persist_token(principal, refreshed, minted=False)
                return refreshed
        except InvalidGrantError:
            await self._publish(
                "connection.refresh_failed",
                principal,
                token_set,
                reason="InvalidGrantError",
            )
            raise

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
