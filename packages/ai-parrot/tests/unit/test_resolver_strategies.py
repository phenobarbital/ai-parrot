"""Unit tests for TASK-1668: Resolver strategy factory dispatch.

Tests:
- factory builds a resolver for each auth kind from a representative config
- existing FEAT-263 resolver constructors remain callable (no breakage)
"""
import pytest
from unittest.mock import MagicMock, AsyncMock

from parrot.auth.credentials import (
    CredentialResolver,
    OAuthCredentialResolver,
    ProviderCredentialConfig,
)
from parrot.auth.broker import CredentialResolverFactory


# ---------------------------------------------------------------------------
# Fake deps
# ---------------------------------------------------------------------------


def _make_deps(**extra):
    """Build a minimal deps dict for the factory."""
    vault = MagicMock()
    vault.read_tokens = AsyncMock(return_value={})
    vault.store_tokens = AsyncMock()
    deps = {"vault": vault}
    deps.update(extra)
    return deps


# ---------------------------------------------------------------------------
# oauth2 strategy
# ---------------------------------------------------------------------------


def test_factory_builds_oauth2_resolver():
    """factory builds an OAuthCredentialResolver from auth='oauth2' config."""
    class FakeOAuthManager:
        async def get_valid_token(self, ch, uid):
            return "token"
        async def create_authorization_url(self, ch, uid):
            return "https://auth.example.com/oauth", {}

    manager = FakeOAuthManager()
    factory = CredentialResolverFactory(deps={"oauth_manager": manager})

    cfg = ProviderCredentialConfig(provider="jira", auth="oauth2")
    resolver = factory.build(cfg)

    assert isinstance(resolver, OAuthCredentialResolver)


def test_factory_oauth2_missing_manager_raises():
    """factory raises KeyError when oauth_manager dep is absent for auth='oauth2'."""
    factory = CredentialResolverFactory(deps={})

    cfg = ProviderCredentialConfig(provider="jira", auth="oauth2")
    with pytest.raises(KeyError, match="oauth_manager"):
        factory.build(cfg)


# ---------------------------------------------------------------------------
# static_key strategy
# ---------------------------------------------------------------------------


def test_factory_builds_static_key_resolver():
    """factory builds a static-key resolver from auth='static_key' config."""
    deps = _make_deps()
    factory = CredentialResolverFactory(deps=deps)

    cfg = ProviderCredentialConfig(
        provider="fireflies",
        auth="static_key",
        options={"capture_url": "https://app/capture"},
    )
    resolver = factory.build(cfg)
    assert isinstance(resolver, CredentialResolver)


@pytest.mark.asyncio
async def test_factory_static_key_resolver_returns_none_on_empty_vault():
    """static-key resolver returns None when vault has no token for user."""
    deps = _make_deps()
    factory = CredentialResolverFactory(deps=deps)

    cfg = ProviderCredentialConfig(
        provider="fireflies",
        auth="static_key",
        options={"capture_url": "https://app/capture"},
    )
    resolver = factory.build(cfg)
    result = await resolver.resolve("chat", "user@example.com")
    assert result is None


@pytest.mark.asyncio
async def test_factory_static_key_resolver_returns_token_from_vault():
    """static-key resolver returns the token when vault has it.

    FirefliesCredentialResolver calls vault.read_tokens(user_id, provider)
    and then returns tokens.get("api_key").
    """
    vault = MagicMock()
    # FirefliesCredentialResolver reads tokens.get("api_key") from vault
    vault.read_tokens = AsyncMock(return_value={"api_key": "ff-apikey-123"})
    deps = {"vault": vault}
    factory = CredentialResolverFactory(deps=deps)

    cfg = ProviderCredentialConfig(
        provider="fireflies",
        auth="static_key",
        options={"vault_key": "fireflies:api_key", "capture_url": "https://app/capture"},
    )
    resolver = factory.build(cfg)
    result = await resolver.resolve("chat", "user@example.com")
    assert result == "ff-apikey-123"


# ---------------------------------------------------------------------------
# mcp strategy
# ---------------------------------------------------------------------------


def test_factory_builds_mcp_resolver():
    """factory builds an MCP vault resolver from auth='mcp' config."""
    deps = _make_deps()
    factory = CredentialResolverFactory(deps=deps)

    cfg = ProviderCredentialConfig(
        provider="myservice",
        auth="mcp",
        options={"vault_key": "myservice:token", "auth_url": "https://myservice.com/auth"},
    )
    resolver = factory.build(cfg)
    assert isinstance(resolver, CredentialResolver)


@pytest.mark.asyncio
async def test_factory_mcp_resolver_returns_token_from_vault():
    """MCP resolver returns bearer token from vault."""
    vault = MagicMock()
    vault.read_tokens = AsyncMock(return_value={"myservice:token": "bearer-xyz"})
    deps = {"vault": vault}
    factory = CredentialResolverFactory(deps=deps)

    cfg = ProviderCredentialConfig(
        provider="myservice",
        auth="mcp",
        options={"vault_key": "myservice:token", "auth_url": "https://myservice.com/auth"},
    )
    resolver = factory.build(cfg)
    result = await resolver.resolve("chat", "user@example.com")
    assert result == "bearer-xyz"


# ---------------------------------------------------------------------------
# Multiple providers on same kind — no new code required
# ---------------------------------------------------------------------------


def test_two_oauth2_providers_from_config_no_new_code():
    """Two oauth2 providers from the same kind need only configs, not new code."""
    class FakeManager:
        async def get_valid_token(self, ch, uid):
            return None
        async def create_authorization_url(self, ch, uid):
            return "https://auth.example.com", {}

    manager = FakeManager()
    factory = CredentialResolverFactory(deps={"oauth_manager": manager})

    jira_cfg = ProviderCredentialConfig(provider="jira", auth="oauth2")
    github_cfg = ProviderCredentialConfig(provider="github", auth="oauth2")

    jira_resolver = factory.build(jira_cfg)
    github_resolver = factory.build(github_cfg)

    # Both are OAuthCredentialResolver — no new class or method needed
    assert isinstance(jira_resolver, OAuthCredentialResolver)
    assert isinstance(github_resolver, OAuthCredentialResolver)


# ---------------------------------------------------------------------------
# Existing constructors backward compatibility
# ---------------------------------------------------------------------------


def test_workiq_obo_resolver_ctor_still_callable():
    """WorkIQOBOCredentialResolver constructor is backward-compatible (FEAT-263)."""
    from parrot.auth.oauth2.workiq_provider import WorkIQOBOCredentialResolver

    # Must still accept the same positional/keyword args as before
    resolver = WorkIQOBOCredentialResolver(
        o365_interface=MagicMock(),
        o365_oauth_manager=MagicMock(),
        vault_token_sync=MagicMock(),
        workiq_scope="api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask",
    )
    assert isinstance(resolver, CredentialResolver)
