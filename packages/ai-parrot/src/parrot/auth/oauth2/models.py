"""Pydantic wire models for the OAuth2 integration layer.

These models represent the data contracts between:
- the HTTP API (``IntegrationsHandler``) and its callers,
- the ``AgentTalk`` envelope response, and
- the DocumentDB persistence layer (``UsersIntegrationRow``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


#: Lifecycle of a user's integration as shown in the UI.
IntegrationStatus = Literal["connected", "disconnected", "needs_reconnect"]


class IntegrationDescriptor(BaseModel):
    """Describes one OAuth2-capable integration for the menu listing.

    Attributes:
        provider: Provider identifier, e.g. ``"jira"``.
        display_name: Human-readable name, e.g. ``"Jira"``.
        icon: Icon identifier (Material Design Icons key) or URL.
        default_scopes: Scopes requested during the OAuth consent screen.
        connected: Whether the integration is usable (``status == "connected"``).
        status: ``connected`` (row + readable tokens), ``disconnected`` (no row)
            or ``needs_reconnect`` (row exists but its vault tokens are missing
            or unreadable — the user must re-link the provider).
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
    status: Optional[IntegrationStatus] = None
    account_id: Optional[str] = None
    display_account_name: Optional[str] = None
    email: Optional[str] = None
    connected_at: Optional[datetime] = None
    channels: List[str] = Field(default_factory=list)
    scopes_granted: List[str] = Field(default_factory=list)
    expires_at: Optional[float] = None
    updated_at: Optional[datetime] = None

    @model_validator(mode="after")
    def _sync_status_and_connected(self) -> "IntegrationDescriptor":
        """Keep ``status`` and the legacy ``connected`` flag in sync.

        Callers may set either one: an explicit ``status`` wins, otherwise it is
        derived from ``connected`` (backwards compatible).
        """
        if self.status is None:
            self.status = "connected" if self.connected else "disconnected"
        else:
            self.connected = self.status == "connected"
        return self


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
        integration: Integration descriptor returned by the compatibility endpoint.
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
        auth_kind: Authentication flow used by the provider.
        user_code: Device-code flow code for the user to enter.
        verification_uri: Device-code flow verification URL.
        expires_in: Seconds until the device code expires.
    """

    type: Literal["auth_required"] = "auth_required"
    provider: str
    tool_name: Optional[str] = None
    auth_url: Optional[str] = None
    scopes: List[str] = Field(default_factory=list)
    message: str
    auth_kind: Optional[str] = None
    user_code: Optional[str] = None
    verification_uri: Optional[str] = None
    expires_in: Optional[int] = None


# ---------------------------------------------------------------------------
# DocumentDB row models (collection-backed; not strict ORM)
# ---------------------------------------------------------------------------


class UsersIntegrationRow(BaseModel):
    """Durable credential record stored in the ``users_integrations`` collection.

    The composite key is ``(user_id, provider)``.

    Attributes:
        user_id: Navigator user identifier.
        provider: Provider identifier, e.g. ``"jira"``.
        canonical_identity: Stable identity shared across channel-specific IDs.
        channels: Every channel that connected or used this integration.
        status: ``"active"`` while the credential is usable; ``"revoked"`` after
            explicit disconnect, or ``"needs_reconnect"`` when credentials must
            be replaced.
        account_id: Provider-side account ID (e.g. Atlassian ``accountId``).
        display_name: Human-readable account name.
        email: Account email.
        scopes: Scopes granted during consent.
        scopes_granted: Explicitly granted provider scopes.
        expires_at: Access-token expiry timestamp, when available.
        cloud_id: Atlassian cloud ID (Jira-specific).
        site_url: Atlassian site URL.
        connected_at: When the credential was first stored.
        updated_at: When the credential status or token data was last updated.
        last_used_at: When the credential was last used (updated by the toolkit).
    """

    user_id: str
    provider: str
    canonical_identity: Optional[str] = None
    channels: List[str] = Field(default_factory=list)
    status: Literal["active", "revoked", "needs_reconnect"] = "active"
    account_id: str
    display_name: str
    email: Optional[str] = None
    scopes: List[str]
    scopes_granted: List[str] = Field(default_factory=list)
    expires_at: Optional[float] = None
    cloud_id: Optional[str] = None
    site_url: Optional[str] = None
    connected_at: datetime
    updated_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None

    @model_validator(mode="before")
    @classmethod
    def _legacy_channel(cls, data: Any) -> Any:
        """Fold a legacy ``channel`` value into ``channels`` before validation."""
        if isinstance(data, dict) and "channel" in data and "channels" not in data:
            data = data.copy()
            data["channels"] = [data.pop("channel")]
        return data
