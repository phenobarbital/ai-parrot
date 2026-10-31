"""Office 365 (Microsoft Graph) OAuth 2.0 manager with PKCE.

Concrete :class:`parrot.auth.oauth2_base.AbstractOAuth2Manager` for
Microsoft Identity Platform delegated (3LO) auth, supporting both
personal and work/school accounts.

The manager talks directly to ``https://login.microsoftonline.com`` and
``https://graph.microsoft.com`` — it does not depend on MSAL, since the
abstract base already handles the moving parts (PKCE, nonces, refresh
locks, vault persistence). The Graph SDK is only used by the toolkit
when calling actual API endpoints.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, ClassVar, Dict, List, Literal, Optional
from urllib.parse import urlencode

import aiohttp

from parrot.auth.oauth2_base import (
    AbstractOAuth2Manager,
    AbstractOAuth2TokenSet,
    InvalidGrantError,
    RefreshTransientError,
)
from parrot.auth.oauth2_base import CredentialPersistenceError  # noqa: F401  (re-raised, documented)
from parrot.auth.principal import Principal

logger = logging.getLogger(__name__)

_LEGACY_REVOKED_KEY = "oauth2:o365:legacy_revoked:{user_id}"
_LEGACY_REVOKED_TTL_SECONDS = 400 * 24 * 60 * 60   # outlives any OAUTH2_LEGACY_KEYS_UNTIL window


# Default delegated scopes — see docs/integrations/office365-oauth2.md
# for the per-tool mapping.
DEFAULT_O365_SCOPES: List[str] = [
    "openid",
    "profile",
    "offline_access",
    "User.Read",
    "Mail.Read",
    "Mail.Send",
    "Files.Read",
    "Files.ReadWrite",
    "Sites.Read.All",
    "Calendars.Read",
]


class O365TokenSet(AbstractOAuth2TokenSet):
    """Office 365 token set extension.

    Adds Microsoft Graph identity fields populated from ``/me``.
    """

    tenant_id: str = ""
    user_principal_name: str = ""
    id_token: Optional[str] = None
    grant_origin: Literal["authorization_code", "device_code"] = "authorization_code"


class O365OAuthManager(AbstractOAuth2Manager):
    """Microsoft Identity Platform OAuth 2.0 (PKCE + client_secret).

    The authorization and token endpoints embed the tenant ID; pass
    ``"common"`` to support both personal and work accounts in one app
    registration. ``handle_callback`` resolves user identity via
    ``GET https://graph.microsoft.com/v1.0/me`` and stores the result on
    :class:`O365TokenSet`.
    """

    provider_id: ClassVar[str] = "o365"
    default_scopes: ClassVar[List[str]] = DEFAULT_O365_SCOPES
    token_set_cls: ClassVar = O365TokenSet
    use_pkce: ClassVar[bool] = True
    require_client_secret: ClassVar[bool] = True

    GRAPH_ME_URL: ClassVar[str] = "https://graph.microsoft.com/v1.0/me"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        *,
        tenant_id: str = "common",
        **kwargs: Any,
    ) -> None:
        # Templated endpoints (per-instance, derived from tenant_id).
        self.tenant_id = tenant_id
        self.authorization_url = (
            f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize"
        )
        self.token_url = (
            f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
        )
        super().__init__(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            **kwargs,
        )

    # ------------------------------------------------------------------ url

    def authorization_url_extra_params(self) -> Dict[str, str]:
        """Force consent prompt and request the account selection screen.

        ``prompt=select_account`` lets the user pick a different tenant if
        they have several Microsoft accounts. ``access_type=offline`` is
        Microsoft's documented way to ensure a refresh_token comes back.
        """
        return {
            "prompt": "select_account",
            "response_mode": "query",
        }

    # ------------------------------------------------------------------ exchange

    async def _exchange_code(
        self, code: str, code_verifier: Optional[str],
    ) -> Dict[str, Any]:
        data: Dict[str, str] = {
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(self.scopes),
        }
        if code_verifier:
            data["code_verifier"] = code_verifier

        session = await self._get_session()
        async with session.post(
            self.token_url,
            data=urlencode(data),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ) as response:
            if response.status != 200:
                text = await response.text()
                raise ValueError(
                    f"O365 token exchange failed with status {response.status}: {text}"
                )
            return await response.json()

    async def _refresh_request(self, refresh_token: str) -> Dict[str, Any]:
        """Refresh against Entra; typed outcomes per S7 (no token material in errors)."""
        data = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": refresh_token,
            "scope": " ".join(self.scopes),
        }
        session = await self._get_session()
        try:
            async with session.post(
                self.token_url,
                data=urlencode(data),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ) as response:
                if response.status == 200:
                    return await response.json()
                status = response.status
                error_code = await self._oauth_error_code(response)
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise RefreshTransientError(f"O365 refresh network error: {type(exc).__name__}") from None

        if error_code == "invalid_grant":
            raise InvalidGrantError(f"O365 refresh token rejected (HTTP {status})")
        if status == 429 or status >= 500:
            raise RefreshTransientError(f"O365 refresh unavailable (HTTP {status})")
        raise RuntimeError(f"O365 token refresh failed (HTTP {status}, error={error_code or 'unknown'})")

    @staticmethod
    async def _oauth_error_code(response: aiohttp.ClientResponse) -> Optional[str]:
        """Return the OAuth ``error`` field, or None for a malformed response body."""
        try:
            payload = await response.json(content_type=None)
        except (ValueError, aiohttp.ContentTypeError):
            return None
        error_code = payload.get("error") if isinstance(payload, dict) else None
        return error_code if isinstance(error_code, str) else None

    async def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        """Public, stateless Entra refresh: exchange a refresh_token for a new token dict.

        Reused by the device-code resolver (FEAT-266) so it can silently
        refresh an expired Entra token via the same code path the 3LO flow
        already uses, without depending on the private :meth:`_refresh_request`
        hook. Does NOT persist the new token — the caller is responsible for
        persisting to its own canonical store (e.g. ``VaultTokenSync``).

        Args:
            refresh_token: The Entra refresh token to exchange.

        Returns:
            The raw JSON token response (``access_token``, ``refresh_token``,
            ``expires_in``, ``scope``, …).

        Raises:
            InvalidGrantError: When Microsoft returns ``invalid_grant``.
            RefreshTransientError: For network errors, rate limits, and 5xx responses.
            RuntimeError: For other OAuth failures.
        """
        return await self._refresh_request(refresh_token)

    async def _discover_identity(self, access_token: str) -> Dict[str, Any]:
        session = await self._get_session()
        async with session.get(
            self.GRAPH_ME_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        ) as response:
            if response.status != 200:
                text = await response.text()
                raise ValueError(
                    f"Graph /me failed with status {response.status}: {text}"
                )
            return await response.json()

    def _build_token_set(
        self,
        token_response: Dict[str, Any],
        identity: Dict[str, Any],
    ) -> O365TokenSet:
        now = time.time()
        scope_str = token_response.get("scope") or ""
        granted_scopes = scope_str.split() if scope_str else list(self.scopes)
        return O365TokenSet(
            access_token=token_response["access_token"],
            refresh_token=token_response.get("refresh_token", ""),
            expires_at=now + int(token_response.get("expires_in", 3600)),
            scopes=granted_scopes,
            granted_at=now,
            last_refreshed_at=now,
            account_id=identity.get("id", ""),
            display_name=identity.get("displayName", ""),
            email=identity.get("mail") or identity.get("userPrincipalName"),
            tenant_id=self.tenant_id,
            user_principal_name=identity.get("userPrincipalName", ""),
            id_token=token_response.get("id_token"),
        )

    # ------------------------------------------------------------------ device code (FEAT-777 M3)

    async def store_device_grant(
        self, principal: Principal, payload: Dict[str, Any], *, channel: str,
    ) -> O365TokenSet:
        """Persist a freshly minted device-code token response as the principal's single O365 record.

        Raises:
            CredentialPersistenceError: durable write failed (no Redis key is written).
            ValueError: identity discovery failed or ``payload`` has no access token.
        """
        if not payload.get("access_token"):
            raise ValueError("Device-code payload carries no access_token")
        identity = await self._discover_identity(payload["access_token"])
        token_set = self._build_token_set(payload, identity).model_copy(update={"grant_origin": "device_code"})
        async with self.principal_lock(principal.user_id):
            await self._persist_token(principal, token_set, minted=True)
        await self._upsert_row(principal, token_set, channel=channel)
        await self._publish("connection.completed", principal, token_set)
        self.logger.info("Stored o365 device-code grant for principal %s", principal.user_id)
        return token_set

    async def migrate_legacy_device_grant(
        self, principal: Principal, legacy: Dict[str, Any], *, channel: str,
    ) -> Optional[O365TokenSet]:
        """Convert one legacy ``o365:*`` dict (absolute ``expires_at``); ``None`` when a current record already wins.

        Raises:
            InvalidGrantError: legacy refresh token is dead (caller falls back to the device flow; legacy kept).
            RefreshTransientError: transient refresh/discovery failure (retryable; legacy kept).
            CredentialPersistenceError: durable write failed (legacy kept).
        """
        if not await self.legacy_migration_allowed(principal.user_id):
            return None
        now = time.time()
        access_token = legacy.get("access_token") or ""
        refresh_token = legacy.get("refresh_token") or ""
        expires_at = self._parse_absolute_expiry(legacy.get("expires_at"))
        scope_str = legacy.get("scope") or ""
        id_token = legacy.get("id_token")
        granted_at = now
        if access_token and expires_at is not None and expires_at > now + O365TokenSet._EXPIRY_LEEWAY_SECONDS:
            usable_token = access_token  # keep the stored absolute expiry EXACTLY
        else:
            if not refresh_token:
                raise InvalidGrantError("Legacy o365 grant has no usable access or refresh token")
            refreshed = await self.refresh_access_token(refresh_token)  # InvalidGrant/Transient propagate
            usable_token = refreshed.get("access_token") or ""
            if not usable_token:
                raise RefreshTransientError("O365 refresh returned no access token")
            expires_at = now + int(refreshed.get("expires_in", 3600))
            refresh_token = refreshed.get("refresh_token") or refresh_token
            scope_str = refreshed.get("scope") or scope_str
            id_token = refreshed.get("id_token") or id_token
        try:
            identity = await self._discover_identity(usable_token)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
            raise RefreshTransientError(
                f"O365 identity discovery failed: {type(exc).__name__}"
            ) from None
        token_set = O365TokenSet(
            access_token=usable_token,
            refresh_token=refresh_token,
            expires_at=float(expires_at),
            scopes=scope_str.split() if scope_str else list(self.scopes),
            granted_at=granted_at,
            last_refreshed_at=now,
            account_id=identity.get("id", ""),
            display_name=identity.get("displayName", ""),
            email=identity.get("mail") or identity.get("userPrincipalName"),
            tenant_id=legacy.get("tenant_id") or self.tenant_id,
            user_principal_name=identity.get("userPrincipalName", ""),
            id_token=id_token,
            grant_origin="device_code",
        )
        async with self.principal_lock(principal.user_id):
            current = (
                await self._read_token_from_cache(principal.user_id)
                or await self._read_token_from_store(principal.user_id)
            )
            if current is not None or not await self.legacy_migration_allowed(principal.user_id):
                return None  # a newer grant or a disconnect wins; never overwrite / resurrect
            await self._persist_token(principal, token_set, minted=True)
        await self._upsert_row(principal, token_set, channel=channel)
        await self._publish("connection.completed", principal, token_set)
        return token_set

    @staticmethod
    def _parse_absolute_expiry(value: Any) -> Optional[float]:
        """Return a finite positive epoch float, or ``None`` when missing/invalid."""
        if value is None or isinstance(value, bool):
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        if parsed != parsed or parsed in (float("inf"), float("-inf")) or parsed <= 0:
            return None
        return parsed

    async def legacy_migration_allowed(self, user_id: str) -> bool:
        """``False`` once the principal disconnected o365: its legacy grant must never be re-imported."""
        return not await self.redis.get(_LEGACY_REVOKED_KEY.format(user_id=user_id))

    async def revoke(self, channel: str, user_id: str, *, channel_user_id: Optional[str] = None) -> None:
        """Revoke as the base class does, then tombstone legacy migration for this principal."""
        await super().revoke(channel, user_id, channel_user_id=channel_user_id)
        await self.redis.set(_LEGACY_REVOKED_KEY.format(user_id=user_id), "1", ex=_LEGACY_REVOKED_TTL_SECONDS)

    async def _upsert_row(self, principal: Principal, token_set: O365TokenSet, *, channel: str) -> None:
        """Write the ``users_integrations`` row the 3LO routes write after ``handle_callback``."""
        from parrot.auth.oauth2.service import IntegrationsService  # lazy: service imports the registry
        from parrot.auth.oauth2.persistence import upsert_users_integration

        row = await IntegrationsService().persist_credential(
            principal.user_id, self.provider_id, token_set,
            channel=channel, canonical_identity=principal.canonical_identity,
        )
        if getattr(row, "grant_origin", None) != token_set.grant_origin:
            # persist_credential is provider-agnostic and does not carry grant_origin.
            await upsert_users_integration(row.model_copy(update={"grant_origin": token_set.grant_origin}))
