"""Tests for unified needs-auth payloads and principal-first OAuth resolution."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import pytest

from parrot.auth.credentials import (
    AuthRequiredPayload,
    CredentialRequired,
    OAuthCredentialResolver,
)
from parrot.auth.exceptions import AuthorizationRequired
from parrot.auth.principal import Principal


class _PrincipalResolver:
    """Resolve principals from an in-memory channel binding map."""

    def __init__(self, principals: Dict[Tuple[str, str], Principal]) -> None:
        self._principals = principals

    async def resolve(
        self, channel: str, channel_user_id: str
    ) -> Optional[Principal]:
        """Return the principal bound to the channel identity."""
        return self._principals.get((channel, channel_user_id))


class _OAuthManager:
    """Record token and authorization calls made by the resolver."""

    provider_id = "jira"

    def __init__(self) -> None:
        self.token_calls: list[Tuple[str, str, str]] = []
        self.auth_calls: list[Tuple[str, str, Principal]] = []

    async def get_valid_token(
        self, channel: str, user_id: str, *, channel_user_id: str
    ) -> str:
        """Record and return a deterministic token."""
        self.token_calls.append((channel, user_id, channel_user_id))
        return f"token-{user_id}"

    async def create_authorization_url(
        self, channel: str, user_id: str, *, principal: Principal
    ) -> Tuple[str, Dict[str, Any]]:
        """Record and return a deterministic authorization URL."""
        self.auth_calls.append((channel, user_id, principal))
        return "https://auth.example/connect", {}


def test_auth_required_payload_superset() -> None:
    """Both needs-auth exceptions serialize through the unified payload."""
    authorization = AuthorizationRequired(
        tool_name="jira_search",
        message="connect",
        auth_url="https://x",
        provider="jira",
        scopes=["read"],
    )
    credential = CredentialRequired(
        "o365",
        "https://dev",
        "device_code",
        user_code="ABCD",
        verification_uri="https://v",
        expires_in=900,
    )

    authorization_payload = authorization.to_payload()
    assert isinstance(authorization_payload, AuthRequiredPayload)
    assert authorization_payload.auth_kind == "oauth2"
    assert authorization_payload.scopes == ["read"]

    credential_payload = credential.to_payload(tool_name="mail")
    assert isinstance(credential_payload, AuthRequiredPayload)
    assert credential_payload.tool_name == "mail"
    assert (
        credential_payload.user_code,
        credential_payload.verification_uri,
        credential_payload.expires_in,
        credential_payload.auth_kind,
    ) == ("ABCD", "https://v", 900, "device_code")


def test_credential_required_invalid_auth_kind_is_omitted() -> None:
    """Unknown legacy auth kinds do not violate the typed payload contract."""
    payload = CredentialRequired("legacy", "https://x", "unknown").to_payload()
    assert payload.auth_kind is None


@pytest.mark.asyncio
async def test_oauth_resolver_resolves_principal_first() -> None:
    """Token lookup uses the Navigator principal and retains the channel id."""
    principal = Principal(
        user_id="1042",
        channel="telegram",
        channel_user_id="88123",
    )
    manager = _OAuthManager()
    resolver = OAuthCredentialResolver(
        manager,
        principal_resolver=_PrincipalResolver({("telegram", "88123"): principal}),
    )

    assert await resolver.resolve("telegram", "88123") == "token-1042"
    assert manager.token_calls == [("telegram", "1042", "88123")]

    assert await resolver.resolve("telegram", "999") is None
    assert manager.token_calls == [("telegram", "1042", "88123")]


@pytest.mark.asyncio
async def test_oauth_resolver_auth_url_uses_principal() -> None:
    """Authorization URL creation receives the resolved principal."""
    principal = Principal(
        user_id="1042",
        channel="a2a",
        channel_user_id="user@example.com",
    )
    manager = _OAuthManager()
    resolver = OAuthCredentialResolver(
        manager,
        principal_resolver=_PrincipalResolver(
            {("a2a", "user@example.com"): principal}
        ),
    )

    assert (
        await resolver.get_auth_url("a2a", "user@example.com")
        == "https://auth.example/connect"
    )
    assert manager.auth_calls == [("a2a", "1042", principal)]


@pytest.mark.asyncio
async def test_oauth_resolver_auth_url_fails_closed_when_unbound() -> None:
    """An unbound channel identity receives a platform-link instruction."""
    manager = _OAuthManager()
    resolver = OAuthCredentialResolver(
        manager,
        principal_resolver=_PrincipalResolver({}),
    )

    with pytest.raises(
        AuthorizationRequired,
        match=r"Link your account to the platform first \(/login\)\.",
    ) as raised:
        await resolver.get_auth_url("telegram", "999")

    assert raised.value.provider == "jira"
    assert manager.auth_calls == []
