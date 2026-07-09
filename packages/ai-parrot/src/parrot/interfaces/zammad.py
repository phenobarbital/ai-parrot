"""Zammad helpdesk interface via REST API v1.

Provides an async-first interface to Zammad servers for ticket, user,
article, and attachment operations. Supports Bearer token authentication
and "On Behalf Of" impersonation via a configurable HTTP header.
"""
from __future__ import annotations

import asyncio
import os
import re
import tempfile
from typing import Any, Optional

import aiohttp
from pydantic import BaseModel, Field
from navconfig.logging import logging

from parrot.conf import (
    ZAMMAD_INSTANCE,
    ZAMMAD_TOKEN,
    ZAMMAD_DEFAULT_CUSTOMER,
    ZAMMAD_DEFAULT_GROUP,
    ZAMMAD_DEFAULT_CATALOG,
    ZAMMAD_ORGANIZATION,
    ZAMMAD_DEFAULT_ROLE,
)


# ── Exceptions ───────────────────────────────────────────────────────────────

class ZammadError(Exception):
    """Base exception for Zammad REST API errors.

    Attributes:
        status_code: HTTP status code returned by Zammad, if any.
    """

    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        """Initialize ZammadError.

        Args:
            message: Human-readable error message.
            status_code: HTTP status code returned by Zammad, if known.
        """
        super().__init__(message)
        self.status_code = status_code


class ZammadAuthError(ZammadError):
    """Raised when authentication fails (401 response)."""


class ZammadConnectionError(ZammadError):
    """Raised on network or connection failures."""


# ── Pydantic Models ───────────────────────────────────────────────────────────

class ZammadConfig(BaseModel):
    """Configuration for Zammad API connection."""

    instance_url: str = Field(..., description="Zammad instance base URL")
    token: str = Field(..., description="API token for authentication")
    default_customer: Optional[str] = Field(default=None, description="Default customer email")
    default_group: Optional[str] = Field(default=None, description="Default ticket group")
    default_catalog: Optional[str] = Field(default=None, description="Default service catalog")
    organization: Optional[str] = Field(default=None, description="Default organization")
    default_role: str = Field(default="Customer", description="Default role for new users")
    timeout: int = Field(default=30, description="Request timeout in seconds")
    verify_ssl: bool = Field(default=True, description="Verify SSL certificates")
    on_behalf_of_header: str = Field(
        default="From",
        description="Header name for on-behalf-of; use 'X-On-Behalf-Of' for older Zammad instances",
    )
    attachment_dir: Optional[str] = Field(
        default=None,
        description="Directory to save downloaded attachments; defaults to a temp dir",
    )


class TicketCreatePayload(BaseModel):
    """Payload for creating a Zammad ticket."""

    title: str = Field(..., description="Ticket title")
    group: str = Field(..., description="Ticket group/queue")
    customer: str = Field(..., description="Customer email or ID")
    article_subject: Optional[str] = Field(default=None, description="Article subject")
    article_body: str = Field(..., description="Article body text")
    article_type: str = Field(default="note", description="Article type")
    article_internal: bool = Field(default=False, description="Internal note flag")
    priority_id: Optional[int] = Field(default=None, description="Priority ID")
    state_id: Optional[int] = Field(default=None, description="State ID")
    on_behalf_of: Optional[str] = Field(
        default=None, description="User ID/login/email for on-behalf-of header"
    )
    attachments: Optional[list[dict[str, str]]] = Field(
        default=None,
        description=(
            "Optional list of attachment dicts with 'filename', 'data' "
            "(base64-encoded content), and 'mime-type' keys, sent as part "
            "of the ticket's initial article."
        ),
    )


class TicketUpdatePayload(BaseModel):
    """Payload for updating a Zammad ticket."""

    ticket_id: int = Field(..., description="Ticket ID to update")
    title: Optional[str] = Field(default=None, description="New title")
    group: Optional[str] = Field(default=None, description="New group")
    state_id: Optional[int] = Field(default=None, description="New state ID")
    priority_id: Optional[int] = Field(default=None, description="New priority ID")
    article_body: Optional[str] = Field(default=None, description="Article body for the update")
    article_type: str = Field(default="note", description="Article type")
    article_internal: bool = Field(default=True, description="Internal note flag")
    on_behalf_of: Optional[str] = Field(
        default=None, description="User ID/login/email for on-behalf-of header"
    )


