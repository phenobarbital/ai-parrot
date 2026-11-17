"""Unit tests for the credential resolver abstraction (TASK-750, FEAT-107)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.auth.credentials import (
    CredentialResolver,
    OAuthCredentialResolver,
    StaticCredentialResolver,
    StaticCredentials,
)


class TestStaticCredentialResolver:
    @pytest.mark.asyncio
    async def test_always_returns_credentials(self) -> None:
        resolver = StaticCredentialResolver(
            server_url="https://jira.example.com",
            username="bot",
            password="secret",
        )
        creds = await resolver.resolve("telegram", "user-1")
        assert isinstance(creds, StaticCredentials)
        assert creds.server_url == "https://jira.example.com"
        assert creds.username == "bot"
        assert creds.password == "secret"
        assert creds.auth_type == "basic_auth"

    @pytest.mark.asyncio
    async def test_is_connected_always_true(self) -> None:
        resolver = StaticCredentialResolver(server_url="https://jira.example.com")
        assert await resolver.is_connected("any", "any") is True

    @pytest.mark.asyncio
    async def test_get_auth_url_raises(self) -> None:
        resolver = StaticCredentialResolver(server_url="https://jira.example.com")
        with pytest.raises(NotImplementedError):
            await resolver.get_auth_url("telegram", "user-1")

    @pytest.mark.asyncio
    async def test_token_auth_variant(self) -> None:
        resolver = StaticCredentialResolver(
            server_url="https://jira.example.com",
            token="pat-xyz",
            auth_type="token_auth",
        )
        creds = await resolver.resolve("api", "bot")
        assert creds.token == "pat-xyz"
        assert creds.auth_type == "token_auth"


class _IdentityPrincipalResolver:
    """Bind every channel identity to a principal with the same id (test double)."""

    async def resolve(self, channel: str, channel_user_id: str):
        from parrot.auth.principal import Principal

        return Principal(user_id=channel_user_id, channel=channel, channel_user_id=channel_user_id)



class TestOAuthCredentialResolver:
    @pytest.mark.asyncio
    async def test_resolve_delegates_to_manager(self) -> None:
        manager = MagicMock()
        token = MagicMock()
        manager.get_valid_token = AsyncMock(return_value=token)
        resolver = OAuthCredentialResolver(oauth_manager=manager, principal_resolver=_IdentityPrincipalResolver())

        result = await resolver.resolve("telegram", "user-123")

        assert result is token
        manager.get_valid_token.assert_awaited_once_with("telegram", "user-123")

    @pytest.mark.asyncio
    async def test_resolve_returns_none_when_no_token(self) -> None:
        manager = MagicMock()
        manager.get_valid_token = AsyncMock(return_value=None)
        resolver = OAuthCredentialResolver(oauth_manager=manager, principal_resolver=_IdentityPrincipalResolver())

        assert await resolver.resolve("telegram", "user-123") is None

    @pytest.mark.asyncio
    async def test_get_auth_url(self) -> None:
        manager = MagicMock()
        manager.create_authorization_url = AsyncMock(
            return_value=("https://auth.url", "nonce"),
        )
        resolver = OAuthCredentialResolver(oauth_manager=manager, principal_resolver=_IdentityPrincipalResolver())

        url = await resolver.get_auth_url("telegram", "user-123")

        assert url == "https://auth.url"
        manager.create_authorization_url.assert_awaited_once_with(
            "telegram", "user-123",
        )

    @pytest.mark.asyncio
    async def test_is_connected_false_when_no_token(self) -> None:
        manager = MagicMock()
        manager.get_valid_token = AsyncMock(return_value=None)
        resolver = OAuthCredentialResolver(oauth_manager=manager, principal_resolver=_IdentityPrincipalResolver())
        assert await resolver.is_connected("tg", "u1") is False

    @pytest.mark.asyncio
    async def test_is_connected_true_when_token_present(self) -> None:
        manager = MagicMock()
        manager.get_valid_token = AsyncMock(return_value=MagicMock())
        resolver = OAuthCredentialResolver(oauth_manager=manager, principal_resolver=_IdentityPrincipalResolver())
        assert await resolver.is_connected("tg", "u1") is True


class TestBaseContract:
    def test_credential_resolver_is_abstract(self) -> None:
        """Directly instantiating the ABC must fail."""
        with pytest.raises(TypeError):
            CredentialResolver()  # type: ignore[abstract]


class TestOAuthCredentialResolverFailsClosed:
    """An unbound channel identity must never reach the manager by its raw id (FEAT-773)."""

    class _Unbound:
        async def resolve(self, channel: str, channel_user_id: str):
            return None

    @pytest.mark.asyncio
    async def test_unbound_resolve_returns_none_without_calling_manager(self) -> None:
        manager = MagicMock()
        manager.get_valid_token = AsyncMock(return_value=MagicMock())
        resolver = OAuthCredentialResolver(oauth_manager=manager, principal_resolver=self._Unbound())

        assert await resolver.resolve("telegram", "raw-id") is None
        manager.get_valid_token.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unbound_auth_url_requires_login_even_for_legacy_manager(self) -> None:
        from parrot.auth.exceptions import AuthorizationRequired

        manager = MagicMock()
        manager.create_authorization_url = AsyncMock(return_value=("https://auth.url", "nonce"))
        resolver = OAuthCredentialResolver(oauth_manager=manager, principal_resolver=self._Unbound())

        with pytest.raises(AuthorizationRequired):
            await resolver.get_auth_url("telegram", "raw-id")
        manager.create_authorization_url.assert_not_awaited()
