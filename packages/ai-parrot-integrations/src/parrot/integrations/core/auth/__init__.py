"""Shared authentication primitives for AI-Parrot integrations.

This subpackage provides provider-agnostic post-auth protocol abstractions
shared across Telegram, Slack, and MS Teams integrations.

Exports:
    PostAuthProvider: Protocol for secondary authentication providers.
    PostAuthRegistry: Registry mapping provider names to PostAuthProvider instances.
    OAuth2ProviderConfig: Configuration dataclass for OAuth2 identity providers.
    OAUTH2_PROVIDERS: Built-in provider catalog (google, etc.).
    get_provider: Look up a provider by name from the catalog.
"""
from parrot.integrations.core.auth.post_auth import PostAuthProvider, PostAuthRegistry
from parrot.integrations.core.auth.oauth2_providers import (
    OAuth2ProviderConfig,
    OAUTH2_PROVIDERS,
    get_provider,
)

__all__ = [
    "PostAuthProvider",
    "PostAuthRegistry",
    "OAuth2ProviderConfig",
    "OAUTH2_PROVIDERS",
    "get_provider",
]
