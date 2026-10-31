"""End-to-end integration tests for the O365 device-code CLI flow (FEAT-266).

Exercises the full broker seam without standing up a real LLM-backed bot:

    CLI identity bootstrap (env O365_PRINCIPAL → CanonicalIdentityMapper)
      → PermissionContext(channel="cli", user_id=<canonical>)
        → CredentialBroker.from_config([...o365 device_code cfg...], deps)
          → AbstractTool(credential_provider="o365").execute(_broker=..., _cred_channel=...,
                                                              _cred_user_id=...)
            → O365DeviceCodeCredentialResolver.resolve() → shared O365 manager record

This mirrors the existing `tests/unit/test_tool_credential_seam.py` pattern
(a minimal `AbstractTool` subclass driving the broker gate directly) rather
than a full `AbstractBot` + LLM harness, since the seam under test is the
credential broker, not LLM orchestration.
"""

from types import SimpleNamespace

import pytest

from parrot.auth.broker import CredentialBroker
from parrot.auth.credentials import ProviderCredentialConfig
from parrot.auth.oauth2.workiq_provider import WorkIQOBOCredentialResolver
from parrot.auth.principal import Principal, set_principal_resolver
from parrot.cli.identity import (
    O365_PRINCIPAL_ENV_VAR,
    build_cli_permission_context,
    resolve_cli_o365_principal,
)
from parrot.tools.abstract import AbstractTool, ToolResult, current_credential

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeO365Client:
    """Stand-in for `O365Client` — simulates a successful device-code login."""

    tenant_id = "tenant-abc"

    def __init__(self):
        self.calls = 0

    async def interactive_login(self, scopes=None, open_browser=True, device_flow_callback=None, **kwargs):
        self.calls += 1
        if device_flow_callback:
            device_flow_callback(
                {
                    "verification_uri": "https://microsoft.com/devicelogin",
                    "user_code": "A1B2-C3D4",
                    "expires_in": 900,
                    "message": "To sign in, use a web browser to open the page "
                    "https://microsoft.com/devicelogin and enter the code A1B2-C3D4.",
                }
            )
        return {
            "access_token": "entra-access-tok",
            "refresh_token": "entra-refresh-tok",
            "expires_in": 3600,
            "scope": "User.Read offline_access",
            "id_token": "entra-id-tok",
        }

    def acquire_token_on_behalf_of(self, user_assertion, scopes=None):
        """Simulates the WorkIQ OBO exchange keyed off the Entra access token."""
        assert user_assertion == "entra-access-tok"
        return {"access_token": "workiq-obo-tok"}


class FakeO365OAuthManager:
    """In-memory shared O365 record used by the resolver."""

    def __init__(self):
        self._store = {}
        self.store_calls = []

    async def get_valid_token(self, channel, user_id, **kwargs):
        return self._store.get(user_id)

    async def store_device_grant(self, principal, payload, *, channel):
        token_set = SimpleNamespace(
            access_token=payload["access_token"],
            refresh_token=payload.get("refresh_token"),
            grant_origin="device_code",
        )
        self._store[principal.user_id] = token_set
        self.store_calls.append((principal, dict(payload), channel))
        return token_set

    async def migrate_legacy_device_grant(self, principal, legacy, *, channel):
        return None

    async def is_connected(self, channel, user_id):
        return user_id in self._store


class FakeVault:
    """In-memory stand-in for `VaultTokenSync` shared across resolvers."""

    def __init__(self):
        self._store = {}

    async def read_tokens(self, user_id, provider):
        return self._store.get((user_id, provider))

    async def store_tokens(self, user_id, provider, tokens):
        existing = self._store.get((user_id, provider), {})
        existing.update({k: v for k, v in tokens.items() if v is not None})
        self._store[(user_id, provider)] = existing

    async def delete_tokens(self, user_id, provider):
        self._store.pop((user_id, provider), None)


class FakePrincipalResolver:
    """Map the CLI identity to one Navigator principal."""

    async def resolve(self, channel, channel_user_id):
        return Principal(
            user_id="1042",
            canonical_identity=channel_user_id,
            channel=channel,
            channel_user_id=channel_user_id,
        )


@pytest.fixture(autouse=True)
def registered_principal_resolver():
    set_principal_resolver(FakePrincipalResolver())
    yield
    set_principal_resolver(None)


