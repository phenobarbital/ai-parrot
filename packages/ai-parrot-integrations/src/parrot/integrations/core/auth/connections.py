"""Channel-neutral connection commands over IntegrationsService (FEAT-776 M5)."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Mapping, Optional, Sequence

from pydantic import BaseModel

from parrot.auth.oauth2.registry import OAuth2Provider, OAuth2ProviderRegistry
from parrot.auth.permission import PermissionContext
from parrot.auth.principal import Principal

if TYPE_CHECKING:  # pragma: no cover
    from parrot.auth.oauth2.service import IntegrationsService

_PROVIDER_ALIASES = {"office365": "o365"}

OutcomeKind = Literal["needs_login", "denied", "unknown_provider", "unavailable", "already_connected", "auth_url", "disconnected"]


class ConnectableProvider(BaseModel):
    """A provider a channel user may connect."""

    provider_id: str
    display_name: str
    icon: Optional[str] = None


class ConnectOutcome(BaseModel):
    """Result of a connect/disconnect command (never sent by this module)."""

    kind: OutcomeKind
    provider_id: str
    display_name: str = ""
    auth_url: Optional[str] = None
    account_display_name: str = ""
    message: str = ""


class ConnectionStatusLine(BaseModel):
    """One provider's connection status for a principal."""

    provider_id: str
    display_name: str
    status: Literal["connected", "disconnected", "needs_reconnect"]
    account_display_name: str = ""


