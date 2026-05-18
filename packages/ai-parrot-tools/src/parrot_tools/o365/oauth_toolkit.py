"""Office 365 toolkit with per-user OAuth 2.0 (delegated / 3LO) auth.

Concrete :class:`parrot.tools.toolkit.AbstractToolkit` that resolves
per-user Microsoft Graph access tokens through a
:class:`parrot.auth.credentials.CredentialResolver` at tool-call time —
the same pattern used by :class:`parrot_tools.jiratoolkit.JiraToolkit`
for ``oauth2_3lo`` mode.

Each public async method becomes an LLM-visible tool. ``_pre_execute``
extracts ``_permission_context`` from kwargs, resolves the token, and
caches an ``aiohttp.ClientSession`` keyed by ``channel:user_id``. The
session sends ``Authorization: Bearer <access_token>`` headers; on a
401 from Graph the cache entry is evicted so the next call re-fetches
from the manager (which may transparently refresh the token).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import aiohttp

from parrot.auth.exceptions import AuthorizationRequired
from parrot.tools.toolkit import AbstractToolkit

if TYPE_CHECKING:  # pragma: no cover
    from parrot.auth.credentials import CredentialResolver
    from parrot.auth.o365_oauth import O365TokenSet


logger = logging.getLogger(__name__)


GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class Office365Toolkit(AbstractToolkit):
    """Microsoft Graph toolkit with delegated per-user OAuth tokens.

    Tools generated automatically from public async methods:

    - :meth:`read_inbox` — list recent messages.
    - :meth:`search_messages` — full-text search the user's mailbox.
    - :meth:`send_email` — send a plain-text message as the user.
    - :meth:`list_onedrive_files` — list files under a OneDrive path.
    - :meth:`list_sharepoint_sites` — search SharePoint sites the user can see.
    - :meth:`list_upcoming_events` — read upcoming calendar events.

    Args:
        credential_resolver: Resolver bound to a
            :class:`parrot.auth.o365_oauth.O365OAuthManager` (typically via
            :class:`parrot.auth.credentials.OAuthCredentialResolver`).
        tenant_id: Microsoft tenant identifier (``"common"``, ``"organizations"``,
            or a GUID). Recorded on each token set; used only for diagnostics.
        cache_size: Maximum number of (channel, user_id) → session entries.
    """

    tool_prefix: Optional[str] = "o365"

    _CLIENT_CACHE_MAX_SIZE: int = 100
    _OAUTH_SCOPES: tuple = (
        "User.Read",
        "Mail.Read",
        "Mail.Send",
        "Files.Read",
        "Files.ReadWrite",
        "Sites.Read.All",
        "Calendars.Read",
    )

    def __init__(
        self,
        credential_resolver: "CredentialResolver",
        tenant_id: str = "common",
        cache_size: int = 100,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        if credential_resolver is None:
            raise ValueError(
                "Office365Toolkit requires a credential_resolver"
            )
        self.credential_resolver = credential_resolver
        self.tenant_id = tenant_id
        self._CLIENT_CACHE_MAX_SIZE = cache_size
        # Per-user (token_fingerprint → token) cache keyed by "channel:user_id".
        self._token_cache: Dict[str, tuple] = {}

    # ------------------------------------------------------------------ pre

    async def _pre_execute(self, tool_name: str, **kwargs: Any) -> None:
        """Resolve the per-user token before the tool runs.

        Mirrors the pattern at ``parrot_tools.jiratoolkit.JiraToolkit._pre_execute``.
        Raises :class:`AuthorizationRequired` when the user has not
        authorized yet, embedding the consent URL the agent should
        surface back to the user.
        """
        perm_ctx = kwargs.get("_permission_context")
        if perm_ctx is None:
            raise AuthorizationRequired(
                tool_name=tool_name,
                message=(
                    "Permission context is required for Office365 tools. "
                    "The call must be routed through ToolManager with a "
                    "populated PermissionContext."
                ),
                provider="o365",
                scopes=list(self._OAUTH_SCOPES),
            )

        user_id = getattr(perm_ctx, "user_id", None)
        channel = getattr(perm_ctx, "channel", None) or "unknown"
        if not user_id:
            raise AuthorizationRequired(
                tool_name=tool_name,
                message="Cannot resolve Office365 credentials without a user_id.",
                provider="o365",
                scopes=list(self._OAUTH_SCOPES),
            )

        token_set = await self.credential_resolver.resolve(channel, user_id)
        if token_set is None:
            try:
                auth_url = await self.credential_resolver.get_auth_url(
                    channel, user_id,
                )
            except NotImplementedError:
                auth_url = None
            raise AuthorizationRequired(
                tool_name=tool_name,
                message="Please authorize your Office365 account to use this tool.",
                auth_url=auth_url,
                provider="o365",
                scopes=list(self._OAUTH_SCOPES),
            )

        # Cache by stable token fingerprint so a refresh forces a new entry.
        user_key = f"{channel}:{user_id}"
        access_token = getattr(token_set, "access_token", "")
        fingerprint = (
            (access_token[:16] + access_token[-8:])
            if len(access_token) > 24 else access_token
        )
        cached = self._token_cache.get(user_key)
        if cached is None or cached[1] != fingerprint:
            if len(self._token_cache) >= self._CLIENT_CACHE_MAX_SIZE:
                oldest = next(iter(self._token_cache))
                self._token_cache.pop(oldest, None)
            self._token_cache[user_key] = (token_set, fingerprint)

        # Stash on the toolkit so the tool method picks it up.
        self._current_token = token_set
        return None

    # ------------------------------------------------------------------ http

    async def _graph_request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Execute a Microsoft Graph REST call using the current user's token.

        Args:
            method: HTTP method, e.g. ``"GET"`` or ``"POST"``.
            path: Path relative to ``https://graph.microsoft.com/v1.0``.
            json_body: Optional JSON body.
            params: Optional query parameters.
        """
        token = getattr(self, "_current_token", None)
        if token is None:
            raise RuntimeError(
                "Office365Toolkit._graph_request called outside a tool "
                "execution — _current_token is not set."
            )
        url = path if path.startswith("http") else f"{GRAPH_BASE}{path}"
        headers = {
            "Authorization": f"Bearer {token.access_token}",
            "Accept": "application/json",
        }
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
        ) as session:
            async with session.request(
                method, url, headers=headers, params=params, json=json_body,
            ) as response:
                if response.status == 204:
                    return None
                if response.status >= 400:
                    text = await response.text()
                    raise RuntimeError(
                        f"Graph {method} {path} failed (HTTP {response.status}): {text}"
                    )
                if response.headers.get("Content-Type", "").startswith("application/json"):
                    return await response.json()
                return await response.text()

    # ------------------------------------------------------------------ tools

    async def read_inbox(self, top: int = 10) -> List[Dict[str, Any]]:
        """Read the user's most recent inbox messages.

        Args:
            top: Number of messages to return (default 10, max 50).

        Returns:
            List of messages with subject, sender, received timestamp, and
            a 200-character preview.
        """
        top = max(1, min(int(top), 50))
        data = await self._graph_request(
            "GET", "/me/mailFolders/inbox/messages",
            params={
                "$top": str(top),
                "$select": "id,subject,from,receivedDateTime,bodyPreview",
                "$orderby": "receivedDateTime desc",
            },
        )
        return [
            {
                "id": m.get("id"),
                "subject": m.get("subject"),
                "from": (
                    (m.get("from") or {}).get("emailAddress", {}).get("address")
                ),
                "received": m.get("receivedDateTime"),
                "preview": (m.get("bodyPreview") or "")[:200],
            }
            for m in data.get("value", [])
        ]

    async def search_messages(self, query: str, top: int = 10) -> List[Dict[str, Any]]:
        """Search the user's mailbox using the Graph ``$search`` operator.

        Args:
            query: Search text (e.g. ``"invoice from contoso"``).
            top: Number of results (default 10, max 50).

        Returns:
            Messages matching the query, with the same fields as :meth:`read_inbox`.
        """
        top = max(1, min(int(top), 50))
        data = await self._graph_request(
            "GET", "/me/messages",
            params={
                "$top": str(top),
                "$search": f'"{query}"',
                "$select": "id,subject,from,receivedDateTime,bodyPreview",
            },
        )
        return [
            {
                "id": m.get("id"),
                "subject": m.get("subject"),
                "from": (
                    (m.get("from") or {}).get("emailAddress", {}).get("address")
                ),
                "received": m.get("receivedDateTime"),
                "preview": (m.get("bodyPreview") or "")[:200],
            }
            for m in data.get("value", [])
        ]

    async def send_email(
        self,
        to: List[str],
        subject: str,
        body: str,
        cc: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Send an email from the user's mailbox.

        Args:
            to: Recipient addresses.
            subject: Subject line.
            body: Plain-text body.
            cc: Optional CC recipients.

        Returns:
            ``{"status": "sent"}`` on success.
        """
        message = {
            "message": {
                "subject": subject,
                "body": {"contentType": "Text", "content": body},
                "toRecipients": [
                    {"emailAddress": {"address": addr}} for addr in to
                ],
                "ccRecipients": (
                    [{"emailAddress": {"address": addr}} for addr in cc]
                    if cc else []
                ),
            },
            "saveToSentItems": True,
        }
        await self._graph_request("POST", "/me/sendMail", json_body=message)
        return {"status": "sent", "to": to, "subject": subject}

    async def list_onedrive_files(
        self, path: str = "/", top: int = 25,
    ) -> List[Dict[str, Any]]:
        """List files in the user's OneDrive under *path*.

        Args:
            path: OneDrive folder path. ``"/"`` lists the drive root.
            top: Maximum entries to return (default 25, max 200).

        Returns:
            List of items with ``name``, ``id``, ``size``, ``last_modified``
            and ``is_folder`` (bool).
        """
        top = max(1, min(int(top), 200))
        path = path.strip()
        if not path or path == "/":
            url_path = "/me/drive/root/children"
        else:
            clean = path.lstrip("/")
            url_path = f"/me/drive/root:/{clean}:/children"
        data = await self._graph_request(
            "GET", url_path,
            params={"$top": str(top), "$select": "id,name,size,lastModifiedDateTime,folder"},
        )
        return [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "size": item.get("size"),
                "last_modified": item.get("lastModifiedDateTime"),
                "is_folder": "folder" in item,
            }
            for item in data.get("value", [])
        ]

    async def list_sharepoint_sites(
        self, query: str = "", top: int = 10,
    ) -> List[Dict[str, Any]]:
        """Search SharePoint sites the user has access to.

        Args:
            query: Free-text query (``""`` returns the user's followed sites).
            top: Maximum results (default 10, max 50).

        Returns:
            List of sites with ``id``, ``name``, ``web_url``.
        """
        top = max(1, min(int(top), 50))
        if query:
            data = await self._graph_request(
                "GET", "/sites",
                params={"search": query, "$top": str(top)},
            )
        else:
            data = await self._graph_request(
                "GET", "/me/followedSites", params={"$top": str(top)},
            )
        return [
            {
                "id": site.get("id"),
                "name": site.get("displayName") or site.get("name"),
                "web_url": site.get("webUrl"),
            }
            for site in data.get("value", [])
        ]

    async def list_upcoming_events(self, top: int = 10) -> List[Dict[str, Any]]:
        """List the user's upcoming calendar events ordered by start time.

        Args:
            top: Number of events to return (default 10, max 50).

        Returns:
            List of events with ``subject``, ``start``, ``end``, ``organizer``,
            ``location``.
        """
        top = max(1, min(int(top), 50))
        data = await self._graph_request(
            "GET", "/me/events",
            params={
                "$top": str(top),
                "$select": "id,subject,start,end,organizer,location",
                "$orderby": "start/dateTime",
            },
        )
        return [
            {
                "id": ev.get("id"),
                "subject": ev.get("subject"),
                "start": (ev.get("start") or {}).get("dateTime"),
                "end": (ev.get("end") or {}).get("dateTime"),
                "organizer": (
                    (ev.get("organizer") or {}).get("emailAddress", {}).get("address")
                ),
                "location": (ev.get("location") or {}).get("displayName"),
            }
            for ev in data.get("value", [])
        ]