class O365GatedTool(AbstractTool):
    """Minimal tool gated on `credential_provider="o365"` (mirrors test_tool_credential_seam.py)."""

    name = "o365_gated_tool"
    description = "Needs an o365 token"
    credential_provider = "o365"

    async def _execute(self, **kwargs) -> ToolResult:
        cred = current_credential()
        return ToolResult(
            status="success",
            result=f"got-cred:{cred}",
            metadata={"credential_received": cred is not None},
        )


# ---------------------------------------------------------------------------
# CLI identity bootstrap
# ---------------------------------------------------------------------------


def test_missing_principal_fails_closed(monkeypatch):
    monkeypatch.delenv(O365_PRINCIPAL_ENV_VAR, raising=False)
    with pytest.raises(RuntimeError):
        resolve_cli_o365_principal()
    with pytest.raises(RuntimeError):
        build_cli_permission_context()


def test_principal_normalizes_via_canonical_identity_mapper(monkeypatch):
    monkeypatch.setenv(O365_PRINCIPAL_ENV_VAR, "  Alice@Corp.COM  ")
    assert resolve_cli_o365_principal() == "alice@corp.com"


def test_build_cli_permission_context_carries_channel_and_user_id(monkeypatch):
    monkeypatch.setenv(O365_PRINCIPAL_ENV_VAR, "alice@corp.com")
    ctx = build_cli_permission_context()
    assert ctx.channel == "cli"
    assert ctx.user_id == "alice@corp.com"


# ---------------------------------------------------------------------------
# End-to-end: CLI identity → broker → tool → resolver → vault
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cli_device_code_end_to_end(monkeypatch):
    monkeypatch.setenv(O365_PRINCIPAL_ENV_VAR, "user@corp.com")
    permission_context = build_cli_permission_context()

    o365_client = FakeO365Client()
    manager = FakeO365OAuthManager()
    vault = FakeVault()
    broker = CredentialBroker.from_config(
        [ProviderCredentialConfig(provider="o365", auth="device_code")],
        o365_client=o365_client,
        o365_oauth_manager=manager,
        vault=vault,
    )

    tool = O365GatedTool()
    result = await tool.execute(
        _broker=broker,
        _cred_channel=permission_context.channel,
        _cred_user_id=permission_context.user_id,
    )

    assert result.status == "success"
    assert result.result == "got-cred:entra-access-tok"
    assert o365_client.calls == 1

    # Token landed in the shared, principal-keyed O365 manager record.
    persisted = manager._store["1042"]
    assert persisted.access_token == "entra-access-tok"
    assert persisted.refresh_token == "entra-refresh-tok"
    assert persisted.grant_origin == "device_code"
    assert manager.store_calls[0][2] == "cli"
    assert ("user@corp.com", "o365") not in vault._store

    # Second resolve is a cache hit — no second device-code round trip.
    result2 = await tool.execute(
        _broker=broker,
        _cred_channel=permission_context.channel,
        _cred_user_id=permission_context.user_id,
    )
    assert result2.status == "success"
    assert result2.result == "got-cred:entra-access-tok"
    assert o365_client.calls == 1  # unchanged — cache hit


@pytest.mark.asyncio
async def test_devicecode_token_consumable_by_workiq_obo(monkeypatch):
    """Proves the canonical-store homologation (spec §1): one Entra sign-in,
    written by device-code, is readable by the existing WorkIQ OBO resolver.
    """
    monkeypatch.setenv(O365_PRINCIPAL_ENV_VAR, "user@corp.com")
    permission_context = build_cli_permission_context()

    o365_client = FakeO365Client()
    manager = FakeO365OAuthManager()
    vault = FakeVault()
    broker = CredentialBroker.from_config(
        [ProviderCredentialConfig(provider="o365", auth="device_code")],
        o365_client=o365_client,
        o365_oauth_manager=manager,
        vault=vault,
    )

    # Step 1: device-code flow persists the principal-keyed O365 token set.
    tool = O365GatedTool()
    await tool.execute(
        _broker=broker,
        _cred_channel=permission_context.channel,
        _cred_user_id=permission_context.user_id,
    )

    # Step 2: WorkIQ reads the same O365 manager record and performs OBO.
    workiq_resolver = WorkIQOBOCredentialResolver(
        o365_interface=o365_client,
        o365_oauth_manager=manager,
        vault_token_sync=vault,
    )
    obo_token = await workiq_resolver.resolve("cli", "user@corp.com")

    assert obo_token == "workiq-obo-tok"
