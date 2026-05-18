"""Office365 OAuth2 provider for the AI-Parrot integrations registry.

Wraps :class:`parrot.auth.o365_oauth.O365OAuthManager` and the
:class:`parrot_tools.o365.oauth_toolkit.Office365Toolkit` factory. Register
once at application startup, after the manager is constructed::

    from parrot.auth.o365_oauth import O365OAuthManager
    from parrot.integrations.oauth2.registry import register_oauth2_provider
    from parrot.integrations.oauth2.o365_provider import O365OAuth2Provider

    manager = O365OAuthManager(client_id=..., client_secret=..., redirect_uri=...,
                               tenant_id=..., app=app)
    manager.setup()
    register_oauth2_provider(O365OAuth2Provider(manager=manager))
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List

from parrot.integrations.oauth2.registry import OAuth2Provider

if TYPE_CHECKING:  # pragma: no cover
    from parrot.auth.credentials import CredentialResolver
    from parrot.auth.o365_oauth import O365OAuthManager
    from parrot_tools.o365.oauth_toolkit import Office365Toolkit


logger = logging.getLogger(__name__)


class O365OAuth2Provider(OAuth2Provider):
    """OAuth2 provider for Microsoft Office 365 (delegated / 3LO).

    Attributes:
        provider_id: Always ``"o365"``.
        display_name: ``"Office 365"``.
        icon: Material Design Icon key ``"mdi:microsoft-office"``.
        default_scopes: Microsoft Graph delegated scopes — mirror
            :data:`parrot.auth.o365_oauth.DEFAULT_O365_SCOPES`.
    """

    provider_id: str = "o365"
    display_name: str = "Office 365"
    icon: str = "mdi:microsoft-office"
    default_scopes: List[str] = [
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
    pbac_action_namespace: str = "integration"

    def __init__(self, manager: "O365OAuthManager") -> None:
        self._manager: "O365OAuthManager" = manager

    @property
    def manager(self) -> "O365OAuthManager":
        return self._manager

    def toolkit_factory(
        self, credential_resolver: "CredentialResolver",
    ) -> "Office365Toolkit":
        from parrot_tools.o365.oauth_toolkit import Office365Toolkit

        return Office365Toolkit(
            credential_resolver=credential_resolver,
            tenant_id=getattr(self._manager, "tenant_id", "common"),
        )
