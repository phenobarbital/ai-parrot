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
from .models import (  # noqa: E402
    AuthRequiredEnvelope,
    ConnectInitRequest,
    ConnectInitResponse,
    DisconnectResponse,
    EnableResponse,
    IntegrationDescriptor,
    UserAgentToolkitRow,
    UsersIntegrationRow,
)
from .registry import (  # noqa: E402
    OAuth2Provider,
    OAuth2ProviderRegistry,
    register_oauth2_provider,
)

from .jira_provider import JiraOAuth2Provider  # noqa: E402

__all__ = [
    "_WEB_CHANNEL",
    # models
    "AuthRequiredEnvelope",
    "ConnectInitRequest",
    "ConnectInitResponse",
    "DisconnectResponse",
    "EnableResponse",
    "IntegrationDescriptor",
    "UserAgentToolkitRow",
    "UsersIntegrationRow",
    # registry
    "OAuth2Provider",
    "OAuth2ProviderRegistry",
    "register_oauth2_provider",
    # providers
    "JiraOAuth2Provider",
]
