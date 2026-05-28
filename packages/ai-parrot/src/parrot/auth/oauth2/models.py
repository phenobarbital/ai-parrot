"""Pydantic wire models for the OAuth2 integration layer.

These models represent the data contracts between:
- the HTTP API (``IntegrationsHandler``) and its callers,
- the ``AgentTalk`` envelope response, and
- the DocumentDB persistence layer (``UsersIntegrationRow``,
  ``UserAgentToolkitRow``).
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class IntegrationDescriptor(BaseModel):
    """Describes one OAuth2-capable integration for the menu listing.

    Attributes:
        provider: Provider identifier, e.g. ``"jira"``.
        display_name: Human-readable name, e.g. ``"Jira"``.
        icon: Icon identifier (Material Design Icons key) or URL.
        default_scopes: Scopes requested during the OAuth consent screen.
        connected: Whether the current user has a ``users_integrations`` row.
        enabled_on_agent: Whether the user has a ``user_agent_toolkits`` row
            for the current ``(user, agent)`` pair.
        account_id: Provider-side account identifier (available when connected).
        display_account_name: Human-readable account name.
        email: Account email (if the provider exposes it).
        connected_at: Timestamp when the credential was first stored.
    """

    provider: str
    display_name: str
    icon: Optional[str] = None
    default_scopes: List[str] = Field(default_factory=list)
    connected: bool = False
    enabled_on_agent: bool = False
    account_id: Optional[str] = None
    display_account_name: Optional[str] = None
    email: Optional[str] = None
    connected_at: Optional[datetime] = None


class ConnectInitRequest(BaseModel):
    """Request body for ``POST .../integrations/{agent_id}/{provider}/connect``.

    Attributes:
        return_origin: The caller's ``window.location.origin`` used as the
            ``postMessage`` target in the popup callback page.  When absent,
            the server reads ``request.headers["Origin"]``.
    """

    return_origin: Optional[str] = None


class ConnectInitResponse(BaseModel):
    """Response for the connect-init endpoint.

    Attributes:
        auth_url: Full Atlassian authorization URL to open in a popup.
        state: Opaque CSRF nonce; the client must not interpret it.
        scopes: Scopes included in the authorization request.
        expires_in: Seconds the nonce remains valid (default 600).
    """

    auth_url: str
    state: str
    scopes: List[str]
    expires_in: int = 600


class EnableResponse(BaseModel):
    """Response for the confirm-enable endpoint.

    Attributes:
        integration: Updated descriptor with ``enabled_on_agent=True``.
    """

    integration: IntegrationDescriptor


class DisconnectResponse(BaseModel):
    """Response for the disconnect endpoint.

    Attributes:
        provider: Provider that was disconnected.
        disconnected: Always ``True`` on success.
    """

    provider: str
    disconnected: bool = True


class AuthRequiredEnvelope(BaseModel):
    """Single-body response returned by ``AgentTalk`` when a tool raises
    ``AuthorizationRequired``.

    The frontend detects ``type == "auth_required"`` and renders a
    ``ConnectIntegrationPill`` inline in the chat.

    Attributes:
        type: Discriminator literal — always ``"auth_required"``.
        provider: Provider identifier, e.g. ``"jira"``.
        tool_name: Name of the tool that triggered the exception.
        auth_url: Authorization URL to open in the popup (may be absent if the
            provider could not generate one at exception time).
        scopes: Scopes needed by the provider.
        message: Human-readable explanation surfaced in the chat UI.
    """

    type: Literal["auth_required"] = "auth_required"
    provider: str
    tool_name: Optional[str] = None
    auth_url: Optional[str] = None
    scopes: List[str] = Field(default_factory=list)
    message: str


# ---------------------------------------------------------------------------
# DocumentDB row models (collection-backed; not strict ORM)
# ---------------------------------------------------------------------------


class UsersIntegrationRow(BaseModel):
    """Durable credential record stored in the ``users_integrations`` collection.

    The composite key is ``(user_id, provider)``.

    Attributes:
        user_id: Navigator user identifier.
        provider: Provider identifier, e.g. ``"jira"``.
        channel: Origin channel — always ``"web"`` for this integration path.
        status: ``"active"`` while the credential is usable; ``"revoked"`` after
            explicit disconnect (soft-delete variant, not used in v1 — v1 does
            hard deletes).
        account_id: Provider-side account ID (e.g. Atlassian ``accountId``).
        display_name: Human-readable account name.
        email: Account email.
        scopes: Scopes granted during consent.
        cloud_id: Atlassian cloud ID (Jira-specific).
        site_url: Atlassian site URL.
        connected_at: When the credential was first stored.
        last_used_at: When the credential was last used (updated by the toolkit).
    """

    user_id: str
    provider: str
    channel: str = "web"
    status: Literal["active", "revoked"] = "active"
    account_id: str
    display_name: str
    email: Optional[str] = None
    scopes: List[str]
    cloud_id: Optional[str] = None
    site_url: Optional[str] = None
    connected_at: datetime
    last_used_at: Optional[datetime] = None


class UserAgentToolkitRow(BaseModel):
    """Per-``(user, agent, toolkit)`` enablement record stored in
    ``user_agent_toolkits``.

    The composite key is ``(user_id, agent_id, toolkit_id)``.

    Attributes:
        user_id: Navigator user identifier.
        agent_id: Agent identifier (slug or UUID used by the manager).
        toolkit_id: Toolkit identifier — equals ``provider`` for OAuth toolkits.
        provider: Provider identifier, e.g. ``"jira"``.
        enabled_at: When the user enabled this toolkit on this agent.
    """

    user_id: str
    agent_id: str
    toolkit_id: str
    provider: str
    enabled_at: datetime