class UserCreatePayload(BaseModel):
    """Payload for creating a Zammad user."""

    firstname: str = Field(..., description="First name")
    lastname: str = Field(..., description="Last name")
    email: str = Field(..., description="Email address")
    organization: Optional[str] = Field(default=None, description="Organization name")
    roles: list[str] = Field(default_factory=lambda: ["Customer"], description="Roles")
    active: bool = Field(default=True, description="Active flag")


# ── Helpers ────────────────────────────────────────────────────────────────

_FILENAME_RE = re.compile(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', re.IGNORECASE)


def _extract_filename(content_disposition: str, fallback: str) -> str:
    """Extract a safe filename from a ``Content-Disposition`` header value.

    The returned name is reduced to its basename to prevent path-traversal
    writes (e.g. a malicious ``filename="../../etc/passwd"``) since the value
    is server-controlled and later joined onto the attachment directory.

    Args:
        content_disposition: Raw ``Content-Disposition`` header value.
        fallback: Filename to use when none can be extracted.

    Returns:
        The extracted, sanitized filename, or ``fallback`` if not found.
    """
    if not content_disposition:
        return fallback
    match = _FILENAME_RE.search(content_disposition)
    if not match:
        return fallback
    # Strip any directory components — never trust a server-supplied path.
    candidate = os.path.basename(match.group(1).strip())
    return candidate or fallback


def _write_bytes(path: str, data: bytes) -> None:
    """Write binary data to a file path, creating parent directories.

    Args:
        path: Destination file path.
        data: Binary content to write.
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)


# ── ZammadInterface ───────────────────────────────────────────────────────────

class ZammadInterface:
    """Async interface for Zammad REST API v1.

    Supports Bearer token authentication and "On Behalf Of" impersonation
    via a configurable HTTP header (defaults to ``From``, configurable to
    ``X-On-Behalf-Of`` for older Zammad instances).

    Example:
        async with ZammadInterface(
            instance_url="https://support.example.com",
            token="my-api-token",
        ) as zammad:
            ticket = await zammad.get_ticket(42)
    """

    def __init__(
        self,
        instance_url: str | None = None,
        token: str | None = None,
        default_customer: str | None = None,
        default_group: str | None = None,
        default_catalog: str | None = None,
        organization: str | None = None,
        default_role: str | None = None,
        timeout: int | None = None,
        verify_ssl: bool | None = None,
        on_behalf_of_header: str = "From",
        attachment_dir: str | None = None,
    ) -> None:
        """Initialize ZammadInterface.

        Falls back to ``parrot.conf`` values when parameters are not provided.

        Args:
            instance_url: Zammad instance base URL.
            token: API token for Bearer authentication.
            default_customer: Default customer email.
            default_group: Default ticket group.
            default_catalog: Default service catalog.
            organization: Default organization.
            default_role: Default role for new users.
            timeout: Request timeout in seconds (default 30).
            verify_ssl: Verify SSL certificates (default True).
            on_behalf_of_header: Header name for on-behalf-of impersonation.
            attachment_dir: Directory to save downloaded attachments;
                defaults to a temp dir.
        """
        resolved_url = instance_url or ZAMMAD_INSTANCE
        resolved_token = token or ZAMMAD_TOKEN
        if not resolved_url:
            raise ZammadError(
                "Zammad instance URL is required: pass instance_url or set "
                "ZAMMAD_INSTANCE."
            )
        if not resolved_token:
            raise ZammadError(
                "Zammad API token is required: pass token or set ZAMMAD_TOKEN."
            )

        self.config = ZammadConfig(
            instance_url=resolved_url,
            token=resolved_token,
            default_customer=default_customer or ZAMMAD_DEFAULT_CUSTOMER,
            default_group=default_group or ZAMMAD_DEFAULT_GROUP,
            default_catalog=default_catalog or ZAMMAD_DEFAULT_CATALOG,
            organization=organization or ZAMMAD_ORGANIZATION,
            default_role=default_role or ZAMMAD_DEFAULT_ROLE or "Customer",
            timeout=timeout if timeout is not None else 30,
            verify_ssl=verify_ssl if verify_ssl is not None else True,
            on_behalf_of_header=on_behalf_of_header,
            # Left as-is (possibly None); a temp dir is created lazily on the
            # first attachment download so unused interfaces leave no dangling
            # directories behind.
            attachment_dir=attachment_dir,
        )
        self._session: aiohttp.ClientSession | None = None
        self.logger = logging.getLogger("parrot.interfaces.zammad")

    def _ensure_attachment_dir(self) -> str:
        """Return the attachment directory, creating a temp dir on first use.

        Returns:
            The configured ``attachment_dir``, or a lazily-created temp
            directory when none was configured.
        """
        if not self.config.attachment_dir:
            self.config.attachment_dir = tempfile.mkdtemp(prefix="zammad_attachments_")
        return self.config.attachment_dir

    # ── Session Management ────────────────────────────────────────────────────

    async def _get_session(self) -> aiohttp.ClientSession:
        """Lazily create and return the aiohttp ClientSession.

        Returns:
            An active ``aiohttp.ClientSession`` configured with auth headers,
            timeout, and SSL verification.
        """
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.config.timeout)
            connector = aiohttp.TCPConnector(ssl=self.config.verify_ssl)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
                headers={
                    "Authorization": f"Bearer {self.config.token}",
                    "Content-Type": "application/json",
                },
            )
        return self._session

    async def close(self) -> None:
        """Close the underlying aiohttp session explicitly."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    # ── Context Manager ───────────────────────────────────────────────────────

    async def __aenter__(self) -> "ZammadInterface":
        """Enter the async context manager, creating the HTTP session.

        Returns:
            Self, ready for use.
        """
        await self._get_session()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit the async context manager, closing the HTTP session.

        Args:
            exc_type: Exception type, if any.
            exc_val: Exception value, if any.
            exc_tb: Exception traceback, if any.
        """
        await self.close()

    # ── Core HTTP Method ──────────────────────────────────────────────────────

    async def _request(
        self,
        method: str,
        path: str,
        data: dict | None = None,
        params: dict | None = None,
        on_behalf_of: str | None = None,
    ) -> dict | list:
        """Dispatch an HTTP request against the Zammad REST API v1.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE).
            path: API path, e.g. ``/api/v1/tickets``.
            data: JSON-serializable request body.
            params: Query string parameters.
            on_behalf_of: User ID/login/email to act on behalf of. When
                provided, sent via the configured ``on_behalf_of_header``.

        Returns:
            The parsed JSON response (dict or list), or an empty dict for
            204 No Content responses.

        Raises:
            ZammadAuthError: On a 401 response.
            ZammadError: On any other non-2xx response.
            ZammadConnectionError: On network or connection failures.
        """
        session = await self._get_session()
        url = f"{self.config.instance_url.rstrip('/')}{path}"
        headers: dict[str, str] = {}
        if on_behalf_of:
            headers[self.config.on_behalf_of_header] = str(on_behalf_of)

        try:
            async with session.request(
                method, url, json=data, params=params, headers=headers
            ) as resp:
                if resp.status == 401:
                    text = await resp.text()
                    raise ZammadAuthError(
                        f"Zammad authentication failed ({resp.status}) for "
                        f"{method} {path}: {text[:200]}",
                        status_code=resp.status,
                    )
                if resp.status >= 400:
                    text = await resp.text()
                    raise ZammadError(
                        f"Zammad API error ({resp.status}) for {method} {path}: "
                        f"{text[:200]}",
                        status_code=resp.status,
                    )
                if resp.status == 204:
                    return {}
                return await resp.json()
        except aiohttp.ClientError as exc:
            raise ZammadConnectionError(
                f"Network error contacting Zammad at {url}: {exc}"
            ) from exc

    # ── Ticket Operations ─────────────────────────────────────────────────────

    async def list_tickets(
        self,
        state_ids: list[int] | None = None,
        page: int = 1,
        per_page: int = 100,
    ) -> dict[str, Any]:
        """List tickets, optionally filtered by state.

        Args:
            state_ids: Optional list of state IDs to filter by.
            page: Page number (1-indexed).
            per_page: Number of tickets per page.

        Returns:
            A dict with keys ``tickets`` (list), ``page``, and ``per_page``.
        """
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if state_ids:
            params["state_ids"] = ",".join(str(s) for s in state_ids)
        result = await self._request("GET", "/api/v1/tickets", params=params)
        tickets = result if isinstance(result, list) else result.get("tickets", [])
        return {"tickets": tickets, "page": page, "per_page": per_page}

    async def get_ticket(self, ticket_id: int, expand: bool = False) -> dict[str, Any]:
        """Retrieve a single ticket by ID.

        Args:
            ticket_id: Ticket ID.
            expand: Whether to request the enriched (``?expand=true``) view.

        Returns:
            The ticket dict.
        """
        params = {"expand": "true"} if expand else None
        return await self._request("GET", f"/api/v1/tickets/{ticket_id}", params=params)

    async def create_ticket(self, payload: TicketCreatePayload) -> dict[str, Any]:
        """Create a new ticket.

        Args:
            payload: Ticket creation payload.

        Returns:
            The created ticket dict.
        """
        article: dict[str, Any] = {
            "subject": payload.article_subject or payload.title,
            "body": payload.article_body,
            "type": payload.article_type,
            "internal": payload.article_internal,
        }
        if payload.attachments:
            article["attachments"] = payload.attachments

        data: dict[str, Any] = {
            "title": payload.title,
            "group": payload.group,
            "customer": payload.customer,
            "article": article,
        }
        if payload.priority_id is not None:
            data["priority_id"] = payload.priority_id
        if payload.state_id is not None:
            data["state_id"] = payload.state_id

        return await self._request(
            "POST", "/api/v1/tickets", data=data, on_behalf_of=payload.on_behalf_of
        )

    async def update_ticket(self, payload: TicketUpdatePayload) -> dict[str, Any]:
        """Update an existing ticket.

        Args:
            payload: Ticket update payload.

        Returns:
            The updated ticket dict.
        """
        data: dict[str, Any] = {}
        if payload.title is not None:
            data["title"] = payload.title
        if payload.group is not None:
            data["group"] = payload.group
        if payload.state_id is not None:
            data["state_id"] = payload.state_id
        if payload.priority_id is not None:
            data["priority_id"] = payload.priority_id
        if payload.article_body is not None:
            data["article"] = {
                "body": payload.article_body,
                "type": payload.article_type,
                "internal": payload.article_internal,
            }

        return await self._request(
            "PUT",
            f"/api/v1/tickets/{payload.ticket_id}",
            data=data,
            on_behalf_of=payload.on_behalf_of,
        )

    async def delete_ticket(self, ticket_id: int) -> None:
        """Delete a ticket by ID.

        Args:
            ticket_id: Ticket ID to delete.
        """
        await self._request("DELETE", f"/api/v1/tickets/{ticket_id}")

    async def search_tickets(
        self, query: str, page: int = 1, per_page: int = 100
    ) -> dict[str, Any]:
        """Search tickets by query string.

        Args:
            query: Zammad search query string.
            page: Page number (1-indexed).
            per_page: Number of results per page (sent as Zammad's ``limit``).

        Returns:
            A dict with keys ``tickets`` (list), ``page``, and ``per_page``.
        """
        params = {"query": query, "page": page, "limit": per_page}
        result = await self._request("GET", "/api/v1/tickets/search", params=params)
        tickets = result if isinstance(result, list) else result.get("tickets", [])
        return {"tickets": tickets, "page": page, "per_page": per_page}

    # ── User Operations ───────────────────────────────────────────────────────

    async def get_user(self, user_id: int, expand: bool = False) -> dict[str, Any]:
        """Retrieve a single user by ID.

        Args:
            user_id: User ID.
            expand: Whether to request the enriched (``?expand=true``) view.

        Returns:
            The user dict.
        """
        params = {"expand": "true"} if expand else None
        return await self._request("GET", f"/api/v1/users/{user_id}", params=params)

    async def get_current_user(self) -> dict[str, Any]:
        """Retrieve the authenticated user (the API token's owner).

        Returns:
            The current user dict.
        """
        return await self._request("GET", "/api/v1/users/me")

    async def search_users(self, query: str) -> list[dict[str, Any]]:
        """Search users by query string.

        Args:
            query: Zammad search query string.

        Returns:
            A list of matching user dicts.
        """
        result = await self._request("GET", "/api/v1/users/search", params={"query": query})
        if isinstance(result, list):
            return result
        return result.get("users", [])

    async def create_user(self, payload: UserCreatePayload) -> dict[str, Any]:
        """Create a new user.

        Args:
            payload: User creation payload.

        Returns:
            The created user dict.
        """
        data: dict[str, Any] = {
            "firstname": payload.firstname,
            "lastname": payload.lastname,
            "email": payload.email,
            "roles": payload.roles,
            "active": payload.active,
        }
        if payload.organization:
            data["organization"] = payload.organization
        return await self._request("POST", "/api/v1/users", data=data)

    async def update_user(self, user_id: int, data: dict) -> dict[str, Any]:
        """Update an existing user.

        Args:
            user_id: User ID to update.
            data: Fields to update.

        Returns:
            The updated user dict.
        """
        return await self._request("PUT", f"/api/v1/users/{user_id}", data=data)

    # ── Article & Attachment Operations ───────────────────────────────────────

    async def get_articles(self, ticket_id: int) -> list[dict[str, Any]]:
        """List all articles for a ticket.

        Args:
            ticket_id: Ticket ID.

        Returns:
            A list of article dicts.
        """
        result = await self._request(
            "GET", f"/api/v1/ticket_articles/by_ticket/{ticket_id}"
        )
        return result if isinstance(result, list) else []

    async def get_attachment(
        self, ticket_id: int, article_id: int, attachment_id: int
    ) -> tuple[bytes, str]:
        """Download an attachment and save it to ``attachment_dir``.

        Args:
            ticket_id: Ticket ID the attachment belongs to.
            article_id: Article ID the attachment belongs to.
            attachment_id: Attachment ID.

        Returns:
            A tuple of ``(binary_data, file_path)``.

        Raises:
            ZammadAuthError: On a 401 response.
            ZammadError: On any other non-2xx response.
            ZammadConnectionError: On network or connection failures.
        """
        session = await self._get_session()
        url = (
            f"{self.config.instance_url.rstrip('/')}"
            f"/api/v1/ticket_attachment/{ticket_id}/{article_id}/{attachment_id}"
        )

        try:
            async with session.get(url) as resp:
                if resp.status == 401:
                    text = await resp.text()
                    raise ZammadAuthError(
                        f"Zammad authentication failed ({resp.status}) fetching "
                        f"attachment: {text[:200]}",
                        status_code=resp.status,
                    )
                if resp.status >= 400:
                    text = await resp.text()
                    raise ZammadError(
                        f"Zammad API error ({resp.status}) fetching attachment: "
                        f"{text[:200]}",
                        status_code=resp.status,
                    )
                content_disposition = resp.headers.get("Content-Disposition", "")
                filename = _extract_filename(
                    content_disposition, fallback=f"attachment_{attachment_id}"
                )
                data = await resp.read()
        except aiohttp.ClientError as exc:
            raise ZammadConnectionError(
                f"Network error contacting Zammad at {url}: {exc}"
            ) from exc

        file_path = os.path.join(self._ensure_attachment_dir(), filename)
        await asyncio.to_thread(_write_bytes, file_path, data)
        self.logger.debug("Saved Zammad attachment to %s", file_path)
        return data, file_path
