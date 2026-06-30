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

import logging
import time
from typing import Any, ClassVar, Dict, List, Optional
from urllib.parse import urlencode

import aiohttp

from parrot.auth.oauth2_base import AbstractOAuth2Manager, AbstractOAuth2TokenSet


logger = logging.getLogger(__name__)


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
        data = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": refresh_token,
            "scope": " ".join(self.scopes),
        }
        session = await self._get_session()
        async with session.post(
            self.token_url,
            data=urlencode(data),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ) as response:
            if response.status == 400 or response.status == 401:
                text = await response.text()
                # 400 invalid_grant is Microsoft's "your refresh token died".
                raise PermissionError(
                    f"O365 refresh token rejected (HTTP {response.status}): {text}"
                )
            if response.status != 200:
                text = await response.text()
                raise aiohttp.ClientError(
                    f"O365 token refresh failed with status {response.status}: {text}"
                )
            return await response.json()

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
            PermissionError: When Microsoft rejects the refresh token
                (HTTP 400/401 — dead/revoked refresh token).
            aiohttp.ClientError: On any other non-200 response.
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
