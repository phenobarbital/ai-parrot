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

import inspect
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:  # pragma: no cover - import only for type checkers
    from .principal import Principal, PrincipalResolver


# ---------------------------------------------------------------------------
# FEAT-264: declarative config + broker signal models
# ---------------------------------------------------------------------------

AuthKind = Literal["obo", "oauth2", "static_key", "mcp", "device_code"]


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
        user_code: Device-code flow only (FEAT-266) — the short code the
            user enters at ``verification_uri``. ``None`` for non-device-code
            auth kinds.
        verification_uri: Device-code flow only (FEAT-266) — the Microsoft
            device-login URL. ``None`` for non-device-code auth kinds.
        expires_in: Device-code flow only (FEAT-266) — seconds until the
            device code expires. ``None`` for non-device-code auth kinds.
    """

    provider: str
    auth_url: str = Field(..., description="Consent URL — NEVER a secret")
    auth_kind: AuthKind = Field(..., description="Drives surface card rendering")
    user_code: Optional[str] = Field(
        default=None, description="Device-code flow: short user-entry code"
    )
    verification_uri: Optional[str] = Field(
        default=None, description="Device-code flow: Microsoft device-login URL"
    )
    expires_in: Optional[int] = Field(
        default=None, description="Device-code flow: seconds until code expiry"
    )


class AuthRequiredPayload(BaseModel):
    """Unified needs-auth payload serialized by ToolManager and AgentTalk."""

    provider: str
    auth_url: Optional[str] = None
    scopes: List[str] = Field(default_factory=list)
    tool_name: Optional[str] = None
    message: str = ""
    auth_kind: Optional[AuthKind] = None
    user_code: Optional[str] = None
    verification_uri: Optional[str] = None
    expires_in: Optional[int] = None


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
        user_code: Device-code flow only (FEAT-266, keyword-only) — the short
            code the user enters at ``verification_uri``.
        verification_uri: Device-code flow only (FEAT-266, keyword-only) —
            the Microsoft device-login URL.
        expires_in: Device-code flow only (FEAT-266, keyword-only) — seconds
            until the device code expires.
    """

    def __init__(
        self,
        provider: str,
        auth_url: str,
        auth_kind: str,
        *,
        user_code: Optional[str] = None,
        verification_uri: Optional[str] = None,
        expires_in: Optional[int] = None,
    ) -> None:
        super().__init__(
            f"Credential required for provider={provider!r} — "
            f"visit {auth_url} to authorize (auth_kind={auth_kind!r})"
        )
        self.provider = provider
        self.auth_url = auth_url
        self.auth_kind = auth_kind
        self.user_code = user_code
        self.verification_uri = verification_uri
        self.expires_in = expires_in

    def to_payload(self, *, tool_name: Optional[str] = None) -> AuthRequiredPayload:
        """Serialize to the unified needs-auth payload."""
        valid_auth_kinds = ("obo", "oauth2", "static_key", "mcp", "device_code")
        auth_kind = self.auth_kind if self.auth_kind in valid_auth_kinds else None
        return AuthRequiredPayload(
            provider=self.provider,
            auth_url=self.auth_url,
            tool_name=tool_name,
            message=str(self),
            auth_kind=auth_kind,
            user_code=self.user_code,
            verification_uri=self.verification_uri,
            expires_in=self.expires_in,
        )


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

    def __init__(
        self,
        oauth_manager: Any,
        *,
        principal_resolver: Optional["PrincipalResolver"] = None,
    ) -> None:
        self._manager = oauth_manager
        self._principal_resolver = principal_resolver

    def _manager_accepts(self, method_name: str, parameter: str) -> bool:
        """Return whether a manager method implements a principal-aware parameter."""
        method = getattr(self._manager, method_name)
        return parameter in inspect.signature(method).parameters

    async def _principal(self, channel: str, user_id: str) -> Optional["Principal"]:
        """Resolve the platform principal, failing closed when unbound."""
        from parrot.auth.principal import resolve_principal

        if self._principal_resolver is not None:
            return await self._principal_resolver.resolve(channel, user_id)
        return await resolve_principal(channel, user_id)

    async def resolve(self, channel: str, user_id: str) -> Optional[Any]:
        principal = await self._principal(channel, user_id)
        if principal is None:
            # Fail closed: an unbound channel identity never reaches a manager by its raw id.
            return None
        if self._manager_accepts("get_valid_token", "channel_user_id"):
            return await self._manager.get_valid_token(channel, principal.user_id, channel_user_id=user_id)
        return await self._manager.get_valid_token(channel, principal.user_id)

    async def get_auth_url(self, channel: str, user_id: str) -> str:
        from parrot.auth.exceptions import AuthorizationRequired

        principal = await self._principal(channel, user_id)
        if principal is None:
            raise AuthorizationRequired(
                tool_name="",
                message="Link your account to the platform first (/login).",
                provider=getattr(self._manager, "provider_id", "unknown"),
            )
        if self._manager_accepts("create_authorization_url", "principal"):
            url, _ = await self._manager.create_authorization_url(channel, principal.user_id, principal=principal)
        else:
            url, _ = await self._manager.create_authorization_url(channel, principal.user_id)
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
