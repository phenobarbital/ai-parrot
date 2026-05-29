"""
Minimal async Microsoft Graph client for the Teams HITL channel.

Provides email-to-AAD resolution used by TeamsHumanChannel.send_interaction
to map a recipient email address to an Azure AD object ID before opening
a proactive 1:1 conversation.

This module has NO dependency on botbuilder and does NOT import aiogram.
It uses only aiohttp (project-standard async HTTP) and pydantic (data models).

Graph app credentials:
    The app registration must have User.Read.All (application permission).
    Credentials are sourced from navconfig / environment variables at boot;
    never hardcoded here.

Usage::

    client = GraphClient(
        client_id="...",
        client_secret="...",
        tenant_id="...",
    )
    user = await client.get_user_by_email("manager@contoso.com")
    if user is None:
        # resolution failed — caller should return False
        ...
    manager = await client.get_user_manager(user.upn)
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

import aiohttp
from pydantic import BaseModel, Field


# ── Data models ───────────────────────────────────────────────────────────────

class ResolvedTeamsUser(BaseModel):
    """Result of a successful Graph email-to-AAD resolution.

    Attributes:
        aad_object_id: Azure AD object ID (GUID) for the user.
        upn: User Principal Name (often the same as email for cloud accounts).
        email: The email address that was resolved.
        service_url: Optional Bot Framework service URL associated with the
            user (populated from the ConversationReference cache, not from
            Graph directly).
    """

    aad_object_id: str = Field(..., description="Azure AD object ID (GUID).")
    upn: str = Field(..., description="User Principal Name.")
    email: str = Field(..., description="Resolved email address.")
    service_url: Optional[str] = Field(
        default=None,
        description="Bot Framework service URL (from convref cache, not Graph).",
    )


# ── GraphClient ───────────────────────────────────────────────────────────────

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_TOKEN_URL_TPL = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
_GRAPH_SCOPE = "https://graph.microsoft.com/.default"


class GraphClient:
    """Async Microsoft Graph client for the Teams HITL channel.

    Handles:
    - Client-credentials token acquisition with in-process expiry caching.
    - ``get_user_by_email``: resolves an email to a
      :class:`ResolvedTeamsUser` via ``/users/{upn}`` first, falling back
      to ``/users?$filter=mail eq '{email}'`` on 404.
    - ``get_user_manager``: returns the Graph user object for ``/users/{upn}/manager``.

    All methods return ``None`` (never raise) on any Graph error so the
    caller (``TeamsHumanChannel``) can fail-fast cleanly.

    Args:
        client_id: Graph app registration client ID.
        client_secret: Graph app registration client secret.
        tenant_id: AAD tenant ID (for the token URL).
        logger: Optional logger. Defaults to module-level logger.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        tenant_id: str,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._tenant_id = tenant_id
        self.logger = logger or logging.getLogger(__name__)

        # In-process token cache: (access_token, expiry_epoch)
        self._token: Optional[str] = None
        self._token_expiry: float = 0.0

    # ── Token acquisition ──────────────────────────────────────────────────

    async def _get_access_token(self) -> Optional[str]:
        """Acquire (or return cached) an access token for Graph.

        Returns:
            The bearer token string, or ``None`` on failure.
        """
        now = time.monotonic()
        # Refresh 60 s before actual expiry to avoid clock-skew races.
        if self._token and now < self._token_expiry - 60:
            return self._token

        token_url = _TOKEN_URL_TPL.format(tenant_id=self._tenant_id)
        payload = {
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "scope": _GRAPH_SCOPE,
            "grant_type": "client_credentials",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(token_url, data=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self._token = data.get("access_token")
                        expires_in = int(data.get("expires_in", 3600))
                        self._token_expiry = now + expires_in
                        return self._token
                    body = await resp.text()
                    self.logger.error(
                        "Graph token acquisition failed (HTTP %s): %s",
                        resp.status,
                        body[:200],
                    )
                    return None
        except Exception:  # noqa: BLE001
            self.logger.exception("Exception during Graph token acquisition")
            return None

    def _auth_headers(self, token: str) -> Dict[str, str]:
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # ── Public API ─────────────────────────────────────────────────────────

    async def get_user_by_email(self, email: str) -> Optional[ResolvedTeamsUser]:
        """Resolve an email address to a :class:`ResolvedTeamsUser`.

        Resolution strategy:
        1. Try ``GET /users/{email}`` (works when ``email == UPN``).
        2. On 404, fall back to ``GET /users?$filter=mail eq '{email}'``.
        3. Return ``None`` on any error or empty result.

        Args:
            email: The recipient's email address.

        Returns:
            A resolved user object, or ``None`` on failure.
        """
        token = await self._get_access_token()
        if not token:
            return None

        headers = self._auth_headers(token)

        # ── Step 1: direct UPN lookup ──────────────────────────────────────
        user_data = await self._get_user_direct(email, headers)
        if user_data is not None:
            return self._build_resolved_user(user_data, email)

        # ── Step 2: mail-filter fallback ───────────────────────────────────
        self.logger.debug(
            "Direct UPN lookup for %r failed; trying mail-filter fallback.", email
        )
        user_data = await self._get_user_by_mail_filter(email, headers)
        if user_data is not None:
            return self._build_resolved_user(user_data, email)

        self.logger.warning("Could not resolve user for email %r via Graph.", email)
        return None

    async def _get_user_direct(
        self, upn: str, headers: Dict[str, str]
    ) -> Optional[Dict[str, Any]]:
        """Try ``GET /users/{upn}`` and return the raw JSON, or None on 404/error."""
        url = f"{_GRAPH_BASE}/users/{upn}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    if resp.status == 404:
                        return None
                    body = await resp.text()
                    self.logger.error(
                        "Graph /users/%s returned HTTP %s: %s",
                        upn,
                        resp.status,
                        body[:200],
                    )
                    return None
        except Exception:  # noqa: BLE001
            self.logger.exception("Exception calling Graph /users/%s", upn)
            return None

    async def _get_user_by_mail_filter(
        self, email: str, headers: Dict[str, str]
    ) -> Optional[Dict[str, Any]]:
        """Try ``GET /users?$filter=mail eq '{email}'`` and return the first hit."""
        url = f"{_GRAPH_BASE}/users"
        params = {
            "$filter": f"mail eq '{email}'",
            "$select": "id,userPrincipalName,mail",
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        users = data.get("value", [])
                        if users:
                            return users[0]
                        return None
                    body = await resp.text()
                    self.logger.error(
                        "Graph mail-filter for %r returned HTTP %s: %s",
                        email,
                        resp.status,
                        body[:200],
                    )
                    return None
        except Exception:  # noqa: BLE001
            self.logger.exception("Exception calling Graph mail-filter for %r", email)
            return None

    @staticmethod
    def _build_resolved_user(
        data: Dict[str, Any], original_email: str
    ) -> ResolvedTeamsUser:
        """Build a :class:`ResolvedTeamsUser` from a Graph user dict.

        Args:
            data: Raw Graph user object (``id``, ``userPrincipalName``, ``mail``).
            original_email: The email address used for the original lookup.

        Returns:
            A populated :class:`ResolvedTeamsUser`.
        """
        return ResolvedTeamsUser(
            aad_object_id=data.get("id", ""),
            upn=data.get("userPrincipalName", original_email),
            email=data.get("mail") or original_email,
        )

    async def get_user_manager(self, upn: str) -> Optional[Dict[str, Any]]:
        """Return the Graph user object for a user's manager.

        Used by the future ``TargetResolver`` (escalation feature) as a
        backend lookup. Returns ``None`` on error or missing manager.

        Args:
            upn: The user's UPN whose manager to retrieve.

        Returns:
            Raw Graph user dict for the manager, or ``None``.
        """
        token = await self._get_access_token()
        if not token:
            return None

        url = f"{_GRAPH_BASE}/users/{upn}/manager"
        headers = self._auth_headers(token)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    if resp.status == 404:
                        self.logger.debug("No manager found for UPN %r.", upn)
                        return None
                    body = await resp.text()
                    self.logger.error(
                        "Graph /users/%s/manager returned HTTP %s: %s",
                        upn,
                        resp.status,
                        body[:200],
                    )
                    return None
        except Exception:  # noqa: BLE001
            self.logger.exception("Exception calling Graph /users/%s/manager", upn)
            return None
