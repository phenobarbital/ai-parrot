"""ZammadToolkit — exposes Zammad helpdesk operations as agent tools.

Composes a :class:`~parrot.interfaces.zammad.ZammadInterface` and turns each
public async method into a tool via :class:`AbstractToolkit`. ``delete_ticket``
is excluded from the generated tool set for safety (it remains callable
directly on the toolkit instance or on ``ZammadInterface``).

Configuration falls back to the ``ZAMMAD_*`` keys in :mod:`parrot.conf`
(via :class:`ZammadInterface`) when constructor arguments are omitted.
"""
from __future__ import annotations

import base64
import logging
import mimetypes
from typing import Any, Optional

from pydantic import BaseModel, Field

from parrot.interfaces.zammad import (
    TicketCreatePayload,
    TicketUpdatePayload,
    UserCreatePayload,
    ZammadInterface,
)
from parrot_tools.decorators import tool_schema
from parrot_tools.toolkit import AbstractToolkit


# ── Input Models ───────────────────────────────────────────────────────────

class CreateTicketInput(BaseModel):
    """Input schema for ``zammad_create_ticket``."""

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
        default=None, description="User ID/login/email to act as"
    )


class GetTicketInput(BaseModel):
    """Input schema for ``zammad_get_ticket``."""

    ticket_id: int = Field(..., description="Ticket ID")
    expand: bool = Field(default=False, description="Request the enriched view")


class ListTicketsInput(BaseModel):
    """Input schema for ``zammad_list_tickets``."""

    state_ids: Optional[list[int]] = Field(
        default=None, description="Optional list of state IDs to filter by"
    )
    page: int = Field(default=1, description="Page number (1-indexed)")
    per_page: int = Field(default=100, description="Number of tickets per page")


class UpdateTicketInput(BaseModel):
    """Input schema for ``zammad_update_ticket``."""

    ticket_id: int = Field(..., description="Ticket ID to update")
    title: Optional[str] = Field(default=None, description="New title")
    group: Optional[str] = Field(default=None, description="New group")
    state_id: Optional[int] = Field(default=None, description="New state ID")
    priority_id: Optional[int] = Field(default=None, description="New priority ID")
    article_body: Optional[str] = Field(default=None, description="Article body for the update")
    article_type: str = Field(default="note", description="Article type")
    article_internal: bool = Field(default=True, description="Internal note flag")
    on_behalf_of: Optional[str] = Field(
        default=None, description="User ID/login/email to act as"
    )


class CloseTicketInput(BaseModel):
    """Input schema for ``zammad_close_ticket``."""

    ticket_id: int = Field(..., description="Ticket ID to close")


class SearchTicketsInput(BaseModel):
    """Input schema for ``zammad_search_tickets``."""

    query: str = Field(..., description="Zammad search query string")
    page: int = Field(default=1, description="Page number (1-indexed)")
    per_page: int = Field(default=100, description="Number of results per page")


class GetUserInput(BaseModel):
    """Input schema for ``zammad_get_user``."""

    user_id: int = Field(..., description="User ID")
    expand: bool = Field(default=False, description="Request the enriched view")


class SearchUsersInput(BaseModel):
    """Input schema for ``zammad_search_users``."""

    query: str = Field(..., description="Zammad user search query string")


class CreateUserInput(BaseModel):
    """Input schema for ``zammad_create_user``."""

    firstname: str = Field(..., description="First name")
    lastname: str = Field(..., description="Last name")
    email: str = Field(..., description="Email address")
    organization: Optional[str] = Field(default=None, description="Organization name")
    roles: list[str] = Field(default_factory=lambda: ["Customer"], description="Roles")
    active: bool = Field(default=True, description="Active flag")


class GetArticlesInput(BaseModel):
    """Input schema for ``zammad_get_articles``."""

    ticket_id: int = Field(..., description="Ticket ID")


class GetAttachmentInput(BaseModel):
    """Input schema for ``zammad_get_attachment``."""

    ticket_id: int = Field(..., description="Ticket ID the attachment belongs to")
    article_id: int = Field(..., description="Article ID the attachment belongs to")
    attachment_id: int = Field(..., description="Attachment ID")


