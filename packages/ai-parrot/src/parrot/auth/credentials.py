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

FEAT-264 additions
------------------
- :class:`ProviderCredentialConfig` — declarative per-provider credential config
  (AgentDefinition / manifest).
- :class:`ResolvedCredential` — credential material resolved from vault (secret
  never logged; only the ``key_fingerprint`` is recorded in the audit ledger).
- :class:`NeedsAuth` — surface-neutral miss signal returned by the broker.
- :class:`CredentialRequired` — exception raised by the tool-loop seam when the
  broker returns ``NeedsAuth``; surfaces catch it to render their UX.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional, TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:  # pragma: no cover - import only for type checkers
    from .jira_oauth import JiraOAuthManager


# ---------------------------------------------------------------------------
# FEAT-264: declarative config + broker signal models
# ---------------------------------------------------------------------------

AuthKind = Literal["obo", "oauth2", "static_key", "mcp"]


class ProviderCredentialConfig(BaseModel):
    """Declarative per-provider credential config (AgentDefinition / manifest).

    Attributes:
        provider: Provider identifier (e.g. ``"workiq"``, ``"fireflies"``).
        auth: Auth kind — selects the resolver strategy in
            :class:`~parrot.auth.broker.CredentialResolverFactory`.
        options: Extra options forwarded to the strategy constructor
            (e.g. ``scope``, ``vault_key``, ``capture_url``).
    """

    provider: str = Field(..., description="Provider identifier, e.g. 'workiq'")
    auth: AuthKind = Field(..., description="Auth kind: obo|oauth2|static_key|mcp")
    options: Dict[str, Any] = Field(
        default_factory=dict,
        description="Strategy-specific options (scope, vault_key, capture_url, ...)",
    )


class ResolvedCredential(BaseModel):
    """Credential material returned by the broker on a successful resolution.

    Attributes:
        provider: Provider identifier.
        secret: Raw credential (token, API key, …).  **NEVER** log this field;
            only :attr:`key_fingerprint` should appear in audit records.
        key_fingerprint: SHA-256 hex digest of ``secret`` (for audit).
    """

    model_config = {"arbitrary_types_allowed": True}

    provider: str
    secret: Any = Field(..., description="Raw credential — NEVER logged")
    key_fingerprint: str = Field(..., description="SHA-256 of secret (audit only)")


class NeedsAuth(BaseModel):
    """Surface-neutral miss signal from the broker.

    Attributes:
        provider: Provider identifier.
        auth_url: Consent / OOB capture URL the user must visit.
            **NEVER** a secret.
        auth_kind: Drives surface rendering (card type).
    """

    provider: str
    auth_url: str = Field(..., description="Consent URL — NEVER a secret")
    auth_kind: AuthKind = Field(..., description="Drives surface card rendering")


class CredentialRequired(Exception):
    """Raised by the tool-loop seam when the broker returns :class:`NeedsAuth`.

    This is the canonical, surface-neutral exception.  Each surface catches it
    and renders the appropriate UX:

    * A2A: suspend + TEXT consent link.
    * MSAgentSDK: Adaptive Card (static key) or OAuthCard (OAuth/OBO).
    * CLI: plain URL printed to stdout.

    Args:
        provider: Provider identifier.
        auth_url: Consent / OOB capture URL (NEVER a secret).
        auth_kind: Auth kind for surface rendering.
    """

    def __init__(self, provider: str, auth_url: str, auth_kind: str) -> None:
        super().__init__(
            f"Credential required for provider={provider!r} — "
            f"visit {auth_url} to authorize (auth_kind={auth_kind!r})"
        )
        self.provider = provider
        self.auth_url = auth_url
        self.auth_kind = auth_kind


# ---------------------------------------------------------------------------
# Existing resolvers (pre-FEAT-264, kept backward-compatible)
# ---------------------------------------------------------------------------


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
