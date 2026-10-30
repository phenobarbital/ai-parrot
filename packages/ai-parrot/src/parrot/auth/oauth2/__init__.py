"""OAuth2 integration package for AI-Parrot.

Provides a registry of OAuth2 providers, Pydantic wire models, and the
``IntegrationsService`` that orchestrates connect / enable / disconnect flows
for the web AgentChat channel.

Channel constant
----------------
``_WEB_CHANNEL`` mirrors the ``_TELEGRAM_CHANNEL = "telegram"`` constant in
``parrot.integrations.telegram.jira_commands`` and is used to tag OAuth2
state payloads that originate from the web channel.
"""
from __future__ import annotations

# Channel constant — mirrors jira_commands.py:39
_WEB_CHANNEL: str = "web"

# Re-exports ----------------------------------------------------------------
from .descriptor import (  # noqa: E402
    DescriptorOAuth2Provider,
    OAuth2ProviderDescriptor,
    RefreshPolicy,
    StandardOAuth2Manager,
    register_descriptor_providers,
)
from .events import (  # noqa: E402
    ChannelNotifier,
    ChannelNotifierRegistry,
    ConnectionEvent,
    ConnectionEventPublisher,
)
from .models import (  # noqa: E402
    AuthRequiredEnvelope,
    ConnectInitRequest,
    ConnectInitResponse,
    DisconnectResponse,
    EnableResponse,
    IntegrationDescriptor,
    UsersIntegrationRow,
)
from .persistence import list_users_integrations  # noqa: E402
from .registry import (  # noqa: E402
    OAuth2Provider,
    OAuth2ProviderRegistry,
    register_oauth2_provider,
)

from .jira_provider import JiraOAuth2Provider  # noqa: E402
from .service import IntegrationsService  # noqa: E402

__all__ = [
    "_WEB_CHANNEL",
    # descriptors
    "DescriptorOAuth2Provider",
    "OAuth2ProviderDescriptor",
    "RefreshPolicy",
    "StandardOAuth2Manager",
    "register_descriptor_providers",
    # events
    "ChannelNotifier",
    "ChannelNotifierRegistry",
    "ConnectionEvent",
    "ConnectionEventPublisher",
    # models
    "AuthRequiredEnvelope",
    "ConnectInitRequest",
    "ConnectInitResponse",
    "DisconnectResponse",
    "EnableResponse",
    "IntegrationDescriptor",
    "UsersIntegrationRow",
    # persistence
    "list_users_integrations",
    # registry
    "OAuth2Provider",
    "OAuth2ProviderRegistry",
    "register_oauth2_provider",
    # providers
    "JiraOAuth2Provider",
    # service
    "IntegrationsService",
]
