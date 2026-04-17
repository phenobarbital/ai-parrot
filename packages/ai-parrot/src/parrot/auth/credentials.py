"""Credential resolution abstractions for toolkits.

:class:`CredentialResolver` is the bridge between a toolkit and its
credential storage.  It hides whether credentials come from a static
configuration (legacy basic auth / PAT) or from a per-user OAuth 2.0
token store backed by Redis, allowing toolkits to simply call
``resolver.resolve(channel, user_id)`` without knowing the scheme.

Two concrete resolvers are provided:

- :class:`OAuthCredentialResolver`: delegates to a :class:`JiraOAuthManager`
  (or any object that exposes ``get_valid_token`` / ``create_authorization_url``).
- :class:`StaticCredentialResolver`: always returns the same
  :class:`StaticCredentials` — used for the existing ``basic_auth`` and
  ``token_auth`` modes so legacy toolkits keep working unchanged.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import only for type checkers
    from .jira_oauth import JiraOAuthManager


class CredentialResolver(ABC):
    """Resolves credentials for a given channel/user pair."""

    @abstractmethod
    async def resolve(self, channel: str, user_id: str) -> Optional[Any]:
        """Return credentials for ``(channel, user_id)`` or ``None``.

        ``None`` indicates the user has not authorized yet and the caller
        should surface an authorization URL (see :meth:`get_auth_url`).
        """
        raise NotImplementedError

    @abstractmethod
    async def get_auth_url(self, channel: str, user_id: str) -> str:
        """Return the authorization URL the user should follow."""
        raise NotImplementedError

    async def is_connected(self, channel: str, user_id: str) -> bool:
        """Return True when :meth:`resolve` currently yields credentials."""
        return (await self.resolve(channel, user_id)) is not None


class OAuthCredentialResolver(CredentialResolver):
    """Resolves credentials from an OAuth 2.0 token store.

    The resolver delegates all lookups to a manager that implements
    ``get_valid_token(channel, user_id)`` and
    ``create_authorization_url(channel, user_id)``.  The reference
    implementation is :class:`JiraOAuthManager`, but any compatible object
    (e.g., a future GitHub or O365 manager) can be plugged in.
    """

    def __init__(self, oauth_manager: "JiraOAuthManager") -> None:
        self._manager = oauth_manager

    async def resolve(self, channel: str, user_id: str) -> Optional[Any]:
        return await self._manager.get_valid_token(channel, user_id)

    async def get_auth_url(self, channel: str, user_id: str) -> str:
        url, _ = await self._manager.create_authorization_url(channel, user_id)
        return url


@dataclass
class StaticCredentials:
    """Credential bundle for non-OAuth (legacy) toolkit modes."""

    server_url: str
    username: Optional[str] = None
    password: Optional[str] = None
    token: Optional[str] = None
    auth_type: str = "basic_auth"


class StaticCredentialResolver(CredentialResolver):
    """Returns a fixed :class:`StaticCredentials` instance.

    Used for ``basic_auth`` / ``token_auth`` modes where a single
    service-account credential is shared across all users.  The resolver
    ignores ``channel`` and ``user_id``.
    """

    def __init__(
        self,
        server_url: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
        token: Optional[str] = None,
        auth_type: str = "basic_auth",
    ) -> None:
        self._creds = StaticCredentials(
            server_url=server_url,
            username=username,
            password=password,
            token=token,
            auth_type=auth_type,
        )

    async def resolve(self, channel: str, user_id: str) -> StaticCredentials:
        return self._creds

    async def get_auth_url(self, channel: str, user_id: str) -> str:
        raise NotImplementedError(
            "Static credentials do not require authorization"
        )
