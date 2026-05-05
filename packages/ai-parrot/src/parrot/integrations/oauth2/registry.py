"""OAuth2 provider registry.

Defines the ``OAuth2Provider`` abstract base class and the
``OAuth2ProviderRegistry`` in-memory singleton.  Providers register themselves
at application startup via :func:`register_oauth2_provider`.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from parrot.auth.credentials import CredentialResolver
    from parrot.tools import AbstractToolkit

logger = logging.getLogger(__name__)


class OAuth2Provider(ABC):
    """Abstract base class for an OAuth2-capable provider.

    Concrete implementations (e.g. ``JiraOAuth2Provider``) declare their
    provider metadata as class-level attributes and implement the two abstract
    members.

    Attributes:
        provider_id: Unique string key, e.g. ``"jira"``.
        display_name: Human-readable name shown in the UI, e.g. ``"Jira"``.
        icon: Icon identifier (Material Design Icons key) or URL.
        default_scopes: Scopes requested during the OAuth consent screen.
        pbac_action_namespace: PBAC action namespace for policy evaluation,
            e.g. ``"integration"``.
    """

    provider_id: str
    display_name: str
    icon: Optional[str] = None
    default_scopes: List[str] = []  # subclasses MUST override with their own list instance
    pbac_action_namespace: str = "integration"

    @property
    @abstractmethod
    def manager(self) -> Any:
        """Return the underlying OAuth manager (e.g. ``JiraOAuthManager``).

        Returns:
            The manager instance used to generate authorization URLs and
            exchange codes for tokens.
        """

    @abstractmethod
    def toolkit_factory(
        self,
        credential_resolver: "CredentialResolver",
    ) -> "AbstractToolkit":
        """Build a fresh toolkit instance bound to *credential_resolver*.

        Args:
            credential_resolver: Resolver that the toolkit uses to retrieve
                valid tokens for the current user at call time.

        Returns:
            A fully configured toolkit ready to be registered with the
            ``ToolManager``.
        """


class OAuth2ProviderRegistry:
    """In-memory singleton registry of :class:`OAuth2Provider` instances.

    Usage::

        registry = OAuth2ProviderRegistry()
        registry.register(JiraOAuth2Provider())
        provider = registry.get("jira")

    The singleton is reset between test cases via :meth:`_reset`.
    """

    _instance: ClassVar[Optional["OAuth2ProviderRegistry"]] = None
    _providers: Dict[str, OAuth2Provider]

    def __new__(cls) -> "OAuth2ProviderRegistry":
        """Return the singleton instance, creating it on first call."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._providers = {}
        return cls._instance

    @classmethod
    def _reset(cls) -> None:
        """Reset the singleton — intended for use in unit tests only."""
        cls._instance = None

    def register(self, provider: OAuth2Provider) -> None:
        """Register *provider*.  A duplicate ``provider_id`` overwrites the
        previous entry.

        Args:
            provider: The provider instance to register.
        """
        logger.debug("Registering OAuth2 provider: %s", provider.provider_id)
        self._providers[provider.provider_id] = provider

    def get(self, provider_id: str) -> Optional[OAuth2Provider]:
        """Return the provider for *provider_id*, or ``None`` if not registered.

        Args:
            provider_id: The unique string key, e.g. ``"jira"``.

        Returns:
            The :class:`OAuth2Provider` instance, or ``None``.
        """
        return self._providers.get(provider_id)

    def all(self) -> List[OAuth2Provider]:
        """Return all registered providers in insertion order.

        Returns:
            List of all registered :class:`OAuth2Provider` instances.
        """
        return list(self._providers.values())


def register_oauth2_provider(provider: OAuth2Provider) -> None:
    """Module-level convenience for application startup.

    Equivalent to::

        OAuth2ProviderRegistry().register(provider)

    Args:
        provider: The provider to register with the global registry.
    """
    OAuth2ProviderRegistry().register(provider)
