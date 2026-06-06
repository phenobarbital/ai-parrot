"""
PostAuthProvider protocol and registry for secondary authentication flows.

Secondary auth providers run AFTER a primary authentication succeeds and
before the auth flow completes on the client side. A provider is responsible
for:

1. Building a provider-specific authorization URL that the login page can
   redirect to after the primary auth completes.
2. Handling the provider-specific result payload received from the combined
   callback — exchanging codes for tokens, persisting them, and creating
   identity mapping records.

This module defines only the **generic framework** (protocol + registry).
Concrete providers (e.g., ``JiraPostAuthProvider``) live in their own
modules (see ``parrot.integrations.telegram.post_auth_jira``).
"""
from __future__ import annotations

import logging
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Protocol,
    runtime_checkable,
)

logger = logging.getLogger(__name__)


@runtime_checkable
class PostAuthProvider(Protocol):
    """Protocol for secondary authentication providers.

    Implementations must declare a class-level ``provider_name`` attribute
    (the key used in YAML ``post_auth_actions``) and implement the two
    async methods below.

    Attributes:
        provider_name: Unique name of the provider (e.g., ``"jira"``).
            Matches the ``provider`` field of ``PostAuthAction`` in YAML.
    """

    provider_name: str

    async def build_auth_url(
        self,
        session: Any,
        config: Any,
        callback_base_url: str,
    ) -> str:
        """Return the authorization URL the login page should redirect to.

        Args:
            session: The current user session (type depends on the calling
                integration, e.g. ``TelegramUserSession`` for the Telegram
                integration).
            config: The agent configuration for the calling integration.
            callback_base_url: Public base URL of the combined callback
                endpoint (e.g., ``https://host/api/auth/callback``).

        Returns:
            An absolute authorization URL for this provider's consent page.
        """
        ...

    async def handle_result(
        self,
        data: Dict[str, Any],
        session: Any,
        primary_auth_data: Dict[str, Any],
    ) -> bool:
        """Process the secondary auth result payload from the callback.

        Args:
            data: Provider-specific payload (e.g., ``{"code", "state"}``
                for OAuth2 providers).
            session: The user session already populated by the primary auth
                handler (type depends on the calling integration).
            primary_auth_data: The payload from the primary auth (e.g.,
                user_id / token / display_name / email).

        Returns:
            True on success, False on any failure (the wrapper decides
            whether to roll back based on the ``required`` flag).
        """
        ...


class PostAuthRegistry:
    """Registry mapping provider names to ``PostAuthProvider`` instances.

    The registry is populated at wrapper initialization from the
    ``post_auth_actions`` YAML config. Each entry's ``provider`` string
    is used as the registry key.

    Example:
        >>> registry = PostAuthRegistry()
        >>> registry.register(JiraPostAuthProvider(oauth_manager))
        >>> provider = registry.get("jira")
        >>> url = await provider.build_auth_url(session, config, base)
    """

    def __init__(self) -> None:
        self._providers: Dict[str, PostAuthProvider] = {}

    def register(self, provider: PostAuthProvider) -> None:
        """Register a provider under its ``provider_name``.

        Args:
            provider: A ``PostAuthProvider`` instance.

        Raises:
            AttributeError: If the provider does not declare
                ``provider_name``.
        """
        name = getattr(provider, "provider_name", None)
        if not name:
            raise AttributeError(
                f"{type(provider).__name__} must declare a "
                f"non-empty 'provider_name' attribute"
            )
        if name in self._providers:
            logger.warning(
                "PostAuthRegistry: overwriting existing provider '%s' (%s)",
                name,
                type(provider).__name__,
            )
        self._providers[name] = provider

    def get(self, name: str) -> Optional[PostAuthProvider]:
        """Look up a provider by name.

        Args:
            name: The provider name (case-sensitive).

        Returns:
            The registered provider, or None if no match.
        """
        return self._providers.get(name)

    @property
    def providers(self) -> List[str]:
        """Return the list of registered provider names."""
        return list(self._providers.keys())

    def __contains__(self, name: str) -> bool:
        return name in self._providers

    def __len__(self) -> int:
        return len(self._providers)