class ConnectionCommandService:
    """Filter providers, choose server-owned scopes, and map service results to outcomes."""

    def __init__(self, *, service: "IntegrationsService", app: Mapping[str, Any], channel: str,
                 allowlist: Optional[Sequence[str]] = None,
                 registry: Optional[OAuth2ProviderRegistry] = None) -> None:
        self._service = service
        self._app = app
        self.channel = channel
        self._allowlist = set(allowlist) if allowlist is not None else None
        self._registry = registry or OAuth2ProviderRegistry()
        self.logger = logging.getLogger(__name__)

    def _connectable(self, provider: OAuth2Provider) -> bool:
        """Return whether a provider may be exposed to this channel."""
        return (
            provider.manager is not None
            and not provider.provider_id.startswith("mcp:")
            and (self._allowlist is None or provider.provider_id in self._allowlist)
        )

    def connectable_providers(self) -> List[ConnectableProvider]:
        """Return connectable registered providers sorted by provider identifier."""
        return sorted(
            (
                ConnectableProvider(provider_id=provider.provider_id, display_name=provider.display_name, icon=provider.icon)
                for provider in self._registry.all()
                if self._connectable(provider)
            ),
            key=lambda provider: provider.provider_id,
        )

    def resolve_provider(self, name: str) -> Optional[ConnectableProvider]:
        """Resolve an alias or case-insensitive connectable provider identifier."""
        candidate = _PROVIDER_ALIASES.get(name.casefold(), name.casefold())
        return next(
            (provider for provider in self.connectable_providers() if provider.provider_id.casefold() == candidate),
            None,
        )

    def _configured_provider(self, name: str) -> Optional[OAuth2Provider]:
        """Find a configured provider before its call-time manager check."""
        candidate = _PROVIDER_ALIASES.get(name.casefold(), name.casefold())
        return next(
            (
                provider
                for provider in self._registry.all()
                if provider.provider_id.casefold() == candidate
                and not provider.provider_id.startswith("mcp:")
                and (self._allowlist is None or provider.provider_id in self._allowlist)
            ),
            None,
        )

    async def connect(self, principal: Optional[Principal], provider_id: str, *,
                      extra_state: Dict[str, Any], permission_context: PermissionContext,
                      scopes: Optional[List[str]] = None) -> ConnectOutcome:
        """Start a connection, or return the mapped command outcome."""
        if principal is None:
            return ConnectOutcome(kind="needs_login", provider_id=provider_id, message="Please log in before connecting.")
        provider = self._configured_provider(provider_id)
        if provider is None:
            return ConnectOutcome(kind="unknown_provider", provider_id=provider_id, message=f"Unknown provider: {provider_id}.")
        if provider.manager is None:
            return ConnectOutcome(kind="unavailable", provider_id=provider.provider_id, display_name=provider.display_name,
                                  message=f"{provider.display_name} is unavailable.")
        requested_scopes = sorted(set(scopes)) if scopes else list(provider.default_scopes)
        try:
            descriptor = await self._service.status(principal.user_id, provider.provider_id, principal=principal,
                                                    permission_context=permission_context)
        except PermissionError:
            return ConnectOutcome(kind="denied", provider_id=provider.provider_id, display_name=provider.display_name,
                                  message=f"Connecting {provider.display_name} is not allowed for your account.")
        except ValueError:
            return ConnectOutcome(kind="unknown_provider", provider_id=provider.provider_id)
        if descriptor.status == "connected" and set(descriptor.scopes_granted) >= set(requested_scopes):
            return ConnectOutcome(kind="already_connected", provider_id=provider.provider_id,
                                  display_name=provider.display_name,
                                  account_display_name=descriptor.display_account_name or "")
        try:
            response = await self._service.start_connect(
                principal.user_id, provider.provider_id, channel=self.channel, principal=principal, extra_state=extra_state,
                scopes=requested_scopes, permission_context=permission_context
            )
        except PermissionError:
            return ConnectOutcome(kind="denied", provider_id=provider.provider_id, display_name=provider.display_name,
                                  message=f"Connecting {provider.display_name} is not allowed for your account.")
        except ValueError:
            return ConnectOutcome(kind="unknown_provider", provider_id=provider.provider_id)
        return ConnectOutcome(kind="auth_url", provider_id=provider.provider_id, display_name=provider.display_name,
                              auth_url=response.auth_url)

    async def disconnect(self, principal: Optional[Principal], provider_id: str, *,
                         permission_context: PermissionContext) -> ConnectOutcome:
        """Disconnect a provider and map service errors to command outcomes."""
        if principal is None:
            return ConnectOutcome(kind="needs_login", provider_id=provider_id, message="Please log in before connecting.")
        provider = self._configured_provider(provider_id)
        if provider is None:
            return ConnectOutcome(kind="unknown_provider", provider_id=provider_id)
        if provider.manager is None:
            return ConnectOutcome(kind="unavailable", provider_id=provider.provider_id, display_name=provider.display_name)
        try:
            await self._service.disconnect(principal.user_id, provider.provider_id, channel=self.channel, principal=principal,
                                           permission_context=permission_context)
        except PermissionError:
            return ConnectOutcome(kind="denied", provider_id=provider.provider_id, display_name=provider.display_name)
        except ValueError:
            return ConnectOutcome(kind="unknown_provider", provider_id=provider.provider_id)
        return ConnectOutcome(kind="disconnected", provider_id=provider.provider_id, display_name=provider.display_name)

    async def statuses(self, principal: Optional[Principal], *,
                       permission_context: PermissionContext) -> List[ConnectionStatusLine]:
        """Return statuses for connectable providers, failing closed on denial."""
        if principal is None:
            return []
        try:
            descriptors = await self._service.list_for_principal(principal.user_id, principal=principal,
                                                                 permission_context=permission_context)
        except PermissionError:
            return []
        connectable_ids = {provider.provider_id for provider in self.connectable_providers()}
        return [
            ConnectionStatusLine(provider_id=descriptor.provider, display_name=descriptor.display_name,
                                 status=descriptor.status, account_display_name=descriptor.display_account_name or "")
            for descriptor in descriptors
            if descriptor.provider in connectable_ids
        ]


__all__ = ["ConnectableProvider", "ConnectOutcome", "ConnectionStatusLine", "ConnectionCommandService", "OutcomeKind"]