class DeleteTicketInput(BaseModel):
    """Input schema for the (excluded) ``delete_ticket`` method."""

    ticket_id: int = Field(..., description="Ticket ID to delete")


class ZammadToolkit(AbstractToolkit):
    """Toolkit exposing Zammad helpdesk operations as agent tools.

    Example:
        toolkit = ZammadToolkit(
            instance_url="https://support.example.com",
            token="my-api-token",
            default_group="Support",
        )
        tools = toolkit.get_tools()
        ticket = await toolkit.create_ticket(
            title="Can't log in",
            group="Support",
            customer="jane@example.com",
            article_body="I forgot my password.",
        )
    """

    tool_prefix = "zammad"

    #: Excluded for safety — prevents LLMs from accidentally deleting tickets.
    #: Still callable directly on this toolkit or on ``ZammadInterface``.
    exclude_tools: tuple[str, ...] = ("delete_ticket",)

    def __init__(
        self,
        instance_url: str | None = None,
        token: str | None = None,
        default_customer: str | None = None,
        default_group: str | None = None,
        on_behalf_of_header: str = "From",
        attachment_dir: str | None = None,
        closed_state_id: int = 4,
        **kwargs: Any,
    ) -> None:
        """Initialize the toolkit.

        Args:
            instance_url: Zammad instance base URL. Falls back to
                ``ZAMMAD_INSTANCE`` (via ``ZammadInterface``).
            token: API token for Bearer authentication. Falls back to
                ``ZAMMAD_TOKEN``.
            default_customer: Default customer email.
            default_group: Default ticket group.
            on_behalf_of_header: Header name for on-behalf-of impersonation.
            attachment_dir: Directory to save downloaded attachments.
            closed_state_id: State ID Zammad uses for "closed" tickets;
                used by :meth:`close_ticket`. Defaults to ``4``, matching a
                stock Zammad installation; override for customized state
                schemes.
            **kwargs: Forwarded to :class:`AbstractToolkit`.
        """
        super().__init__(**kwargs)
        self._instance_url = instance_url
        self._token = token
        self._default_customer = default_customer
        self._default_group = default_group
        self._on_behalf_of_header = on_behalf_of_header
        self._attachment_dir = attachment_dir
        self._closed_state_id = closed_state_id
        self._interface: ZammadInterface | None = None
        self.logger = logging.getLogger(__name__)

    # ── Lifecycle ───────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Create and open the underlying ``ZammadInterface`` session."""
        self._interface = ZammadInterface(
            instance_url=self._instance_url,
            token=self._token,
            default_customer=self._default_customer,
            default_group=self._default_group,
            on_behalf_of_header=self._on_behalf_of_header,
            attachment_dir=self._attachment_dir,
        )
        await self._interface.__aenter__()

    async def stop(self) -> None:
        """Close the underlying ``ZammadInterface`` session."""
        if self._interface:
            await self._interface.close()

    # ── Ticket Tools ──────────────────────────────────────────────────────────

    @tool_schema(CreateTicketInput)
    async def create_ticket(
        self,
        title: str,
        group: str,
        customer: str,
        article_body: str,
        article_subject: Optional[str] = None,
        article_type: str = "note",
        article_internal: bool = False,
        priority_id: Optional[int] = None,
        state_id: Optional[int] = None,
        on_behalf_of: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create a new support ticket in Zammad."""
        payload = TicketCreatePayload(
            title=title,
            group=group,
            customer=customer,
            article_subject=article_subject,
            article_body=article_body,
            article_type=article_type,
            article_internal=article_internal,
            priority_id=priority_id,
            state_id=state_id,
            on_behalf_of=on_behalf_of,
        )
        return await self._interface.create_ticket(payload)

    @tool_schema(GetTicketInput)
    async def get_ticket(self, ticket_id: int, expand: bool = False) -> dict[str, Any]:
        """Retrieve a single Zammad ticket by ID."""
        return await self._interface.get_ticket(ticket_id, expand=expand)

    @tool_schema(ListTicketsInput)
    async def list_tickets(
        self,
        state_ids: Optional[list[int]] = None,
        page: int = 1,
        per_page: int = 100,
    ) -> dict[str, Any]:
        """List Zammad tickets, optionally filtered by state."""
        return await self._interface.list_tickets(
            state_ids=state_ids, page=page, per_page=per_page
        )

    @tool_schema(UpdateTicketInput)
    async def update_ticket(
        self,
        ticket_id: int,
        title: Optional[str] = None,
        group: Optional[str] = None,
        state_id: Optional[int] = None,
        priority_id: Optional[int] = None,
        article_body: Optional[str] = None,
        article_type: str = "note",
        article_internal: bool = True,
        on_behalf_of: Optional[str] = None,
    ) -> dict[str, Any]:
        """Update an existing Zammad ticket."""
        payload = TicketUpdatePayload(
            ticket_id=ticket_id,
            title=title,
            group=group,
            state_id=state_id,
            priority_id=priority_id,
            article_body=article_body,
            article_type=article_type,
            article_internal=article_internal,
            on_behalf_of=on_behalf_of,
        )
        return await self._interface.update_ticket(payload)

    @tool_schema(CloseTicketInput)
    async def close_ticket(self, ticket_id: int) -> dict[str, Any]:
        """Close a Zammad ticket by setting its state to 'closed'."""
        payload = TicketUpdatePayload(ticket_id=ticket_id, state_id=self._closed_state_id)
        return await self._interface.update_ticket(payload)

    @tool_schema(SearchTicketsInput)
    async def search_tickets(
        self, query: str, page: int = 1, per_page: int = 100
    ) -> dict[str, Any]:
        """Search Zammad tickets by query string."""
        return await self._interface.search_tickets(query, page=page, per_page=per_page)

    async def delete_ticket(self, ticket_id: int) -> dict[str, Any]:
        """Delete a Zammad ticket by ID.

        Excluded from the generated tool set via ``exclude_tools`` — not
        exposed to LLMs. Remains callable directly for programmatic use.
        """
        await self._interface.delete_ticket(ticket_id)
        return {"ticket_id": ticket_id, "deleted": True}

    # ── User Tools ────────────────────────────────────────────────────────────

    @tool_schema(GetUserInput)
    async def get_user(self, user_id: int, expand: bool = False) -> dict[str, Any]:
        """Retrieve a single Zammad user by ID."""
        return await self._interface.get_user(user_id, expand=expand)

    @tool_schema(SearchUsersInput)
    async def search_users(self, query: str) -> list[dict[str, Any]]:
        """Search Zammad users by query string."""
        return await self._interface.search_users(query)

    @tool_schema(CreateUserInput)
    async def create_user(
        self,
        firstname: str,
        lastname: str,
        email: str,
        organization: Optional[str] = None,
        roles: Optional[list[str]] = None,
        active: bool = True,
    ) -> dict[str, Any]:
        """Create a new Zammad user."""
        payload = UserCreatePayload(
            firstname=firstname,
            lastname=lastname,
            email=email,
            organization=organization,
            roles=roles or ["Customer"],
            active=active,
        )
        return await self._interface.create_user(payload)

    # ── Article & Attachment Tools ────────────────────────────────────────────

    @tool_schema(GetArticlesInput)
    async def get_articles(self, ticket_id: int) -> list[dict[str, Any]]:
        """List all articles for a Zammad ticket."""
        return await self._interface.get_articles(ticket_id)

    @tool_schema(GetAttachmentInput)
    async def get_attachment(
        self, ticket_id: int, article_id: int, attachment_id: int
    ) -> dict[str, Any]:
        """Download a Zammad attachment and return its content and metadata."""
        data, file_path = await self._interface.get_attachment(
            ticket_id, article_id, attachment_id
        )
        filename = file_path.rsplit("/", 1)[-1]
        mime_type, _ = mimetypes.guess_type(filename)
        return {
            "file_path": file_path,
            "base64": base64.b64encode(data).decode("ascii"),
            "mime_type": mime_type or "application/octet-stream",
            "filename": filename,
        }
