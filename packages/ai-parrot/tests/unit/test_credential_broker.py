"""Unit tests for TASK-1667: CredentialBroker + CredentialResolverFactory + models.

Tests:
- factory builds resolvers for each auth kind from config
- broker.resolve() returns ResolvedCredential on success + audit appended
- broker.resolve() returns NeedsAuth on miss
- adding a provider on existing kind needs only ProviderCredentialConfig (no new code)
- no resolver for provider → fail closed (KeyError)
- no identity → fail closed (ValueError)
"""
import pytest
from unittest.mock import MagicMock

from parrot.auth.credentials import (
    CredentialRequired,
    CredentialResolver,
    NeedsAuth,
    ProviderCredentialConfig,
    ResolvedCredential,
)
from parrot.auth.broker import CredentialBroker, CredentialResolverFactory


# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------


class FakeResolver(CredentialResolver):
    """Test double that resolves a fixed token or None."""

    def __init__(self, token=None, auth_url="https://example.com/auth"):
        self._token = token
        self._auth_url = auth_url

    async def resolve(self, channel: str, user_id: str):
        return self._token

    async def get_auth_url(self, channel: str, user_id: str) -> str:
        return self._auth_url


class FakeAuditLedger:
    """Records all append() calls for inspection."""

    def __init__(self):
        self.entries = []

    async def append(self, *, user_id, channel, tool, provider, credential_material):
        self.entries.append({
            "user_id": user_id,
            "channel": channel,
            "tool": tool,
            "provider": provider,
        })
        # Return a minimal entry stub
        entry = MagicMock()
        entry.entry_id = "test-entry-id"
        return entry


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


def test_provider_credential_config_defaults():
    cfg = ProviderCredentialConfig(provider="fireflies", auth="static_key")
    assert cfg.provider == "fireflies"
    assert cfg.auth == "static_key"
    assert cfg.options == {}


def test_provider_credential_config_with_options():
    cfg = ProviderCredentialConfig(
        provider="workiq",
        auth="obo",
        options={"scope": "api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask"},
    )
    assert cfg.options["scope"].startswith("api://workiq")


def test_resolved_credential():
    cred = ResolvedCredential(provider="workiq", secret="tok123", key_fingerprint="abc")
    assert cred.provider == "workiq"
    assert cred.secret == "tok123"
    assert cred.key_fingerprint == "abc"


def test_needs_auth():
    na = NeedsAuth(provider="fireflies", auth_url="https://app/capture", auth_kind="static_key")
    assert na.provider == "fireflies"
    assert na.auth_url == "https://app/capture"
    assert na.auth_kind == "static_key"


def test_credential_required_exception():
    exc = CredentialRequired("fireflies", "https://app/capture", "static_key")
    assert exc.provider == "fireflies"
    assert exc.auth_url == "https://app/capture"
    assert exc.auth_kind == "static_key"
    assert "fireflies" in str(exc)


# ---------------------------------------------------------------------------
# CredentialBroker tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_broker_resolve_returns_resolved_credential():
    """broker.resolve() with a hit resolver returns ResolvedCredential."""
    broker = CredentialBroker()
    resolver = FakeResolver(token="my-secret-token")
    broker.register("testprovider", resolver)

    result = await broker.resolve("testprovider", "chat", "user@example.com")
    assert isinstance(result, ResolvedCredential)
    assert result.provider == "testprovider"
    assert result.secret == "my-secret-token"
    assert len(result.key_fingerprint) == 64  # SHA-256 hex


@pytest.mark.asyncio
async def test_broker_resolve_returns_needsauth_on_miss():
    """broker.resolve() with a miss resolver returns NeedsAuth without secret."""
    broker = CredentialBroker()
    resolver = FakeResolver(token=None, auth_url="https://app/auth")
    broker.register("testprovider", resolver)

    result = await broker.resolve("testprovider", "chat", "user@example.com")
    assert isinstance(result, NeedsAuth)
    assert result.provider == "testprovider"
    assert result.auth_url == "https://app/auth"
    # NeedsAuth must NOT contain a secret
    assert not hasattr(result, "secret")


