"""Jira OAuth2 provider for the AI-Parrot integrations registry.

``JiraOAuth2Provider`` wraps the existing ``JiraOAuthManager`` (thin wrapper —
no Jira-specific business logic lives here) and the ``JiraToolkit`` factory.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List

from parrot.integrations.oauth2.registry import OAuth2Provider

if TYPE_CHECKING:  # pragma: no cover
    from parrot.auth.credentials import CredentialResolver
    from parrot.auth.jira_oauth import JiraOAuthManager
    from parrot_tools.jiratoolkit import JiraToolkit as _JiraToolkit

logger = logging.getLogger(__name__)


class JiraOAuth2Provider(OAuth2Provider):
    """OAuth2 provider for Atlassian Jira Cloud (3LO flow).

    This provider thin-wraps the existing :class:`~parrot.auth.jira_oauth.JiraOAuthManager`
    and :class:`~parrot_tools.jiratoolkit.JiraToolkit`.

    Register it at application startup once the ``JiraOAuthManager`` is
    available::

        register_oauth2_provider(JiraOAuth2Provider(manager=jira_oauth_manager))

    Attributes:
        provider_id: Always ``"jira"``.
        display_name: Always ``"Jira"``.
        icon: Material Design Icon key ``"mdi:jira"``.
        default_scopes: Standard Jira read/write + offline_access scopes.
        pbac_action_namespace: ``"integration"``.
    """

    provider_id: str = "jira"
    display_name: str = "Jira"
    icon: str = "mdi:jira"
    default_scopes: List[str] = [
        "read:jira-user",
        "read:jira-work",
        "write:jira-work",
        "offline_access",
    ]
    pbac_action_namespace: str = "integration"

    def __init__(self, manager: "JiraOAuthManager") -> None:
        """Initialize the provider with the shared ``JiraOAuthManager``.

        Args:
            manager: The application-level ``JiraOAuthManager`` instance stored
                at ``app["jira_oauth_manager"]`` after startup.  Injected at
                provider registration time so the provider can be unit-tested
                with a mock.
        """
        self._manager: "JiraOAuthManager" = manager

    @property
    def manager(self) -> "JiraOAuthManager":
        """Return the underlying :class:`~parrot.auth.jira_oauth.JiraOAuthManager`.

        Returns:
            The ``JiraOAuthManager`` instance passed at construction time.
        """
        return self._manager

    def toolkit_factory(
        self,
        credential_resolver: "CredentialResolver",
    ) -> "_JiraToolkit":
        """Build a fresh :class:`~parrot_tools.jiratoolkit.JiraToolkit` bound to
        *credential_resolver*.

        Args:
            credential_resolver: Resolver that the toolkit uses to retrieve a
                valid access token at tool-call time.

        Returns:
            A :class:`~parrot_tools.jiratoolkit.JiraToolkit` configured for
            ``auth_type="oauth2_3lo"`` with the supplied resolver.

        Raises:
            ValueError: If ``credential_resolver`` is ``None`` (the toolkit
                enforces this at construction; see jiratoolkit.py:766-770).
        """
        from parrot_tools.jiratoolkit import JiraToolkit  # local import avoids circular

        return JiraToolkit(
            auth_type="oauth2_3lo",
            credential_resolver=credential_resolver,
        )