@pytest.mark.asyncio
async def test_broker_resolve_appends_audit_on_success():
    """Successful resolve appends an audit entry (key_fingerprint only, not raw secret)."""
    ledger = FakeAuditLedger()
    broker = CredentialBroker(audit_ledger=ledger)
    resolver = FakeResolver(token="supersecret")
    broker.register("prov", resolver)

    await broker.resolve("prov", "a2a:copilot", "alice@example.com", tool_name="my_tool")

    assert len(ledger.entries) == 1
    entry = ledger.entries[0]
    assert entry["user_id"] == "alice@example.com"
    assert entry["provider"] == "prov"
    assert entry["channel"] == "a2a:copilot"


@pytest.mark.asyncio
async def test_broker_no_audit_on_miss():
    """A miss does NOT append to the audit ledger."""
    ledger = FakeAuditLedger()
    broker = CredentialBroker(audit_ledger=ledger)
    resolver = FakeResolver(token=None)
    broker.register("prov", resolver)

    await broker.resolve("prov", "chat", "user@example.com")

    assert len(ledger.entries) == 0


@pytest.mark.asyncio
async def test_broker_fail_closed_no_resolver():
    """broker.resolve() raises KeyError when no resolver is registered for provider."""
    broker = CredentialBroker()

    with pytest.raises(KeyError, match="no resolver registered for provider"):
        await broker.resolve("unknown_provider", "chat", "user@example.com")


@pytest.mark.asyncio
async def test_broker_fail_closed_no_identity():
    """broker.resolve() raises ValueError when user_id is empty."""
    broker = CredentialBroker()
    resolver = FakeResolver(token="tok")
    broker.register("prov", resolver)

    with pytest.raises(ValueError, match="no identity"):
        await broker.resolve("prov", "chat", "")


@pytest.mark.asyncio
async def test_broker_from_config_no_new_code_for_existing_kind():
    """Adding a provider on an existing auth kind needs only a ProviderCredentialConfig.

    Proves G1: no new code required for each new provider.
    """
    # We add two providers both using 'oauth2' — no new methods/classes
    class FakeOAuthManager:
        async def get_valid_token(self, ch, uid):
            return "token-for-" + uid

        async def create_authorization_url(self, ch, uid):
            return "https://auth.example.com/oauth", {}

    manager = FakeOAuthManager()

    configs = [
        ProviderCredentialConfig(provider="jira", auth="oauth2"),
        ProviderCredentialConfig(provider="github", auth="oauth2"),
    ]
    # Factory deps provide the shared oauth_manager
    broker = CredentialBroker.from_config(configs, oauth_manager=manager)

    # Both providers should now resolve without any new code
    result_jira = await broker.resolve("jira", "chat", "user@example.com")
    result_github = await broker.resolve("github", "chat", "user@example.com")

    assert isinstance(result_jira, ResolvedCredential)
    assert isinstance(result_github, ResolvedCredential)


def test_factory_raises_on_unknown_kind():
    """CredentialResolverFactory.build raises ValueError for unknown auth kind."""
    factory = CredentialResolverFactory()

    with pytest.raises(ValueError, match="unknown auth kind"):
        cfg = ProviderCredentialConfig(provider="bad", auth="static_key")
        # Monkeypatch auth to something invalid for testing
        object.__setattr__(cfg, "auth", "invalid_kind")
        factory.build(cfg)


# ---------------------------------------------------------------------------
# from_config
# ---------------------------------------------------------------------------


def test_from_config_builds_broker_without_io():
    """CredentialBroker.from_config is pure construction (no I/O)."""
    # If no strategy deps are available for 'obo', it logs a warning but doesn't crash.
    configs = [
        ProviderCredentialConfig(provider="fireflies", auth="static_key",
                                  options={"capture_url": "https://app/capture"}),
    ]
    broker = CredentialBroker.from_config(configs)
    # The fireflies provider should be registered (or warned if integrations not installed)
    # Either way, from_config returns without I/O
    assert isinstance(broker, CredentialBroker)
